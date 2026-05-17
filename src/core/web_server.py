import os
import re
import tempfile
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from ai.vision import analyze_coffee_bag, get_last_vision_error
from ai.rag import get_best_grind_setting
from core.optional_deps import load_dotenv_if_available
from database.database import Base, SessionLocal, engine
from database.models import AppSetting, Bean, DialInLog, Equipment

load_dotenv_if_available()

_static_dir = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "web", "static")
)


# ── DB helpers ────────────────────────────────────────────────────────────────


def _init_db() -> None:
    for attempt in range(1, 6):
        try:
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                conn.commit()
            Base.metadata.create_all(bind=engine)
            print("Database tables created.")
            return
        except Exception as exc:
            print(f"DB init error (attempt {attempt}/5): {exc}")
            if attempt < 5:
                time.sleep(2)


def _seed_db() -> None:
    db = SessionLocal()
    try:
        if not db.query(Equipment).first():
            db.add_all(
                [
                    Equipment(
                        type="espresso_machine", brand="AVX", model="Hero Plus 2024"
                    ),
                    Equipment(type="grinder", brand="Kingrinder", model="K6"),
                ]
            )
            db.commit()
            print("Basic equipment added.")
    except Exception as exc:
        print(f"Seed error: {exc}")
    finally:
        db.close()


def _ensure_tables() -> None:
    Base.metadata.create_all(bind=engine)


def get_default_dose_g(db: Any) -> float:
    try:
        setting = (
            db.query(AppSetting).filter(AppSetting.key == "default_dose_g").first()
        )
    except ProgrammingError as exc:
        if "app_settings" not in str(exc):
            raise
        db.rollback()
        _ensure_tables()
        setting = (
            db.query(AppSetting).filter(AppSetting.key == "default_dose_g").first()
        )
    if not setting:
        return 16.0
    try:
        dose = float(setting.value)
        if dose > 0:
            return dose
    except (TypeError, ValueError):
        pass
    return 16.0


def set_default_dose_g(db: Any, dose: float) -> None:
    setting = db.query(AppSetting).filter(AppSetting.key == "default_dose_g").first()
    if setting:
        setting.value = str(dose)
    else:
        db.add(AppSetting(key="default_dose_g", value=str(dose)))
    db.commit()


def get_grind_offset_clicks(db: Any) -> float:
    try:
        setting = (
            db.query(AppSetting)
            .filter(AppSetting.key == "default_grind_offset_clicks")
            .first()
        )
    except ProgrammingError as exc:
        if "app_settings" not in str(exc):
            raise
        db.rollback()
        _ensure_tables()
        setting = (
            db.query(AppSetting)
            .filter(AppSetting.key == "default_grind_offset_clicks")
            .first()
        )
    if not setting:
        return 0.0
    try:
        return float(setting.value)
    except (TypeError, ValueError):
        return 0.0


def set_grind_offset_clicks(db: Any, offset: float) -> None:
    setting = (
        db.query(AppSetting)
        .filter(AppSetting.key == "default_grind_offset_clicks")
        .first()
    )
    if setting:
        setting.value = str(offset)
    else:
        db.add(AppSetting(key="default_grind_offset_clicks", value=str(offset)))
    db.commit()


def _as_non_empty_text(value: Any, default: str = "Unknown") -> str:
    if value is None:
        return default
    t = str(value).strip()
    if not t or t.lower() == "none":
        return default
    return t


def _normalize_label(value: str) -> str:
    lowered = value.strip().lower()
    deaccented = (
        unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode()
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", deaccented).split())


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_label(a), _normalize_label(b)).ratio()


def _find_existing_bean(
    db: Any, name: str, roaster: str, origin: str, process: str
) -> Any:
    exact = db.query(Bean).filter(Bean.name == name, Bean.roaster == roaster).first()
    if exact:
        return exact

    roaster_norm = _normalize_label(roaster)
    name_norm = _normalize_label(name)
    origin_norm = _normalize_label(origin)
    process_norm = _normalize_label(process)

    best_candidate, best_score = None, 0.0
    for candidate in db.query(Bean).all():
        if (
            roaster_norm != "unknown"
            and _normalize_label(str(candidate.roaster)) != roaster_norm
        ):
            continue
        score = _similarity(name, str(candidate.name))
        if _normalize_label(str(candidate.name)) == name_norm:
            score = 1.0
        if (
            origin_norm != "unknown"
            and _normalize_label(str(candidate.origin)) not in ("unknown",)
            and _normalize_label(str(candidate.origin)) == origin_norm
        ):
            score += 0.05
        if (
            process_norm != "unknown"
            and _normalize_label(str(candidate.process)) not in ("unknown",)
            and _normalize_label(str(candidate.process)) == process_norm
        ):
            score += 0.05
        if score > best_score:
            best_score = score
            best_candidate = candidate

    return best_candidate if best_candidate and best_score >= 0.9 else None


def _save_dial_in_log(
    coffee_data: dict[str, Any],
    recommendation: str,
    actual_grind: str | None = None,
    dose_g: float | None = None,
) -> None:
    db = SessionLocal()
    try:
        bean_name = _as_non_empty_text(coffee_data.get("name"))
        bean_roaster = _as_non_empty_text(coffee_data.get("roaster"))
        bean_origin = _as_non_empty_text(coffee_data.get("origin"))
        bean_process = _as_non_empty_text(coffee_data.get("process"))
        bean_roast_level = _as_non_empty_text(coffee_data.get("roast_level"))

        bean = _find_existing_bean(
            db,
            name=bean_name,
            roaster=bean_roaster,
            origin=bean_origin,
            process=bean_process,
        )
        if not bean:
            bean = Bean(
                roaster=bean_roaster,
                name=bean_name,
                origin=bean_origin,
                process=bean_process,
                roast_level=bean_roast_level,
            )
            db.add(bean)
            db.commit()
            db.refresh(bean)

        grinder = db.query(Equipment).filter(Equipment.type == "grinder").first()
        machine = (
            db.query(Equipment).filter(Equipment.type == "espresso_machine").first()
        )
        if not grinder or not machine:
            return

        if actual_grind:
            grind_setting = actual_grind
        else:
            grind_setting = "Unknown"
            if "Suggested Grind Setting:" in recommendation:
                try:
                    start = recommendation.find("Suggested Grind Setting:") + len(
                        "Suggested Grind Setting:"
                    )
                    end = recommendation.find("\n", start)
                    grind_setting = recommendation[start:end].strip()
                except Exception:
                    pass

        resolved_dose_g = dose_g if dose_g is not None else get_default_dose_g(db)

        db.add(
            DialInLog(
                bean_id=bean.id,
                grinder_id=grinder.id,
                machine_id=machine.id,
                grind_setting=grind_setting,
                dose_g=resolved_dose_g,
                yield_g=round(resolved_dose_g * 2.0, 1),
                time_s=28,
                rating=5,
                tasting_notes=f"Web app: {recommendation[:100]}...",
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _generate_app_icons() -> None:
    """Generate PNG app icons from Pillow for PWA / iOS home screen.

    Runs at startup; silently skipped if icons already exist or if the
    filesystem is read-only (production containers pre-bake icons via
    the Dockerfile RUN step instead).
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return
    icons_dir = os.path.join(_static_dir, "icons")
    try:
        os.makedirs(icons_dir, exist_ok=True)
    except OSError:
        return  # read-only filesystem – icons were pre-generated in image

    bg = (15, 10, 6)
    accent = (200, 134, 10)

    for size in (180, 192, 512):
        path = os.path.join(icons_dir, f"icon-{size}.png")
        if os.path.exists(path):
            continue
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Rounded-square background
        r = size // 5
        draw.rounded_rectangle([0, 0, size, size], radius=r, fill=bg)
        # Amber circle
        pad = size // 6
        draw.ellipse([pad, pad, size - pad, size - pad], fill=accent)
        # White cup silhouette (simplified)
        cx, cy = size // 2, size // 2
        cup_w = size // 3
        cup_h = int(size * 0.28)
        cup_x = cx - cup_w // 2
        cup_y = cy - cup_h // 2 + size // 20
        draw.rectangle([cup_x, cup_y, cup_x + cup_w, cup_y + cup_h], fill="white")
        # Handle
        hw = size // 12
        draw.arc(
            [
                cup_x + cup_w - hw // 2,
                cup_y + cup_h // 4,
                cup_x + cup_w + hw,
                cup_y + cup_h - cup_h // 4,
            ],
            start=-90,
            end=90,
            fill="white",
            width=max(2, size // 40),
        )
        # Saucer
        s_pad = size // 5
        s_h = max(3, size // 40)
        draw.rectangle(
            [
                s_pad,
                cup_y + cup_h + size // 20,
                size - s_pad,
                cup_y + cup_h + size // 20 + s_h,
            ],
            fill="white",
        )
        try:
            img.save(path, "PNG")
        except OSError:
            return  # read-only filesystem


# ── FastAPI app ───────────────────────────────────────────────────────────────

_init_db()
_seed_db()
_generate_app_icons()

app = FastAPI(title="WCDA Web")

app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/")
async def root(request: Request) -> FileResponse:
    user_agent = request.headers.get("user-agent", "").lower()
    is_mobile = any(
        token in user_agent for token in ("iphone", "android", "mobile", "ipad", "ipod")
    )
    target = "index.html" if is_mobile else "desktop.html"
    return FileResponse(os.path.join(_static_dir, target))


@app.get("/mobile")
async def mobile_ui() -> FileResponse:
    return FileResponse(os.path.join(_static_dir, "index.html"))


@app.get("/desktop")
async def desktop_ui() -> FileResponse:
    return FileResponse(os.path.join(_static_dir, "desktop.html"))


@app.get("/sw.js")
async def service_worker() -> FileResponse:
    return FileResponse(
        os.path.join(_static_dir, "sw.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class FeedbackRequest(BaseModel):
    coffee_data: dict[str, Any]
    recommendation: str
    actual_grind: str | None = None
    dose_g: float | None = None


class EquipmentUpdate(BaseModel):
    brand: str
    model: str


class DoseUpdate(BaseModel):
    dose_g: float


class GrindOffsetUpdate(BaseModel):
    offset_clicks: float


class LogDetailsInput(BaseModel):
    grind_setting: str | None = None
    dose_g: float | None = None
    yield_g: float | None = None
    time_s: int | None = None
    rating: int | None = None
    tasting_notes: str | None = None


class BeanRecordInput(BaseModel):
    roaster: str
    name: str
    origin: str
    process: str
    roast_level: str
    log: LogDetailsInput | None = None


# ── API endpoints ─────────────────────────────────────────────────────────────


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
        _save_dial_in_log(
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
        grinder = db.query(Equipment).filter(Equipment.type == "grinder").first()
        machine = (
            db.query(Equipment).filter(Equipment.type == "espresso_machine").first()
        )
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
        grinder = db.query(Equipment).filter(Equipment.type == "grinder").first()
        if grinder:
            grinder.brand = body.brand
            grinder.model = body.model
        else:
            db.add(Equipment(type="grinder", brand=body.brand, model=body.model))
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
        machine = (
            db.query(Equipment).filter(Equipment.type == "espresso_machine").first()
        )
        if machine:
            machine.brand = body.brand
            machine.model = body.model
        else:
            db.add(
                Equipment(type="espresso_machine", brand=body.brand, model=body.model)
            )
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


def _ensure_default_equipment(db: Any) -> tuple[Any, Any]:
    grinder = db.query(Equipment).filter(Equipment.type == "grinder").first()
    machine = db.query(Equipment).filter(Equipment.type == "espresso_machine").first()
    if not grinder:
        grinder = Equipment(type="grinder", brand="Unknown", model="Unknown")
        db.add(grinder)
    if not machine:
        machine = Equipment(type="espresso_machine", brand="Unknown", model="Unknown")
        db.add(machine)
    db.commit()
    db.refresh(grinder)
    db.refresh(machine)
    return grinder, machine


def _resolve_log_values(log: LogDetailsInput | None, db: Any) -> dict[str, Any]:
    default_dose = get_default_dose_g(db)
    dose = default_dose
    if log and log.dose_g is not None and log.dose_g > 0:
        dose = float(log.dose_g)
    yield_g = round(dose * 2.0, 1)
    if log and log.yield_g is not None and log.yield_g > 0:
        yield_g = float(log.yield_g)
    time_s = 28
    if log and log.time_s is not None and log.time_s > 0:
        time_s = int(log.time_s)
    rating = 5
    if log and log.rating is not None:
        rating = max(1, min(5, int(log.rating)))
    grind_setting = "Unknown"
    if log and log.grind_setting:
        grind_setting = log.grind_setting.strip() or "Unknown"
    notes = None
    if log and log.tasting_notes:
        notes = log.tasting_notes.strip() or None
    return {
        "dose_g": dose,
        "yield_g": yield_g,
        "time_s": time_s,
        "rating": rating,
        "grind_setting": grind_setting,
        "tasting_notes": notes,
    }


@app.post("/api/logs/manual")
async def create_manual_log(body: BeanRecordInput) -> dict[str, Any]:
    db = SessionLocal()
    try:
        bean = Bean(
            roaster=_as_non_empty_text(body.roaster),
            name=_as_non_empty_text(body.name),
            origin=_as_non_empty_text(body.origin),
            process=_as_non_empty_text(body.process),
            roast_level=_as_non_empty_text(body.roast_level),
        )
        db.add(bean)
        db.commit()
        db.refresh(bean)

        grinder, machine = _ensure_default_equipment(db)
        values = _resolve_log_values(body.log, db)
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

        bean.roaster = _as_non_empty_text(body.roaster)
        bean.name = _as_non_empty_text(body.name)
        bean.origin = _as_non_empty_text(body.origin)
        bean.process = _as_non_empty_text(body.process)
        bean.roast_level = _as_non_empty_text(body.roast_level)

        latest_log = None
        if bean.logs:
            latest_log = max(bean.logs, key=lambda log: log.created_at)

        values = _resolve_log_values(body.log, db)
        if latest_log is None:
            grinder, machine = _ensure_default_equipment(db)
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


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("WEB_PORT", "8080"))
    uvicorn.run("core.web_server:app", host="0.0.0.0", port=port, reload=False)
