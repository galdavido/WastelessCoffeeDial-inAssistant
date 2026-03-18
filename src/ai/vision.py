import json
from typing import Any

from pydantic import BaseModel
from core.optional_deps import (
    load_dotenv_if_available,
    require_genai,
    require_pillow_image,
)

load_dotenv_if_available()


# 1. Define the Pydantic model (The data structure we expect from the AI)
class CoffeeData(BaseModel):
    roaster: str | None
    name: str | None
    origin: str | None
    process: str | None
    roast_level: str | None
    roast_date: str | None


def _get_image_module_and_client() -> tuple[Any, Any, Any] | None:
    """Return PIL image module plus initialized GenAI client/types."""
    try:
        image_module = require_pillow_image()
        genai, types = require_genai()
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return None

    return image_module, genai.Client(), types


def _build_prompt() -> str:
    """Build the extraction prompt for coffee bag image analysis."""
    return (
        "You are an expert barista. Analyze this coffee bag packaging and "
        "extract the specific details."
    )


def analyze_coffee_bag(image_path: str) -> dict[str, Any] | None:
    """Analyze a coffee bag image and return normalized coffee metadata."""
    print(f"Image analysis in progress with the new GenAI SDK: {image_path}...")

    setup = _get_image_module_and_client()
    if setup is None:
        return None
    image_module, client, types = setup

    try:
        img = image_module.open(image_path)
    except FileNotFoundError:
        print(f"Error: The '{image_path}' file is not found in the folder!")
        return None

    prompt = _build_prompt()

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

        # The response (response.text) is now guaranteed to be JSON matching the above Pydantic schema
        text = response.text
        if text is None:
            return None
        return json.loads(text)

    except Exception as e:
        print(f"Error occurred during API call: {e}")
        return None
    finally:
        client.close()


if __name__ == "__main__":
    test_image = "test_bag.jpg"
    result = analyze_coffee_bag(test_image)

    if result:
        print("\n🎉 SUCCESSFUL EXTRACTION! Result:")
        print(json.dumps(result, indent=4, ensure_ascii=False))
