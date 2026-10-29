"""Report writers: Claude turns a ``ReportInput`` into ``DailyContent``/``WeeklyContent``; the rule writer does the
same without a model (fallback, daily cap, no API key).

The model per report kind comes from the environment, so it can be changed and compared without a deploy:
STRESSLESS_DAILY_MODEL (default claude-sonnet-5-5), STRESSLESS_WEEKLY_MODEL (default claude-sonnet-5-5) and
STRESSLESS_REPORT_EFFORT (default medium).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..reports import CONTENT_MODELS, DayHighlight, Finding, ReportContent, ReportInput, unknown_evidence

log = logging.getLogger("stressless.engine.report_writer")

DEFAULT_MODELS = {"daily": "claude-sonnet-5-5", "weekly": "claude-sonnet-5-5"}
MAX_TOKENS = 8000

SYSTEM = """You write short, clear reports for StressLess. The person's watch app already shows their sleep \
and heart rate, so repeating those numbers adds nothing. What StressLess adds is the links between their data \
sources: watch (sleep, heart rate, steps), calendar, workouts, music and podcasts, streaming, phone use and \
coffee/alcohol check-ins. A good report reads like a calm, attentive coach who noticed something in their data and \
says it plainly: "on your 12 days with Metallica, your daytime heart rate was 5 bpm higher than on your other 40 \
days" or "you sleep better after a run, but not after the gym".

You get one JSON object computed by the app. The app has done all the maths; you choose what is worth telling and \
put it into words.
- patterns: the links. A pattern with sources (cause first, then what it affects) is a link found in the person's \
own history: detail says it in one sentence with the numbers, effect is its strongest part, n and n_without are the \
days compared, confidence says how sure the app is, and happened is how many days of this report's period the cause \
occurred (0 means it is background: true in their history, but it did not happen this time). A pattern without \
sources is one of the app's likely causes behind last night's sleep. against_research is true when the link goes the \
other way than sleep research expects (more late phone use going with better sleep).
- days: the day before (daily) or each day of the week (weekly), with tags describing what happened.
- metrics: measured values next to the person's usual (baseline). Context only.
- suggestions: ready-made suggestions, best first.
- notes: gaps and caveats that must be respected.

Choosing what to tell:
- Build the report on two to four links. Prefer links that connect two different sources, that happened in this \
period (tie them to the day: "yesterday you had four meetings in a row, and on days like that..."), that are \
surprising, fun or something the person can act on, and whose effect is big enough to notice.
- Leave out links that are obvious (a short night is followed by a tired day), that stay within one source, that \
repeat another link (the same days seen twice, such as podcast days and one podcast; keep the more specific or \
fun one), and early hints, unless an early hint is genuinely fun; then call it an early hint. Leaving most links \
out is normal. Use background links only when they make a better story than what happened.
- Think about each link before you use it. Does it make sense, or is something else more likely behind it? \
Days with lots of phone use, few steps or late evenings are often free days or weekends that you sleep in after; \
a link can come from that rather than from the habit itself. A link with against_research true is almost always \
like this. Never present such a link as good news, never tell the person to do more of a habit that research \
says harms sleep, and never build the suggestion on it. Either leave it out or, if it is a fun puzzle, tell it as \
a puzzle and name the likely real reason ("late scrolling evenings went with longer sleep, but those were probably \
nights you could sleep in"). Use at most one such link.
- The findings, summary and suggestion (next_week in a weekly report) must agree with each other: do not praise a \
habit in one finding and suggest cutting it in the suggestion.
- Mention the sleep score or other plain metrics at most once, as context, never as a finding of their own.
- Artist, podcast and show names, and the titles of calendar activities in the links (a course, a shift, a study \
session), may be used freely; they make the report personal. Keep the activity in what you write: "you study with \
fewer phone pickups when Ludovico Einaudi is playing", not "Einaudi days".
- Each event once: when two links are the same days seen twice (a recurring evening shift and late meetings; a \
podcast and podcast days), tell the more specific one and leave the other out.
- Never argue with a link from a handful of days. Two good days with Metallica say nothing against a link measured \
over weeks; do not mention them. Anything you say must rest on a pattern or a metric, not on a few days' tags.

Writing:
- Plain words. No puns, metaphors, slang or hype ("secret weapon", "run hot", "team up", "wound-up"). A title says \
what goes with what: "Statistics days: higher heart rate", "Study music: fewer phone pickups".
- Say each fact once. The headline names the main link; the summary tells how the links fit together without \
repeating the findings' numbers; each finding gives its own numbers once.
- Give every number its comparison and its days, from n and n_without: "on your 9 study days with Ludovico \
Einaudi, 29 fewer pickups than on your other 11 study days". A bare "8 bpm lower" is not enough.
- No filler and no guessing at feelings or the body ("your evening probably started with a busier body").
- Short sentences. Leave a field empty or null rather than fill it with something weak.

Rules:
- Use only numbers that appear in the JSON, rounded the way a person would say them. Never compute new figures.
- These are correlations in one person's data. Say "likely", "tends to" or "goes with", never "caused".
- No medical advice, no diagnoses, and no alarm. If something looks off, say it is worth keeping an eye on.
- Every finding must list the pattern (and metric) keys it rests on, exactly as they appear in the JSON.
- If notes say data is missing or history is short, make that clear in caveats and keep claims modest.
- Write in English, friendly and plain, without jargon."""

TASK = {
    "daily": "Write this morning's daily report: what in yesterday likely shaped last night and today, told through "
             "the most interesting links.",
    "weekly": "Write the weekly report for the week in the JSON: the links that showed up this week, looking back over "
              "the whole week and ahead to the next one.",
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
    # cross-source links that happened first; links against research are not told as a rule of thumb
    links_first = sorted((p for p in inp.patterns if not p.against_research), key=lambda p: not (p.sources and p.happened))
    for p in links_first[:3]:
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
    common = dict(headline=headline, summary=summary, findings=_findings(inp), fun_fact=None, caveats=list(inp.notes))
    if inp.kind == "daily":
        return CONTENT_MODELS["daily"](**common, suggestion=(inp.suggestions[0].rstrip(".") + ".") if inp.suggestions else None)
    scored = [d for d in inp.days if d.score is not None]
    best = max(scored, key=lambda d: d.score) if len(scored) >= 2 else None
    worst = min(scored, key=lambda d: d.score) if len(scored) >= 2 else None
    spread = best is not None and worst is not None and best.score - worst.score >= 5

    def hi(d) -> DayHighlight:
        return DayHighlight(day=d.day, reason="Sleep score %d. The day: %s." % (d.score, ", ".join(d.tags) if d.tags else "nothing special in the calendar"))
    top = next((p for p in inp.patterns if p.direction == "hurt"), None)
    return CONTENT_MODELS["weekly"](
        **common, best_day=hi(best) if spread else None, hardest_day=hi(worst) if spread else None,
        next_week=("Watch out for %s next week; it is your strongest pattern." % top.title.lower()) if top
        else "Keep the rhythm that worked this week.")


def write_rules(inp: ReportInput) -> Written:
    return Written(content=rule_content(inp), mode="rules")
