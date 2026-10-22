"""Report writers: Claude turns a ``ReportInput`` into ``DailyContent``/``WeeklyContent``; the rule writer does the
same without a model (fallback, daily cap, no API key).

The model per report kind comes from the environment, so it can be changed and compared without a deploy:
STRESSLESS_DAILY_MODEL (default claude-sonnet-5-5), STRESSLESS_WEEKLY_MODEL (default claude-haiku-5-5) and
STRESSLESS_REPORT_EFFORT (default medium).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..reports import CONTENT_MODELS, DayHighlight, Finding, ReportContent, ReportInput, unknown_evidence

log = logging.getLogger("stressless.engine.report_writer")

DEFAULT_MODELS = {"daily": "claude-sonnet-5-5", "weekly": "claude-haiku-5-5"}
MAX_TOKENS = 8000

SYSTEM = """You write short, friendly health reports for StressLess, an app that explains a person's sleep and \
recovery from their calendar, watch and phone data and what they log (cups of coffee, units of alcohol). The reader is the person themselves: a curious adult, not a clinician.

You get one JSON object computed by the app:
- metrics: measured values, each next to the person's own usual value (baseline) and a status \
(good, typical, watch, unknown).
- patterns: relationships the app found in this person's own history. The app computed and tested each one; detail \
states it with its numbers. effect is the size of the relationship in unit, measured on outcome (the sleep score when \
outcome is missing); effect_low to effect_high is the range the app is fairly sure the effect lies in; n is how many \
days or nights it happened on and n_without how many it is compared against; confidence says how sure the app is. \
Patterns about steps, phone use, coffee, bedtimes and sleep debt use limits taken from this person's own data \
(their "low-step days" are low for them), and "short nights" looks at the day after the night, not the night itself.
- Patterns with confidence low are early hints: a smaller difference or only a few days behind it. They are still \
worth sharing, because the app is meant to suggest things to try, not to prove them. Present them lightly ("an \
early hint", "might", "so far") and invite the person to keep logging or try a small change to see if it holds. \
Never present a low-confidence pattern as settled, and put stronger patterns first.
- days (weekly only): each day with the sleep score of the night after it and short tags describing the day.
- suggestions: ready-made suggestions, best first.
- notes: gaps and caveats that must be respected.

Rules:
- Use only numbers that appear in the JSON, rounded the way a person would say them. Never invent or compute new \
figures beyond simple rounding or differences shown in delta.
- These are correlations in one person's data. Say "likely", "tends to" or "is associated with", never "caused". \
Something else can drive both sides (a busy or a sick week), so frame a pattern as something worth trying, not a rule.
- Describe a pattern only with what its detail and numbers say. Do not add relationships, limits or explanations \
of your own, and do not turn a pattern around (an active-day pattern says nothing certain about low-step days).
- No medical advice, no diagnoses, and no alarm. If something looks unusual, say it is worth keeping an eye on.
- Prefer what the person can act on (their calendar, evenings, workouts, daily steps, phone use late in the \
evening, coffee and alcohol) over what they cannot.
- Coffee and alcohol are logged by the person. Talk about them in a neutral, non-judgmental way: describe what their \
own data shows, never moralise, and give no drinking guidelines or health warnings.
- Every finding must list the metric or pattern keys it rests on, exactly as they appear in the JSON.
- If notes say data is missing or history is short, make that clear in caveats and keep claims modest.
- Write in English, warm and plain, without jargon. Spell out what HRV is the first time you use it."""

TASK = {
    "daily": "Write this morning's daily report. It explains last night's sleep from the day before it.",
    "weekly": "Write the weekly report for the week in the JSON. It looks back over the whole week and ahead to "
              "the next one.",
}


class ReportWriterError(Exception):
    """The model could not produce a usable report; the caller falls back to the rule writer."""


@dataclass
class Written:
    content: ReportContent
    mode: str                                  # "claude" | "rules"
    model: Optional[str] = None
    usage: Optional[Dict[str, int]] = None     # token counts, for logging and cost estimates


def model_for(kind: str) -> str:
    return os.environ.get("STRESSLESS_%s_MODEL" % kind.upper()) or DEFAULT_MODELS[kind]


def claude_enabled() -> bool:
    """Same switch as the morning narrative: STRESSLESS_REASONER=claude and the anthropic package installed."""
    from .reasoning import reasoning_mode
    return reasoning_mode() == "claude"


def build_request(report_input: ReportInput, model: Optional[str] = None) -> Dict[str, Any]:
    """Keyword arguments for ``messages.parse``; also used by the try-out tool to show what is sent."""
    kind = report_input.kind
    model = model or model_for(kind)
    req: Dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": TASK[kind] + "\n\n" + report_input.model_dump_json(exclude={"kind"})}],
        "output_format": CONTENT_MODELS[kind],
        "output_config": {"effort": os.environ.get("STRESSLESS_REPORT_EFFORT", "medium")},
    }
    if model.startswith(("claude-opus", "claude-fable", "claude-sonnet")):
        # On a safety decline the API re-runs the request on a suitable model instead of returning a refusal.
        req["betas"] = ["server-side-fallback-2026-07-01"]
        req["fallbacks"] = "default"
    return req


class ClaudeReportWriter:
    def __init__(self, client: Any = None) -> None:
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def write(self, report_input: ReportInput, model: Optional[str] = None) -> Written:
        req = build_request(report_input, model)
        client = self._get_client()
        try:
            if "fallbacks" in req:
                response = client.beta.messages.parse(**req)
            else:
                response = client.messages.parse(**req)
        except Exception as exc:
            raise ReportWriterError("%s: %s" % (type(exc).__name__, exc)) from exc
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            raise ReportWriterError("the model declined to write the report")
        if stop == "max_tokens":
            raise ReportWriterError("the report was cut off at max_tokens")
        content = getattr(response, "parsed_output", None)
        if content is None:
            raise ReportWriterError("no parsed output (stop_reason %s)" % stop)
        bad = unknown_evidence(content, report_input)
        if bad:                                # keep the report, drop the keys the input does not have
            log.warning("model cited unknown evidence keys %s; dropping them", bad)
            for f in content.findings:
                f.evidence = [k for k in f.evidence if k not in bad]
        u = getattr(response, "usage", None)
        usage = {k: getattr(u, k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens")
                 if u is not None and isinstance(getattr(u, k, None), int)}
        return Written(content=content, mode="claude", model=getattr(response, "model", None) or req["model"], usage=usage)


# --------------------------------------------------------------------------- #
# Rule writer
# --------------------------------------------------------------------------- #
def _fmt(v: Optional[float], unit: str) -> str:
    if v is None:
        return "–"
    if unit == "min":
        m = int(round(v))
        return "%d h %02d min" % (m // 60, m % 60) if m >= 60 else "%d min" % m
    if unit == "points":
        return "%d" % round(v)
    if unit in ("steps", "count"):
        return "{:,}".format(int(round(v))).replace(",", " ")
    return ("%.1f" % v).rstrip("0").rstrip(".") + (" " + unit if unit else "")


def _findings(inp: ReportInput) -> List[Finding]:
    out: List[Finding] = []
    for p in inp.patterns[:3]:
        out.append(Finding(title=p.title, body="%s. %s" % (p.detail.rstrip("."), "Worth keeping an eye on."
                                                           if p.direction == "hurt" else "This tends to help."),
                           tone="watch" if p.direction == "hurt" else "good", confidence=p.confidence, evidence=[p.key]))
    for m in inp.metrics:
        if len(out) >= 4:
            break
        if m.status in ("good", "watch") and m.key != "sleep.score" and m.baseline is not None:
            out.append(Finding(title=m.label, body="%s, against your usual %s." % (_fmt(m.value, m.unit), _fmt(m.baseline, m.unit)),
                               tone=m.status, confidence="medium", evidence=[m.key]))
    return out


def rule_content(inp: ReportInput) -> ReportContent:
    score = next((m for m in inp.metrics if m.key == "sleep.score"), None)
    if score is None or score.value is None:
        headline, summary = "No sleep data to explain", "The watch recorded no night for this report."
    elif score.baseline is None or score.delta is None or abs(score.delta) < 3:
        headline = "A typical night" if inp.kind == "daily" else "A typical week"
        summary = "Your sleep score %s %s, close to your usual." % ("was" if inp.kind == "daily" else "averaged", _fmt(score.value, "points"))
    else:
        word = "below" if score.delta < 0 else "above"
        headline = ("Sleep %s your usual" if inp.kind == "daily" else "A week %s your usual") % word
        summary = "Your sleep score %s %s, %s points %s your usual %s." % (
            "was" if inp.kind == "daily" else "averaged", _fmt(score.value, "points"), _fmt(abs(score.delta), "points"),
            word, _fmt(score.baseline, "points"))
    common = dict(headline=headline, summary=summary, findings=_findings(inp), fun_fact=None,
                  suggestion=(inp.suggestions[0].rstrip(".") + ".") if inp.suggestions else None, caveats=list(inp.notes))
    if inp.kind == "daily":
        return CONTENT_MODELS["daily"](**common)
    scored = [d for d in inp.days if d.score is not None]
    best = max(scored, key=lambda d: d.score) if len(scored) >= 2 else None
    worst = min(scored, key=lambda d: d.score) if len(scored) >= 2 else None
    spread = best is not None and worst is not None and best.score - worst.score >= 5

    def hi(d) -> DayHighlight:
        return DayHighlight(day=d.day, reason="Sleep score %d. The day: %s." % (d.score, ", ".join(d.tags) if d.tags else "nothing special in the calendar"))
    top = next((p for p in inp.patterns if p.direction == "hurt"), None)
    return CONTENT_MODELS["weekly"](
        **common, trend=summary, best_day=hi(best) if spread else None, hardest_day=hi(worst) if spread else None,
        next_week=("Watch out for %s next week; it is your strongest pattern." % top.title.lower()) if top
        else "Keep the rhythm that worked this week.")


def write_rules(inp: ReportInput) -> Written:
    return Written(content=rule_content(inp), mode="rules")
