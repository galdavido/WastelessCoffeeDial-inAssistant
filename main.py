import os
import sys
from vision import analyze_coffee_bag
from rag import get_best_grind_setting

def main(image_path: str) -> None:
    print("\n" + "="*50)
    print("☕ BARISTAI - AI DIAL-IN ASSZISZTENS")
    print("="*50)
    print(f"📸 1. Lépés: Kép feldolgozása ({image_path})...")
    
    # 1. Kép elemzése a Gemini Vision API-val
    coffee_data = analyze_coffee_bag(image_path)
    
    if not coffee_data:
        print("❌ Hiba: Nem sikerült kinyerni az adatokat a képből.")
        return

    print("\n✅ Kávé adatok sikeresen kinyerve a csomagolásról:")
    for key, value in coffee_data.items():
        print(f"  - {key.capitalize()}: {value}")
        
    # 2. RAG keresés az adatbázisban a kinyert JSON alapján
    print("\n🧠 2. Lépés: AI Barista keresése a korábbi naplóidban...")
    recommendation = get_best_grind_setting(coffee_data)
    
    # Végeredmény kiírása
    print("\n" + "="*50)
    print("💡 VÉGSŐ JAVASLAT A KÁVÉHOZ:")
    print("="*50)
    print(recommendation)
    print("="*50 + "\n")

if __name__ == "__main__":
    # Ha futtatáskor megadunk egy fájlnevet, azt használja, 
    # különben alapértelmezetten a "test_bag.jpg"-t keresi.
    target_image = "test_bag.jpg"
    
    if len(sys.argv) > 1:
        target_image = sys.argv[1]
        
    if not os.path.exists(target_image):
        print(f"❌ Hiba: A '{target_image}' fájl nem található a mappában!")
        print("Tipp: Dobj be egy képet a mappába, és nevezd el test_bag.jpg-nek!")
    else:
        main(target_image)
