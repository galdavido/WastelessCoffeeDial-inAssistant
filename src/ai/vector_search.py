# import os
from typing import List, Optional
from ..database.database import SessionLocal
from ..database.models import ScrapedEquipment
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

def get_query_embedding(query: str) -> Optional[List[float]]:
    """
    Converts a search query string into a 768-dimensional float vector 
    using Google's embedding model.
    """
    client = genai.Client()
    
    try:
        response = client.models.embed_content(
            model='gemini-embedding-001',
            contents=query,
            config=types.EmbedContentConfig(output_dimensionality=768)
        )
        
        # Ensure we have valid embeddings before returning to satisfy Pylance
        embeddings = response.embeddings
        if not embeddings or not embeddings[0].values:
            return None
        
        # Explicitly cast to List[float]
        return list(embeddings[0].values)
        
    except Exception as e:
        print(f"Error during embedding generation: {str(e)}")
        return None

def search_equipment(query: str, limit: int = 3) -> str:
    """
    Searches the pgvector database for the most similar equipment 
    based on the cosine distance of the query embedding.
    """
    print(f"\n🔍 Searching for: '{query}'...")
    
    query_vector: Optional[List[float]] = get_query_embedding(query)
    
    if not query_vector:
        return "Error: Could not generate vector for the search query."

    db = SessionLocal()
    try:
        # Pylance strict mode might show a minor warning for SQLAlchemy's dynamic attributes,
        # but this is the standard and correct way to use pgvector's cosine_distance.
        results = (
            db.query(ScrapedEquipment)
            .order_by(ScrapedEquipment.embedding.cosine_distance(query_vector))  # type: ignore
            .limit(limit)
            .all()
        )

        if not results:
            return "No matching equipment found in the database."

        response_lines: List[str] = [f"✅ Top {limit} results for '{query}':\n"]
        
        for item in results:
            # Explicit type casting to ensure Pylance knows these are strings
            brand: str = str(item.brand or "Unknown Brand")
            model: str = str(item.model or "Unknown Model")
            features: str = str(item.features_text or "No features listed")
            
            response_lines.append(f"🔹 {brand} {model}")
            response_lines.append(f"   Details: {features}\n")

        return "\n".join(response_lines)

    except Exception as e:
        return f"Database query error: {str(e)}"
    finally:
        db.close()

if __name__ == "__main__":
    # Test the semantic search with a natural language query
    test_query: str = "quiet flat burr grinder for espresso"
    
    search_result: str = search_equipment(query=test_query, limit=1)
    print(search_result)
