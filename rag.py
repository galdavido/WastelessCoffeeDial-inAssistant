# import os
from typing import Dict, Any
from database import SessionLocal
from models import Bean, DialInLog, Equipment
from google import genai

def get_best_grind_setting(coffee_json: Dict[str, Any]) -> str:
    """
    Kikeresi a saját adatokat, majd meghívja az LLM-et, hogy szintetizálja a végső javaslatot.
    """
    db = SessionLocal()
    try:
        origin = str(coffee_json.get("origin", ""))
        process = str(coffee_json.get("process", ""))
        roast_level = str(coffee_json.get("roast_level", ""))
        name = str(coffee_json.get("name", ""))
        roast_date = str(coffee_json.get("roast_date", ""))
        
        print(f"\n🔍 2/A. Keresés a saját Postgres adatbázisban ({origin}, {process})...")

        # 1. RETRIEVAL: Adatbázis lekérdezés
        similar_logs = (
            db.query(DialInLog, Bean, Equipment)
            .join(Bean, DialInLog.bean_id == Bean.id)
            .join(Equipment, DialInLog.grinder_id == Equipment.id)
            .filter(
                DialInLog.rating >= 4,
                (Bean.process == process) | (Bean.origin == origin)
            )
            .all()
        )

        # 2. KONTEXTUS ÉPÍTÉSE AZ LLM-NEK
        db_context = ""
        if not similar_logs:
            db_context = "A felhasználó adatbázisa üres ehhez a kávéprofilhoz. Nincs korábbi tapasztalat."
        else:
            db_context = "A felhasználó korábbi SIKERES beállításai hasonló kávékhoz:\n"
            for log, bean, grinder in similar_logs:
                db_context += f"- Kávé: {bean.name} ({bean.origin}, {bean.process})\n"
                db_context += f"  Eszköz: {grinder.brand} {grinder.model}\n"
                db_context += f"  Beállítás: {log.grind_setting} klikk, Dózis: {log.dose_g}g\n"
                db_context += f"  Jegyzet: {log.tasting_notes}\n\n"

        # 3. GENERATION: LLM hívás a szintézishez
        print("🧠 2/B. LLM Barista hívása az adatok kiegészítésére...")
        
        client = genai.Client()
        
        # A "System Prompt", ami irányítja az AI viselkedését
        prompt = f"""
        Te egy profi Head Barista vagy. A felhasználó egy új kávét szeretne beállítani:
        - Név: {name}
        - Származás: {origin}
        - Feldolgozás: {process}
        - Pörkölés: {roast_level}, {roast_date}
        
        A felhasználó felszerelése: AVX Hero Plus 2024 (eszpresszó gép) és Kingrinder K6 (kézi őrlő).
        
        Itt vannak a felhasználó saját, múltbeli adatai a naplójából (RAG Database Context):
        ---
        {db_context}
        ---
        
        FELADATOD:
        Adj egy konkrét, gyakorlatias induló receptet (Dózis, Kingrinder K6 klikk, Hőmérséklet)!
        
        SZABÁLYOK:
        1. Ha a "RAG Database Context" tartalmaz adatot a Kingrinder K6-ra, akkor ELSŐSORBAN azokra a klikk értékekre támaszkodj!
        2. Ha a kontextus üres, használd a saját általános barista tudásodat! (Tipp: A Kingrinder K6-on az eszpresszó tartomány általában 30 és 45 klikk között van, pörköléstől függően. Világos pörkölés finomabb, sötét durvább).
        3. Fogalmazz röviden, barátságosan, magyar nyelven.
        """

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        client.close()

        return response.text or "Hiba: Üres válasz érkezett az AI Baristától."

    except Exception as e:
        return f"Hiba történt az LLM augmentáció során: {e}"
    finally:
        db.close()

if __name__ == "__main__":
    # Teszt futtatás
    test_json: Dict[str, Any] = {
        "roaster": "Minta",
        "name": "Ismeretlen Kolumbiai",
        "origin": "Colombia",
        "process": "Anaerobic",
        "roast_level": "Light"
    }
    print(get_best_grind_setting(test_json))
