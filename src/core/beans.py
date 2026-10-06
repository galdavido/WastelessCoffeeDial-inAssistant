"""Coffee (bean) matching, stand-ins and shaping for the library and recipes."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from database.models import Bean, DialInLog

from .brewing import ROAST_FILL, roast_fill, value_of
from .parsing import (
    as_non_empty_text,
    normalize_label,
    parse_roast_date,
    roast_level_ordinal,
)


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


def match_bean(db: Any, owner: str, coffee_data: dict[str, Any]) -> Bean | None:
    """The owner's stored bean for these scanned/typed fields, if any."""
    return find_existing_bean(
        db,
        owner,
        name=as_non_empty_text(coffee_data.get("name")),
        roaster=as_non_empty_text(coffee_data.get("roaster")),
        origin=as_non_empty_text(coffee_data.get("origin")),
        process=as_non_empty_text(coffee_data.get("process")),
    )


def transient_bean(owner: str, coffee_data: dict[str, Any]) -> Bean:
    """An unsaved Bean built from the coffee fields.

    It still carries roast level, process and origin, which is what similarity
    scoring needs -- so a coffee scanned for the first time gets sensible
    retrieval rather than none.
    """
    roast_level = as_non_empty_text(coffee_data.get("roast_level"))
    return Bean(
        owner=owner,
        roaster=as_non_empty_text(coffee_data.get("roaster")),
        name=as_non_empty_text(coffee_data.get("name")),
        origin=as_non_empty_text(coffee_data.get("origin")),
        process=as_non_empty_text(coffee_data.get("process")),
        roast_level=roast_level,
        roast_date=parse_roast_date(coffee_data.get("roast_date")),
        # It drives the roast-level temperature band and the roast term in
        # similarity, so a bean stored without it is invisible to both.
        roast_level_ord=roast_level_ordinal(roast_level),
    )


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
