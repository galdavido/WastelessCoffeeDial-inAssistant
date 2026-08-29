from __future__ import annotations

import os
from collections.abc import Callable, Iterable

GEMINI_MODEL_CANDIDATES: tuple[str, ...] = (
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
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


def thinking_level_for(model_name: str, *, default: str = "high") -> str | None:
    """Return the "thinking" level to request for a model, or None.

    Gemini 3.x models accept a ``thinking_level`` of ``"low"`` or ``"high"``;
    ``"high"`` is the extended-reasoning mode. Older models do not support it and
    always get ``None``.

    ``default`` is the level used when ``WCDA_GEMINI_THINKING`` is unset - callers
    pass a lower default for latency-sensitive paths (bag OCR) than for the
    reasoning-heavy grind recommendation. Setting ``WCDA_GEMINI_THINKING`` to
    ``low`` | ``high`` | ``off`` overrides every path.
    """
    if not model_name.startswith("gemini-3"):
        return None
    level = os.getenv("WCDA_GEMINI_THINKING", default).strip().lower()
    if level in ("", "off", "none", "disabled", "false"):
        return None
    return level if level in ("low", "high") else "high"


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
