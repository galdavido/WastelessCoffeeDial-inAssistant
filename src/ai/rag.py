from datetime import date, datetime
import re
from statistics import median
from typing import Any, Dict, Sequence, TypedDict
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from ai.model_selection import GEMINI_MODEL_CANDIDATES, try_model_candidates
from core.optional_deps import require_genai
from database.database import SessionLocal
from database.models import AppSetting, Bean, BrewSetup, DialInLog, Equipment


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
    preferred_grind_offset_clicks: float | None


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


def _to_normalized(value: str) -> str:
    return value.strip().lower()


def _get_active_setup_equipment(
    db: Session,
) -> tuple[Equipment | None, Equipment | None]:
    active_setup_id: int | None = None
    active_setting = db.scalars(
        select(AppSetting).where(AppSetting.key == "active_setup_id").limit(1)
    ).first()
    if active_setting:
        try:
            active_setup_id = int(active_setting.value)
        except (TypeError, ValueError):
            active_setup_id = None

    active_setup: BrewSetup | None = None
    if active_setup_id is not None:
        active_setup = db.scalars(
            select(BrewSetup).where(BrewSetup.id == active_setup_id).limit(1)
        ).first()

    if active_setup is None:
        active_setup = db.scalars(
            select(BrewSetup).order_by(BrewSetup.id.asc())
        ).first()

    if active_setup is None:
        return None, None

    grinder = db.scalars(
        select(Equipment).where(Equipment.id == active_setup.grinder_id).limit(1)
    ).first()
    machine = db.scalars(
        select(Equipment).where(Equipment.id == active_setup.machine_id).limit(1)
    ).first()
    return grinder, machine


def _rank_similar_logs_for_active_setup(
    similar_logs: Sequence[SimilarLogRow],
    grinder: Equipment | None,
    machine: Equipment | None,
    limit: int = 12,
) -> list[SimilarLogRow]:
    if not similar_logs:
        return []

    grinder_brand = _to_normalized(grinder.brand) if grinder else None
    grinder_model = _to_normalized(grinder.model) if grinder else None
    machine_brand = _to_normalized(machine.brand) if machine else None
    machine_model = _to_normalized(machine.model) if machine else None

    def equipment_score(row: SimilarLogRow) -> int:
        _, _, row_grinder, row_machine = row
        score = 0

        if grinder_brand and grinder_model:
            if (
                _to_normalized(row_grinder.brand) == grinder_brand
                and _to_normalized(row_grinder.model) == grinder_model
            ):
                score += 2

        if machine_brand and machine_model:
            if (
                _to_normalized(row_machine.brand) == machine_brand
                and _to_normalized(row_machine.model) == machine_model
            ):
                score += 2

        return score

    ranked = sorted(
        similar_logs,
        key=lambda row: (equipment_score(row), row[0].created_at),
        reverse=True,
    )
    return ranked[:limit]


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

    preferred_grind_offset_clicks: float | None = None
    raw_offset = coffee_json.get("preferred_grind_offset_clicks")
    if raw_offset is not None:
        try:
            preferred_grind_offset_clicks = float(raw_offset)
        except (TypeError, ValueError):
            preferred_grind_offset_clicks = None

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
        "preferred_grind_offset_clicks": preferred_grind_offset_clicks,
    }


def _extract_click_value(text: str) -> float | None:
    cleaned = text.strip().lower()
    if not cleaned:
        return None

    number_match = re.search(r"-?\d+(?:[\.,]\d+)?", cleaned)
    if not number_match:
        return None

    raw = number_match.group(0).replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _get_historical_clicks(
    similar_logs: Sequence[SimilarLogRow],
    grinder: Equipment | None,
) -> list[float]:
    if not similar_logs:
        return []

    if grinder is None:
        return [
            value
            for log, _, _, _ in similar_logs
            for value in [_extract_click_value(log.grind_setting)]
            if value is not None
        ]

    current_brand = grinder.brand.strip().lower()
    current_model = grinder.model.strip().lower()

    same_grinder_values = [
        value
        for log, _, log_grinder, _ in similar_logs
        if log_grinder.brand.strip().lower() == current_brand
        and log_grinder.model.strip().lower() == current_model
        for value in [_extract_click_value(log.grind_setting)]
        if value is not None
    ]
    if same_grinder_values:
        return same_grinder_values

    return [
        value
        for log, _, _, _ in similar_logs
        for value in [_extract_click_value(log.grind_setting)]
        if value is not None
    ]


def _build_grind_guardrails(
    similar_logs: Sequence[SimilarLogRow],
    grinder: Equipment | None,
    latest_successful_click: float | None,
) -> tuple[str, tuple[float, float] | None, float | None]:
    click_values = _get_historical_clicks(similar_logs, grinder)

    if click_values:
        anchor = float(median(click_values))
        min_click = min(click_values)
        max_click = max(click_values)
        lower = min(min_click, anchor - 4.0)
        upper = max(max_click, anchor + 4.0)
        return (
            (
                "Grind guardrail: prioritize user's historical grinder range. "
                f"Anchor around {anchor:.1f} clicks, keep initial recommendation within "
                f"{lower:.1f}-{upper:.1f} clicks unless there is a strong explicit reason."
            ),
            (lower, upper),
            anchor,
        )

    if latest_successful_click is not None:
        lower = max(0.0, latest_successful_click - 3.0)
        upper = latest_successful_click + 3.0
        return (
            (
                "Grind guardrail fallback: use latest successful shot as anchor. "
                f"Anchor around {latest_successful_click:.1f} clicks and keep recommendation "
                f"within {lower:.1f}-{upper:.1f} clicks unless clear evidence suggests otherwise."
            ),
            (lower, upper),
            latest_successful_click,
        )

    if (
        grinder
        and grinder.brand.strip().lower() == "kingrinder"
        and grinder.model.strip().lower() == "k6"
    ):
        return (
            (
                "Grind guardrail for Kingrinder K6: start near 35 clicks for espresso "
                "and stay in a conservative 30-40 click range unless user asks otherwise."
            ),
            (30.0, 40.0),
            35.0,
        )

    return (
        "No grinder-specific numeric history found; keep recommendation conservative and avoid extreme click values.",
        None,
        None,
    )


def _clamp_grind_recommendation(
    response_text: str,
    click_bounds: tuple[float, float] | None,
) -> str:
    if click_bounds is None:
        return response_text

    lower, upper = click_bounds
    pattern = r"(Suggested Grind Setting:\s*)(-?\d+(?:[\.,]\d+)?)"
    match = re.search(pattern, response_text)

    if not match:
        return response_text

    try:
        current = float(match.group(2).replace(",", "."))
    except ValueError:
        return response_text

    clamped = min(max(current, lower), upper)
    if clamped == current:
        return response_text

    clamped_text = f"{clamped:.1f}" if not clamped.is_integer() else str(int(clamped))
    updated = re.sub(pattern, f"\\1{clamped_text}", response_text, count=1)
    note = f"\n\nNote: Grind setting was adjusted to stay within guardrails ({lower:.1f}-{upper:.1f} clicks)."
    return updated + note


def _apply_grind_offset(
    response_text: str,
    offset_clicks: float | None,
    click_bounds: tuple[float, float] | None,
) -> str:
    if offset_clicks is None or offset_clicks == 0:
        return response_text

    pattern = r"(Suggested Grind Setting:\s*)(-?\d+(?:[\.,]\d+)?)"
    match = re.search(pattern, response_text)
    if not match:
        return response_text

    try:
        current = float(match.group(2).replace(",", "."))
    except ValueError:
        return response_text

    adjusted = current + offset_clicks
    if click_bounds is not None:
        lower, upper = click_bounds
        adjusted = min(max(adjusted, lower), upper)

    adjusted_text = (
        f"{adjusted:.1f}" if not adjusted.is_integer() else str(int(adjusted))
    )
    updated = re.sub(pattern, f"\\1{adjusted_text}", response_text, count=1)
    note = f"\n\nNote: Applied your grind offset ({offset_clicks:+.1f} clicks)."
    return updated + note


def _get_latest_successful_click(
    db: Session,
    grinder: Equipment | None,
) -> float | None:
    if grinder is None:
        return None

    latest_log = db.scalars(
        select(DialInLog)
        .where(DialInLog.grinder_id == grinder.id)
        .where(DialInLog.rating >= 4)
        .order_by(DialInLog.created_at.desc())
        .limit(1)
    ).first()

    if latest_log is None:
        return None
    return _extract_click_value(latest_log.grind_setting)


def _build_prompt(
    profile: CoffeeProfile,
    equipment_info: str,
    db_context: str,
    grind_guardrail: str,
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
        - Preferred grind offset: {profile["preferred_grind_offset_clicks"]} clicks

        The user's equipment: {equipment_info}

        Here are the user's own past data from their log (RAG Database Context):
        ---
        {db_context}
        ---

        Grind guardrails:
        - {grind_guardrail}

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
        8. If Preferred grind offset is provided, apply it as an additive correction to the recommended clicks.
        9. If the context is empty, use your own general barista knowledge! (Tip: For espresso, aim for 25-30 second extraction times with 18-20g in, 36g out. Adjust grind finer for lighter roasts, coarser for darker).
        10. Always include a line in this exact format: Suggested Grind Setting: <number> clicks
        11. Use grounded web facts when useful for coffee/origin/process specifics, but prioritize the user's own data when there is conflict.
        12. Formulate briefly, friendly, in English.
        """


def _generate_recommendation_with_grounding(genai: Any, types: Any, prompt: str) -> str:
    client = genai.Client()
    try:

        def evaluate_text(response: Any) -> tuple[bool, str | None]:
            if getattr(response, "text", None):
                return True, None
            return False, "empty response"

        grounded_result, grounded_error = try_model_candidates(
            GEMINI_MODEL_CANDIDATES,
            call_model=lambda model_name: client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            ),
            evaluate_result=evaluate_text,
        )
        if grounded_result is not None and grounded_result.text:
            return grounded_result.text

        plain_result, plain_error = try_model_candidates(
            GEMINI_MODEL_CANDIDATES,
            call_model=lambda model_name: client.models.generate_content(
                model=model_name,
                contents=prompt,
            ),
            evaluate_result=evaluate_text,
        )
        if plain_result is not None and plain_result.text:
            return plain_result.text

        return f"Error: {plain_error or grounded_error or 'Empty response received from AI Barista.'}"
    finally:
        client.close()


def get_best_grind_setting(coffee_json: Dict[str, Any]) -> str:
    """
    Retrieves own data, then calls the LLM to synthesize the final recommendation.
    """
    try:
        genai, types = require_genai()
    except RuntimeError as exc:
        return f"Error occurred during LLM augmentation: {exc}"

    db: Session = SessionLocal()
    try:
        profile = _normalize_coffee_profile(coffee_json)
        origin = profile["origin"]
        process = profile["process"]

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

        # Use active setup equipment, not "first equipment in DB".
        grinder, machine = _get_active_setup_equipment(db)
        equipment_info = _describe_equipment(grinder, machine)
        latest_successful_click = _get_latest_successful_click(db, grinder)
        ranked_similar_logs = _rank_similar_logs_for_active_setup(
            similar_logs,
            grinder,
            machine,
        )

        # 2. BUILDING CONTEXT FOR THE LLM
        db_context = _build_db_context(ranked_similar_logs)
        grind_guardrail, click_bounds, _ = _build_grind_guardrails(
            ranked_similar_logs,
            grinder,
            latest_successful_click,
        )

        # 3. GENERATION: LLM call for synthesis
        prompt = _build_prompt(profile, equipment_info, db_context, grind_guardrail)

        raw_text = _generate_recommendation_with_grounding(genai, types, prompt)
        offset_text = _apply_grind_offset(
            raw_text,
            profile["preferred_grind_offset_clicks"],
            click_bounds,
        )
        return _clamp_grind_recommendation(offset_text, click_bounds)

    except Exception as e:
        return f"Error occurred during LLM augmentation: {e}"
    finally:
        db.close()
