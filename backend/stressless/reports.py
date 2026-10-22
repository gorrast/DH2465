"""Schemas for the generated daily and weekly reports.

Three layers
------------
* ``ReportInput`` — everything the engine computed before the model is called. The model sees only this:
  numbers, labels and dates, never ids, clock times, places or people (same rule as ``reasoning.build_payload``).
* ``DailyContent`` / ``WeeklyContent`` — what the model writes. Words only: a finding points at the numbers
  behind it with ``evidence`` keys from the input, so the UI shows computed values and never model-written ones.
* ``Report`` — the stored row: input + content + how and when it was made.

The content models are sent to the API as a structured-output schema, so they must stay within its limits:
no dicts, no recursion, no numeric or length constraints. Field descriptions are part of the prompt.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReportKind = Literal["daily", "weekly"]
Confidence = Literal["high", "medium", "low"]
MetricStatus = Literal["good", "typical", "watch", "unknown"]
Direction = Literal["helped", "hurt", "neutral"]
Tone = Literal["good", "neutral", "watch"]


# --------------------------------------------------------------------------- #
# Data sources (also drives the "ready to generate?" dialog)
# --------------------------------------------------------------------------- #
class SourceStatus(BaseModel):
    key: str                                   # "watch" | "calendar" | "screen_time" | ...
    label: str                                 # "Health data (Android)"
    connected: bool
    data_until: Optional[datetime] = None      # newest data point we hold
    synced_at: Optional[datetime] = None       # last successful upload
    required: bool = False                     # a report cannot be generated without it
    ready: bool = False                        # data covers the whole report period


# --------------------------------------------------------------------------- #
# Input: computed by the engine
# --------------------------------------------------------------------------- #
class Metric(BaseModel):
    """One measured value for the period, next to the person's own usual."""
    key: str                                   # "sleep.score" | "hr.resting" | "screen.minutes" — unique in a report
    label: str                                 # "Resting heart rate"
    source: str                                # SourceStatus.key it came from
    value: Optional[float]
    unit: str                                  # "points" | "bpm" | "ms" | "min" | "%"
    baseline: Optional[float] = None           # personal usual for this metric
    delta: Optional[float] = None              # value - baseline
    status: MetricStatus = "unknown"


class Pattern(BaseModel):
    """A relationship the engine found in the person's history that applies to this period."""
    key: str                                   # "pattern.late_meeting" — unique in a report
    title: str                                 # "Late meetings"
    detail: str                                # one sentence with the numbers, written by code
    direction: Direction
    effect: Optional[float] = None             # signed size of the effect
    unit: str = "points"                       # what ``effect`` is measured in
    n: int = 0                                 # observations behind it
    confidence: Confidence = "low"
    outcome: Optional[str] = None              # what ``effect`` is measured on, when not the sleep score ("Time asleep")
    effect_low: Optional[float] = None         # 95 % interval of ``effect``
    effect_high: Optional[float] = None
    n_without: Optional[int] = None            # observations it is compared against


class DayPoint(BaseModel):
    """One day of the week being summarised (weekly reports only)."""
    day: date
    score: Optional[int] = None                # sleep score for the night after this day
    tags: List[str] = Field(default_factory=list)   # "Travel day", "5 meetings", "Morning workout"


class ReportInput(BaseModel):
    kind: ReportKind
    period_start: date                         # daily: the morning; weekly: the Monday
    period_end: date                           # daily: same as period_start; weekly: the Sunday
    n_nights: int                              # nights of history behind the baselines and patterns
    metrics: List[Metric] = Field(default_factory=list)
    patterns: List[Pattern] = Field(default_factory=list)
    days: List[DayPoint] = Field(default_factory=list)       # weekly only
    suggestions: List[str] = Field(default_factory=list)     # ready-made suggestion titles, best first
    notes: List[str] = Field(default_factory=list)           # gaps and caveats the report must respect

    def keys(self) -> set[str]:
        return {m.key for m in self.metrics} | {p.key for p in self.patterns}


# --------------------------------------------------------------------------- #
# Content: written by the model
# --------------------------------------------------------------------------- #
class _Content(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Finding(_Content):
    title: str = Field(description="Three to six words naming the finding.")
    body: str = Field(description="One or two sentences explaining it in plain, warm language. Say 'likely' or "
                                  "'is associated with', never 'caused'.")
    tone: Tone = Field(description="good: worth celebrating. watch: worth attention. neutral: just interesting.")
    confidence: Confidence = Field(description="Copy the confidence of the pattern it rests on; low if it rests on none.")
    evidence: List[str] = Field(description="Keys of the metrics and patterns from the input that back this finding. "
                                            "At least one; use only keys that exist in the input.")


class DayHighlight(_Content):
    day: date = Field(description="A date taken from the input's days.")
    reason: str = Field(description="One sentence on what likely made this day stand out.")


class ReportContent(_Content):
    headline: str = Field(description="At most ten words. The single most important thing, in a friendly voice.")
    summary: str = Field(description="Two or three sentences giving the overall picture. Use only numbers present in "
                                     "the input.")
    findings: List[Finding] = Field(description="Two to four findings, strongest first.")
    fun_fact: Optional[str] = Field(description="One playful sentence about a surprising number in the input, or null "
                                                "if nothing stands out.")
    suggestion: Optional[str] = Field(description="One sentence built on the first entry of the input's suggestions, "
                                                  "or null if there are none.")
    caveats: List[str] = Field(description="Short honest limits of this report, taken from the input's notes. Empty "
                                           "if there are none.")


class DailyContent(ReportContent):
    """Explains last night and what today looks like."""


class WeeklyContent(ReportContent):
    """Looks back over one whole week."""
    trend: str = Field(description="One or two sentences on how the week compared with the person's usual.")
    best_day: Optional[DayHighlight] = Field(description="The best day of the week, or null if the days barely differ.")
    hardest_day: Optional[DayHighlight] = Field(description="The hardest day of the week, or null if the days barely "
                                                            "differ.")
    next_week: str = Field(description="One sentence on what to keep or change next week.")


CONTENT_MODELS = {"daily": DailyContent, "weekly": WeeklyContent}


def unknown_evidence(content: ReportContent, report_input: ReportInput) -> List[str]:
    """Evidence keys the model cited that are not in the input (should be empty)."""
    known = report_input.keys()
    return sorted({k for f in content.findings for k in f.evidence if k not in known})


# --------------------------------------------------------------------------- #
# Stored report
# --------------------------------------------------------------------------- #
class Report(BaseModel):
    kind: ReportKind
    period_start: date
    period_end: date
    generated_at: datetime
    mode: Literal["claude", "rules"]           # rules = written without a model (fallback or cap reached)
    model: Optional[str] = None                # model id when mode == "claude"
    input: ReportInput
    content: Union[WeeklyContent, DailyContent]
    sources: List[SourceStatus] = Field(default_factory=list)   # as they were when the report was generated

    @model_validator(mode="after")
    def _content_matches_kind(self) -> "Report":
        if not isinstance(self.content, CONTENT_MODELS[self.kind]):
            raise ValueError("%s report needs %s" % (self.kind, CONTENT_MODELS[self.kind].__name__))
        return self
