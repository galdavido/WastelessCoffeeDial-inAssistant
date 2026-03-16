from mcp.server.fastmcp import FastMCP
from vision import analyze_coffee_bag
from rag import get_best_grind_setting

# Létrehozzuk magát az MCP szervert
mcp = FastMCP("BaristAI")

# A @mcp.tool() dekorátor a lényeg! 
# Ez mondja meg az LLM-nek (pl. Claude), hogy ezt a függvényt eszközként használhatja.
# A "docstring" (a tripla idézőjeles szöveg) extrém fontos, mert az AI ebből 
# érti meg, hogy mikor kell meghívnia ezt a toolt.
@mcp.tool()
def get_coffee_dial_in(image_path: str) -> str:
    """
    Analyzes a picture of a coffee bean bag and returns the best recommended 
    grind setting, dose, and temperature based on the user's historical database.
    Use this tool when the user asks for dial-in settings for a new coffee bag.
    """
    # 1. Vision API - Kép elemzése
    coffee_data = analyze_coffee_bag(image_path)
    
    if not coffee_data:
        return "Error: Nem sikerült adatot kinyerni a megadott képből."
    
    # 2. RAG - Adatbázis keresés
    recommendation = get_best_grind_setting(coffee_data)
    
    # 3. Formázott válasz visszaadása az AI Ágensnek
    coffee_info = f"Kávé: {coffee_data.get('roaster')} {coffee_data.get('name')} ({coffee_data.get('origin')}, {coffee_data.get('process')})"
    
    return f"{coffee_info}\n\nJavaslat az adatbázisból:\n{recommendation}"

if __name__ == "__main__":
    # Ez indítja el a szervert "stdio" (Standard Input/Output) módban.
    # Így az AI kliensek a háttérben, folyamatként tudják futtatni és kommunikálni vele.
    print("BaristAI MCP Szerver indul...")
    mcp.run()
