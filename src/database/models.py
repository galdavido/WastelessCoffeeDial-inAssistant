from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# The friends instance is multi-user: `owner` is the Tailscale login the row
# belongs to (see core.auth). The single-user dev instance puts every row under
# one owner ("owner" by default), which is also what migration 0005 backfills
# onto pre-multi-user data. Equipment is deliberately not owned -- it is a
# shared hardware-spec catalogue.


# 1. Beans table
class Bean(Base):
    __tablename__ = "beans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner: Mapped[str] = mapped_column(String, index=True)
    roaster: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    origin: Mapped[str] = mapped_column(String)
    process: Mapped[str] = mapped_column(String)
    roast_level: Mapped[str] = mapped_column(String)
    roast_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 1 light .. 5 dark; canonicalises the several spellings of "medium-light".
    roast_level_ord: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Back reference to logs
    logs: Mapped[list[DialInLog]] = relationship(back_populates="bean")


# 2. Equipment table (Grinder and Espresso Machine)
class Equipment(Base):
    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    type: Mapped[str] = mapped_column(String)
    brand: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)

    # Hardware capability. These bound every number the engine recommends;
    # without them the engine abstains rather than guessing a click number.
    grind_min_clicks: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    grind_max_clicks: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    grind_step_clicks: Mapped[float | None] = mapped_column(
        Numeric(5, 3), nullable=True
    )
    grind_um_per_click: Mapped[float | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    finer_direction: Mapped[str | None] = mapped_column(String, nullable=True)
    burr_type: Mapped[str | None] = mapped_column(String, nullable=True)
    burr_size_mm: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    basket_size_g: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    temp_min_c: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    temp_max_c: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    temp_controllable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    # A capability row without a citation is a guess. Store the URL.
    spec_source: Mapped[str | None] = mapped_column(Text, nullable=True)


class BrewSetup(Base):
    __tablename__ = "brew_setups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    grinder_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    machine_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    # 'espresso' | 'pourover' | 'moka'. Drives target bands and which levers
    # the correction policy is even allowed to move.
    method: Mapped[str | None] = mapped_column(String, nullable=True)

    grinder: Mapped[Equipment] = relationship(foreign_keys=[grinder_id])
    machine: Mapped[Equipment] = relationship(foreign_keys=[machine_id])


# 2b. Every engine output, persisted so proposed-vs-actual can be back-tested.
class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    setup_id: Mapped[int | None] = mapped_column(
        ForeignKey("brew_setups.id"), nullable=True
    )
    bean_id: Mapped[int | None] = mapped_column(ForeignKey("beans.id"), nullable=True)
    engine_version: Mapped[str] = mapped_column(String)
    method: Mapped[str | None] = mapped_column(String, nullable=True)
    grind_clicks: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    dose_g: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    yield_g: Mapped[float | None] = mapped_column(Numeric(6, 1), nullable=True)
    water_g: Mapped[float | None] = mapped_column(Numeric(6, 1), nullable=True)
    brew_temp_c: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    target_time_s: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    basis: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    inputs_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rationale_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String, nullable=True)


# 3. The "Shot" logs table (This connects the coffee and equipment)
class DialInLog(Base):
    __tablename__ = "dial_in_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner: Mapped[str] = mapped_column(String, index=True)
    bean_id: Mapped[int] = mapped_column(ForeignKey("beans.id"))
    grinder_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    machine_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    grind_setting: Mapped[str] = mapped_column(
        String
    )  # legacy; superseded by grind_clicks
    dose_g: Mapped[float] = mapped_column(Float)  # Input weight
    # Nullable since 0002: an unmeasured shot is recorded as unmeasured.
    # Never invent a value here -- calibration reads these as ground truth.
    yield_g: Mapped[float | None] = mapped_column(Float, nullable=True)  # Output weight
    time_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tasting_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    # Engine columns (0002).
    setup_id: Mapped[int | None] = mapped_column(
        ForeignKey("brew_setups.id"), nullable=True
    )
    brew_method: Mapped[str | None] = mapped_column(String, nullable=True)
    grind_clicks: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    water_g: Mapped[float | None] = mapped_column(Numeric(6, 1), nullable=True)
    taste_axis: Mapped[str | None] = mapped_column(String, nullable=True)
    astringent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    brew_temp_c: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    # Pre-infusion duration, and the rest between cutting it and pulling.
    # Kept out of time_s on purpose: the grind law governs pressurised flow,
    # so folding these in would corrupt it. They are covariates, not part of
    # the shot time.
    preinfusion_s: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    pause_s: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    # Optional forever: no code path may require a refractometer.
    tds_pct: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)
    # 'measured' | 'partial' | 'synthetic' | 'imported'.
    # Only 'measured' rows may feed calibration.
    data_quality: Mapped[str] = mapped_column(
        String, nullable=False, server_default="measured", default="measured"
    )
    # LLM prose lives here; tasting_notes is reserved for the human.
    llm_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_id: Mapped[int | None] = mapped_column(
        ForeignKey("recommendations.id"), nullable=True
    )

    # These lines tell Python what the ForeignKey IDs belong to
    bean: Mapped[Bean] = relationship(back_populates="logs")
    grinder: Mapped[Equipment] = relationship(foreign_keys=[grinder_id])
    machine: Mapped[Equipment] = relationship(foreign_keys=[machine_id])
    setup: Mapped[BrewSetup | None] = relationship(foreign_keys=[setup_id])


# 4. Simple key-value settings table for app preferences.
# Every billable AI call is counted here before it is made. The Gemini key is
# a single shared credential with a daily ceiling, so an unmetered instance is
# one enthusiastic user away from being unusable for everyone -- see
# core.quota for the limits and how they are enforced.
class AiUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (
        UniqueConstraint(
            "owner", "period", "kind", name="uq_ai_usage_owner_period_kind"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner: Mapped[str] = mapped_column(String, index=True)
    # Calendar month as "YYYY-MM", in UTC. A rolling window would be fairer
    # but needs per-call rows; a month is what the user is told and what the
    # counter resets on.
    period: Mapped[str] = mapped_column(String(7), index=True)
    # core.quota.AiCall: "vision" (reading a bag) or "rationale" (the prose).
    kind: Mapped[str] = mapped_column(String(16))
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# Prose already written for an identical recipe. The client refreshes the
# recommendation on every dose change, every setup switch and after every
# saved shot, so the same explanation was being paid for repeatedly. Keyed on
# a hash of the prompt itself, so a cache hit is byte-identical to what the
# model would have been asked.
class RationaleCache(Base):
    __tablename__ = "rationale_cache"
    __table_args__ = (
        UniqueConstraint(
            "owner", "fingerprint", name="uq_rationale_cache_owner_fingerprint"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Scoped per owner even though the prompt hash would collide safely: the
    # context line carries the owner's own shot history, so sharing rows
    # across users would leak one person's history into another's prose.
    owner: Mapped[str] = mapped_column(String, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    headline: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text)
    what_to_watch: Mapped[str] = mapped_column(Text)
    # Which model wrote it; NULL is never stored here, because a template
    # rationale costs nothing and is not worth caching.
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# Settings are per-owner: active_setup_id, default_dose_g and
# default_grind_offset_clicks were global singletons before multi-user, so the
# unique key is (owner, key), not key alone.
class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = (
        UniqueConstraint("owner", "key", name="uq_app_settings_owner_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner: Mapped[str] = mapped_column(String, index=True)
    key: Mapped[str] = mapped_column(String, index=True)
    value: Mapped[str] = mapped_column(String)
