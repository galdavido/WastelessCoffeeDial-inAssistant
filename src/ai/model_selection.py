from __future__ import annotations

import os
from collections.abc import Callable, Iterable

from google.genai import types
from pydantic import BaseModel

# Newest first; every entry was confirmed present in models.list on 2026-09-14.
# try_model_candidates stops the chain on a non-transient error rather than
# falling through, so a name that 404s here takes the whole call down with it.
GEMINI_MODEL_CANDIDATES: tuple[str, ...] = (
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
)


def resolve_model_candidates(default_models: Iterable[str]) -> list[str]:
    override = os.getenv("WCDA_GEMINI_MODELS")
    if override:
        models = [item.strip() for item in override.split(",") if item.strip()]
        if models:
            return models
    return list(default_models)


def thinking_level_for(model_name: str, *, default: str = "low") -> str | None:
    """The ``thinking_level`` to request for a model, or None if unsupported.

    Gemini 3.x accepts ``"low"`` or ``"high"``; ``"high"`` is extended
    reasoning. Older models reject the parameter, and a rejection is not a
    transient error, so it would abort the whole candidate chain rather than
    fall through -- hence the explicit version gate rather than a try/except.

    Both call sites are in a path where the user is waiting, so both default to
    ``"low"``. ``WCDA_GEMINI_THINKING`` (low | high | off) overrides every path.
    """
    if not model_name.startswith("gemini-3"):
        return None
    level = os.getenv("WCDA_GEMINI_THINKING", default).strip().lower()
    if level in ("", "off", "none", "disabled", "false"):
        return None
    return level if level in ("low", "high") else default


def json_config(
    model_name: str, schema: type[BaseModel], temperature: float
) -> types.GenerateContentConfig:
    """Structured-output config for one candidate model.

    Both Gemini calls want the same thing: JSON matching a schema, at a low
    temperature, with thinking_level only where the model accepts it.
    """
    level = thinking_level_for(model_name)
    return types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        temperature=temperature,
        thinking_config=(
            types.ThinkingConfig(thinking_level=types.ThinkingLevel(level.upper()))
            if level
            else None
        ),
    )


def is_transient_model_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "high demand",
            "resource exhausted",
            "temporarily unavailable",
            "service unavailable",
            "quota",
            "rate limit",
            "overloaded",
        )
    )


def try_model_candidates[ResultT](
    default_models: Iterable[str],
    call_model: Callable[[str], ResultT],
    evaluate_result: Callable[[ResultT], tuple[bool, str | None]],
) -> tuple[ResultT | None, str | None]:
    """Try candidate models in order and return first successful result."""

    last_error: str | None = None
    for model_name in resolve_model_candidates(default_models):
        try:
            result = call_model(model_name)
            ok, error_message = evaluate_result(result)
            if ok:
                return result, None
            last_error = f"{model_name}: {error_message or 'unsuccessful response'}"
        except Exception as exc:
            last_error = f"{model_name}: {exc}"
            if not is_transient_model_error(exc):
                break

    return None, last_error
