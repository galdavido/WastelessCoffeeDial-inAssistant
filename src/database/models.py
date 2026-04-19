from __future__ import annotations

from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector  # type: ignore
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


# 1. Beans table
class Bean(Base):
    __tablename__ = "beans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    roaster: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    origin: Mapped[str] = mapped_column(String)
    process: Mapped[str] = mapped_column(String)
    roast_level: Mapped[str] = mapped_column(String)

    # Back reference to logs
    logs: Mapped[list[DialInLog]] = relationship(back_populates="bean")


# 2. Equipment table (Grinder and Espresso Machine)
class Equipment(Base):
    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    type: Mapped[str] = mapped_column(String)
    brand: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)


# 3. The "Shot" logs table (This connects the coffee and equipment)
class DialInLog(Base):
    __tablename__ = "dial_in_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    bean_id: Mapped[int] = mapped_column(ForeignKey("beans.id"))
    grinder_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    machine_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    grind_setting: Mapped[str] = mapped_column(String)
    dose_g: Mapped[float] = mapped_column(Float)  # Input weight
    yield_g: Mapped[float] = mapped_column(Float)  # Output weight
    time_s: Mapped[int] = mapped_column(Integer)
    rating: Mapped[int] = mapped_column(Integer)
    tasting_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # These lines tell Python what the ForeignKey IDs belong to
    bean: Mapped[Bean] = relationship(back_populates="logs")
    grinder: Mapped[Equipment] = relationship(foreign_keys=[grinder_id])
    machine: Mapped[Equipment] = relationship(foreign_keys=[machine_id])


# 4. Equipment scraped from the web (Vector database table)
class ScrapedEquipment(Base):
    __tablename__ = "scraped_equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    brand: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    equipment_type: Mapped[str] = mapped_column(String)
    burr_size_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    burr_type: Mapped[str | None] = mapped_column(String, nullable=True)
    boiler_type: Mapped[str | None] = mapped_column(String, nullable=True)

    # Here we save the properties extracted by AI as a single text
    features_text: Mapped[str] = mapped_column(Text)

    # THIS IS THE ESSENCE! Here come the mathematical vectors.
    # The Gemini embedding model (text-embedding-004) returns exactly 768-dimensional numbers.
    embedding: Mapped[list[float]] = mapped_column(Vector(768))  # type: ignore[arg-type]


# 5. Simple key-value settings table for bot/app preferences
class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String, unique=True, index=True)
    value: Mapped[str] = mapped_column(String)
