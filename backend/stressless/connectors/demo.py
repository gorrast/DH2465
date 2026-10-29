"""Demo sources: the connector interfaces served from a generated dataset."""
from __future__ import annotations

from datetime import date
from typing import List

from ..models import CalendarEvent, DailyActivity, Dataset, HeartRateDay, SleepNight
from .base import BiometricSource, CalendarSource


class DemoSources(CalendarSource, BiometricSource):
    def __init__(self, dataset: Dataset) -> None:
        self.ds = dataset

    def events(self, start: date, end: date) -> List[CalendarEvent]:
        return [e for e in self.ds.events if start <= e.start.date() <= end]

    def hr_days(self, start: date, end: date) -> List[HeartRateDay]:
        return [h for h in self.ds.hr_days if start <= h.date <= end]

    def nights(self, start: date, end: date) -> List[SleepNight]:
        return [n for n in self.ds.nights if start <= n.date <= end]

    def activity(self, start: date, end: date) -> List[DailyActivity]:
        return [a for a in self.ds.activity if start <= a.date <= end]
