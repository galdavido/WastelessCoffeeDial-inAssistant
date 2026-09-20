"""The explanation around a recipe, bought only when it is worth buying.

``ai.rationale.write_rationale`` is a Gemini call, and the clients ask for a
recommendation far more often than a person reads a new explanation: every
dose change, every setup switch, and once more after every saved shot. So
this sits between the engine and the model and answers three questions in
order -- have we already written this, is this owner allowed one, and only
then, what does the model say.

Degrading is always safe here. ``render_template`` produces the same
explanation deterministically, and the *numbers are identical either way*:
the engine fixes every one of them and ``scrub_numerals`` rejects any figure
the model invents. A free-tier user loses the phrasing, not the recipe.
"""

from __future__ import annotations

import os

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ai.rationale import (
    Rationale,
    prompt_fingerprint,
    render_template,
    write_rationale,
)
from database.models import RationaleCache

from .brewing import Recipe
from .quota import AiCall, allowance, consume

# Cached rows are worthless once a coffee has moved on, and they are cheap to
# regenerate, so the cache is capped per owner rather than allowed to grow.
_DEFAULT_CACHE_PER_OWNER = 200


def _cache_limit() -> int:
    raw = os.getenv("WCDA_RATIONALE_CACHE_PER_OWNER", "").strip()
    if not raw:
        return _DEFAULT_CACHE_PER_OWNER
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_CACHE_PER_OWNER


def _lookup(
    db: Session, owner: str, fingerprint: str
) -> tuple[Rationale, str | None] | None:
    row = db.execute(
        select(RationaleCache).where(
            RationaleCache.owner == owner,
            RationaleCache.fingerprint == fingerprint,
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return (
        Rationale(headline=row.headline, why=row.why, what_to_watch=row.what_to_watch),
        row.model,
    )


def _store(
    db: Session, owner: str, fingerprint: str, rationale: Rationale, model: str
) -> None:
    # DO NOTHING rather than DO UPDATE: two concurrent identical requests
    # would otherwise race to overwrite each other with the same text.
    db.execute(
        pg_insert(RationaleCache)
        .values(
            owner=owner,
            fingerprint=fingerprint,
            headline=rationale.headline,
            why=rationale.why,
            what_to_watch=rationale.what_to_watch,
            model=model,
        )
        .on_conflict_do_nothing(constraint="uq_rationale_cache_owner_fingerprint")
    )
    _prune(db, owner)


def _prune(db: Session, owner: str) -> None:
    limit = _cache_limit()
    if limit <= 0:
        return
    keep = (
        select(RationaleCache.id)
        .where(RationaleCache.owner == owner)
        .order_by(RationaleCache.id.desc())
        .limit(limit)
    )
    db.execute(
        delete(RationaleCache).where(
            RationaleCache.owner == owner,
            RationaleCache.id.notin_(keep.scalar_subquery()),
        )
    )


def rationale_for(
    db: Session,
    owner: str,
    recipe: Recipe,
    confidence_label: str,
    context: str = "",
) -> tuple[Rationale, str | None]:
    """Explain a recipe. Returns (rationale, model name or None).

    A None model name means the deterministic template was used, which is a
    normal outcome and not an error -- it is what a cache miss on the free
    tier, an exhausted quota, or an unreachable model all look like.
    """
    fingerprint = prompt_fingerprint(recipe, confidence_label, context)

    cached = _lookup(db, owner, fingerprint)
    if cached is not None:
        return cached

    if allowance(db, owner, AiCall.RATIONALE).exhausted:
        return render_template(recipe, confidence_label), None

    rationale, model = write_rationale(recipe, confidence_label, context)
    if model is None:
        # The template came back: either the model was unreachable or it
        # produced something that failed the numeral check. Nothing worth
        # caching, and nothing worth charging for.
        return rationale, None

    consume(db, owner, AiCall.RATIONALE)
    _store(db, owner, fingerprint, rationale, model)
    return rationale, model
