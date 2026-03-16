from mcp.server.fastmcp import FastMCP
from ..ai.vision import analyze_coffee_bag
from ..ai.rag import get_best_grind_setting

# Create the MCP server itself
mcp = FastMCP("BaristAI")

# The @mcp.tool() decorator is the key!
# This tells the LLM (e.g. Claude) that it can use this function as a tool.
# The "docstring" (the triple-quoted text) is extremely important because the AI from this
# understands when to call this tool.
@mcp.tool()
def get_coffee_dial_in(image_path: str) -> str:
    """
    Analyzes a picture of a coffee bean bag and returns the best recommended 
    grind setting, dose, and temperature based on the user's historical database.
    Use this tool when the user asks for dial-in settings for a new coffee bag.
    """
    # 1. Vision API - Image analysis
    coffee_data = analyze_coffee_bag(image_path)
    
    if not coffee_data:
        return "Error: Failed to extract data from the specified image."
    
    # 2. RAG - Database search
    recommendation = get_best_grind_setting(coffee_data)
    
    # 3. Return formatted response to the AI Agent
    coffee_info = f"Coffee: {coffee_data.get('roaster')} {coffee_data.get('name')} ({coffee_data.get('origin')}, {coffee_data.get('process')})"
    
    return f"{coffee_info}\n\nRecommendation from the database:\n{recommendation}"

if __name__ == "__main__":
    # This starts the server in "stdio" (Standard Input/Output) mode.
    # This way AI clients can run it in the background, as a process, and communicate with it.
    print("BaristAI MCP Server starting...")
    mcp.run()
