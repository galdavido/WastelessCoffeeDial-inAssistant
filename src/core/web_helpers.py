from __future__ import annotations

import os
import re
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from database.database import Base, SessionLocal, engine
from database.models import AppSetting, Bean, BrewSetup, DialInLog, Equipment

from .web_schemas import LogDetailsInput


def init_db() -> None:
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


def seed_db() -> None:
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


def ensure_tables() -> None:
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
        ensure_tables()
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
        ensure_tables()
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


def as_non_empty_text(value: Any, default: str = "Unknown") -> str:
    if value is None:
        return default
    text_value = str(value).strip()
    if not text_value or text_value.lower() == "none":
        return default
    return text_value


def normalize_label(value: str) -> str:
    lowered = value.strip().lower()
    deaccented = (
        unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode()
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", deaccented).split())


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_label(a), normalize_label(b)).ratio()


def find_existing_bean(
    db: Any, name: str, roaster: str, origin: str, process: str
) -> Any:
    exact = db.query(Bean).filter(Bean.name == name, Bean.roaster == roaster).first()
    if exact:
        return exact

    roaster_norm = normalize_label(roaster)
    name_norm = normalize_label(name)
    origin_norm = normalize_label(origin)
    process_norm = normalize_label(process)

    best_candidate, best_score = None, 0.0
    for candidate in db.query(Bean).all():
        if (
            roaster_norm != "unknown"
            and normalize_label(str(candidate.roaster)) != roaster_norm
        ):
            continue
        score = similarity(name, str(candidate.name))
        if normalize_label(str(candidate.name)) == name_norm:
            score = 1.0
        if (
            origin_norm != "unknown"
            and normalize_label(str(candidate.origin)) not in ("unknown",)
            and normalize_label(str(candidate.origin)) == origin_norm
        ):
            score += 0.05
        if (
            process_norm != "unknown"
            and normalize_label(str(candidate.process)) not in ("unknown",)
            and normalize_label(str(candidate.process)) == process_norm
        ):
            score += 0.05
        if score > best_score:
            best_score = score
            best_candidate = candidate

    return best_candidate if best_candidate and best_score >= 0.9 else None


def ensure_default_equipment(db: Any) -> tuple[Any, Any]:
    grinder = db.query(Equipment).filter(Equipment.type == "grinder").first()
    machine = db.query(Equipment).filter(Equipment.type != "grinder").first()
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


def serialize_equipment(item: Equipment) -> dict[str, Any]:
    return {
        "id": item.id,
        "type": item.type,
        "brand": item.brand,
        "model": item.model,
    }


def get_setting(db: Any, key: str) -> str | None:
    setting = db.query(AppSetting).filter(AppSetting.key == key).first()
    return setting.value if setting else None


def set_setting(db: Any, key: str, value: str) -> None:
    setting = db.query(AppSetting).filter(AppSetting.key == key).first()
    if setting:
        setting.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


def ensure_default_setup(db: Any) -> BrewSetup:
    setup = db.query(BrewSetup).order_by(BrewSetup.id.asc()).first()
    if setup:
        return setup

    grinder, machine = ensure_default_equipment(db)
    setup = BrewSetup(
        name="Default Setup", grinder_id=grinder.id, machine_id=machine.id
    )
    db.add(setup)
    db.commit()
    db.refresh(setup)
    return setup


def get_active_setup(db: Any) -> BrewSetup:
    fallback = ensure_default_setup(db)
    setting_value = get_setting(db, "active_setup_id")
    if setting_value:
        try:
            setup_id = int(setting_value)
            existing = db.query(BrewSetup).filter(BrewSetup.id == setup_id).first()
            if existing:
                return existing
        except ValueError:
            pass
    set_setting(db, "active_setup_id", str(fallback.id))
    return fallback


def serialize_setup(setup: BrewSetup) -> dict[str, Any]:
    return {
        "id": setup.id,
        "name": setup.name,
        "grinder": serialize_equipment(setup.grinder),
        "machine": serialize_equipment(setup.machine),
    }


def resolve_log_values(log: LogDetailsInput | None, db: Any) -> dict[str, Any]:
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


def save_dial_in_log(
    coffee_data: dict[str, Any],
    recommendation: str,
    actual_grind: str | None = None,
    dose_g: float | None = None,
) -> None:
    db = SessionLocal()
    try:
        bean_name = as_non_empty_text(coffee_data.get("name"))
        bean_roaster = as_non_empty_text(coffee_data.get("roaster"))
        bean_origin = as_non_empty_text(coffee_data.get("origin"))
        bean_process = as_non_empty_text(coffee_data.get("process"))
        bean_roast_level = as_non_empty_text(coffee_data.get("roast_level"))

        bean = find_existing_bean(
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

        active_setup = get_active_setup(db)
        grinder = active_setup.grinder if active_setup else None
        machine = active_setup.machine if active_setup else None
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


def generate_app_icons(static_dir: str) -> None:
    """Generate PNG app icons from Pillow for PWA / iOS home screen.

    Runs at startup; silently skipped if icons already exist or if the
    filesystem is read-only (production containers pre-bake icons via
    the Dockerfile RUN step instead).
    """

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return

    icons_dir = os.path.join(static_dir, "icons")
    try:
        os.makedirs(icons_dir, exist_ok=True)
    except OSError:
        return

    bg = (15, 10, 6)
    accent = (200, 134, 10)

    for size in (180, 192, 512):
        path = os.path.join(icons_dir, f"icon-{size}.png")
        if os.path.exists(path):
            continue
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        r = size // 5
        draw.rounded_rectangle([0, 0, size, size], radius=r, fill=bg)

        pad = size // 6
        draw.ellipse([pad, pad, size - pad, size - pad], fill=accent)

        cx, cy = size // 2, size // 2
        cup_w = size // 3
        cup_h = int(size * 0.28)
        cup_x = cx - cup_w // 2
        cup_y = cy - cup_h // 2 + size // 20
        draw.rectangle([cup_x, cup_y, cup_x + cup_w, cup_y + cup_h], fill="white")

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
            return
