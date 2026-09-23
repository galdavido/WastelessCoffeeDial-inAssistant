"""The language model's remaining job: explain numbers it did not choose.

The engine decides the recipe. Gemini writes the prose around it -- a job
where a language model is genuinely better than arithmetic, and one that
involves no measurement.

Three independent layers stop a number leaking back in, because a prompt
instruction alone is the weakest possible guarantee:

1. **Schema.** Rationale has no numeric fields, and structured output cannot
   emit a field the schema does not declare.
2. **Numeric allow-list.** Every digit in the returned text must match a
   number the engine itself produced. One stray figure rejects the whole
   response.
3. **Deterministic template.** If Gemini is unavailable, rate-limited, or
   keeps smuggling numbers in, render_template() produces the explanation from
   the engine's own decision. The recommendation path therefore has no hard
   dependency on the LLM at all.

Google Search grounding is deliberately not used here. It existed to let the
model fetch numbers off the web, which is precisely the behaviour being
removed.
"""

from __future__ import annotations

import re
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

from core.brewing import Recipe

from .model_selection import (
    ATTEMPT_CEILING_MS,
    DEFAULT_ATTEMPT_TIMEOUT_S,
    GEMINI_MODEL_CANDIDATES,
    json_config,
    resolve_budget_s,
    try_model_candidates,
)

_NUMERAL = re.compile(r"\d+(?:[.,]\d+)?")

# Small integers are allowed through unconditionally: they appear in ordinary
# prose ("a couple of shots", "step 2") and carry no risk of being mistaken
# for a recipe value.
_ALWAYS_ALLOWED = {str(n) for n in range(0, 11)}


class Rationale(BaseModel):
    """What the model may return. Note the absence of any numeric field."""

    headline: str
    why: str
    what_to_watch: str


def scrub_numerals(text: str, allowed: frozenset[str]) -> str | None:
    """Return the text unchanged, or None if it contains an unapproved number.

    Rejecting wholesale rather than editing is deliberate: a sentence with a
    number silently removed reads as though the model meant something else.
    """
    for match in _NUMERAL.finditer(text):
        token = match.group(0).replace(",", ".")
        normalised = token.rstrip("0").rstrip(".") if "." in token else token
        if (
            token in allowed
            or normalised in allowed
            or token in _ALWAYS_ALLOWED
            or normalised in _ALWAYS_ALLOWED
        ):
            continue
        return None
    return text


def _allowed_tokens(recipe: Recipe, *engine_text: str) -> frozenset[str]:
    """Every number the model is permitted to repeat.

    The rule being enforced is "no number the *engine* did not produce", and
    the engine produces more than the recipe fields: its notes and confidence
    label name past grind settings, shot counts and the like, and the prompt
    puts all of them in front of the model and invites it to explain them.
    Allowing only ``recipe.numeric_tokens()`` therefore rejected responses for
    quoting the engine's own words back -- a real recommendation was thrown
    away for saying "26", a setting the engine itself had just described.

    Passing the engine-authored prompt text here keeps the guarantee intact
    while removing the false rejection: a figure the model invents still
    appears nowhere in ``engine_text`` and is still refused.
    """
    tokens = set(recipe.numeric_tokens())
    # Ratio, as it is usually written in prose ("1:2").
    if recipe.yield_g and recipe.dose_g:
        ratio = recipe.yield_g / recipe.dose_g
        tokens.update({f"{ratio:g}", f"{ratio:.1f}"})
    for source in engine_text:
        for match in _NUMERAL.finditer(source or ""):
            token = match.group(0).replace(",", ".")
            tokens.add(token)
            if "." in token:
                tokens.add(token.rstrip("0").rstrip("."))
    return frozenset(tokens)


def render_template(recipe: Recipe, confidence_label: str) -> Rationale:
    """The deterministic explanation. Also the fallback when the LLM fails."""
    bits: list[str] = []
    if recipe.grind_clicks is not None:
        bits.append(f"grind {recipe.grind_clicks:g}")
    bits.append(f"{recipe.dose_g:g} g in")
    if recipe.yield_g is not None:
        bits.append(f"{recipe.yield_g:g} g out")
    elif recipe.water_g is not None:
        bits.append(f"{recipe.water_g:g} g water")
    if recipe.brew_temp_c is not None:
        bits.append(f"{recipe.brew_temp_c:g} C")

    headline = ", ".join(bits)

    why_parts = list(recipe.notes)
    if not why_parts:
        why_parts.append("This comes from your target band and what you last measured.")
    why_parts.append(confidence_label)

    watch = (
        f"Aim for about {recipe.target_time_s:g} seconds."
        if recipe.target_time_s is not None
        else "Note the time and how it tastes, and I'll solve the next step from that."
    )
    return Rationale(
        headline=headline,
        why=" ".join(why_parts),
        what_to_watch=watch,
    )


def _build_prompt(recipe: Recipe, confidence_label: str, context: str) -> str:
    """The numbers arrive already decided. The model's job is to explain them."""
    return f"""You are a friendly, plain-spoken barista explaining a recipe that
has ALREADY been decided by a physical model of extraction. You are writing the
explanation only.

THE DECISION (fixed, not yours to change):
{recipe}

Confidence in this recommendation: {confidence_label}

Why the engine chose it:
{context}

Write three short fields:
- headline: what to do, in under 80 characters.
- why: the reasoning, under 400 characters, in warm plain English.
- what_to_watch: what to pay attention to during the brew, under 200 characters.

HARD RULES:
- Do NOT state any number that does not already appear in the decision above.
  No grind settings, doses, weights, times, temperatures or ratios of your own.
  If you want to mention a quantity, refer to it qualitatively ("a little
  coarser", "slightly longer") instead.
- Do not contradict the decision or suggest an alternative recipe.
- Do not claim to know the extraction yield: it has not been measured.
- No markdown, no bullet points, no headings.
"""


def write_rationale(
    recipe: Recipe,
    confidence_label: str,
    context: str = "",
) -> tuple[Rationale, str | None]:
    """Explain a recipe. Falls back to the template rather than failing.

    Returns (rationale, model_name_or_None). A None model name means the
    deterministic template was used, which is a normal outcome, not an error.
    """
    template = render_template(recipe, confidence_label)
    allowed = _allowed_tokens(recipe, confidence_label, context, str(recipe))

    # The ceiling is not the budget -- the API rejects a deadline under 10s
    # (it doubles as X-Server-Timeout). try_model_candidates enforces the real
    # budget; this only stops an abandoned attempt lingering indefinitely.
    try:
        client = genai.Client(
            http_options=types.HttpOptions(timeout=ATTEMPT_CEILING_MS)
        )
    except Exception:  # no API key: the template is a complete answer
        return template, None

    prompt = _build_prompt(recipe, confidence_label, context)
    parsed: Rationale | None = None
    used_model: str | None = None

    def call_model(model_name: str) -> Any:
        nonlocal used_model
        used_model = model_name
        # Prose only: the engine has already fixed every number, and
        # scrub_numerals rejects any the model invents. Extended reasoning has
        # nothing to decide here, so json_config keeps thinking at "low".
        return client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=json_config(model_name, Rationale, temperature=0.2),
        )

    def evaluate(response: Any) -> tuple[bool, str | None]:
        nonlocal parsed
        text = getattr(response, "text", None)
        if not text:
            return False, "empty response"
        try:
            candidate = Rationale.model_validate_json(text)
        except Exception as exc:
            return False, f"invalid schema: {exc}"
        for field in (candidate.headline, candidate.why, candidate.what_to_watch):
            if scrub_numerals(field, allowed) is None:
                # The model invented a figure. Reject the whole response.
                return False, "response contained a number the engine did not produce"
        parsed = candidate
        return True, None

    def close_client() -> None:
        # Deferred to try_model_candidates: an abandoned attempt is still
        # using this client, and closing it underneath one raises
        # "[Errno 9] Bad file descriptor" in that thread.
        close = getattr(client, "close", None)
        if callable(close):
            close()

    try:
        try_model_candidates(
            GEMINI_MODEL_CANDIDATES,
            call_model=call_model,
            evaluate_result=evaluate,
            budget_s=resolve_budget_s(),
            attempt_timeout_s=DEFAULT_ATTEMPT_TIMEOUT_S,
            on_all_done=close_client,
        )
    except Exception:
        return template, None

    if parsed is None:
        return template, None
    return parsed, used_model
