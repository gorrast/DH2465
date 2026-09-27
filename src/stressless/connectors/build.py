"""Assemble an imported Dataset from parsed sources (SPEC §6.1)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional, Sequence

from ..models import CalendarEvent, DailyActivity, Dataset, HeartRateDay, LocationVisit, Persona, SleepNight
from ..timeutil import DEFAULT_TZ, tz


def build_dataset(persona: Persona, events: Sequence[CalendarEvent], visits: Sequence[LocationVisit], hr_days: Sequence[HeartRateDay],
                  nights: Sequence[SleepNight], activity: Sequence[DailyActivity], today: date, days: Optional[int] = None) -> Dataset:
    end = today - timedelta(days=1)
    night_dates = [n.date for n in nights if n.date <= end]
    if days:
        start = end - timedelta(days=days - 1)
    elif night_dates:
        start = min(night_dates)
    else:
        start = end - timedelta(days=69)
    by_date = {n.date: n for n in nights}
    full: List[SleepNight] = []
    d = start
    while d <= end:
        full.append(by_date.get(d) or SleepNight(date=d, worn=False))
        d += timedelta(days=1)
    return Dataset(persona=persona, seed=0, source="imported", start=start, end=end, today=today,
                   events=[e for e in events if start <= e.start.date() <= today + timedelta(days=7)],
                   visits=[v for v in visits if start <= v.start.date() <= end], hr_days=[h for h in hr_days if start <= h.date <= today],
                   nights=full, activity=[a for a in activity if start <= a.date <= end], truth=None,
                   generated_at=datetime.now(tz(persona.tz)), showcase=False)


def imported_persona(name: str, tzname: str = DEFAULT_TZ) -> Persona:
    return Persona(key="imported", name=name, tagline="Your own data", description="Imported from Apple Health, your calendar and Google Takeout.", tz=tzname)
