"""Counterfactual replay: what if the same decision had been executed differently?

Two views are produced, and they must not be confused:

* HINDSIGHT (per trade): which alternative would have rescued this particular
  loser. Useful to explain a trade, useless as a rule — choosing the best
  alternative after seeing the outcome is pure look-ahead.
* POLICY (per setup): apply one alternative to EVERY trade of a setup, winners
  included, and measure the change in expectancy. Only this view can become a
  rule, and it is validated on later data like any other hypothesis.

All outcomes are expressed in "base R": P&L divided by the ORIGINAL trade's
risk, so alternatives with different stops are comparable in money terms.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import DEFAULT, LabConfig
from .simulator import Path, simulate

VARIANTS = {
    # name: description
    "base": "As taken: market entry at next bar, structural stop, 2R target, 48h time stop.",
    "enter_earlier_1": "Enter one bar earlier (at the previous bar's close/next open), same stop and target prices.",
    "enter_later_1": "Wait one bar, then enter at market. Same stop and target prices.",
    "enter_later_3": "Wait three bars, then enter at market. Same stop and target prices.",
    "confirm_close": "Only enter if the next bar closes in the trade direction; otherwise skip.",
    "retest_limit": "Limit order back at the signal bar's midpoint for 6h instead of chasing.",
    "stop_0.5x": "Stop at half the distance.",
    "stop_1.5x": "Stop 1.5x further away (same target price).",
    "stop_2x": "Stop twice as far away (same target price).",
    "stop_atr2": "Stop at 2 x ATR(H1) from entry (volatility stop).",
    "target_1r": "Target at 1R.",
    "target_1.5r": "Target at 1.5R.",
    "target_3r": "Target at 3R.",
    "target_level": "Target at the nearest opposing swing level (if beyond 0.5R, else 1R).",
    "time_exit_12h": "No target: exit after 12 hours.",
    "breakeven_1r": "2R target, stop moved to entry once +1R is reached.",
    "trail_2atr": "No fixed target: chandelier trailing stop 2 x ATR(H1) behind the best price, 96h max.",
    "trail_3atr_after_1r": "No fixed target: 3 x ATR trail switched on after +1R, 96h max.",
    "partial_1r_trail": "Half off at +1R, other half on a 2 x ATR trailing stop (96h max).",
    "opposite": "Take the opposite direction with a mirrored stop/target.",
    "skip": "Do not take the trade (0R).",
}


def _base_r(res: dict, d: int, base_risk: float) -> float:
    if not res.get("filled"):
        return 0.0
    return d * (res["exit"] - res["entry"]) / base_risk


def run_counterfactuals(trades: pd.DataFrame, f: pd.DataFrame, path: Path,
                        cfg: LabConfig = DEFAULT) -> pd.DataFrame:
    tc = f["tc"].values
    o, h, l, c, a = (f[x].values for x in ("open", "high", "low", "close", "atr"))
    mm = cfg.trade.max_hours * 60
    co = cfg.costs
    rows = []
    for t in trades.itertuples(index=False):
        i, d = int(t.idx), int(t.direction)
        stop, tgt, risk, atr = float(t.stop_px), float(t.target_px), float(t.risk), float(a[t.idx])
        mid0 = float(t.entry_mid)
        out = {"trade_id": t.trade_id, "base": float(t.r) * 1.0}
        s0 = path.start_index(tc[i])

        def sim(start, stop_=stop, tgt_=tgt, **kw):
            return simulate(path, start, d, stop_, tgt_, mm, atr, costs=co, **kw)

        # timing
        if i >= 1:
            r = sim(path.start_index(tc[i - 1]))
            out["enter_earlier_1"] = _base_r(r, d, risk)
        for k, name in ((1, "enter_later_1"), (3, "enter_later_3")):
            if i + k < len(tc):
                r = sim(path.start_index(tc[i + k]))
                out[name] = _base_r(r, d, risk)
        if i + 1 < len(tc):
            conf = (c[i + 1] - o[i + 1]) * d > 0
            out["confirm_close"] = _base_r(sim(path.start_index(tc[i + 1])), d, risk) if conf else 0.0
        midpoint = (h[i] + l[i]) / 2
        if (midpoint - stop) * d > 0:
            r = sim(s0, entry_type="limit", order_price=midpoint, expiry_minutes=360)
            out["retest_limit"] = _base_r(r, d, risk)
        # stops (target price unchanged unless stated)
        for mult, name in ((0.5, "stop_0.5x"), (1.5, "stop_1.5x"), (2.0, "stop_2x")):
            out[name] = _base_r(sim(s0, stop_=mid0 - d * mult * risk, min_risk_atr=0.0), d, risk)
        out["stop_atr2"] = _base_r(sim(s0, stop_=mid0 - d * 2 * atr), d, risk)
        # targets
        for rr, name in ((1.0, "target_1r"), (1.5, "target_1.5r"), (3.0, "target_3r")):
            out[name] = _base_r(sim(s0, tgt_=mid0 + d * rr * risk), d, risk)
        room = float(t.room_fwd) * atr if not np.isnan(t.room_fwd) else np.nan
        lvl_t = mid0 + d * room if (not np.isnan(room) and room > 0.5 * risk) else mid0 + d * risk
        out["target_level"] = _base_r(sim(s0, tgt_=lvl_t), d, risk)
        r = simulate(path, s0, d, stop, None, 12 * 60, atr, costs=co)
        out["time_exit_12h"] = _base_r(r, d, risk)
        out["breakeven_1r"] = _base_r(sim(s0, breakeven_at_r=1.0), d, risk)
        tr2 = simulate(path, s0, d, stop, None, 96 * 60, atr, costs=co, trail_atr=2.0)
        out["trail_2atr"] = _base_r(tr2, d, risk)
        out["trail_3atr_after_1r"] = _base_r(simulate(path, s0, d, stop, None, 96 * 60, atr, costs=co,
                                                      trail_atr=3.0, trail_after_r=1.0), d, risk)
        out["partial_1r_trail"] = 0.5 * out["target_1r"] + 0.5 * out["trail_2atr"]
        r = simulate(path, s0, -d, mid0 + d * risk, mid0 - d * 2 * risk, mm, atr, costs=co, min_risk_atr=0.0)
        out["opposite"] = _base_r(r, -d, risk)
        out["skip"] = 0.0
        rows.append(out)
    return pd.DataFrame(rows)


def hindsight_fix(cf: pd.DataFrame) -> pd.DataFrame:
    """For every trade, the best alternative after the fact (explanation only!)."""
    cols = [c for c in VARIANTS if c in cf and c not in ("base",)]
    m = cf[cols]
    best = m.idxmax(axis=1)
    return pd.DataFrame({"trade_id": cf["trade_id"], "best_alt": best,
                         "best_alt_r": m.max(axis=1), "improvement": m.max(axis=1) - cf["base"]})


def policy_table(trades: pd.DataFrame, cf: pd.DataFrame, by=("setup", "direction"),
                 split: str | None = None) -> pd.DataFrame:
    """Mean base-R of each alternative applied to ALL trades of a group."""
    x = trades[["trade_id", *by, "split"]].merge(cf, on="trade_id")
    if split:
        x = x[x["split"] == split]
    cols = [c for c in VARIANTS if c in x]
    g = x.groupby(list(by))[cols].mean()
    g["n"] = x.groupby(list(by)).size()
    return g
