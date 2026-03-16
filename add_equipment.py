# import os
from typing import Optional, List, Dict, Any
from database import SessionLocal
from models import ScrapedEquipment
from google import genai
from scraper import scrape_equipment_data
from dotenv import load_dotenv
from google.genai import types

# Load environment variables (API keys)
load_dotenv()

def get_embedding(text: str) -> Optional[List[float]]:
    """
    Converts text into a 768-dimensional float vector using Google's newest embedding model.
    """
    client = genai.Client()
    
    try:
        # We use the new model and strictly enforce the 768 dimensionality 
        response = client.models.embed_content(
            model='gemini-embedding-001',
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=768)
        )
        
        # Ensure we have valid embeddings to satisfy Pylance
        embeddings = response.embeddings
        if not embeddings or not embeddings[0].values:
            return None
            
        # Explicitly cast the result to a List of floats
        return list(embeddings[0].values)
        
    except Exception as e:
        print(f"❌ Error generating embedding: {str(e)}")
        return None

def add_url_to_database(url: str) -> None:
    """
    Scrapes a URL, generates an embedding for the extracted data, 
    and saves it to the PostgreSQL pgvector database.
    """
    print(f"\n🌍 Step 1: Scraping equipment data from {url}...")
    
    # We define the expected return type from the scraper
    equipment_data: Optional[Dict[str, Any]] = scrape_equipment_data(url)
    
    if not equipment_data:
        print("❌ Process aborted: Failed to scrape data from the URL.")
        return

    print("🧠 Step 2: Preparing text and generating vector embedding...")
    
    # Safely extract and type-cast the dictionary values for Pylance
    brand: str = str(equipment_data.get('brand') or "Unknown")
    model: str = str(equipment_data.get('model') or "Unknown")
    equipment_type: str = str(equipment_data.get('equipment_type') or "Unknown")
    
    # Extract features list safely
    raw_features: Any = equipment_data.get('key_features')
    features_list: List[str] = raw_features if isinstance(raw_features, list) else []
    features_str: str = ", ".join([str(f) for f in features_list])
    
    # Build the contextual sentence for the AI to embed
    text_to_embed: str = f"Brand: {brand}, Model: {model}. Features: {features_str}"
    
    embedding_vector: Optional[List[float]] = get_embedding(text_to_embed)
    
    if not embedding_vector:
        print("❌ Process aborted: Failed to generate embedding vector.")
        return

    print("💾 Step 3: Saving data to the pgvector database...")
    db = SessionLocal()
    try:
        # Safely extract optionals (integers and strings that might be None)
        raw_burr_size: Any = equipment_data.get('burr_size_mm')
        burr_size_mm: Optional[int] = int(raw_burr_size) if raw_burr_size is not None else None
        
        raw_burr_type: Any = equipment_data.get('burr_type')
        burr_type: Optional[str] = str(raw_burr_type) if raw_burr_type is not None else None
        
        raw_boiler: Any = equipment_data.get('boiler_type')
        boiler_type: Optional[str] = str(raw_boiler) if raw_boiler is not None else None

        # Instantiate the database model
        new_equipment = ScrapedEquipment(
            brand=brand,
            model=model,
            equipment_type=equipment_type,
            burr_size_mm=burr_size_mm,
            burr_type=burr_type,
            boiler_type=boiler_type,
            features_text=text_to_embed,
            embedding=embedding_vector
        )
        
        db.add(new_equipment)
        db.commit()
        print(f"✅ SUCCESS! Equipment added to database: {brand} {model}")
        
    except Exception as e:
        print(f"❌ Database save error: {str(e)}")
        db.rollback()
    finally:
        db.close()

def add_urls_to_database(urls: List[str]) -> None:
    """
    Scrapes multiple URLs, generates embeddings for each, 
    and saves them to the PostgreSQL pgvector database.
    """
    print(f"\n🌍 Processing {len(urls)} URLs...")
    
    for i, url in enumerate(urls, 1):
        print(f"\n--- Processing URL {i}/{len(urls)} ---")
        add_url_to_database(url)
        print(f"--- Completed URL {i}/{len(urls)} ---")
    
    print(f"\n✅ Finished processing all {len(urls)} URLs!")

def add_urls_from_file(file_path: str) -> None:
    """
    Reads URLs from a text file (one URL per line) and adds them to the database.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        
        if not urls:
            print(f"❌ No valid URLs found in {file_path}")
            return
            
        print(f"📄 Found {len(urls)} URLs in {file_path}")
        add_urls_to_database(urls)
        
    except FileNotFoundError:
        print(f"❌ File not found: {file_path}")
    except Exception as e:
        print(f"❌ Error reading file: {e}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        add_urls_from_file(file_path)
    else:
        # Test with multiple URLs
        test_urls: List[str] = [
            "https://www.avxcafe.hu/nb64v-single-dose-red-burrs-mp-kaveorlo-fekete-brazil-fazenda-da-lagoa-specialty-84p-porkolt-kave-1000g-ks",
            # Add more URLs here as needed
        ]
        
        if len(test_urls) == 1:
            # Single URL mode (backward compatibility)
            add_url_to_database(url=test_urls[0])
        else:
            # Multiple URLs mode
            add_urls_to_database(urls=test_urls)
