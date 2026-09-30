"""Helpers behind the routes: settings, parsing, coffee matching, shot rows."""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from database.models import (
    AppSetting,
    Bean,
    BrewSetup,
    DialInLog,
    Equipment,
    Recommendation,
    as_float,
)

from .brewing import ROAST_FILL, roast_fill, value_of
from .web_schemas import FeedbackRequest, LogDetailsInput

DEFAULT_DOSE_G = 16.0


def get_default_dose_g(db: Any, owner: str) -> float:
    """The user's stored default dose, or 16 g."""
    try:
        dose = float(get_setting(db, owner, "default_dose_g") or DEFAULT_DOSE_G)
    except ValueError:
        return DEFAULT_DOSE_G
    return dose if dose > 0 else DEFAULT_DOSE_G


def set_default_dose_g(db: Any, owner: str, dose: float) -> None:
    set_setting(db, owner, "default_dose_g", str(dose))


def as_non_empty_text(value: Any, default: str = "Unknown") -> str:
    if value is None:
        return default
    text_value = str(value).strip()
    if not text_value or text_value.lower() == "none":
        return default
    return text_value


_LEADING_NUMBER = re.compile(r"\s*(-?\d+(?:[.,]\d+)?)")

# 1 light .. 5 dark. Prod contains "Medium-light", "Medium Light" and
# "Medium-Light" for the same roast, so match on normalised labels. The trade
# names are the ones roasters print instead of a plain level.
_ROAST_ORDINALS: dict[str, int] = {
    "light": 1,
    "blonde": 1,
    "blond": 1,
    "cinnamon": 1,
    "nordic": 1,
    "scandinavian": 1,
    "medium light": 2,
    "light medium": 2,
    "medium": 3,
    "medium dark": 4,
    "dark medium": 4,
    "dark": 5,
    "french": 5,
    "italian": 5,
    "vienna": 5,
}


def parse_grind_clicks(value: str | float | None) -> float | None:
    """Numeric grind value from a free-text setting, or None if there isn't one.

    Historic rows hold strings like "38", "33 clicks" or "Unknown". Returning
    None for the unparseable case is deliberate -- a missing grind value must
    not become a number.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _LEADING_NUMBER.match(str(value))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def parse_roast_date(value: Any) -> date | None:
    """Parse the roast date vision extracts, tolerating the usual formats.

    Returns None rather than guessing: days-since-roast widens the acceptance
    bands, so a wrong date silently changes the advice.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in ("none", "unknown", "n/a"):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%Y.%m.%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def roast_level_ordinal(label: str | None) -> int | None:
    """Map a roast-level label onto the 1 (light) .. 5 (dark) ordinal scale."""
    if not label:
        return None
    key = normalize_label(label).removesuffix(" roast")
    return _ROAST_ORDINALS.get(key)


def starting_dose_for_roast(
    roast_level_ord: int | None, basket_size_g: float | None = None
) -> float | None:
    """A first-shot dose for this roast level, or None when it is unknown.

    A fill of the brewer's basket when its size is recorded, otherwise of an
    18 g reference basket -- which reproduces the old fixed table exactly.
    Rounded to half a gram: it is a first guess shown with a hint to adjust
    it, the basket guardrail still applies, and the user's own dose takes
    over from the first logged shot.
    """
    if roast_level_ord is None:
        return None
    if roast_level_ord not in ROAST_FILL:
        return None
    basket = basket_size_g or value_of("starting_reference_basket_g")
    return round(basket * roast_fill(roast_level_ord) * 2) / 2


def normalize_label(value: str) -> str:
    lowered = value.strip().lower()
    deaccented = (
        unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode()
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", deaccented).split())


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_label(a), normalize_label(b)).ratio()


def find_existing_bean(
    db: Any, owner: str, name: str, roaster: str, origin: str, process: str
) -> Any:
    exact = (
        db.query(Bean)
        .filter(Bean.owner == owner, Bean.name == name, Bean.roaster == roaster)
        .first()
    )
    if exact:
        return exact

    roaster_norm = normalize_label(roaster)
    name_norm = normalize_label(name)
    origin_norm = normalize_label(origin)
    process_norm = normalize_label(process)

    best_candidate, best_score = None, 0.0
    for candidate in db.query(Bean).filter(Bean.owner == owner).all():
        if (
            roaster_norm != "unknown"
            and normalize_label(str(candidate.roaster)) != roaster_norm
        ):
            continue
        score = _name_similarity(name, str(candidate.name))
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
    # Shared entries only: a new user's default setup points at the seeded
    # baseline hardware, never at something another friend added.
    shared = db.query(Equipment).filter(Equipment.owner.is_(None))
    grinder = shared.filter(Equipment.type == "grinder").order_by(Equipment.id).first()
    machine = shared.filter(Equipment.type != "grinder").order_by(Equipment.id).first()
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


def bean_coffee_data(bean: Bean) -> dict[str, Any]:
    """The coffee_data shape the rest of the API speaks, straight from a row.

    Used when recommending for a coffee already in the library, so the client
    never has to rebuild this payload from what it happens to have on screen.
    """
    return {
        "bean_id": bean.id,
        "name": bean.name,
        "roaster": bean.roaster,
        "origin": bean.origin,
        "process": bean.process,
        "roast_level": bean.roast_level,
        "roast_date": bean.roast_date.isoformat() if bean.roast_date else None,
    }


def latest_photo_log(logs: Any) -> DialInLog | None:
    """The most recent shot on a coffee that carries a bag photo, if any.

    The photo is taken once, on the first shot after a scan; every later shot
    is logged with no image. So a coffee's photo lives on an older log than its
    newest one, and the recents list must look past `latest_log` to find it --
    otherwise the card loses the photo the moment a second shot is recorded.
    """
    return max(
        (log for log in logs if log.image_path),
        key=lambda log: log.created_at,
        default=None,
    )


_CACHE_VERSION_RE = re.compile(r"const CACHE\s*=\s*'wcda-v(\d+)'")


def read_asset_version(static_dir: str) -> int | None:
    """The shipped bundle version, parsed from sw.js.

    sw.js's CACHE constant is the one hand-authored version number in the
    project; everything else derives from it. Returns None rather than a guess
    when it cannot be read, so the client shows no update prompt instead of a
    false one.
    """
    try:
        text = (Path(static_dir) / "sw.js").read_text(encoding="utf-8")
    except OSError:
        return None
    match = _CACHE_VERSION_RE.search(text)
    return int(match.group(1)) if match else None


def serialize_equipment(item: Equipment, owner: str | None = None) -> dict[str, Any]:
    return {
        "id": item.id,
        "type": item.type,
        "brand": item.brand,
        "model": item.model,
        # Only whoever added an entry may change it; shared ones are read-only.
        "shared": item.owner is None,
        "editable": owner is not None and item.owner == owner,
        # Capability data. Nulls are meaningful: where these are unknown the
        # engine abstains rather than guessing, so the UI shows them as gaps
        # worth filling rather than hiding them.
        "grind_min_clicks": as_float(item.grind_min_clicks),
        "grind_max_clicks": as_float(item.grind_max_clicks),
        "grind_step_clicks": as_float(item.grind_step_clicks),
        "grind_um_per_click": as_float(item.grind_um_per_click),
        "finer_direction": item.finer_direction,
        "burr_type": item.burr_type,
        "basket_size_g": as_float(item.basket_size_g),
        "temp_min_c": as_float(item.temp_min_c),
        "temp_max_c": as_float(item.temp_max_c),
        "temp_controllable": bool(item.temp_controllable),
        "spec_source": item.spec_source,
    }


def get_setting(db: Any, owner: str, key: str) -> str | None:
    setting = (
        db.query(AppSetting)
        .filter(AppSetting.owner == owner, AppSetting.key == key)
        .first()
    )
    return setting.value if setting else None


def set_setting(db: Any, owner: str, key: str, value: str) -> None:
    setting = (
        db.query(AppSetting)
        .filter(AppSetting.owner == owner, AppSetting.key == key)
        .first()
    )
    if setting:
        setting.value = value
    else:
        db.add(AppSetting(owner=owner, key=key, value=value))
    db.commit()


def ensure_default_setup(db: Any, owner: str) -> BrewSetup:
    setup = (
        db.query(BrewSetup)
        .filter(BrewSetup.owner == owner)
        .order_by(BrewSetup.id.asc())
        .first()
    )
    if setup:
        return setup

    # Equipment is a shared catalogue, so a new user's first setup points at
    # whatever baseline hardware already exists rather than owning its own.
    grinder, machine = ensure_default_equipment(db)
    setup = BrewSetup(
        owner=owner,
        name="Default Setup",
        grinder_id=grinder.id,
        machine_id=machine.id,
    )
    db.add(setup)
    db.commit()
    db.refresh(setup)
    return setup


def get_active_setup(db: Any, owner: str) -> BrewSetup:
    """The setup recipes are computed for and new shots are logged on.

    The one chosen in the app, else the user's oldest. It only writes the
    first time a user is ever seen, to give them a default setup.
    """
    chosen = get_setting(db, owner, "active_setup_id")
    if chosen and chosen.isdigit():
        setup = (
            db.query(BrewSetup)
            .filter(BrewSetup.id == int(chosen), BrewSetup.owner == owner)
            .first()
        )
        if setup is not None:
            return setup
    return ensure_default_setup(db, owner)


def serialize_setup(setup: BrewSetup) -> dict[str, Any]:
    return {
        "id": setup.id,
        "name": setup.name,
        "method": setup.method,
        "grinder": serialize_equipment(setup.grinder),
        "machine": serialize_equipment(setup.machine),
    }


def classify_data_quality(
    *,
    grind_clicks: float | None,
    time_s: int | None,
    yield_g: float | None,
    water_g: float | None,
    rating: int | None,
    taste_axis: str | None,
) -> str:
    """'measured' only when the engine has what it needs to learn from a shot.

    Calibration reads 'measured' rows exclusively, so this is the gate that
    keeps guessed or half-filled shots out of the physics.
    """
    has_outcome = rating is not None or taste_axis is not None
    complete = (
        grind_clicks is not None
        and time_s is not None
        and (yield_g is not None or water_g is not None)
        and has_outcome
    )
    return "measured" if complete else "partial"


def resolve_log_values(
    log: LogDetailsInput | None, db: Any, owner: str
) -> dict[str, Any]:
    """Normalise a log payload without inventing measurements.

    Anything the user did not supply stays None. Before this, absent values
    were filled with yield_g = dose*2, time_s = 28 and rating = 5, and those
    fabricated rows were later retrieved as real successful shots -- the
    system learned from its own defaults. The dose default is retained
    because it is a stored user preference, not a guess about an outcome.
    """
    dose = get_default_dose_g(db, owner)
    if log and log.dose_g is not None and log.dose_g > 0:
        dose = float(log.dose_g)

    yield_g = (
        float(log.yield_g)
        if log and log.yield_g is not None and log.yield_g > 0
        else None
    )
    time_s = (
        round(log.time_s) if log and log.time_s is not None and log.time_s > 0 else None
    )
    rating = max(1, min(5, int(log.rating))) if log and log.rating is not None else None

    grind_setting = "Unknown"
    if log and log.grind_setting:
        grind_setting = log.grind_setting.strip() or "Unknown"
    grind_clicks = parse_grind_clicks(grind_setting)

    notes = None
    if log and log.tasting_notes:
        notes = log.tasting_notes.strip() or None

    return {
        "dose_g": dose,
        "yield_g": yield_g,
        "time_s": time_s,
        "rating": rating,
        "grind_setting": grind_setting,
        "grind_clicks": grind_clicks,
        "tasting_notes": notes,
        "data_quality": classify_data_quality(
            grind_clicks=grind_clicks,
            time_s=time_s,
            yield_g=yield_g,
            water_g=None,
            rating=rating,
            taste_axis=None,
        ),
    }


def new_shot(owner: str, bean_id: int, setup: BrewSetup, **fields: Any) -> DialInLog:
    """A shot row logged on `setup`: its equipment and method are the setup's."""
    return DialInLog(
        owner=owner,
        bean_id=bean_id,
        grinder_id=setup.grinder_id,
        machine_id=setup.machine_id,
        setup_id=setup.id,
        brew_method=setup.method,
        **fields,
    )


def _bean_for_shot(db: Any, owner: str, coffee_data: dict[str, Any]) -> Bean:
    """The coffee a shot belongs to, created on its first shot.

    An explicit id beats the fuzzy name match: find_existing_bean's 0.9
    similarity threshold is a good guess at identity but is not identity, so a
    shot logged against a known bean must never land on a similarly-named one.
    """
    explicit_id = coffee_data.get("bean_id")
    if isinstance(explicit_id, int) or (
        isinstance(explicit_id, str) and explicit_id.isdigit()
    ):
        bean = db.get(Bean, int(explicit_id))
        # A bean_id from another user's library must not attach a shot.
        if bean is not None and bean.owner == owner:
            return bean

    name = as_non_empty_text(coffee_data.get("name"))
    roaster = as_non_empty_text(coffee_data.get("roaster"))
    origin = as_non_empty_text(coffee_data.get("origin"))
    process = as_non_empty_text(coffee_data.get("process"))
    existing = find_existing_bean(
        db, owner, name=name, roaster=roaster, origin=origin, process=process
    )
    if existing is not None:
        return existing

    roast_level = as_non_empty_text(coffee_data.get("roast_level"))
    bean = Bean(
        owner=owner,
        roaster=roaster,
        name=name,
        origin=origin,
        process=process,
        roast_level=roast_level,
        roast_date=parse_roast_date(coffee_data.get("roast_date")),
        # It drives the roast-level temperature band and the roast term in
        # similarity, so a bean stored without it is invisible to both.
        roast_level_ord=roast_level_ordinal(roast_level),
    )
    db.add(bean)
    db.flush()
    return bean


def save_shot(db: Any, owner: str, setup: BrewSetup, body: FeedbackRequest) -> Bean:
    """Record a shot from the wizard, and return the coffee it was logged on.

    One transaction: a first shot on a new bag creates the coffee and the shot
    together, or neither.
    """
    bean = _bean_for_shot(db, owner, body.coffee_data)

    # The grind value comes from what the user actually set. It is never
    # recovered by parsing the LLM's prose -- that round-trip is what fed
    # generated numbers back in as if they were measurements.
    grind_setting = body.actual_grind.strip() if body.actual_grind else "Unknown"
    grind_clicks = parse_grind_clicks(grind_setting)
    # The wizard's timer measures tenths; the column is whole seconds.
    time_s = None if body.time_s is None else round(body.time_s)
    image_name = body.image_name or body.coffee_data.get("image_name")

    # The client echoes the id of the recommendation it was shown. Only link
    # it if it is this user's: otherwise any id would attach a stranger's
    # recommendation to this shot, and the shot history would then show their
    # suggested grind.
    recommendation_id = body.recommendation_id
    if recommendation_id is not None:
        owned = (
            db.query(Recommendation.id)
            .filter(
                Recommendation.id == recommendation_id,
                Recommendation.owner == owner,
            )
            .first()
        )
        if owned is None:
            recommendation_id = None

    db.add(
        new_shot(
            owner,
            bean.id,
            setup,
            grind_setting=grind_setting,
            grind_clicks=grind_clicks,
            dose_g=body.dose_g
            if body.dose_g is not None
            else get_default_dose_g(db, owner),
            # Whatever the user actually measured; anything they left blank
            # stays None rather than being filled with a default.
            yield_g=body.yield_g,
            water_g=body.water_g,
            time_s=time_s,
            taste_axis=body.taste_axis,
            astringent=body.astringent,
            brew_temp_c=body.brew_temp_c,
            preinfusion_s=body.preinfusion_s,
            pause_s=body.pause_s,
            recommendation_id=recommendation_id,
            data_quality=classify_data_quality(
                grind_clicks=grind_clicks,
                time_s=time_s,
                yield_g=body.yield_g,
                water_g=body.water_g,
                rating=None,
                taste_axis=body.taste_axis,
            ),
            image_path=os.path.basename(str(image_name)) if image_name else None,
        )
    )
    db.commit()
    return bean
