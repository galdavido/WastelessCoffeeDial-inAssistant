import json
from typing import Any

from pydantic import BaseModel
from core.optional_deps import (
    load_dotenv_if_available,
    require_genai,
    require_pillow_image,
)

load_dotenv_if_available()


_LAST_VISION_ERROR: str | None = None


# 1. Define the Pydantic model (The data structure we expect from the AI)
class CoffeeData(BaseModel):
    roaster: str | None
    name: str | None
    origin: str | None
    process: str | None
    roast_level: str | None
    roast_date: str | None


def get_last_vision_error() -> str | None:
    return _LAST_VISION_ERROR


def _set_last_vision_error(message: str | None) -> None:
    global _LAST_VISION_ERROR
    _LAST_VISION_ERROR = message


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


def _vision_models() -> list[str]:
    # Ordered by preference, with stable fallbacks for account/API differences.
    return [
        "gemini-3.1-flash-lite-preview",
        "gemini-flash-lite-latest",
        "gemini-2.5-flash",
        "gemini-2.0-flash-lite",
    ]


def analyze_coffee_bag(image_path: str) -> dict[str, Any] | None:
    """Analyze a coffee bag image and return normalized coffee metadata."""
    _set_last_vision_error(None)
    print(f"Image analysis in progress with the new GenAI SDK: {image_path}...")

    setup = _get_image_module_and_client()
    if setup is None:
        return None
    image_module, client, types = setup

    try:
        img = image_module.open(image_path).convert("RGB")
    except FileNotFoundError:
        message = f"The '{image_path}' file is not found in the folder."
        print(f"Error: {message}")
        _set_last_vision_error(message)
        return None

    prompt = _build_prompt()

    try:
        last_error = "Unknown extraction error"
        for model_name in _vision_models():
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[prompt, img],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=CoffeeData,
                        temperature=0.1,  # Low value: we want facts, not hallucinations
                    ),
                )

                text = response.text
                if text is None:
                    last_error = f"{model_name}: empty response"
                    continue
                parsed = json.loads(text)
                _set_last_vision_error(None)
                return parsed
            except Exception as e:
                last_error = f"{model_name}: {e}"
                print(f"Vision model '{model_name}' failed: {e}")

        _set_last_vision_error(last_error)
        return None
    finally:
        client.close()


if __name__ == "__main__":
    test_image = "test_bag.jpg"
    result = analyze_coffee_bag(test_image)

    if result:
        print("\n🎉 SUCCESSFUL EXTRACTION! Result:")
        print(json.dumps(result, indent=4, ensure_ascii=False))
