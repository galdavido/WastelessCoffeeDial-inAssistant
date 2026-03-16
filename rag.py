# import os
from typing import Dict, Any
from database import SessionLocal
from models import Bean, DialInLog, Equipment
from google import genai

def get_best_grind_setting(coffee_json: Dict[str, Any]) -> str:
    """
    Retrieves own data, then calls the LLM to synthesize the final recommendation.
    """
    db = SessionLocal()
    try:
        origin = str(coffee_json.get("origin", ""))
        process = str(coffee_json.get("process", ""))
        roast_level = str(coffee_json.get("roast_level", ""))
        name = str(coffee_json.get("name", ""))
        roast_date = str(coffee_json.get("roast_date", ""))
        
        print(f"\n🔍 2/A. Searching in own Postgres database ({origin}, {process})...")

        # 1. RETRIEVAL: Database query
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

        # 2. BUILDING CONTEXT FOR THE LLM
        db_context = ""
        if not similar_logs:
            db_context = "The user's database is empty for this coffee profile. No previous experience."
        else:
            db_context = "The user's previous SUCCESSFUL settings for similar coffees:\n"
            for log, bean, grinder in similar_logs:
                db_context += f"- Coffee: {bean.name} ({bean.origin}, {bean.process})\n"
                db_context += f"  Equipment: {grinder.brand} {grinder.model}\n"
                db_context += f"  Setting: {log.grind_setting} clicks, Dose: {log.dose_g}g\n"
                db_context += f"  Notes: {log.tasting_notes}\n\n"

        # 3. GENERATION: LLM call for synthesis
        print("🧠 2/B. Calling LLM Barista to supplement the data...")
        
        client = genai.Client()
        
        # The "System Prompt" that guides the AI's behavior
        prompt = f"""
        You are a professional Head Barista. The user wants to dial in a new coffee:
        - Name: {name}
        - Origin: {origin}
        - Process: {process}
        - Roast: {roast_level}, {roast_date}
        
        The user's equipment: AVX Hero Plus 2024 (espresso machine) and Kingrinder K6 (manual grinder).
        
        Here are the user's own past data from their log (RAG Database Context):
        ---
        {db_context}
        ---
        
        YOUR TASK:
        Give a specific, practical starting recipe (Dose, Kingrinder K6 clicks, Temperature)!
        
        RULES:
        1. If the "RAG Database Context" contains data for the Kingrinder K6, then PRIMARILY rely on those click values!
        2. If the context is empty, use your own general barista knowledge! (Tip: On the Kingrinder K6, the espresso range is generally between 30 and 45 clicks, depending on roast. Light roast finer, dark coarser).
        3. Formulate briefly, friendly, in English.
        """

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        client.close()

        return response.text or "Error: Empty response received from AI Barista."

    except Exception as e:
        return f"Error occurred during LLM augmentation: {e}"
    finally:
        db.close()

if __name__ == "__main__":
    # Test run
    test_json: Dict[str, Any] = {
        "roaster": "Sample",
        "name": "Unknown Colombian",
        "origin": "Colombia",
        "process": "Anaerobic",
        "roast_level": "Light"
    }
    print(get_best_grind_setting(test_json))
