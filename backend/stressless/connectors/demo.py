"""Demo sources: the three connector interfaces served from a generated dataset."""
from __future__ import annotations

from datetime import date
from typing import List

from ..models import CalendarEvent, DailyActivity, Dataset, HeartRateDay, LocationVisit, SleepNight
from .base import BiometricSource, CalendarSource, LocationSource


class DemoSources(CalendarSource, LocationSource, BiometricSource):
    def __init__(self, dataset: Dataset) -> None:
        self.ds = dataset

    def events(self, start: date, end: date) -> List[CalendarEvent]:
        return [e for e in self.ds.events if start <= e.start.date() <= end]

    def visits(self, start: date, end: date) -> List[LocationVisit]:
        return [v for v in self.ds.visits if start <= v.start.date() <= end]

    def hr_days(self, start: date, end: date) -> List[HeartRateDay]:
        return [h for h in self.ds.hr_days if start <= h.date <= end]

    def nights(self, start: date, end: date) -> List[SleepNight]:
        return [n for n in self.ds.nights if start <= n.date <= end]

    def activity(self, start: date, end: date) -> List[DailyActivity]:
        return [a for a in self.ds.activity if start <= a.date <= end]
