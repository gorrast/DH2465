"""Shared test helpers. All tests use a fixed anchor date so nothing drifts with the calendar."""
import copy
import functools
from datetime import date

ANCHOR = date(2026, 9, 27)


@functools.lru_cache(maxsize=None)
def dataset(persona: str = "alex", seed: int = 7, days: int = 70):
    """Generate (once per process) the demo dataset for ``persona``. Do not mutate; use fresh_dataset."""
    from stressless.sim import generate_dataset
    return generate_dataset(persona, seed=seed, days=days, anchor=ANCHOR)


def fresh_dataset(persona: str = "alex", seed: int = 7, days: int = 70):
    """A deep copy safe to mutate (answers, added events)."""
    return copy.deepcopy(dataset(persona, seed, days))
