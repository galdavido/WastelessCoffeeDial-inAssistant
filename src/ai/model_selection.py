from __future__ import annotations

import os
from typing import Callable, Iterable, TypeVar


GEMINI_MODEL_CANDIDATES: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.0-flash-lite",
    "gemini-3.1-flash-lite-preview",
)


_ResultT = TypeVar("_ResultT")


def resolve_model_candidates(default_models: Iterable[str]) -> list[str]:
    override = os.getenv("WCDA_GEMINI_MODELS")
    if override:
        models = [item.strip() for item in override.split(",") if item.strip()]
        if models:
            return models
    return list(default_models)


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


def try_model_candidates(
    default_models: Iterable[str],
    call_model: Callable[[str], _ResultT],
    evaluate_result: Callable[[_ResultT], tuple[bool, str | None]],
) -> tuple[_ResultT | None, str | None]:
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
