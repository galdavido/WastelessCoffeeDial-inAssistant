from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from threading import Lock

# Availability is checked by *calling* a model, not by reading models.list:
# on 2026-09-15 gemini-2.5-flash-lite was still listed and yet returned 404
# "no longer available" on every call. gemini-3.8-flash and gemini-3.7-flash
# are absent for returning 503 "high demand" on every attempt, one of them
# after hanging 56.9s. WCDA_GEMINI_MODELS overrides the list when that
# capacity comes back.
#
# Ordered by measured latency rather than by model tier, which is the reverse
# of the obvious instinct and is what the measurements actually support. On
# the rationale prompt flash-lite-latest answered in 1.1-1.6s and
# 3.1-flash-lite in 2.4-4.6s, against 6.7-13.7s for gemini-2.5-flash; on bag
# OCR the two lite models returned the *same* reading as gemini-2.5-flash and
# did it several seconds sooner. Neither job is model-limited: the rationale
# writes prose about numbers the engine has already fixed, and the bag reading
# is short printed text. The heavier models stay on as fallbacks.
GEMINI_MODEL_CANDIDATES: tuple[str, ...] = (
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
)

# The user is waiting on the recommendation, so the whole candidate chain --
# not each attempt -- gets this many seconds before the deterministic template
# wins by default. Four, not five, leaves room for the engine's own arithmetic
# and the database round-trips inside the same request.
DEFAULT_BUDGET_S = 4.0

# No single candidate may spend the whole budget. gemini-flash-lite-latest
# answers in 1.2-1.9s when healthy but intermittently hangs to the server's
# own deadline (~14.5s, a 504), and a lead model that hangs must not cost the
# rest of the chain its turn -- that is precisely how a wait becomes a
# template fallback. Two seconds clears the healthy case with room to spare
# and still leaves the budget enough for a second candidate.
DEFAULT_ATTEMPT_TIMEOUT_S = 2.0

# Reading a bag photo is a different wait: a single successful call measured
# 12.6-19.3s, and unlike the rationale there is no deterministic fallback --
# giving up means the user types the bag in by hand. So the budget is wide
# enough for a retry after one bad candidate, and is not trying to be quick.
VISION_BUDGET_S = 45.0

# ...and a per-attempt cap to match: a real bag reading measured 12.6-19.3s,
# so the prose call's 2s would abandon every one of them.
VISION_ATTEMPT_TIMEOUT_S = 22.0

# HttpOptions.timeout doubles as the X-Server-Timeout header, so it is a
# *server* deadline as well as a client one and the API rejects it below 10s.
# It therefore cannot enforce the budgets above; it is set only so an attempt
# that has already been abandoned stops holding its thread and connection.
#
# It still has to sit above a legitimate call, or it truncates real work:
# at 15s it turned gemini-2.5-flash's 19.3s bag reading into a 504.
ATTEMPT_CEILING_MS = 15000
VISION_ATTEMPT_CEILING_MS = 40000


def resolve_model_candidates(default_models: Iterable[str]) -> list[str]:
    override = os.getenv("WCDA_GEMINI_MODELS")
    if override:
        models = [item.strip() for item in override.split(",") if item.strip()]
        if models:
            return models
    return list(default_models)


def resolve_budget_s(
    default_budget_s: float = DEFAULT_BUDGET_S,
    env_var: str = "WCDA_LLM_BUDGET_S",
) -> float:
    """The wall-clock budget for a whole candidate chain, in seconds.

    Each call site names its own environment variable, because the two budgets
    are not interchangeable: one bounds a wait the user can already skip (the
    template renders without any model at all), the other bounds a wait with
    nothing behind it.
    """
    raw = os.getenv(env_var)
    if raw:
        try:
            parsed = float(raw)
        except ValueError:
            return default_budget_s
        if parsed > 0:
            return parsed
    return default_budget_s


def thinking_level_for(model_name: str, *, default: str = "low") -> str | None:
    """The ``thinking_level`` to request for a model, or None if unsupported.

    Gemini 3.x accepts ``"low"`` or ``"high"``; ``"high"`` is extended
    reasoning. Older models reject the parameter, and that rejection is fatal
    rather than skippable, so the version gate is explicit rather than a
    try/except.

    Both call sites are in a path where the user is waiting, so both default to
    ``"low"``. ``WCDA_GEMINI_THINKING`` (low | high | off) overrides every path.
    """
    if not model_name.startswith("gemini-3"):
        return None
    level = os.getenv("WCDA_GEMINI_THINKING", default).strip().lower()
    if level in ("", "off", "none", "disabled", "false"):
        return None
    return level if level in ("low", "high") else default


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
            "deadline exceeded",
            "timed out",
            "timeout",
        )
    )


def is_model_unavailable_error(error: Exception) -> bool:
    """True when *this model* cannot be used but another one still might.

    A retired model name is the case that matters: gemini-2.5-flash-lite began
    returning 404 "no longer available" while still appearing in models.list.
    That is not transient, but it is also no reason to abandon the remaining
    candidates -- which is exactly what the old break did, hiding a working
    gemini-flash-lite-latest behind a dead name.
    """
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "not_found",
            "not found",
            "no longer available",
            "is not supported",
            "unsupported",
            "unrecognized",
            "unrecognised",
            "unknown field",
            "unknown name",
            "invalid_argument",
        )
    )


def should_try_next_model(error: Exception) -> bool:
    """Whether to fall through to the next candidate after ``error``.

    Only a fault that every candidate would hit alike -- a bad API key, a
    revoked project -- is worth stopping the chain for. Anything specific to
    one model should cost that model its turn, nothing more.
    """
    message = str(error).lower()
    fatal = (
        "api key",
        "api_key",
        "permission_denied",
        "permission denied",
        "unauthenticated",
        "unauthorized",
        "401",
        "403",
    )
    if any(marker in message for marker in fatal):
        return False
    return is_transient_model_error(error) or is_model_unavailable_error(error)


def _arrange_cleanup(
    pool: ThreadPoolExecutor,
    outstanding: list[Future[object]],
    on_all_done: Callable[[], None] | None,
) -> None:
    """Release the caller's resources once no abandoned attempt can use them.

    An abandoned attempt still holds the shared genai client. Closing that
    client the moment the chain gives up -- which is what the caller's
    ``finally: client.close()`` does -- pulls the socket out from under a live
    request, and the thread dies with "[Errno 9] Bad file descriptor".
    """
    if not outstanding:
        if on_all_done is not None:
            on_all_done()
        pool.shutdown(wait=False)
        return

    remaining = [len(outstanding)]
    lock = Lock()

    def one_finished(_future: Future[object]) -> None:
        with lock:
            remaining[0] -= 1
            last = remaining[0] == 0
        if last:
            if on_all_done is not None:
                on_all_done()
            pool.shutdown(wait=False)

    for future in outstanding:
        future.add_done_callback(one_finished)


def try_model_candidates[ResultT](
    default_models: Iterable[str],
    call_model: Callable[[str], ResultT],
    evaluate_result: Callable[[ResultT], tuple[bool, str | None]],
    budget_s: float | None = None,
    attempt_timeout_s: float | None = None,
    on_all_done: Callable[[], None] | None = None,
) -> tuple[ResultT | None, str | None]:
    """Try candidate models in order and return the first successful result.

    ``budget_s`` bounds the whole chain in wall-clock time and
    ``attempt_timeout_s`` bounds any one candidate within it, so a model that
    hangs costs its own turn rather than the entire chain's. Both are enforced
    client-side, in worker threads, because the SDK cannot express them:
    ``HttpOptions.timeout`` also populates ``X-Server-Timeout``, which the API
    rejects below 10s, and the SDK passes ``timeout=None`` per request,
    overriding any client-level setting.

    An over-budget attempt is *abandoned*, not cancelled -- the request is
    already in flight and cannot be recalled. Its thread runs to completion
    unobserved and its answer is dropped, so each attempt gets its own worker
    rather than queueing behind one that is still stuck.

    ``on_all_done`` is where the caller closes its client. It runs once no
    abandoned attempt can still be using it, which may be after this function
    has already returned.
    """
    budget = resolve_budget_s() if budget_s is None else budget_s
    attempt_cap = attempt_timeout_s if attempt_timeout_s is not None else budget
    deadline = time.monotonic() + budget
    last_error: str | None = None
    models = resolve_model_candidates(default_models)

    pool = ThreadPoolExecutor(
        max_workers=max(1, len(models)), thread_name_prefix="gemini"
    )
    outstanding: list[Future[object]] = []
    try:
        for model_name in models:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                last_error = last_error or f"budget of {budget:g}s exhausted"
                break
            future = pool.submit(call_model, model_name)
            try:
                result = future.result(timeout=min(attempt_cap, remaining))
            except FutureTimeout:
                outstanding.append(future)  # type: ignore[arg-type]
                last_error = f"{model_name}: no answer within {attempt_cap:g}s"
                continue
            except Exception as exc:
                last_error = f"{model_name}: {exc}"
                if not should_try_next_model(exc):
                    break
                continue

            ok, error_message = evaluate_result(result)
            if ok:
                return result, None
            last_error = f"{model_name}: {error_message or 'unsuccessful response'}"
    finally:
        _arrange_cleanup(pool, outstanding, on_all_done)

    return None, last_error
