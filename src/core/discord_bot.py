import asyncio
import discord
from difflib import SequenceMatcher
import os
import re
import tempfile
import time
import unicodedata
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from ai.vision import analyze_coffee_bag
from ai.rag import get_best_grind_setting
from database.database import SessionLocal, engine, Base
from database.models import AppSetting, Bean, Equipment, DialInLog
from core.optional_deps import load_dotenv_if_available
from typing import Any, Dict

load_dotenv_if_available()


# Initialize the database on startup
def init_db():
    for attempt in range(1, 6):
        try:
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                conn.commit()
            Base.metadata.create_all(bind=engine)
            print("Database tables created.")
            return
        except Exception as e:
            print(f"DB init error (attempt {attempt}/5): {e}")
            if attempt < 5:
                time.sleep(2)


def ensure_tables_exist() -> None:
    Base.metadata.create_all(bind=engine)


# Seed data (simplified)
def seed_db():
    db = SessionLocal()
    try:
        if not db.query(Equipment).first():
            machine = Equipment(
                type="espresso_machine", brand="AVX", model="Hero Plus 2024"
            )
            grinder = Equipment(type="grinder", brand="Kingrinder", model="K6")
            db.add_all([machine, grinder])
            db.commit()
            print("Basic equipment added.")
    except Exception as e:
        print(f"Seed error: {e}")
    finally:
        db.close()


# Run the init
init_db()
seed_db()

intents = discord.Intents.default()  # type: ignore[reportUnknownMemberType]
intents.message_content = True  # type: ignore[reportUnknownMemberType]
client = discord.Client(intents=intents)  # type: ignore[reportUnknownArgumentType]


@client.event
async def on_ready():
    print(f"WCDA Discord Bot logged in as {client.user}")  # type: ignore[reportUnknownMemberType]


def get_default_dose_g(db: Any) -> float:
    try:
        setting = (
            db.query(AppSetting).filter(AppSetting.key == "default_dose_g").first()
        )
    except ProgrammingError as e:
        if "app_settings" not in str(e):
            raise
        db.rollback()  # type: ignore[reportUnknownMemberType]
        ensure_tables_exist()
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
    except ProgrammingError as e:
        if "app_settings" not in str(e):
            raise
        db.rollback()  # type: ignore[reportUnknownMemberType]
        ensure_tables_exist()
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


def set_grind_offset_clicks(db: Any, offset_clicks: float) -> None:
    setting = (
        db.query(AppSetting)
        .filter(AppSetting.key == "default_grind_offset_clicks")
        .first()
    )
    if setting:
        setting.value = str(offset_clicks)
    else:
        db.add(AppSetting(key="default_grind_offset_clicks", value=str(offset_clicks)))
    db.commit()


def _as_non_empty_text(value: Any, default: str = "Unknown") -> str:
    if value is None:
        return default
    text_value = str(value).strip()
    if not text_value or text_value.lower() == "none":
        return default
    return text_value


def _normalize_label(value: str) -> str:
    lowered = value.strip().lower()
    deaccented = (
        unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode()
    )
    cleaned = re.sub(r"[^a-z0-9]+", " ", deaccented)
    return " ".join(cleaned.split())


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_label(a), _normalize_label(b)).ratio()


def _find_existing_bean(
    db: Any,
    name: str,
    roaster: str,
    origin: str,
    process: str,
) -> Any:
    # 1) Fast exact lookup
    exact = (
        db.query(Bean)
        .filter(  # type: ignore[reportUnknownMemberType]
            Bean.name == name,
            Bean.roaster == roaster,
        )
        .first()
    )
    if exact:
        return exact

    roaster_norm = _normalize_label(roaster)
    name_norm = _normalize_label(name)
    origin_norm = _normalize_label(origin)
    process_norm = _normalize_label(process)

    # 2) OCR-tolerant fuzzy match among same roaster candidates
    candidates = db.query(Bean).all()  # type: ignore[reportUnknownMemberType]
    best_candidate = None
    best_score = 0.0

    for candidate in candidates:
        candidate_roaster_norm = _normalize_label(str(candidate.roaster))
        if roaster_norm != "unknown" and candidate_roaster_norm != roaster_norm:
            continue

        candidate_name = str(candidate.name)
        score = _similarity(name, candidate_name)

        candidate_name_norm = _normalize_label(candidate_name)
        if candidate_name_norm == name_norm:
            score = 1.0

        candidate_origin_norm = _normalize_label(str(candidate.origin))
        if (
            origin_norm != "unknown"
            and candidate_origin_norm != "unknown"
            and candidate_origin_norm == origin_norm
        ):
            score += 0.05

        candidate_process_norm = _normalize_label(str(candidate.process))
        if (
            process_norm != "unknown"
            and candidate_process_norm != "unknown"
            and candidate_process_norm == process_norm
        ):
            score += 0.05

        if score > best_score:
            best_score = score
            best_candidate = candidate

    # High threshold to avoid accidental merges.
    if best_candidate is not None and best_score >= 0.9:
        return best_candidate

    return None


async def save_dial_in_log(
    coffee_data: Dict[str, Any],
    recommendation: str,
    user_name: str,
    actual_grind: str | None = None,
    dose_g: float | None = None,
):
    """Save new log to database (simplified)"""
    db = SessionLocal()  # type: ignore[reportUnknownVariableType]
    try:
        bean_name = _as_non_empty_text(coffee_data.get("name"))
        bean_roaster = _as_non_empty_text(coffee_data.get("roaster"))
        bean_origin = _as_non_empty_text(coffee_data.get("origin"))
        bean_process = _as_non_empty_text(coffee_data.get("process"))
        bean_roast_level = _as_non_empty_text(coffee_data.get("roast_level"))

        # Find or create the bean (fuzzy matching avoids duplicate rows from OCR variations)
        bean = _find_existing_bean(
            db,
            name=bean_name,
            roaster=bean_roaster,
            origin=bean_origin,
            process=bean_process,
        )
        if not bean:
            bean = Bean(  # type: ignore[reportUnknownVariableType]
                roaster=bean_roaster,
                name=bean_name,
                origin=bean_origin,
                process=bean_process,
                roast_level=bean_roast_level,
            )
            db.add(bean)  # type: ignore[reportUnknownMemberType]
            db.commit()  # type: ignore[reportUnknownMemberType]
            db.refresh(bean)  # type: ignore[reportUnknownMemberType]

        # Find the default equipment (assume it exists)
        grinder = db.query(Equipment).filter(Equipment.type == "grinder").first()  # type: ignore[reportUnknownMemberType]
        machine = (
            db.query(Equipment).filter(Equipment.type == "espresso_machine").first()
        )  # type: ignore[reportUnknownMemberType]
        if not grinder or not machine:
            return  # No equipment, don't save

        # Setting: if provided, use it, otherwise parse
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

        # Keep defaults practical when the user only confirms grind setting.
        estimated_yield_g = round(resolved_dose_g * 2.0, 1)
        estimated_time_s = 28

        log = DialInLog(  # type: ignore[reportUnknownVariableType]
            bean_id=bean.id,  # type: ignore[reportUnknownMemberType]
            grinder_id=grinder.id,  # type: ignore[reportUnknownMemberType]
            machine_id=machine.id,  # type: ignore[reportUnknownMemberType]
            grind_setting=grind_setting,
            dose_g=resolved_dose_g,
            yield_g=estimated_yield_g,
            time_s=estimated_time_s,
            rating=5,  # good feedback
            tasting_notes=f"Discord feedback: {user_name} - {recommendation[:100]}...",
        )
        db.add(log)  # type: ignore[reportUnknownMemberType]
        db.commit()  # type: ignore[reportUnknownMemberType]
    except Exception:
        db.rollback()  # type: ignore[reportUnknownMemberType]
        raise
    finally:
        db.close()  # type: ignore[reportUnknownMemberType]


@client.event
async def on_message(message: Any):
    author: Any = message.author  # type: ignore[assignment]
    if author == client.user:
        return

    if message.content == "!help":  # type: ignore[attr-defined]
        help_text = (
            "📘 **WCDA Bot Commands**\n"
            "• `!help` - Show this help message\n"
            "• `!set_grinder <brand> <model>` - Set your grinder\n"
            "• `!set_machine <brand> <model>` - Set your espresso machine\n"
            "• `!show_equipment` - Show current grinder and machine\n"
            "• `!set_dose <grams>` - Set default dose (example: `!set_dose 16`)\n"
            "• `!show_dose` - Show current default dose\n\n"
            "• `!set_grind_offset <clicks>` - Set grind calibration offset (example: `!set_grind_offset -2`)\n"
            "• `!show_grind_offset` - Show current grind offset\n\n"
            "☕ To get a recommendation: upload a coffee bag photo."
        )
        await message.reply(help_text)  # type: ignore[reportUnknownMemberType]
        return

    # Handle equipment setting commands
    if message.content.startswith("!set_grinder "):  # type: ignore[attr-defined]
        parts = message.content.split(" ", 2)  # type: ignore[attr-defined]
        if len(parts) >= 3:
            brand = parts[1]
            model = " ".join(parts[2:])  # In case model has spaces
            db = SessionLocal()
            try:
                grinder = (
                    db.query(Equipment).filter(Equipment.type == "grinder").first()
                )
                if grinder:
                    grinder.brand = brand
                    grinder.model = model  # type: ignore[assignment]
                else:
                    grinder = Equipment(type="grinder", brand=brand, model=model)
                    db.add(grinder)
                db.commit()
                await message.reply(f"✅ Grinder updated to {brand} {model}")  # type: ignore[reportUnknownMemberType]
            except Exception as e:
                await message.reply(f"❌ Error updating grinder: {e}")  # type: ignore[reportUnknownMemberType]
            finally:
                db.close()
        else:
            await message.reply("❌ Usage: !set_grinder <brand> <model>")  # type: ignore[reportUnknownMemberType]
        return

    if message.content.startswith("!set_machine "):  # type: ignore[attr-defined]
        parts = message.content.split(" ", 2)  # type: ignore[attr-defined]
        if len(parts) >= 3:
            brand = parts[1]
            model = " ".join(parts[2:])
            db = SessionLocal()
            try:
                machine = (
                    db.query(Equipment)
                    .filter(Equipment.type == "espresso_machine")
                    .first()
                )
                if machine:
                    machine.brand = brand
                    machine.model = model  # type: ignore[assignment]
                else:
                    machine = Equipment(
                        type="espresso_machine", brand=brand, model=model
                    )
                    db.add(machine)
                db.commit()
                await message.reply(f"✅ Espresso machine updated to {brand} {model}")  # type: ignore[reportUnknownMemberType]
            except Exception as e:
                await message.reply(f"❌ Error updating machine: {e}")  # type: ignore[reportUnknownMemberType]
            finally:
                db.close()
        else:
            await message.reply("❌ Usage: !set_machine <brand> <model>")  # type: ignore[reportUnknownMemberType]
        return

    if message.content == "!show_equipment":  # type: ignore[attr-defined]
        db = SessionLocal()
        try:
            grinder = db.query(Equipment).filter(Equipment.type == "grinder").first()
            machine = (
                db.query(Equipment).filter(Equipment.type == "espresso_machine").first()
            )
            grinder_info = f"{grinder.brand} {grinder.model}" if grinder else "Not set"
            machine_info = f"{machine.brand} {machine.model}" if machine else "Not set"
            await message.reply(
                f"🔧 **Current Equipment:**\n• Grinder: {grinder_info}\n• Espresso Machine: {machine_info}"
            )  # type: ignore[reportUnknownMemberType]
        except Exception as e:
            await message.reply(f"❌ Error retrieving equipment: {e}")  # type: ignore[reportUnknownMemberType]
        finally:
            db.close()
        return

    if message.content.startswith("!set_dose "):  # type: ignore[attr-defined]
        parts = message.content.split(" ", 1)  # type: ignore[attr-defined]
        if len(parts) == 2:
            raw_value = parts[1].strip().lower().replace("g", "")
            try:
                dose = float(raw_value)
                if dose <= 0:
                    raise ValueError("Dose must be positive")
            except Exception:
                await message.reply(
                    "❌ Usage: !set_dose <grams> (example: !set_dose 16)"
                )  # type: ignore[reportUnknownMemberType]
                return

            db = SessionLocal()
            try:
                set_default_dose_g(db, dose)
                await message.reply(f"✅ Default dose updated to {dose:.1f}g")  # type: ignore[reportUnknownMemberType]
            except Exception as e:
                await message.reply(f"❌ Error updating dose: {e}")  # type: ignore[reportUnknownMemberType]
            finally:
                db.close()
        else:
            await message.reply("❌ Usage: !set_dose <grams> (example: !set_dose 16)")  # type: ignore[reportUnknownMemberType]
        return

    if message.content == "!show_dose":  # type: ignore[attr-defined]
        db = SessionLocal()
        try:
            dose = get_default_dose_g(db)
            await message.reply(f"⚖️ Current default dose: {dose:.1f}g")  # type: ignore[reportUnknownMemberType]
        except Exception as e:
            await message.reply(f"❌ Error retrieving dose: {e}")  # type: ignore[reportUnknownMemberType]
        finally:
            db.close()
        return

    if message.content.startswith("!set_grind_offset "):  # type: ignore[attr-defined]
        parts = message.content.split(" ", 1)  # type: ignore[attr-defined]
        if len(parts) == 2:
            raw_value = (
                parts[1].strip().lower().replace("clicks", "").replace("click", "")
            )
            try:
                offset = float(raw_value)
            except Exception:
                await message.reply(
                    "❌ Usage: !set_grind_offset <clicks> (example: !set_grind_offset -2)"
                )  # type: ignore[reportUnknownMemberType]
                return

            db = SessionLocal()
            try:
                set_grind_offset_clicks(db, offset)
                await message.reply(f"✅ Grind offset updated to {offset:+.1f} clicks")  # type: ignore[reportUnknownMemberType]
            except Exception as e:
                await message.reply(f"❌ Error updating grind offset: {e}")  # type: ignore[reportUnknownMemberType]
            finally:
                db.close()
        else:
            await message.reply(
                "❌ Usage: !set_grind_offset <clicks> (example: !set_grind_offset -2)"
            )  # type: ignore[reportUnknownMemberType]
        return

    if message.content == "!show_grind_offset":  # type: ignore[attr-defined]
        db = SessionLocal()
        try:
            offset = get_grind_offset_clicks(db)
            await message.reply(f"🎯 Current grind offset: {offset:+.1f} clicks")  # type: ignore[reportUnknownMemberType]
        except Exception as e:
            await message.reply(f"❌ Error retrieving grind offset: {e}")  # type: ignore[reportUnknownMemberType]
        finally:
            db.close()
        return

    # If there is an attachment (image), and it's an image file
    if message.attachments:  # type: ignore[reportUnknownMemberType]
        for attachment in message.attachments:  # type: ignore[reportUnknownMemberType]
            if attachment.content_type and attachment.content_type.startswith("image/"):  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                # Download the image to a temp file
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".jpg"
                ) as temp_file:
                    await attachment.save(temp_file.name)  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                    temp_path = temp_file.name

                try:
                    # Analysis
                    coffee_data = analyze_coffee_bag(temp_path)
                    if not coffee_data:
                        await message.reply(
                            "❌ Failed to extract data from the image. Try again with a better quality photo!"
                        )  # type: ignore[reportUnknownMemberType]
                        return

                    db = SessionLocal()
                    try:
                        default_dose_g = get_default_dose_g(db)
                        grind_offset_clicks = get_grind_offset_clicks(db)
                    finally:
                        db.close()

                    coffee_data["preferred_dose_g"] = default_dose_g
                    coffee_data["preferred_grind_offset_clicks"] = grind_offset_clicks

                    # RAG search
                    recommendation = get_best_grind_setting(coffee_data)

                    # Response
                    coffee_info = (
                        f"☕ **{coffee_data.get('roaster', 'Unknown')} {coffee_data.get('name', 'Unknown')} {coffee_data.get('roast_date', 'Unknown')}**\n"
                        f"🌍 {coffee_data.get('origin', 'Unknown')} | {coffee_data.get('process', 'Unknown')} | {coffee_data.get('roast_level', 'Unknown')}"
                    )

                    response = f"{coffee_info}\n\n💡 **Recommendation from the database:**\n{recommendation}\n\n👍 If it was good, react with thumbs up to save this setting!"

                    sent_message = await message.reply(response)  # type: ignore[reportUnknownMemberType]

                    # Wait for reaction (simple feedback)
                    def check(reaction: Any, user: Any) -> bool:
                        return (
                            user == author
                            and str(reaction.emoji) == "👍"
                            and reaction.message.id == sent_message.id
                        )  # type: ignore[reportUnknownMemberType]

                    try:
                        _, user = await client.wait_for(
                            "reaction_add", timeout=300.0, check=check
                        )  # 5 minutes  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                        # If thumbs up, ask for the actual setting
                        await message.reply(
                            "👍 Great! What was the actual grind setting you used? Reply e.g. '36 clicks' or 'fine'."
                        )  # type: ignore[reportUnknownMemberType]

                        # Wait for the response
                        def msg_check(m: Any) -> bool:
                            return m.author == user and m.channel == message.channel  # type: ignore[reportUnknownMemberType]

                        try:
                            reply = await client.wait_for(
                                "message", timeout=120.0, check=msg_check
                            )  # 2 minutes  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                        except asyncio.TimeoutError:
                            # If no response, save the default
                            try:
                                await save_dial_in_log(
                                    coffee_data,
                                    recommendation,
                                    author.name,
                                    dose_g=default_dose_g,
                                )  # type: ignore[arg-type]
                                await message.reply(
                                    "⏰ Timeout. Saved the default recommendation."
                                )  # type: ignore[reportUnknownMemberType]
                            except Exception as e:
                                await message.reply(
                                    f"❌ Failed to save the default setting: {e}"
                                )  # type: ignore[reportUnknownMemberType]
                        else:
                            actual_grind = reply.content.strip()
                            try:
                                await save_dial_in_log(
                                    coffee_data,
                                    recommendation,
                                    author.name,
                                    actual_grind,
                                    default_dose_g,
                                )  # type: ignore[arg-type]
                                await message.reply(
                                    f"✅ Saved: '{actual_grind}' setting to the database!"
                                )  # type: ignore[reportUnknownMemberType]
                            except Exception as e:
                                await message.reply(
                                    f"❌ Failed to save your setting: {e}"
                                )  # type: ignore[reportUnknownMemberType]
                    except Exception:
                        pass  # Timeout or didn't react

                finally:
                    # Delete the temp file
                    os.unlink(temp_path)


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("DISCORD_TOKEN not set!")
        exit(1)
    client.run(token)
