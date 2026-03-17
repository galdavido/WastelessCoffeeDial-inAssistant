import json
import requests
from bs4 import BeautifulSoup
from typing import Any
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()


# 1. Define Pydantic model for equipment
# Field(description=...) helps the AI understand exactly what we're looking for!
class EquipmentData(BaseModel):
    brand: str | None = Field(
        description="Manufacturer name (e.g., Kingrinder, Lelit, AVX)"
    )
    model: str | None = Field(
        description="Exact model name (e.g., K6, Bianca, Hero Plus)"
    )
    equipment_type: str | None = Field(
        description="Can only be 'grinder' or 'espresso_machine'"
    )
    burr_size_mm: int | None = Field(
        description="For grinders: burr diameter in millimeters. For machines: null."
    )
    burr_type: str | None = Field(
        description="For grinders: 'Conical' or 'Flat'. For machines: null."
    )
    boiler_type: str | None = Field(
        description="For machines: 'Single', 'HX', or 'Dual Boiler'. For grinders: null."
    )
    key_features: list[str] = Field(
        description="Maximum 5 most important features in English."
    )


def scrape_equipment_data(url: str) -> dict[str, Any] | None:
    print(f"🌍 1. Downloading webpage: {url}...")

    try:
        # Send headers to appear as a browser, otherwise many webshops block us
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # Use BeautifulSoup to extract only visible text from HTML
        soup = BeautifulSoup(response.text, "html.parser")
        page_text = soup.get_text(separator="\n", strip=True)

        # Limit text size to avoid sending unnecessarily huge content to LLM (approx. first 15000 chars)
        page_text = page_text[:15000]

    except Exception as e:
        print(f"❌ Error downloading webpage: {e}")
        return None

    print("🧠 2. Passing raw text to AI for structuring...")
    client = genai.Client()

    prompt = f"""
    You are an expert on coffee machines and grinders.
    The text below is from a product page on an online store.
    Find the product's technical specifications and fill in the JSON schema!

    Webpage text:
    {page_text}
    """

    try:
        # Make LLM call with enforced Pydantic schema
        ai_response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=EquipmentData,
                temperature=0.1,
            ),
        )

        # Safety check (for Pylance)
        if not ai_response.text:
            print("❌ Empty response received from AI.")
            return None

        return json.loads(ai_response.text)

    except Exception as e:
        print(f"❌ Error during AI processing: {e}")
        return None


if __name__ == "__main__":
    # Test with a real AVX Cafe link (a Eureka grinder)
    test_url = "https://www.avxcafe.hu/nb64v-single-dose-red-burrs-mp-kaveorlo-fekete-brazil-fazenda-da-lagoa-specialty-84p-porkolt-kave-1000g-ks"

    result = scrape_equipment_data(test_url)

    if result:
        print("\n🎉 DATA EXTRACTION SUCCESSFUL! Result:")
        print(json.dumps(result, indent=4, ensure_ascii=False))
