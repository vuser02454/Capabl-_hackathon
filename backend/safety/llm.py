"""Groq client for the narrative half of the safety analysis.

The model writes prose and nothing else. It never produces a risk level, a score, a count, or any
field a downstream number depends on — those come from `rules.py` and pandas. What it adds is the
part rules are bad at: reading a paragraph back in plain language a safety officer can act on.

Chosen over the project's configured Gemini path because Gemini's free tier is 20 requests/day and
is already exhausted; Groq is OpenAI-compatible, so `httpx` (already a dependency) is enough and no
new package is needed.

Every call can fail and none of them is load-bearing. `available()` reports configuration, each
helper returns `None` on any fault, and the callers substitute a deterministic sentence. A missing
API key degrades the wording, never the classification.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 2


def available() -> bool:
    from config import settings

    return bool(settings.groq_api_key)


def model_name() -> Optional[str]:
    from config import settings

    return settings.groq_model if settings.groq_api_key else None


def _chat(system: str, user: str, *, json_mode: bool = True, max_tokens: int = 900) -> Optional[str]:
    """One completion, or None. Retries transient faults; never raises into a request handler."""
    from config import settings

    if not settings.groq_api_key:
        return None
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx ships with the backend
        return None

    body: Dict[str, Any] = {
        "model": settings.groq_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = httpx.post(
                f"{settings.groq_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                json=body,
                timeout=TIMEOUT_SECONDS,
            )
            if response.status_code == 429 and attempt < MAX_RETRIES:
                time.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code >= 400:
                logger.warning("groq_http_error status=%s", response.status_code)
                return None
            content = response.json()["choices"][0]["message"].get("content")
            return content if content else None
        except Exception as exc:  # noqa: BLE001 - the narrative is optional by design
            logger.warning("groq_call_failed attempt=%s error=%s", attempt, type(exc).__name__)
            if attempt >= MAX_RETRIES:
                return None
            time.sleep(1.0 * (attempt + 1))
    return None


def _json(system: str, user: str, max_tokens: int = 900) -> Optional[Dict[str, Any]]:
    raw = _chat(system, user, json_mode=True, max_tokens=max_tokens)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        logger.warning("groq_returned_invalid_json")
        return None


# --- the three places prose genuinely helps ---------------------------------------------------

_GROUNDING = (
    "You write for an industrial safety officer. Use ONLY facts present in the provided report or "
    "structured findings. Never invent equipment, injuries, times, names or causes. If something is "
    "not stated, omit it rather than guessing. Be specific and concise; no filler, no reassurance."
)


def summarise_report(text: str, facts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One-line summary plus a grounded root-cause reading. Both optional."""
    return _json(
        _GROUNDING + ' Return JSON: {"summary": "one sentence, max 30 words", '
        '"root_cause": "the most likely immediate cause stated or clearly implied, else null", '
        '"contributing_factors": ["short phrases, only if stated"]}',
        f"REPORT:\n{text}\n\nDETECTED HAZARDS: {facts.get('hazards')}\n"
        f"MISSING CONTROLS: {facts.get('missing_controls')}",
        max_tokens=600,
    )


def explain_risk(text: str, level: str, contributions: List[Dict[str, Any]]) -> Optional[List[str]]:
    """Why this level, in the officer's language.

    The level is passed IN, already decided by the rules. The model explains a conclusion; it does
    not reach one, and it is told so explicitly so it cannot argue with the classification.
    """
    factors = "; ".join(f"{c['factor']} (+{c['points']})" for c in contributions) or "none detected"
    result = _json(
        _GROUNDING + f" The risk level {level} has ALREADY been determined by deterministic rules. "
        "Do not dispute, re-rate or hedge it. Explain WHY these specific findings justify it. "
        'Return JSON: {"reasoning": ["2-4 short sentences, each citing a finding"]}',
        f"REPORT:\n{text}\n\nSCORED FACTORS: {factors}\nLEVEL: {level}",
        max_tokens=600,
    )
    if not result:
        return None
    reasoning = result.get("reasoning")
    if isinstance(reasoning, list):
        return [str(r) for r in reasoning if str(r).strip()][:4]
    return None


def recommend(level: str, facts: Dict[str, Any], patterns: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Concrete actions. The pattern context is what makes them specific rather than generic."""
    return _json(
        _GROUNDING + " Recommend actions a supervisor can carry out this week. Name the location, "
        "equipment or control involved. Never write generic advice like 'improve safety' or "
        '"provide training" without saying on what. Return JSON: '
        '{"recommended_actions": ["3 max, imperative, specific"], '
        '"preventive_actions": ["2 max, address recurrence"], '
        '"reasoning": "one sentence tying the actions to the findings"}',
        f"RISK LEVEL: {level}\nHAZARDS: {facts.get('hazards')}\n"
        f"MISSING CONTROLS: {facts.get('missing_controls')}\n"
        f"LOCATION: {facts.get('location')}\nEQUIPMENT: {facts.get('equipment')}\n"
        f"RECURRING ACROSS FLEET: {json.dumps(patterns)[:700]}",
        max_tokens=800,
    )


def interpret_patterns(stats: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Read the aggregate counts back as a trend. The counts themselves come from pandas."""
    return _json(
        _GROUNDING + " You are reading aggregate counts across many reports. Do NOT recompute or "
        "restate the numbers — interpret what the distribution implies operationally. "
        'Return JSON: {"trend_summary": "2-3 sentences", '
        '"emerging_patterns": [{"pattern": "short title", "detail": "one sentence", '
        '"evidence": "which counts support it"}]}',
        json.dumps(stats)[:2500],
        max_tokens=900,
    )
