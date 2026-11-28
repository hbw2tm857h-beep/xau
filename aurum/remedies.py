"""Composite remedies: every trade re-executed under ENTRY x STOP x EXIT fixes.

ENTRY  mkt      market at the next open (as taken)
       late1    wait one bar, then market
       late3    wait three bars, then market
       confirm  enter only if the next bar closes in the trade direction (then at the following open)
       retest   limit order back at the signal bar's midpoint, valid 6h
STOP   1x       the structural stop as planned
       1.5x/2x  1.5 / 2 times further from the planned entry
       atr2     2 x ATR(H1) from the planned entry
EXIT   t2r      2R target (as taken)            t1r / t3r   1R / 3R target
       be1r     2R target, stop to entry at +1R  time12      no target, exit after 12h
       trail2   2 ATR chandelier trail, 96h      trail3a1    3 ATR trail switched on after +1R, 96h
       partial  half at +1R, half on the 2 ATR trail

Results are in each variant's OWN R (P&L / risk at its own fill), after costs. A remedy that
does not fill, or whose fill lands beyond its stop, is 0R (no trade). Plus "skip" (0R) and
"opposite" (mirrored trade). 5 x 4 x 8 + 2 = 162 remedies per trade.
"""
from __future__ import annotations

import multiprocessing as mp

import numpy as np
import pandas as pd

from .config import DEFAULT
from .simulator import simulate

ENTRIES = ["mkt", "late1", "late3", "confirm", "retest"]
STOPS = ["1x", "1.5x", "2x", "atr2"]
EXITS = ["t2r", "t1r", "t3r", "be1r", "time12", "trail2", "trail3a1", "partial"]
REMEDIES = [f"{e}|{s}|{x}" for e in ENTRIES for s in STOPS for x in EXITS] + ["skip", "opposite"]
BASE = "mkt|1x|t2r"
LABEL = {"mkt": "enter as taken", "late1": "wait 1 bar", "late3": "wait 3 bars", "confirm": "wait for confirming close",
         "retest": "limit at signal-bar midpoint", "1x": "planned stop", "1.5x": "stop 1.5x wider", "2x": "stop 2x wider",
         "atr2": "2 ATR stop", "t2r": "2R target", "t1r": "1R target", "t3r": "3R target", "be1r": "breakeven at +1R",
         "time12": "exit after 12h", "trail2": "2 ATR trail", "trail3a1": "3 ATR trail after +1R",
         "partial": "half at 1R, half trailed"}


def describe(name: str) -> str:
    if name in ("skip", "opposite"):
        return {"skip": "skip the trade", "opposite": "take the opposite trade"}[name]
    e, s, x = name.split("|")
    return f"{LABEL[e]} · {LABEL[s]} · {LABEL[x]}"


_G: dict = {}


def _init(path, tc, o, c, h, l, atr, costs):
    _G.update(path=path, tc=tc, o=o, c=c, h=h, l=l, atr=atr, costs=costs)


def _one(row) -> np.ndarray:
    P, tc, o, c, h, l, A, co = (_G[k] for k in ("path", "tc", "o", "c", "h", "l", "atr", "costs"))
    i, d, stop0, mid0, risk0 = int(row[0]), int(row[1]), row[2], row[3], row[4]
    atr = float(A[i])
    n = len(tc)
    out = np.zeros(len(REMEDIES) - 2, dtype=np.float32)
    starts = {"mkt": P.start_index(tc[i]),
              "late1": P.start_index(tc[i + 1]) if i + 1 < n else None,
              "late3": P.start_index(tc[i + 3]) if i + 3 < n else None,
              "confirm": (P.start_index(tc[i + 1]) if (i + 1 < n and (c[i + 1] - o[i + 1]) * d > 0) else None),
              "retest": P.start_index(tc[i])}
    midpoint = (h[i] + l[i]) / 2
    stops = {"1x": stop0, "1.5x": mid0 - d * 1.5 * risk0, "2x": mid0 - d * 2.0 * risk0, "atr2": mid0 - d * 2.0 * atr}
    k = 0
    for e in ENTRIES:
        s0 = starts[e]
        for sname in STOPS:
            st = stops[sname]
            res = {}
            if s0 is not None and not (e == "retest" and (midpoint - st) * d <= 0):
                kw = dict(entry_type="limit", order_price=midpoint, expiry_minutes=360) if e == "retest" else {}

                def run(target_r=None, mm=48 * 60, **extra):
                    r = simulate(P, s0, d, st, 0.0 if target_r else None, mm, atr, costs=co,
                                 target_r=target_r, min_risk_atr=0.3 if sname == "1x" else 0.0, **kw, **extra)
                    return float(r["r"]) if r.get("filled") else 0.0
                res["t2r"] = run(2.0)
                res["t1r"] = run(1.0)
                res["t3r"] = run(3.0)
                res["be1r"] = run(2.0, breakeven_at_r=1.0)
                res["time12"] = run(None, 12 * 60)
                res["trail2"] = run(None, 96 * 60, trail_atr=2.0)
                res["trail3a1"] = run(None, 96 * 60, trail_atr=3.0, trail_after_r=1.0)
                res["partial"] = 0.5 * res["t1r"] + 0.5 * res["trail2"]
            for x in EXITS:
                out[k] = res.get(x, 0.0)
                k += 1
    return out


def run_remedies(trades: pd.DataFrame, f: pd.DataFrame, path, cf: pd.DataFrame, procs: int | None = None,
                 costs=DEFAULT.costs) -> pd.DataFrame:
    rows = np.column_stack([trades["idx"].values, trades["direction"].values, trades["stop_px"].values,
                            trades["entry_mid"].values, trades["risk"].values]).astype(float)
    args = (path, f["tc"].values, f["open"].values, f["close"].values, f["high"].values, f["low"].values,
            f["atr"].values, costs)
    procs = procs or max(1, mp.cpu_count())
    ctx = mp.get_context("fork")
    with ctx.Pool(procs, initializer=_init, initargs=args) as pool:
        mats = pool.map(_one, list(rows), chunksize=500)
    M = np.vstack(mats)
    out = pd.DataFrame(M, columns=REMEDIES[:-2])
    out["skip"] = np.float32(0.0)
    opp = trades[["trade_id"]].merge(cf[["trade_id", "opposite"]], on="trade_id", how="left")["opposite"]
    out["opposite"] = opp.values.astype(np.float32)
    out.insert(0, "trade_id", trades["trade_id"].values)
    return out
