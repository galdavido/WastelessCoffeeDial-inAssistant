from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from ai.model_selection import GEMINI_MODEL_CANDIDATES, try_model_candidates
from core.optional_deps import (
    load_dotenv_if_available,
    require_genai,
    require_pillow_image,
)

load_dotenv_if_available()


_last_vision_error: str | None = None


# 1. Define the Pydantic model (The data structure we expect from the AI)
class CoffeeData(BaseModel):
    roaster: str | None
    name: str | None
    origin: str | None
    process: str | None
    roast_level: str | None
    roast_date: str | None


def get_last_vision_error() -> str | None:
    return _last_vision_error


def _set_last_vision_error(message: str | None) -> None:
    global _last_vision_error
    _last_vision_error = message


def _get_image_module_and_client() -> tuple[Any, Any, Any] | None:
    """Return PIL image module plus initialized GenAI client/types."""
    try:
        image_module = require_pillow_image()
        genai, types = require_genai()
    except RuntimeError as exc:
        _set_last_vision_error(str(exc))
        return None

    return image_module, genai.Client(), types


def _build_prompt() -> str:
    """Build the extraction prompt for coffee bag image analysis."""
    return (
        "You are an expert barista. Analyze this coffee bag packaging and "
        "extract the specific details. "
        "The source text may be Hungarian or another non-English language. "
        "Always normalize extracted values to English in the JSON fields. "
        "Translate process/style terms to standard English coffee terms "
        "(for example, 'mosott' -> 'Washed', 'vilagos porkoles' -> 'Light')."
    )


def _parse_coffee_data_response(text: str) -> dict[str, Any] | None:
    """Parse and validate model JSON response into a stable dict payload."""
    try:
        payload = json.loads(text)
        model = CoffeeData.model_validate(payload)
        return model.model_dump()
    except Exception:
        return None


def analyze_coffee_bag(image_path: str) -> dict[str, Any] | None:
    """Analyze a coffee bag image and return normalized coffee metadata."""
    _set_last_vision_error(None)

    setup = _get_image_module_and_client()
    if setup is None:
        return None
    image_module, client, types = setup

    try:
        img = image_module.open(image_path).convert("RGB")
    except FileNotFoundError:
        message = f"The '{image_path}' file is not found in the folder."
        _set_last_vision_error(message)
        return None
    except Exception as exc:
        _set_last_vision_error(f"Failed to read image: {exc}")
        return None

    prompt = _build_prompt()

    try:
        parsed_payload: dict[str, Any] | None = None

        def call_model(model_name: str) -> Any:
            return client.models.generate_content(
                model=model_name,
                contents=[prompt, img],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CoffeeData,
                    temperature=0.1,
                ),
            )

        def evaluate_response(response: Any) -> tuple[bool, str | None]:
            nonlocal parsed_payload

            text = getattr(response, "text", None)
            if text is None:
                return False, "empty response"

            parsed = _parse_coffee_data_response(text)
            if parsed is None:
                return False, "invalid JSON schema in response"

            parsed_payload = parsed
            return True, None

        _response, last_error = try_model_candidates(
            GEMINI_MODEL_CANDIDATES,
            call_model=call_model,
            evaluate_result=evaluate_response,
        )

        if parsed_payload is not None:
            _set_last_vision_error(None)
            return parsed_payload

        _set_last_vision_error(last_error or "Unknown extraction error")
        return None
    finally:
        client.close()
