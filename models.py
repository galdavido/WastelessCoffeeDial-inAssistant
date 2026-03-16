from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime, timezone
from database import Base

# 1. Kávék táblája
class Bean(Base):
    __tablename__ = "beans"

    id = Column(Integer, primary_key=True, index=True)
    roaster = Column(String, index=True)  # pl. Casino Mocca
    name = Column(String)                 # pl. Honduras Las Capucas
    origin = Column(String)               # Származás
    process = Column(String)              # Feldolgozás (Washed, Natural stb.)
    roast_level = Column(String)          # Pörkölési szint

    # Visszamutató kapcsolat a logokhoz
    logs = relationship("DialInLog", back_populates="bean")

# 2. Eszközök táblája (Daráló és Kávégép)
class Equipment(Base):
    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String)                 # "grinder" vagy "espresso_machine"
    brand = Column(String)                # pl. Comandante
    model = Column(String)                # pl. C40 MK4

# 3. A "Shot" logok táblája (Ez köti össze a kávét és az eszközöket)
class DialInLog(Base):
    __tablename__ = "dial_in_logs"

    id = Column(Integer, primary_key=True, index=True)
    bean_id = Column(Integer, ForeignKey("beans.id"))
    grinder_id = Column(Integer, ForeignKey("equipment.id"))
    machine_id = Column(Integer, ForeignKey("equipment.id"))
    
    grind_setting = Column(String)        # pl. "14 clicks"
    dose_g: Mapped[float] = mapped_column(Float)                # Bemenő súly
    yield_g: Mapped[float] = mapped_column(Float)               # Kijövő súly
    time_s = Column(Integer)              # Lefolyási idő
    rating = Column(Integer)              # Értékelés 1-5
    tasting_notes = Column(Text, nullable=True) # Szöveges értékelés
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Ezek a sorok mondják meg a Pythonnak, hogy a ForeignKey ID-k mikhez tartoznak
    bean = relationship("Bean", back_populates="logs")
    grinder = relationship("Equipment", foreign_keys=[grinder_id])
    machine = relationship("Equipment", foreign_keys=[machine_id])
