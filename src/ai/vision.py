from __future__ import annotations

import io
import json
from typing import Any

from google import genai
from google.genai import types
from PIL import Image
from pydantic import BaseModel

from ai.model_selection import (
    GEMINI_MODEL_CANDIDATES,
    json_config,
    try_model_candidates,
)


class VisionError(Exception):
    """The bag could not be read. The message is safe to show the user."""


class CoffeeData(BaseModel):
    """What the model must return for a bag photo."""

    roaster: str | None
    name: str | None
    origin: str | None
    process: str | None
    roast_level: str | None
    roast_date: str | None


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


def analyze_coffee_bag(image: bytes) -> dict[str, Any]:
    """Read a coffee bag photo into normalised coffee metadata.

    Raises VisionError on failure. The error travels with the call rather
    than through module state: routes run on a thread pool, so a shared
    "last error" could hand one user's failure to another's scan.
    """
    # Decoding locally is the validation: a file Pillow cannot open never
    # costs a Gemini call.
    try:
        photo = Image.open(io.BytesIO(image)).convert("RGB")
    except Exception as exc:
        raise VisionError(f"Failed to read image: {exc}") from exc

    try:
        client = genai.Client()
    except Exception as exc:  # no API key, most likely
        raise VisionError(f"The bag reader is not available: {exc}") from exc

    prompt = _build_prompt()

    try:
        parsed_payload: dict[str, Any] | None = None

        contents: list[types.PartUnionDict] = [prompt, photo]

        def call_model(model_name: str) -> Any:
            return client.models.generate_content(
                model=model_name,
                contents=contents,
                config=json_config(model_name, CoffeeData, temperature=0.1),
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

        if parsed_payload is None:
            raise VisionError(last_error or "Unknown extraction error")
        return parsed_payload
    finally:
        client.close()
