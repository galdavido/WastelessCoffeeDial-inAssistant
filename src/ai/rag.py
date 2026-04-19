# import os
from datetime import date, datetime
from typing import Any, Dict, Sequence, TypedDict
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from core.optional_deps import require_genai
from database.database import SessionLocal
from database.models import Bean, DialInLog, Equipment


type SimilarLogRow = tuple[DialInLog, Bean, Equipment, Equipment]


class CoffeeProfile(TypedDict):
    name: str
    origin: str
    process: str
    roast_level: str
    roast_date: str
    brew_date: str
    days_since_roast: int | None
    preferred_dose_g: float | None


def _parse_date(date_text: str) -> date | None:
    cleaned = date_text.strip()
    if not cleaned:
        return None

    # Accept common date formats from OCR/metadata.
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _describe_equipment(
    grinder: Equipment | None,
    machine: Equipment | None,
) -> str:
    if grinder and machine:
        return (
            f"{machine.brand} {machine.model} (espresso machine) and "
            f"{grinder.brand} {grinder.model} (grinder)."
        )
    if grinder:
        return (
            f"Unknown espresso machine and {grinder.brand} {grinder.model} (grinder)."
        )
    if machine:
        return (
            f"{machine.brand} {machine.model} (espresso machine) and unknown grinder."
        )
    return "Unknown equipment."


def _build_db_context(similar_logs: Sequence[SimilarLogRow]) -> str:
    if not similar_logs:
        return "The user's database is empty for this coffee profile. No previous experience."

    lines = ["The user's previous SUCCESSFUL settings for similar coffees:"]
    for log, bean, grinder, machine in similar_logs:
        lines.append(f"- Coffee: {bean.name} ({bean.origin}, {bean.process})")
        lines.append(f"  Grinder: {grinder.brand} {grinder.model}")
        lines.append(f"  Machine: {machine.brand} {machine.model}")
        lines.append(f"  Brew date: {log.created_at.date().isoformat()}")
        lines.append(f"  Setting: {log.grind_setting} clicks, Dose: {log.dose_g}g")
        lines.append(f"  Notes: {log.tasting_notes}")
        lines.append("")

    return "\n".join(lines)


def _normalize_coffee_profile(coffee_json: Dict[str, Any]) -> CoffeeProfile:
    roast_date_raw = str(coffee_json.get("roast_date", "")).strip()
    brew_date_raw = str(coffee_json.get("brew_date", "")).strip()

    roast_date_parsed = _parse_date(roast_date_raw)
    brew_date_parsed = _parse_date(brew_date_raw)

    if brew_date_parsed is None:
        brew_date_parsed = date.today()

    days_since_roast: int | None = None
    if roast_date_parsed is not None:
        delta_days = (brew_date_parsed - roast_date_parsed).days
        if delta_days >= 0:
            days_since_roast = delta_days

    preferred_dose_g: float | None = None
    raw_dose = coffee_json.get("preferred_dose_g")
    if raw_dose is not None:
        try:
            candidate = float(raw_dose)
            if candidate > 0:
                preferred_dose_g = candidate
        except (TypeError, ValueError):
            preferred_dose_g = None

    return {
        "name": str(coffee_json.get("name", "")),
        "origin": str(coffee_json.get("origin", "")),
        "process": str(coffee_json.get("process", "")),
        "roast_level": str(coffee_json.get("roast_level", "")),
        "roast_date": (
            roast_date_parsed.isoformat() if roast_date_parsed else roast_date_raw
        ),
        "brew_date": brew_date_parsed.isoformat(),
        "days_since_roast": days_since_roast,
        "preferred_dose_g": preferred_dose_g,
    }


def _build_prompt(
    profile: CoffeeProfile,
    equipment_info: str,
    db_context: str,
) -> str:
    return f"""
        You are a professional Head Barista. The user wants to dial in a new coffee:
        - Name: {profile["name"]}
        - Origin: {profile["origin"]}
        - Process: {profile["process"]}
        - Roast level: {profile["roast_level"]}
        - Roast date: {profile["roast_date"]}
        - Brew date: {profile["brew_date"]}
        - Days since roast: {profile["days_since_roast"]}
        - Preferred dose: {profile["preferred_dose_g"]}g

        The user's equipment: {equipment_info}

        Here are the user's own past data from their log (RAG Database Context):
        ---
        {db_context}
        ---

        YOUR TASK:
        Give a specific, practical starting recipe (Dose, grinder clicks, Temperature)!

        RULES:
        1. If the "RAG Database Context" contains data for the user's equipment, then PRIMARILY rely on those setting values!
        2. Always factor roast date and brew date into the recommendation. Use "Days since roast" to adapt the recipe.
        3. If Days since roast is 0-6, expect more CO2: suggest slightly coarser grind and/or lower temperature to reduce channeling and sourness.
        4. If Days since roast is 7-21, treat as normal peak window and prioritize balance.
        5. If Days since roast is >21, suggest slightly finer grind and/or higher extraction support (temperature, ratio) to recover sweetness and clarity.
        6. If roast date is missing or invalid, explicitly say so and use roast level + historical logs.
        7. If Preferred dose is provided, keep dose at that value in your recipe unless there is a strong reason to adjust.
        8. If the context is empty, use your own general barista knowledge! (Tip: For espresso, aim for 25-30 second extraction times with 18-20g in, 36g out. Adjust grind finer for lighter roasts, coarser for darker).
        9. Formulate briefly, friendly, in English.
        """


def get_best_grind_setting(coffee_json: Dict[str, Any]) -> str:
    """
    Retrieves own data, then calls the LLM to synthesize the final recommendation.
    """
    try:
        genai, _ = require_genai()
    except RuntimeError as exc:
        return f"Error occurred during LLM augmentation: {exc}"

    db: Session = SessionLocal()
    try:
        profile = _normalize_coffee_profile(coffee_json)
        origin = profile["origin"]
        process = profile["process"]

        print(f"\n🔍 2/A. Searching in own Postgres database ({origin}, {process})...")

        # 1. RETRIEVAL: Database query
        grinder_alias = aliased(Equipment)
        machine_alias = aliased(Equipment)
        similar_logs_stmt = (
            select(DialInLog, Bean, grinder_alias, machine_alias)
            .join(Bean, DialInLog.bean_id == Bean.id)
            .join(grinder_alias, DialInLog.grinder_id == grinder_alias.id)
            .join(machine_alias, DialInLog.machine_id == machine_alias.id)
            .where(DialInLog.rating >= 4)
            .where((Bean.process == process) | (Bean.origin == origin))
        )
        similar_logs: Sequence[SimilarLogRow] = (
            db.execute(similar_logs_stmt).tuples().all()
        )

        # Get current equipment
        grinder = db.scalars(
            select(Equipment).where(Equipment.type == "grinder")
        ).first()
        machine = db.scalars(
            select(Equipment).where(Equipment.type == "espresso_machine")
        ).first()
        equipment_info = _describe_equipment(grinder, machine)

        # 2. BUILDING CONTEXT FOR THE LLM
        db_context = _build_db_context(similar_logs)

        # 3. GENERATION: LLM call for synthesis
        print("🧠 2/B. Calling LLM Barista to supplement the data...")

        client = genai.Client()

        # The "System Prompt" that guides the AI's behavior
        prompt = _build_prompt(profile, equipment_info, db_context)

        response = client.models.generate_content(
            model="gemini-2.5-flash", contents=prompt
        )

        client.close()

        return response.text or "Error: Empty response received from AI Barista."

    except Exception as e:
        return f"Error occurred during LLM augmentation: {e}"
    finally:
        db.close()


if __name__ == "__main__":
    # Test run
    test_json: Dict[str, Any] = {
        "roaster": "Sample",
        "name": "Unknown Colombian",
        "origin": "Colombia",
        "process": "Anaerobic",
        "roast_level": "Light",
    }
    print(get_best_grind_setting(test_json))
