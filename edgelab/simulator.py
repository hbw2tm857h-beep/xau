"""Trade execution simulator.

Decisions are made at the CLOSE of an H1 bar (time ``tc``). The trade path is
then replayed on M15 bars starting at ``tc`` (H1 bars where M15 is missing, e.g.
2003-07), so the order of stop/target hits inside an hour is resolved by real
intrabar data rather than assumed.

Fill rules (all deliberately conservative):
* market   : fills at the next bar's open, plus half spread and slippage.
* stop     : fills at max(order, bar open) (gaps fill worse), plus costs.
* limit    : fills when price trades at the order price; no slippage, half spread.
* If stop and target are both inside one path bar, the STOP is assumed first.
* On the fill bar of a stop/limit entry the target only counts if the bar also
  closes beyond it; the stop always counts.
* Stops are exited at max(stop, bar open) against you (gap risk) + slippage.
* Costs: half spread at entry and half at exit; spread/slippage are multiplied in
  news windows and around the daily rollover.
R is measured on the realised fill: R = direction*(exit-entry) / |entry - stop|.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import CostModel, DEFAULT
from . import data as D


@dataclass
class Path:
    """Contiguous OHLC arrays used to replay trades (M15 merged with H1 fallback)."""
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    minutes: np.ndarray
    news: np.ndarray
    rollover: np.ndarray

    @classmethod
    def build(cls, h1: pd.DataFrame, m15: pd.DataFrame | None) -> "Path":
        cols = ["t", "open", "high", "low", "close"]
        if m15 is not None and len(m15):
            start = m15["t"].min()
            a = h1.loc[h1["t"] < start, cols].assign(minutes=60)
            b = m15[cols].assign(minutes=15)
            p = pd.concat([a, b], ignore_index=True)
        else:
            p = h1[cols].assign(minutes=60)
        p = p.sort_values("t").reset_index(drop=True)
        news = (D.mark_events(p["t"]) != "").values
        hr = p["t"].dt.hour.values
        roll = (hr >= 21) & (hr < 23)
        return cls(p["t"].values, p["open"].values, p["high"].values, p["low"].values,
                   p["close"].values, p["minutes"].values, news, roll)

    def start_index(self, ts) -> int:
        """First path bar whose open time is >= ts (the decision time)."""
        return int(np.searchsorted(self.t, np.datetime64(ts), side="left"))

    def index_at_or_after(self, ts_array) -> np.ndarray:
        return np.searchsorted(self.t, ts_array.astype("datetime64[ns]"), side="left")


def _first_true(mask: np.ndarray) -> int:
    i = int(np.argmax(mask))
    return i if mask.size and mask[i] else -1


def simulate(path: Path, start: int, direction: int, stop: float, target: float | None,
             max_minutes: int, atr: float, entry_type: str = "market", order_price: float | None = None,
             expiry_minutes: int = 0, costs: CostModel = DEFAULT.costs,
             breakeven_at_r: float | None = None, post_minutes: int = 0,
             target_r: float | None = None, min_risk_atr: float = 0.3) -> dict:
    """Simulate a single trade. Returns a dict with fill, exit, R and path statistics.

    ``start`` is the first path bar after the decision. ``direction`` is +1/-1.
    ``target`` None means time-exit only.
    """
    n = len(path.t)
    res = {"filled": False, "r": 0.0, "r_gross": 0.0, "exit_reason": "no_fill"}
    if start >= n:
        res["exit_reason"] = "no_data"
        return res
    d = direction
    # ------------------------------------------------------------------ entry
    if entry_type == "market":
        k = start
        mid = path.o[k]
        fill_bar_full = True                    # whole bar is after the fill
        slip = costs.slippage(atr, path.news[k])
    else:
        # bars available for the order to trigger
        t0 = path.t[start]
        end = np.searchsorted(path.t, t0 + np.timedelta64(int(expiry_minutes), "m"), side="left")
        end = min(max(end, start + 1), n)
        hi, lo = path.h[start:end], path.l[start:end]
        if entry_type == "stop":
            hit = (hi >= order_price) if d > 0 else (lo <= order_price)
        else:  # limit
            hit = (lo <= order_price) if d > 0 else (hi >= order_price)
        j = _first_true(hit)
        if j < 0:
            return res
        k = start + j
        op = path.o[k]
        if entry_type == "stop":
            mid = max(order_price, op) if d > 0 else min(order_price, op)
            slip = costs.slippage(atr, path.news[k])
        else:
            mid = min(order_price, op) if d > 0 else max(order_price, op)
            slip = 0.0
        fill_bar_full = mid == op               # gap fill at open: whole bar is after the fill
    half = costs.spread(mid, path.news[k], path.rollover[k]) / 2
    entry = mid + d * (half + slip)
    risk = abs(mid - stop)
    if risk <= 0 or (d > 0 and stop >= mid) or (d < 0 and stop <= mid):
        res["exit_reason"] = "invalid_stop"
        return res
    if risk < min_risk_atr * atr:
        # price gapped to within a sliver of the stop: a trader would cancel
        res["exit_reason"] = "cancelled_gap"
        return res
    if target_r is not None:
        target = mid + d * target_r * risk     # R-multiple target measured from the real fill
    # ------------------------------------------------------------------ exit scan
    t_fill = path.t[k]
    end = np.searchsorted(path.t, t_fill + np.timedelta64(int(max_minutes), "m"), side="left")
    end = min(max(end, k + 1), n)
    hi, lo, op, cl = path.h[k:end], path.l[k:end], path.o[k:end], path.c[k:end]
    if d > 0:
        stop_hit = lo <= stop
        tgt_hit = hi >= target if target is not None else np.zeros_like(stop_hit)
    else:
        stop_hit = hi >= stop
        tgt_hit = lo <= target if target is not None else np.zeros_like(stop_hit)
    if not fill_bar_full and target is not None:
        # fill bar: target only if the bar also closes beyond it
        tgt_hit = tgt_hit.copy()
        tgt_hit[0] = (cl[0] >= target) if d > 0 else (cl[0] <= target)
    cur_stop = np.full(len(hi), stop)
    if breakeven_at_r is not None:
        be_level = mid + d * breakeven_at_r * risk
        reached = (hi >= be_level) if d > 0 else (lo <= be_level)
        jb = _first_true(reached)
        if jb >= 0 and jb + 1 < len(hi):
            cur_stop[jb + 1:] = mid
            stop_hit = (lo <= cur_stop) if d > 0 else (hi >= cur_stop)
    js, jt = _first_true(stop_hit), _first_true(tgt_hit)
    if js >= 0 and (jt < 0 or js <= jt):        # ties -> stop first (pessimistic)
        j = js
        level = cur_stop[j]
        px = min(level, op[j]) if d > 0 else max(level, op[j])  # gap through stop
        if j == 0 and not fill_bar_full:
            px = level
        exit_mid = px - d * costs.slippage(atr, path.news[k + j])
        reason = "stop" if level == stop else "breakeven"
    elif jt >= 0:
        j = jt
        px = max(target, op[j]) if d > 0 else min(target, op[j])
        if j == 0 and not fill_bar_full:
            px = target
        exit_mid = px
        reason = "target"
    else:
        j = len(hi) - 1
        exit_mid = cl[j]
        reason = "time"
    exit_half = costs.spread(exit_mid, path.news[k + j], path.rollover[k + j]) / 2
    exit_px = exit_mid - d * exit_half
    seg_h, seg_l = hi[: j + 1], lo[: j + 1]
    mfe = ((seg_h.max() - mid) if d > 0 else (mid - seg_l.min())) / risk
    mae = ((mid - seg_l.min()) if d > 0 else (seg_h.max() - mid)) / risk
    jm = int(np.argmax(seg_h) if d > 0 else np.argmin(seg_l))
    res.update({
        "filled": True, "fill_idx": k, "exit_idx": k + j,
        "fill_time": pd.Timestamp(path.t[k]), "exit_time": pd.Timestamp(path.t[k + j]),
        "entry_mid": mid, "target_px": target, "stop_px": stop, "entry": entry, "exit": exit_px, "risk": risk,
        "r": d * (exit_px - entry) / risk, "r_gross": d * (exit_mid - mid) / risk,
        "cost_r": (d * (exit_mid - mid) - d * (exit_px - entry)) / risk,
        "exit_reason": reason, "minutes_held": float((path.t[k + j] - path.t[k]) / np.timedelta64(1, "m")),
        "mfe_r": mfe, "mae_r": mae, "mfe_minutes": float((path.t[k + jm] - path.t[k]) / np.timedelta64(1, "m")),
    })
    # ---------------------------------------------------- after-exit path (diagnosis only)
    if post_minutes > 0 and target is not None:
        pe = np.searchsorted(path.t, path.t[k + j] + np.timedelta64(int(post_minutes), "m"), side="left")
        ph, pl = path.h[k + j + 1: pe], path.l[k + j + 1: pe]
        if len(ph):
            fav = ((ph.max() - mid) if d > 0 else (mid - pl.min())) / risk
            adv = ((mid - pl.min()) if d > 0 else (ph.max() - mid)) / risk
            hit_t = (ph >= target) if d > 0 else (pl <= target)
            res.update({"post_mfe_r": fav, "post_mae_r": adv,
                        "post_hit_target": bool(hit_t.any())})
    return res
