from __future__ import annotations

from datetime import datetime, timezone

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


class BrewSetup(Base):
    __tablename__ = "brew_setups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    grinder_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    machine_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))

    grinder: Mapped[Equipment] = relationship(foreign_keys=[grinder_id])
    machine: Mapped[Equipment] = relationship(foreign_keys=[machine_id])


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
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # These lines tell Python what the ForeignKey IDs belong to
    bean: Mapped[Bean] = relationship(back_populates="logs")
    grinder: Mapped[Equipment] = relationship(foreign_keys=[grinder_id])
    machine: Mapped[Equipment] = relationship(foreign_keys=[machine_id])


# 4. Simple key-value settings table for app preferences
class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String, unique=True, index=True)
    value: Mapped[str] = mapped_column(String)
