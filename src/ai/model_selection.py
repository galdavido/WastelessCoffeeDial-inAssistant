from __future__ import annotations

import os
from typing import Iterable


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
