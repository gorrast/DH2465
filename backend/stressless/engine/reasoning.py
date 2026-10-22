"""The Morning view's narrative, written by rules on the server (SPEC §7.9).

It used to have an optional Claude writer (Opus 5, one call per user per day); the generated daily and weekly
reports replaced it, so the narrative never calls a model. ``reasoning_mode`` is still the switch for those reports.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

log = logging.getLogger("stressless.engine.reasoning")

FORBIDDEN_KEYS = {"start", "end", "location_hint", "attendees", "lat", "lon", "id", "event_ids", "visit_id", "event_id"}


def build_payload(report: Any) -> Dict[str, Any]:
    """De-identified summary: numbers and titles only, no ids, times, places or people counts."""
    def cause(c) -> Dict[str, Any]:
        return {"title": c.title, "detail": c.detail, "points": c.points, "confidence": c.confidence}
    return {
        "score": report.score,
        "usual_score": None if report.baseline_score is None else round(report.baseline_score),
        "rating": report.rating,
        "causes": [cause(c) for c in report.causes],
        "helpers": [cause(c) for c in report.helpers],
        "facts": [e.text for e in report.proximal],
        "unexplained_note": report.unexplained_note,
        "n_nights": report.model.n_nights if report.model else None,
        "suggestion": report.suggestions[0].title if report.suggestions else None,
        "missing_data": report.missing_data,
    }


class Reasoner:
    mode = "rules"

    def narrate(self, payload: Dict[str, Any]) -> str:
        raise NotImplementedError


class RuleReasoner(Reasoner):
    mode = "rules"

    def narrate(self, payload: Dict[str, Any]) -> str:
        n = payload.get("n_nights")
        footer = "Based on %s nights of your data · correlation, not proof." % (n if n is not None else "your")
        if payload.get("missing_data"):
            return "Your watch has no data for last night, so there is no score to explain. %s The calendar still shows what the day looked like; the suggestion below is based on your patterns." % ""
        if n is not None and n < 10:
            return "Building your baseline: %d of 10 nights recorded. StressLess needs about ten nights before it starts explaining scores; until then it shows what your watch measured." % n
        score, usual = payload.get("score"), payload.get("usual_score")
        parts: List[str] = []
        if score is not None and usual is not None:
            diff = score - usual
            if abs(diff) < 3:
                parts.append("Your sleep score was %d, about your usual %d." % (score, usual))
            else:
                parts.append("Your sleep score was %d, %d %s your usual %d." % (score, abs(diff), "below" if diff < 0 else "above", usual))
        elif score is not None:
            parts.append("Your sleep score was %d." % score)
        causes = payload.get("causes") or []
        if causes:
            c = causes[0]
            detail = c["detail"][0].lower() + c["detail"][1:] if c.get("detail") else ""
            parts.append("The strongest likely cause was %s%s" % (c["title"][0].lower() + c["title"][1:], (": " + detail + ".") if detail else "."))
            if len(causes) > 1:
                c2 = causes[1]
                parts.append("%s also fits a pattern: %s." % (c2["title"], (c2["detail"][0].lower() + c2["detail"][1:]) if c2.get("detail") else "on days like that your sleep tends to be shorter"))
            if len(causes) > 2:
                parts.append("%s likely played a smaller part." % causes[2]["title"])
        else:
            parts.append("Nothing in your calendar stands out for this night.")
        helpers = payload.get("helpers") or []
        if helpers:
            parts.append("%s likely helped." % helpers[0]["title"])
        if payload.get("unexplained_note"):
            parts.append(payload["unexplained_note"])
        if payload.get("suggestion"):
            parts.append("Suggestion: %s." % payload["suggestion"].rstrip("."))
        parts.append(footer)
        return " ".join(parts)


def reasoning_mode() -> str:
    if os.environ.get("STRESSLESS_REASONER", "").lower() == "claude":
        try:
            import anthropic  # noqa: F401
            return "claude"
        except Exception:
            log.warning("STRESSLESS_REASONER=claude but the anthropic package is not importable; using rules")
    return "rules"


def get_reasoner() -> Reasoner:
    return RuleReasoner()
