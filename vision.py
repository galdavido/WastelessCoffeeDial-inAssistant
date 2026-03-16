import json
from PIL import Image
from dotenv import load_dotenv
from pydantic import BaseModel

# Az ÚJ Google SDK importjai
from google import genai
from google.genai import types

load_dotenv()

# 1. Definiáljuk a Pydantic modellt (Az adatstruktúra, amit az AI-tól várunk)
class CoffeeData(BaseModel):
    roaster: str | None
    name: str | None
    origin: str | None
    process: str | None
    roast_level: str | None
    roast_date: str | None

def analyze_coffee_bag(image_path: str):
    print(f"Kép elemzése folyamatban az új GenAI SDK-val: {image_path}...")
    
    try:
        img = Image.open(image_path)
    except FileNotFoundError:
        print(f"Hiba: A '{image_path}' fájl nem található a mappában!")
        return None

    # Kliens inicializálása (Automatikusan behúzza a GEMINI_API_KEY-t a .env fájlból)
    client = genai.Client()
    
    # Mivel kikényszerítjük a sémát, a prompt lehet nagyon egyszerű
    prompt = "You are an expert barista. Analyze this coffee bag packaging and extract the specific details."

    try:
        # Hívás a Gemini modellhez, KIKÉNYSZERÍTETT JSON sémával
        response = client.models.generate_content(
            model='gemini-2.5-flash', # A legújabb, képelemzésre is kiváló modell
            contents=[prompt, img],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CoffeeData,
                temperature=0.1, # Alacsony érték: tényeket akarunk, nem hallucinációt
            ),
        )

        client.close()

        # A válasz (response.text) most már garantáltan a fenti Pydantic sémának megfelelő JSON
        text = response.text
        if text is None:
            return None
        return json.loads(text)
        
    except Exception as e:
        print(f"Hiba történt az API hívás során: {e}")
        client.close()
        return None
    
if __name__ == "__main__":
    test_image = "test_bag.jpg" 
    result = analyze_coffee_bag(test_image)
    
    if result:
        print("\n🎉 SIKERES KINYERÉS! Eredmény:")
        print(json.dumps(result, indent=4, ensure_ascii=False))
