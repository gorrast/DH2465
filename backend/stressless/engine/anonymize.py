"""Calendar anonymisation for the report input: event titles become generic labels ("Meeting 3"), places and notes
are dropped. Off unless STRESSLESS_ANONYMIZE_CALENDAR is true.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List

from ..reports import ReportInput


def enabled() -> bool:
    return os.environ.get("STRESSLESS_ANONYMIZE_CALENDAR", "").strip().lower() in ("1", "true", "yes")


def _labels(report_input: ReportInput) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    counts: Dict[str, int] = {}
    for e in sorted(report_input.calendar, key=lambda e: e.start):
        if e.title in labels:
            continue
        counts[e.type] = counts.get(e.type, 0) + 1
        labels[e.title] = "%s %d" % (e.type.capitalize(), counts[e.type])
    return labels


def _replace(text: str, pattern: "re.Pattern[str] | None", labels: Dict[str, str]) -> str:
    return pattern.sub(lambda m: labels[m.group(0)], text) if pattern and text else text


def anonymize(report_input: ReportInput) -> ReportInput:
    labels = _labels(report_input)
    titles = sorted((t for t in labels if t.strip()), key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(t) for t in titles)) if titles else None

    def sub(text: str) -> str:
        return _replace(text, pattern, labels)

    def sub_all(texts: List[str]) -> List[str]:
        return [sub(t) for t in texts]

    return report_input.model_copy(update={
        "calendar": [e.model_copy(update={"title": labels[e.title], "location_hint": None, "notes": None})
                     for e in report_input.calendar],
        "patterns": [p.model_copy(update={"title": sub(p.title), "detail": sub(p.detail)}) for p in report_input.patterns],
        "days": [d.model_copy(update={"tags": sub_all(d.tags)}) for d in report_input.days],
        "suggestions": sub_all(report_input.suggestions),
        "notes": sub_all(report_input.notes),
    })
