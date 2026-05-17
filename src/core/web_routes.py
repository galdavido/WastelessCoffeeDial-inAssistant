from __future__ import annotations

import os
import tempfile
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ai.rag import get_best_grind_setting
from ai.vision import analyze_coffee_bag, get_last_vision_error
from database.database import SessionLocal
from database.models import Bean, BrewSetup, DialInLog, Equipment

from .web_helpers import (
    as_non_empty_text,
    get_active_setup,
    get_default_dose_g,
    get_grind_offset_clicks,
    resolve_log_values,
    save_dial_in_log,
    serialize_equipment,
    serialize_setup,
    set_default_dose_g,
    set_grind_offset_clicks,
    set_setting,
)
from .web_schemas import (
    BeanRecordInput,
    DoseUpdate,
    EquipmentLibraryCreateInput,
    EquipmentLibraryUpdateInput,
    EquipmentUpdate,
    FeedbackRequest,
    GrindOffsetUpdate,
    SetupInput,
    SetupSelectInput,
)


def register_routes(app: FastAPI, static_dir: str) -> None:
    @app.get("/")
    async def root(request: Request) -> FileResponse:
        user_agent = request.headers.get("user-agent", "").lower()
        is_mobile = any(
            token in user_agent
            for token in ("iphone", "android", "mobile", "ipad", "ipod")
        )
        target = "index.html" if is_mobile else "desktop.html"
        return FileResponse(os.path.join(static_dir, target))

    @app.get("/mobile")
    async def mobile_ui() -> FileResponse:
        return FileResponse(os.path.join(static_dir, "index.html"))

    @app.get("/desktop")
    async def desktop_ui() -> FileResponse:
        return FileResponse(os.path.join(static_dir, "desktop.html"))

    @app.get("/sw.js")
    async def service_worker() -> FileResponse:
        return FileResponse(
            os.path.join(static_dir, "sw.js"),
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )

    @app.post("/api/analyze")
    async def analyze_image(file: UploadFile = File(...)) -> dict[str, Any]:
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image.")

        suffix = ".jpg"
        if file.filename and "." in file.filename:
            suffix = os.path.splitext(file.filename)[1] or ".jpg"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        try:
            coffee_data = analyze_coffee_bag(tmp_path)
        finally:
            os.unlink(tmp_path)

        if not coffee_data:
            detail = get_last_vision_error() or "Failed to extract data from image."
            raise HTTPException(status_code=422, detail=detail)

        db = SessionLocal()
        try:
            coffee_data["preferred_dose_g"] = get_default_dose_g(db)
            coffee_data["preferred_grind_offset_clicks"] = get_grind_offset_clicks(db)
        finally:
            db.close()

        recommendation = get_best_grind_setting(coffee_data)
        return {"coffee_data": coffee_data, "recommendation": recommendation}

    @app.post("/api/feedback")
    async def save_feedback(body: FeedbackRequest) -> dict[str, str]:
        try:
            save_dial_in_log(
                body.coffee_data,
                body.recommendation,
                actual_grind=body.actual_grind,
                dose_g=body.dose_g,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return {"status": "saved"}

    @app.get("/api/equipment")
    async def get_equipment() -> dict[str, Any]:
        db = SessionLocal()
        try:
            setup = get_active_setup(db)
            grinder = setup.grinder
            machine = setup.machine
            return {
                "grinder": {"brand": grinder.brand, "model": grinder.model}
                if grinder
                else None,
                "machine": {"brand": machine.brand, "model": machine.model}
                if machine
                else None,
            }
        finally:
            db.close()

    @app.put("/api/equipment/grinder")
    async def update_grinder(body: EquipmentUpdate) -> dict[str, str]:
        db = SessionLocal()
        try:
            setup = get_active_setup(db)
            grinder = setup.grinder
            grinder.brand = body.brand
            grinder.model = body.model
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()
        return {"status": "updated"}

    @app.put("/api/equipment/machine")
    async def update_machine(body: EquipmentUpdate) -> dict[str, str]:
        db = SessionLocal()
        try:
            setup = get_active_setup(db)
            machine = setup.machine
            machine.brand = body.brand
            machine.model = body.model
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()
        return {"status": "updated"}

    @app.get("/api/settings")
    async def get_settings() -> dict[str, float]:
        db = SessionLocal()
        try:
            return {
                "dose_g": get_default_dose_g(db),
                "grind_offset_clicks": get_grind_offset_clicks(db),
            }
        finally:
            db.close()

    @app.get("/api/logs")
    async def get_logs(limit: int = 20) -> dict[str, list[dict[str, Any]]]:
        db = SessionLocal()
        try:
            safe_limit = max(1, min(limit, 50))
            beans = db.query(Bean).order_by(Bean.id.desc()).limit(safe_limit).all()

            entries: list[dict[str, Any]] = []
            for bean in beans:
                latest_log = None
                if bean.logs:
                    latest_log = max(bean.logs, key=lambda log: log.created_at)

                entries.append(
                    {
                        "bean_id": bean.id,
                        "bean_name": bean.name,
                        "roaster": bean.roaster,
                        "origin": bean.origin,
                        "process": bean.process,
                        "roast_level": bean.roast_level,
                        "logs_count": len(bean.logs),
                        "latest_log": {
                            "id": latest_log.id,
                            "created_at": latest_log.created_at.isoformat(),
                            "grinder": latest_log.grinder.brand
                            + " "
                            + latest_log.grinder.model,
                            "machine": latest_log.machine.brand
                            + " "
                            + latest_log.machine.model,
                            "grind_setting": latest_log.grind_setting,
                            "dose_g": latest_log.dose_g,
                            "yield_g": latest_log.yield_g,
                            "time_s": latest_log.time_s,
                            "rating": latest_log.rating,
                            "tasting_notes": latest_log.tasting_notes,
                        }
                        if latest_log
                        else None,
                    }
                )

            return {"entries": entries}
        finally:
            db.close()

    @app.get("/api/equipment/library")
    async def get_equipment_library() -> dict[str, list[dict[str, Any]]]:
        db = SessionLocal()
        try:
            items = (
                db.query(Equipment)
                .order_by(
                    Equipment.type.asc(), Equipment.brand.asc(), Equipment.model.asc()
                )
                .all()
            )
            grinders = [
                serialize_equipment(item) for item in items if item.type == "grinder"
            ]
            machines = [
                serialize_equipment(item) for item in items if item.type != "grinder"
            ]
            return {"grinders": grinders, "machines": machines}
        finally:
            db.close()

    @app.post("/api/equipment/library")
    async def create_equipment_library_item(
        body: EquipmentLibraryCreateInput,
    ) -> dict[str, Any]:
        db = SessionLocal()
        try:
            eq_type = as_non_empty_text(body.type).lower()
            if eq_type not in {"grinder", "espresso_machine", "filter", "other"}:
                raise HTTPException(status_code=400, detail="Invalid equipment type")

            item = Equipment(
                type=eq_type,
                brand=as_non_empty_text(body.brand),
                model=as_non_empty_text(body.model),
            )
            db.add(item)
            db.commit()
            db.refresh(item)
            return {"status": "created", "equipment": serialize_equipment(item)}
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()

    @app.put("/api/equipment/library/{equipment_id}")
    async def update_equipment_library_item(
        equipment_id: int,
        body: EquipmentLibraryUpdateInput,
    ) -> dict[str, Any]:
        db = SessionLocal()
        try:
            item = db.query(Equipment).filter(Equipment.id == equipment_id).first()
            if not item:
                raise HTTPException(status_code=404, detail="Equipment not found")

            eq_type = as_non_empty_text(body.type).lower()
            if eq_type not in {"grinder", "espresso_machine", "filter", "other"}:
                raise HTTPException(status_code=400, detail="Invalid equipment type")

            if eq_type == "grinder":
                setup_refs = (
                    db.query(BrewSetup)
                    .filter(BrewSetup.machine_id == equipment_id)
                    .count()
                )
                log_refs = (
                    db.query(DialInLog)
                    .filter(DialInLog.machine_id == equipment_id)
                    .count()
                )
            else:
                setup_refs = (
                    db.query(BrewSetup)
                    .filter(BrewSetup.grinder_id == equipment_id)
                    .count()
                )
                log_refs = (
                    db.query(DialInLog)
                    .filter(DialInLog.grinder_id == equipment_id)
                    .count()
                )

            if setup_refs > 0 or log_refs > 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot change equipment category while it is referenced",
                )

            item.type = eq_type
            item.brand = as_non_empty_text(body.brand)
            item.model = as_non_empty_text(body.model)
            db.commit()
            db.refresh(item)
            return {"status": "updated", "equipment": serialize_equipment(item)}
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()

    @app.delete("/api/equipment/library/{equipment_id}")
    async def delete_equipment_library_item(equipment_id: int) -> dict[str, str]:
        db = SessionLocal()
        try:
            item = db.query(Equipment).filter(Equipment.id == equipment_id).first()
            if not item:
                raise HTTPException(status_code=404, detail="Equipment not found")

            setup_refs = (
                db.query(BrewSetup)
                .filter(
                    (BrewSetup.grinder_id == equipment_id)
                    | (BrewSetup.machine_id == equipment_id)
                )
                .count()
            )
            log_refs = (
                db.query(DialInLog)
                .filter(
                    (DialInLog.grinder_id == equipment_id)
                    | (DialInLog.machine_id == equipment_id)
                )
                .count()
            )

            if setup_refs > 0 or log_refs > 0:
                raise HTTPException(
                    status_code=400,
                    detail="Equipment is in use by setups/logs and cannot be deleted",
                )

            db.delete(item)
            db.commit()
            return {"status": "deleted"}
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()

    @app.get("/api/setups")
    async def get_setups() -> dict[str, Any]:
        db = SessionLocal()
        try:
            active = get_active_setup(db)
            setups = (
                db.query(BrewSetup)
                .order_by(BrewSetup.name.asc(), BrewSetup.id.asc())
                .all()
            )
            return {
                "active_setup_id": active.id,
                "setups": [serialize_setup(item) for item in setups],
            }
        finally:
            db.close()

    @app.post("/api/setups")
    async def create_setup(body: SetupInput) -> dict[str, Any]:
        db = SessionLocal()
        try:
            grinder = (
                db.query(Equipment)
                .filter(Equipment.id == body.grinder_id, Equipment.type == "grinder")
                .first()
            )
            machine = (
                db.query(Equipment)
                .filter(Equipment.id == body.machine_id, Equipment.type != "grinder")
                .first()
            )
            if not grinder or not machine:
                raise HTTPException(
                    status_code=400, detail="Selected equipment not found"
                )

            setup = BrewSetup(
                name=as_non_empty_text(body.name),
                grinder_id=grinder.id,
                machine_id=machine.id,
            )
            db.add(setup)
            db.commit()
            db.refresh(setup)
            return {"status": "created", "setup": serialize_setup(setup)}
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()

    @app.put("/api/setups/{setup_id}")
    async def update_setup(setup_id: int, body: SetupInput) -> dict[str, Any]:
        db = SessionLocal()
        try:
            setup = db.query(BrewSetup).filter(BrewSetup.id == setup_id).first()
            if not setup:
                raise HTTPException(status_code=404, detail="Setup not found")

            grinder = (
                db.query(Equipment)
                .filter(Equipment.id == body.grinder_id, Equipment.type == "grinder")
                .first()
            )
            machine = (
                db.query(Equipment)
                .filter(Equipment.id == body.machine_id, Equipment.type != "grinder")
                .first()
            )
            if not grinder or not machine:
                raise HTTPException(
                    status_code=400, detail="Selected equipment not found"
                )

            setup.name = as_non_empty_text(body.name)
            setup.grinder_id = grinder.id
            setup.machine_id = machine.id
            db.commit()
            db.refresh(setup)
            return {"status": "updated", "setup": serialize_setup(setup)}
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()

    @app.put("/api/setups/active")
    async def select_setup(body: SetupSelectInput) -> dict[str, Any]:
        db = SessionLocal()
        try:
            selected_id = body.setup_id or body.active_setup_id
            if not selected_id:
                raise HTTPException(status_code=422, detail="setup_id is required")

            setup = db.query(BrewSetup).filter(BrewSetup.id == selected_id).first()
            if not setup:
                raise HTTPException(status_code=404, detail="Setup not found")
            set_setting(db, "active_setup_id", str(setup.id))
            return {"status": "selected", "setup_id": setup.id}
        finally:
            db.close()

    @app.delete("/api/setups/{setup_id}")
    async def delete_setup(setup_id: int) -> dict[str, str]:
        db = SessionLocal()
        try:
            setup = db.query(BrewSetup).filter(BrewSetup.id == setup_id).first()
            if not setup:
                raise HTTPException(status_code=404, detail="Setup not found")
            if db.query(BrewSetup).count() <= 1:
                raise HTTPException(
                    status_code=400, detail="At least one setup must remain"
                )

            db.delete(setup)
            db.commit()

            next_setup = db.query(BrewSetup).order_by(BrewSetup.id.asc()).first()
            if next_setup:
                set_setting(db, "active_setup_id", str(next_setup.id))
            return {"status": "deleted"}
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()

    @app.post("/api/logs/manual")
    async def create_manual_log(body: BeanRecordInput) -> dict[str, Any]:
        db = SessionLocal()
        try:
            bean = Bean(
                roaster=as_non_empty_text(body.roaster),
                name=as_non_empty_text(body.name),
                origin=as_non_empty_text(body.origin),
                process=as_non_empty_text(body.process),
                roast_level=as_non_empty_text(body.roast_level),
            )
            db.add(bean)
            db.commit()
            db.refresh(bean)

            active_setup = get_active_setup(db)
            grinder, machine = active_setup.grinder, active_setup.machine
            values = resolve_log_values(body.log, db)
            db.add(
                DialInLog(
                    bean_id=bean.id,
                    grinder_id=grinder.id,
                    machine_id=machine.id,
                    grind_setting=values["grind_setting"],
                    dose_g=values["dose_g"],
                    yield_g=values["yield_g"],
                    time_s=values["time_s"],
                    rating=values["rating"],
                    tasting_notes=values["tasting_notes"],
                )
            )
            db.commit()
            return {"status": "created", "bean_id": bean.id}
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()

    @app.put("/api/logs/{bean_id}")
    async def update_log_record(bean_id: int, body: BeanRecordInput) -> dict[str, Any]:
        db = SessionLocal()
        try:
            bean = db.query(Bean).filter(Bean.id == bean_id).first()
            if not bean:
                raise HTTPException(status_code=404, detail="Bean not found")

            bean.roaster = as_non_empty_text(body.roaster)
            bean.name = as_non_empty_text(body.name)
            bean.origin = as_non_empty_text(body.origin)
            bean.process = as_non_empty_text(body.process)
            bean.roast_level = as_non_empty_text(body.roast_level)

            latest_log = None
            if bean.logs:
                latest_log = max(bean.logs, key=lambda log: log.created_at)

            values = resolve_log_values(body.log, db)
            if latest_log is None:
                active_setup = get_active_setup(db)
                grinder, machine = active_setup.grinder, active_setup.machine
                db.add(
                    DialInLog(
                        bean_id=bean.id,
                        grinder_id=grinder.id,
                        machine_id=machine.id,
                        grind_setting=values["grind_setting"],
                        dose_g=values["dose_g"],
                        yield_g=values["yield_g"],
                        time_s=values["time_s"],
                        rating=values["rating"],
                        tasting_notes=values["tasting_notes"],
                    )
                )
            else:
                latest_log.grind_setting = values["grind_setting"]
                latest_log.dose_g = values["dose_g"]
                latest_log.yield_g = values["yield_g"]
                latest_log.time_s = values["time_s"]
                latest_log.rating = values["rating"]
                latest_log.tasting_notes = values["tasting_notes"]

            db.commit()
            return {"status": "updated", "bean_id": bean.id}
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()

    @app.delete("/api/logs/{bean_id}")
    async def delete_log_record(bean_id: int) -> dict[str, str]:
        db = SessionLocal()
        try:
            bean = db.query(Bean).filter(Bean.id == bean_id).first()
            if not bean:
                raise HTTPException(status_code=404, detail="Bean not found")

            db.query(DialInLog).filter(DialInLog.bean_id == bean_id).delete()
            db.delete(bean)
            db.commit()
            return {"status": "deleted"}
        except HTTPException:
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()

    @app.put("/api/settings/dose")
    async def update_dose(body: DoseUpdate) -> dict[str, Any]:
        if body.dose_g <= 0:
            raise HTTPException(status_code=400, detail="Dose must be positive.")
        db = SessionLocal()
        try:
            set_default_dose_g(db, body.dose_g)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()
        return {"status": "updated", "dose_g": body.dose_g}

    @app.put("/api/settings/grind-offset")
    async def update_grind_offset(body: GrindOffsetUpdate) -> dict[str, Any]:
        db = SessionLocal()
        try:
            set_grind_offset_clicks(db, body.offset_clicks)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            db.close()
        return {"status": "updated", "offset_clicks": body.offset_clicks}
