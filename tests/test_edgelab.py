"""Core guarantees of the lab: no look-ahead, conservative fills, correct statistics."""
import numpy as np
import pandas as pd
import pytest

from edgelab import data as D
from edgelab.config import CostModel
from edgelab.simulator import Path, simulate
from edgelab.stats import benjamini_hochberg, max_drawdown, deflated_sharpe, summarise
from edgelab.structure import pivots


def _path(rows, minutes=15):
    t = pd.date_range("2024-01-02 10:00", periods=len(rows), freq=f"{minutes}min")
    o, h, l, c = (np.array([r[i] for r in rows], float) for i in range(4))
    n = len(rows)
    return Path(t.values, o, h, l, c, np.full(n, minutes), np.zeros(n, bool), np.zeros(n, bool))


ZERO = CostModel(spread_min=0.0, spread_bps=0.0, slip_atr=0.0)


def test_stop_first_when_both_hit_in_same_bar():
    p = _path([(100, 100.5, 99.5, 100), (100, 103, 98, 100)])
    r = simulate(p, 0, 1, stop=99.0, target=102.0, max_minutes=600, atr=1.0, costs=ZERO, min_risk_atr=0)
    # bar 0 range does not touch either; bar 1 touches both -> pessimistic stop
    assert r["exit_reason"] == "stop" and r["r"] == pytest.approx(-1.0)


def test_gap_through_stop_fills_at_open():
    p = _path([(100, 100.2, 99.8, 100), (97, 97.5, 96.5, 97)])
    r = simulate(p, 0, 1, stop=99.0, target=105.0, max_minutes=600, atr=1.0, costs=ZERO, min_risk_atr=0)
    assert r["exit_reason"] == "stop" and r["exit"] == pytest.approx(97.0)


def test_costs_reduce_r():
    p = _path([(100, 100.2, 99.8, 100), (100, 102.5, 99.9, 102)])
    gross = simulate(p, 0, 1, 99.0, 102.0, 600, 1.0, costs=ZERO, min_risk_atr=0)
    net = simulate(p, 0, 1, 99.0, 102.0, 600, 1.0, costs=CostModel(spread_min=0.2, spread_bps=0, slip_atr=0.05),
                   min_risk_atr=0)
    assert gross["r"] == pytest.approx(2.0) and net["r"] < gross["r"]


def test_short_trade_symmetry():
    p = _path([(100, 100.2, 99.8, 100), (100, 100.1, 97.5, 98)])
    r = simulate(p, 0, -1, stop=101.0, target=98.0, max_minutes=600, atr=1.0, costs=ZERO, min_risk_atr=0)
    assert r["exit_reason"] == "target" and r["r"] == pytest.approx(2.0)


def test_pivot_needs_right_bars():
    h = np.array([1, 2, 5, 2, 1, 1, 1], float)
    ph, _ = pivots(h, h, 2, 2)
    assert ph[2] and ph.sum() == 1
    ph2, _ = pivots(h[:4], h[:4], 2, 2)   # not enough bars after the peak yet
    assert not ph2.any()


def test_htf_attach_never_uses_forming_bar():
    t = pd.date_range("2024-01-02 00:00", periods=60, freq="h")
    h1 = pd.DataFrame({"t": t, "tc": t + pd.Timedelta(hours=1), "open": 1.0, "high": 2.0, "low": 0.5,
                       "close": np.arange(60, dtype=float)})
    d1 = D.resample(h1, 24)
    m = D.attach_htf(h1, d1, "d_", ["close"])
    ok = m.dropna(subset=["d_tc"])
    assert (ok["d_tc"] <= ok["tc"]).all()


def test_bh_and_drawdown():
    q = benjamini_hochberg(np.array([0.001, 0.01, 0.04, 0.5]))
    assert q[0] <= q[1] <= q[2] <= q[3] and q[0] == pytest.approx(0.004)
    assert max_drawdown(np.array([1, -1, -1, 2, -3])) == pytest.approx(3.0)


def test_deflated_sharpe_penalises_many_trials():
    rng = np.random.default_rng(0)
    r = rng.normal(0.05, 1, 500)
    assert deflated_sharpe(r, 1000, 0.01) < deflated_sharpe(r, 2, 0.01)


def test_summarise_basic():
    s = summarise([1, -1, 2, -1])
    assert s["n"] == 4 and s["win"] == 0.5 and s["avg_r"] == pytest.approx(0.25)


@pytest.mark.slow
def test_truncation_audit_clean():
    from edgelab.validation import truncation_audit
    a = truncation_audit(D.load_h1(), n_cuts=2, window=3000)
    assert a["mismatches"].sum() == 0


def test_trailing_stop_uses_only_past_bars():
    # long from 100, stop 99; price rallies to 105 then drops; trail 1 ATR -> exit near 104
    p = _path([(100, 100.2, 99.8, 100), (100, 102, 99.9, 102), (102, 105, 101.9, 104.8), (104.8, 104.9, 101, 101.5)])
    r = simulate(p, 0, 1, 99.0, None, 600, 1.0, costs=ZERO, min_risk_atr=0, trail_atr=1.0)
    assert r["exit_reason"] == "trail" and r["exit"] == pytest.approx(104.0)
    # the same-bar high of bar 2 must not tighten bar 2's own stop
    p2 = _path([(100, 100.2, 99.8, 100), (100, 105, 101.5, 102)])
    r2 = simulate(p2, 0, 1, 99.0, None, 600, 1.0, costs=ZERO, min_risk_atr=0, trail_atr=1.0)
    assert r2["exit_reason"] == "time"


def test_every_setup_has_unique_trade_code():
    from edgelab.setups import SETUPS
    from edgelab.trades import CODE
    assert set(SETUPS) <= set(CODE) and len(set(CODE.values())) == len(CODE)
