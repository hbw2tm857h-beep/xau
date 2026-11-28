"""The anatomy notes added to signals.py: correct timing, gold only, never alter trades."""
from datetime import datetime, timedelta, timezone

import pytest

import signals as S

UTC = timezone.utc


class _F:
    """Minimal stand-in for signals.Features with a missing hour (gold's daily break)."""
    def __init__(self, start, closes, skip_hour):
        self.h1 = []
        t = start
        for c in closes:
            if t.hour == skip_hour:
                t += timedelta(hours=1)
            self.h1.append({"t": t, "o": c, "h": c + 1, "l": c - 1, "c": c})
            t += timedelta(hours=1)

    def close_time(self, i):
        return self.h1[i]["t"] + timedelta(hours=1)


def test_progress_note_fires_once_across_a_missing_hour():
    F = _F(datetime(2026, 5, 19, 18, tzinfo=UTC), [100, 101, 102, 103, 104, 105], skip_hour=21)
    idea = {"dir": 1, "entry": 100.0, "stop": 98.0, "risk": 2.0, "triggered": True,
            "entry_time": F.close_time(1).isoformat(), "strategy": "trend"}
    cfg = dict(S.CONFIG)
    fired = [i for i in range(len(F.h1)) if S.anatomy_progress(F, i, idea, cfg)]
    assert len(fired) == 1 and F.close_time(fired[0]) >= F.close_time(1) + timedelta(hours=2)


def test_notes_are_gold_only():
    idea = {"anatomy": {"tf_conflict": True}, "strategy": "trend"}
    assert S.anatomy_note(idea, dict(S.CONFIG)) is not None
    assert S.anatomy_note(idea, dict(S.CONFIG, market_name="Bitcoin")) is None


def test_behaviour_switches_default_off():
    assert S.CONFIG["anatomy_skip_h4_conflict"] is False
    assert S.CONFIG["anatomy_progress"] is False
