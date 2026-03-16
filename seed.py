from database import SessionLocal
from models import Equipment, Bean, DialInLog

def seed_data():
    # Megnyitunk egy session-t az adatbázishoz
    db = SessionLocal()

    try:
        print("Adatok betöltése indul...")

        # 1. ESZKÖZÖK (Felszerelés) FELVITELE
        machine = Equipment(type="espresso_machine", brand="AVX", model="Hero Plus 2024")
        grinder = Equipment(type="grinder", brand="Kingrinder", model="K6")
        
        db.add(machine)
        db.add(grinder)
        db.commit() # Elmentjük, hogy kapjanak ID-t
        
        # Frissítjük az objektumokat, hogy tudjuk az ID-jukat használni
        db.refresh(machine)
        db.refresh(grinder)

        # 2. KÁVÉK FELVITELE (Néhány példa a jegyzetedből)
        bean_nensebo = Bean(name="Nensebo", origin="Ethiopia", process="Washed", roast_level="Medium-Light")
        bean_santos = Bean(name="Brasil Santos", origin="Brazil", process="Natural", roast_level="Medium")
        bean_daisuke = Bean(name="Daisuke Ronaldinho", origin="Brazil", process="Natural", roast_level="Medium")
        
        db.add_all([bean_nensebo, bean_santos, bean_daisuke])
        db.commit()

        # 3. A "SHOT" LOGOK (Dial-in eredmények) FELVITELE
        # A 3 pipát (✅✅✅) lefordítottam 5-ös (tökéletes) ratingre!
        
        log1 = DialInLog(
            bean_id=bean_nensebo.id,
            grinder_id=grinder.id,
            machine_id=machine.id,
            grind_setting="36", # 36 klikk a K6-on
            dose_g=16.0,
            rating=5,
            tasting_notes="Tökéletes, a jegyzet alapján 3 pipás."
        )

        log2 = DialInLog(
            bean_id=bean_santos.id,
            grinder_id=grinder.id,
            machine_id=machine.id,
            grind_setting="39",
            dose_g=16.0,
            rating=5,
            tasting_notes="Tökéletes, a jegyzet alapján 3 pipás."
        )
        
        log3 = DialInLog(
            bean_id=bean_daisuke.id,
            grinder_id=grinder.id,
            machine_id=machine.id,
            grind_setting="39",
            dose_g=16.0,
            rating=5,
            tasting_notes="Tökéletes, a jegyzet alapján 3 pipás."
        )

        db.add_all([log1, log2, log3])
        db.commit()

        print("Siker! Az eszközök, kávék és a beállítások bekerültek az adatbázisba.")

    except Exception as e:
        print(f"Hiba történt: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
