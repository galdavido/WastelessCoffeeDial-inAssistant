import json
from PIL import Image
from dotenv import load_dotenv
from pydantic import BaseModel

# The NEW Google SDK imports
from google import genai
from google.genai import types

load_dotenv()


# 1. Define the Pydantic model (The data structure we expect from the AI)
class CoffeeData(BaseModel):
    roaster: str | None
    name: str | None
    origin: str | None
    process: str | None
    roast_level: str | None
    roast_date: str | None


def analyze_coffee_bag(image_path: str):
    print(f"Image analysis in progress with the new GenAI SDK: {image_path}...")

    try:
        img = Image.open(image_path)
    except FileNotFoundError:
        print(f"Error: The '{image_path}' file is not found in the folder!")
        return None

    # Client initialization (Automatically pulls GEMINI_API_KEY from .env file)
    client = genai.Client()

    # Since we enforce the schema, the prompt can be very simple
    prompt = "You are an expert barista. Analyze this coffee bag packaging and extract the specific details."

    try:
        # Call to Gemini model, with ENFORCED JSON schema
        response = client.models.generate_content(
            model="gemini-2.5-flash",  # The latest model, excellent for image analysis too
            contents=[prompt, img],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CoffeeData,
                temperature=0.1,  # Low value: we want facts, not hallucinations
            ),
        )

        client.close()

        # The response (response.text) is now guaranteed to be JSON matching the above Pydantic schema
        text = response.text
        if text is None:
            return None
        return json.loads(text)

    except Exception as e:
        print(f"Error occurred during API call: {e}")
        client.close()
        return None


if __name__ == "__main__":
    test_image = "test_bag.jpg"
    result = analyze_coffee_bag(test_image)

    if result:
        print("\n🎉 SUCCESSFUL EXTRACTION! Result:")
        print(json.dumps(result, indent=4, ensure_ascii=False))
