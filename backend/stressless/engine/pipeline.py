"""The Engine façade: everything the server and CLI need, with instance-level caches (SPEC §7.10)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..models import (CalendarEvent, Dataset, Habit, ModelSummary, MorningReport, RealityCheck, Suggestion,
                      WhatIfResult, to_jsonable)
from ..sim.sleep_score import rating
from ..timeutil import day_hour, fmt_day, fmt_minutes, tz
from . import attribution as A
from . import baselines as bl
from .features import day_features, describe_features
from .habits import rank_habits, weekly_insight
from .matching import event_response, evening_summary, hr_norm_curve
from .reality import reality_checks
from .reasoning import build_payload, get_reasoner
from .suggestions import suggest, to_ics
from .whatif import predict_day

log = logging.getLogger("stressless.engine.pipeline")
RECENT_DAYS = 14


class EngineError(Exception):
    status = 400


class NotFound(EngineError):
    status = 404


class Engine:
    def __init__(self, ds: Dataset, store: Optional[Any] = None) -> None:
        self.ds = ds
        self.store = store
        self._cache: Dict[Any, Any] = {}
        self.reasoner = get_reasoner()
        if store is not None:
            store.apply_to(ds)

    # ------------------------------------------------------------ plumbing --
    def invalidate(self) -> None:
        self._cache.clear()
        self.ds.reindex()

    def _answers(self) -> Dict[str, Dict[str, Any]]:
        return self.store.answers() if self.store is not None else {}

    def _accepted(self) -> Dict[str, str]:
        return self.store.accepted() if self.store is not None else {}

    def fit_for(self, upto: date, history_days: Optional[int] = None, include_unattended: bool = False) -> A.FitResult:
        return A.fit(self.ds, upto, history_days=history_days, cache=self._cache, include_unattended=include_unattended)

    def norm_for(self, upto: date):
        return hr_norm_curve(self.ds, upto, cache=self._cache)

    def _check_report_date(self, morning: date) -> None:
        if morning > self.ds.today:
            raise NotFound("No report yet for %s — the night has not happened." % morning.isoformat())
        if morning <= self.ds.start:
            raise NotFound("Your data starts on %s." % self.ds.start.isoformat())

    def _check_day(self, d: date) -> None:
        if d < self.ds.start or d > self.ds.today + timedelta(days=7):
            raise NotFound("No data for %s." % d.isoformat())

    # ---------------------------------------------------------------- core --
    def sources_for(self, d: date) -> Dict[str, int]:
        hr = self.ds.hr(d)
        return {"calendar_events": len(self.ds.events_on(d)),
                "maps_places": len({v.place_name for v in self.ds.visits_on(d) if v.place_type != "transit"}),
                "watch_minutes": sum(1 for b in hr.bpm if b is not None) if hr else 0}

    def habits(self, upto: date, history_days: Optional[int] = None) -> List[Habit]:
        return rank_habits(self.ds, upto, history_days, fit=self.fit_for(upto, history_days), cache=self._cache)

    def morning_report(self, morning: date, history_days: Optional[int] = None) -> MorningReport:
        self._check_report_date(morning)
        night_date = morning - timedelta(days=1)
        night = self.ds.night(night_date)
        worn = night is not None and night.worn and night.score is not None
        fit_ = self.fit_for(morning, history_days)
        norm = self.norm_for(morning)
        causes, helpers, proximal, meta = A.explain_night(self.ds, morning, fit_, norm, self._cache)
        if not worn:
            causes, helpers, proximal = [], [], []
        recovery = bl.recovery_metrics(self.ds, night_date) if worn else []
        base = bl.baseline_for(self.ds, night_date, "score", 28, history_days)
        baseline_score = base["median"]
        habits = self.habits(morning, history_days)
        suggestions = suggest(self.ds, morning, causes, habits, fit_, self._accepted(), self._cache)
        model = A.summary(fit_)
        score = night.score if worn else None
        if fit_.insufficient:
            note = "Building your baseline: %d of 10 nights recorded. Causes appear once ten nights are in." % fit_.n
        else:
            note = "Based on %d nights · explains about %d %% of night-to-night variation out of sample · correlation, not proof" % (
                fit_.n, int(round(100 * fit_.r2_loo)))
        report = MorningReport(
            date=morning, night_date=night_date, night=night, score=score, baseline_score=baseline_score,
            delta_vs_baseline=(score - baseline_score) if (score is not None and baseline_score is not None) else None,
            causes=causes, helpers=helpers, proximal=proximal, recovery=recovery, narrative="",
            reasoning_mode=self.reasoner.mode, suggestions=suggestions, predicted_score=meta.get("predicted"),
            residual=meta.get("residual"), unexplained_note=meta.get("unexplained_note") if worn else None, model=model,
            missing_data=None if worn else "No watch data for the night of %s — was the watch charging?" % fmt_day(night_date),
            confidence_note=note, calm_day_pred=meta.get("calm_day_pred"), rating=rating(score) if score is not None else None,
            sources=self.sources_for(night_date))
        report.narrative = self._narrative(report, morning, history_days)
        return report

    def _narrative(self, report: MorningReport, morning: date, history_days: Optional[int]) -> str:
        payload = build_payload(report)
        if self.reasoner.mode == "claude" and self.store is not None:
            key = "%s:%s:claude:%s" % (morning.isoformat(), history_days, self.store.state_version())
            cached = self.store.get_narrative(key)
            if cached:
                return cached
            text = self.reasoner.narrate(payload)
            self.store.set_narrative(key, "claude", text)
            return text
        return self.reasoner.narrate(payload)

    def week(self, end: date, history_days: Optional[int] = None) -> Dict[str, Any]:
        end = min(end, self.ds.today)
        return weekly_insight(self.ds, end, habits=self.habits(end, history_days), cache=self._cache, history_days=history_days)

    def model_summary(self, upto: date, history_days: Optional[int] = None) -> ModelSummary:
        return A.summary(self.fit_for(min(upto, self.ds.today), history_days))

    # ------------------------------------------------------------- reality --
    def _all_checks(self) -> List[RealityCheck]:
        return reality_checks(self.ds, self.ds.start, self.ds.end, self._answers(), self._cache)

    def reality(self) -> Dict[str, List[RealityCheck]]:
        checks = self._all_checks()
        cutoff = self.ds.today - timedelta(days=RECENT_DAYS)
        return {"open": [c for c in checks if c.status == "open" and c.date >= cutoff],
                "older": [c for c in checks if c.status == "open" and c.date < cutoff],
                "resolved": [c for c in checks if c.status != "open"]}

    def _related_habit(self, check: RealityCheck) -> Optional[str]:
        ev = self.ds.event(check.event_id) if check.event_id else check.suggested_event
        if ev is None:
            return None
        if ev.type == "workout":
            from .features import workout_slot_for
            d = ev.start.date()
            bedtime = self.ds.persona.usual_bedtime
            slot = workout_slot_for(day_hour(ev.start, d), day_hour(ev.end, d), bedtime + 24.0 if bedtime < 12 else bedtime)
            return {"morning": "morning_workout", "evening": "evening_workout", "late": "late_workout"}.get(slot)
        if ev.type == "social":
            return "evening_social"
        if ev.type == "travel":
            return "travel"
        return None

    def _habit_snapshot(self, key: Optional[str]) -> Optional[Dict[str, Any]]:
        if key is None:
            return None
        for h in self.habits(self.ds.today):
            if h.key == key:
                return {"key": h.key, "title": h.title, "effect": h.effect, "adjusted_effect": h.adjusted_effect, "n_with": h.n_with,
                        "confidence": h.confidence}
        return None

    def answer(self, check_id: str, answer: str) -> Dict[str, Any]:
        answer = (answer or "").lower()
        if answer not in ("yes", "no"):
            raise EngineError("answer must be 'yes' or 'no'")
        check = next((c for c in self._all_checks() if c.id == check_id), None)
        if check is None:
            raise NotFound("Unknown reality check %s" % check_id)
        habit_key = self._related_habit(check)
        before = self._habit_snapshot(habit_key)
        event_id = check.event_id
        if check.kind in ("booked_not_seen", "location_mismatch") and check.event_id:
            self.ds.set_attended(check.event_id, answer == "yes")
        elif check.kind == "seen_not_booked" and answer == "yes" and check.suggested_event is not None:
            if self.ds.event(check.suggested_event.id) is None:
                self.ds.add_event(check.suggested_event)
                if self.store is not None:
                    self.store.add_user_event(check.suggested_event)
            event_id = check.suggested_event.id
        if self.store is not None:
            self.store.save_answer(check_id, answer, event_id, check.visit_id)
        self.invalidate()
        after = self._habit_snapshot(habit_key)
        updated = next((c for c in self._all_checks() if c.id == check_id), check)
        return {"check": updated, "report_dates_affected": [check.date + timedelta(days=1)], "habit_before": before,
                "habit_after": after, "replay_date": check.date}

    # -------------------------------------------------------------- whatif --
    def whatif(self, d: date, mods: List[Dict[str, Any]]) -> WhatIfResult:
        self._check_day(d)
        try:
            return predict_day(self.ds, d, mods or [], self.fit_for(self.ds.today))
        except ValueError as exc:
            raise EngineError(str(exc))

    def _find_suggestion(self, morning: date, suggestion_id: str) -> Suggestion:
        report = self.morning_report(morning)
        for s in report.suggestions:
            if s.id == suggestion_id:
                return s
        raise NotFound("Unknown suggestion %s" % suggestion_id)

    def accept_suggestion(self, morning: date, suggestion_id: str) -> Tuple[Suggestion, CalendarEvent, str]:
        s = self._find_suggestion(morning, suggestion_id)
        if s.proposed_event is None:
            raise EngineError("This suggestion changes an existing event — try it in the Planner.")
        accepted = self._accepted()
        if suggestion_id in accepted and self.ds.event(accepted[suggestion_id]) is not None:
            ev = self.ds.event(accepted[suggestion_id])
            s.accepted = True
            return s, ev, to_ics(ev, self.ds.persona.tz)
        ev = s.proposed_event
        ev.source = "user"
        if self.ds.event(ev.id) is None:
            self.ds.add_event(ev)
        if self.store is not None:
            self.store.add_user_event(ev)
            self.store.save_accepted(suggestion_id, ev.id)
        self.invalidate()
        s.accepted = True
        return s, ev, to_ics(ev, self.ds.persona.tz)

    def suggestion_ics(self, morning: date, suggestion_id: str) -> str:
        s = self._find_suggestion(morning, suggestion_id)
        ev = s.proposed_event or self.ds.event(self._accepted().get(suggestion_id, ""))
        if ev is None:
            raise EngineError("This suggestion has no calendar block to export.")
        return to_ics(ev, self.ds.persona.tz)

    # ------------------------------------------------------------ day view --
    def day_bundle(self, d: date) -> Dict[str, Any]:
        self._check_day(d)
        ds = self.ds
        norm = self.norm_for(min(d + timedelta(days=1), ds.today))
        events = ds.events_on(d, include_unattended=True)
        hr = ds.hr(d)
        act = ds.activity_on(d)
        f = day_features(ds, d)
        checks = [c for c in self._all_checks() if c.date == d]
        responses = {}
        if hr is not None:
            for ev in events:
                if ev.type in ("meeting", "social", "workout") and ev.attended is not False:
                    responses[ev.id] = event_response(ds, ev, norm)
        return {"date": d, "events": events, "visits": ds.visits_on(d), "hr": hr.bpm if hr else None, "norm": norm,
                "night": ds.night(d), "night_prev": ds.night(d - timedelta(days=1)), "activity": act,
                "workouts": act.workouts if act else [], "features": f, "chips": describe_features(f), "checks": checks,
                "responses": responses, "evening": evening_summary(ds, d, norm) if hr else None, "is_today": d == ds.today,
                "persona_tz": ds.persona.tz}

    # ----------------------------------------------------------- validation --
    def validation(self) -> Dict[str, Any]:
        fit_ = self.fit_for(self.ds.today)
        fit_before = self.fit_for(self.ds.today, include_unattended=True) if self._answers() else None
        return A.validation(self.ds, fit_, fit_before, self._all_checks(), self._cache)

    # ------------------------------------------------------------ markdown --
    def report_markdown(self, r: MorningReport) -> str:
        lines = ["# StressLess morning report — %s" % fmt_day(r.date), ""]
        if r.score is None:
            lines += ["**%s**" % (r.missing_data or "No score"), ""]
        else:
            delta = "" if r.delta_vs_baseline is None else " (%+.0f vs your usual %.0f)" % (r.delta_vs_baseline, r.baseline_score)
            lines += ["**Sleep score %d · %s**%s" % (r.score, r.rating, delta), ""]
        if r.causes:
            lines += ["## Likely causes", ""]
            for c in r.causes:
                lines.append("%d. **%s** — %s (%+.1f pts, %s confidence, %d similar nights)" % (c.rank, c.title, c.detail, c.points, c.confidence, c.n_similar))
            lines.append("")
        if r.helpers:
            lines += ["## What helped", ""] + ["- **%s** — %s (%+.1f pts)" % (h.title, h.detail, h.points) for h in r.helpers] + [""]
        if r.proximal:
            lines += ["## Last night in numbers", ""] + ["- %s" % e.text for e in r.proximal] + [""]
        if r.unexplained_note:
            lines += ["> %s" % r.unexplained_note, ""]
        lines += ["## Explanation", "", r.narrative, ""]
        if r.suggestions:
            lines += ["## Suggestions", ""] + ["- **%s** — %s" % (s.title, s.body) for s in r.suggestions] + [""]
        lines += ["---", "_%s_" % r.confidence_note, ""]
        return "\n".join(lines)

    # ---------------------------------------------------------- demo check --
    def demo_check(self) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []

        def add(name: str, ok: bool, detail: str) -> None:
            checks.append({"name": name, "ok": bool(ok), "detail": detail})

        try:
            r = self.morning_report(self.ds.today)
            add("Last night has watch data", r.score is not None, "score %s" % r.score)
            add("At least three likely causes", len(r.causes) >= 3, ", ".join(c.title for c in r.causes) or "none")
            add("Top cause is not low confidence", bool(r.causes) and r.causes[0].confidence != "low", r.causes[0].confidence if r.causes else "no causes")
            add("A protect-evening suggestion exists", any(s.kind == "protect_evening" for s in r.suggestions), ", ".join(s.kind for s in r.suggestions) or "none")
            add("Enough history for a model", not (r.model and r.model.insufficient), "%s nights" % (r.model.n_nights if r.model else "?"))
        except Exception as exc:  # pragma: no cover
            add("Morning report builds", False, str(exc))
        today_events = self.ds.events_on(self.ds.today)
        add("Today has a late meeting for the Planner", any(e.type == "meeting" and day_hour(e.end, self.ds.today) >= 19.5 for e in today_events),
            ", ".join("%s until %s" % (e.title, e.end.strftime("%H:%M")) for e in today_events if e.type == "meeting") or "no meetings")
        rc = self.reality()
        kinds = {c.kind for c in rc["open"]}
        add("Open reality checks of both kinds", "booked_not_seen" in kinds and "seen_not_booked" in kinds, "%d open: %s" % (len(rc["open"]), ", ".join(sorted(kinds)) or "none"))
        try:
            v = self.validation()
            sp = v.get("spearman_total")
            add("Engine agrees with planted truth (Spearman >= 0.6)", sp is not None and sp >= 0.6, "Spearman %s" % (None if sp is None else round(sp, 2)))
        except Exception as exc:  # pragma: no cover
            add("Validation runs", False, str(exc))
        return {"ok": all(c["ok"] for c in checks), "checks": checks}
