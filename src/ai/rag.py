# import os
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
        lines.append(f"  Setting: {log.grind_setting} clicks, Dose: {log.dose_g}g")
        lines.append(f"  Notes: {log.tasting_notes}")
        lines.append("")

    return "\n".join(lines)


def _normalize_coffee_profile(coffee_json: Dict[str, Any]) -> CoffeeProfile:
    return {
        "name": str(coffee_json.get("name", "")),
        "origin": str(coffee_json.get("origin", "")),
        "process": str(coffee_json.get("process", "")),
        "roast_level": str(coffee_json.get("roast_level", "")),
        "roast_date": str(coffee_json.get("roast_date", "")),
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
        - Roast: {profile["roast_level"]}, {profile["roast_date"]}

        The user's equipment: {equipment_info}

        Here are the user's own past data from their log (RAG Database Context):
        ---
        {db_context}
        ---

        YOUR TASK:
        Give a specific, practical starting recipe (Dose, grinder clicks, Temperature)!

        RULES:
        1. If the "RAG Database Context" contains data for the user's equipment, then PRIMARILY rely on those setting values!
        2. If the context is empty, use your own general barista knowledge! (Tip: For espresso, aim for 25-30 second extraction times with 18-20g in, 36g out. Adjust grind finer for lighter roasts, coarser for darker).
        3. Formulate briefly, friendly, in English.
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
