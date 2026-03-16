from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime, timezone
from database import Base

# 1. Beans table
class Bean(Base):
    __tablename__ = "beans"

    id = Column(Integer, primary_key=True, index=True)
    roaster = Column(String, index=True)  # e.g. Casino Mocca
    name = Column(String)                 # e.g. Honduras Las Capucas
    origin = Column(String)               # Origin
    process = Column(String)              # Process (Washed, Natural etc.)
    roast_level = Column(String)          # Roast level

    # Back reference to logs
    logs = relationship("DialInLog", back_populates="bean")

# 2. Equipment table (Grinder and Espresso Machine)
class Equipment(Base):
    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String)                 # "grinder" or "espresso_machine"
    brand = Column(String)                # e.g. Comandante
    model = Column(String)                # e.g. C40 MK4

# 3. The "Shot" logs table (This connects the coffee and equipment)
class DialInLog(Base):
    __tablename__ = "dial_in_logs"

    id = Column(Integer, primary_key=True, index=True)
    bean_id = Column(Integer, ForeignKey("beans.id"))
    grinder_id = Column(Integer, ForeignKey("equipment.id"))
    machine_id = Column(Integer, ForeignKey("equipment.id"))
    
    grind_setting = Column(String)        # e.g. "14 clicks"
    dose_g: Mapped[float] = mapped_column(Float)                # Input weight
    yield_g: Mapped[float] = mapped_column(Float)               # Output weight
    time_s = Column(Integer)              # Extraction time
    rating = Column(Integer)              # Rating 1-5
    tasting_notes = Column(Text, nullable=True) # Textual evaluation
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # These lines tell Python what the ForeignKey IDs belong to
    bean = relationship("Bean", back_populates="logs")
    grinder = relationship("Equipment", foreign_keys=[grinder_id])
    machine = relationship("Equipment", foreign_keys=[machine_id])
