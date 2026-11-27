"""Build the decision frame: H1 bars + causal features + structure + H4/D1 context.

Row i describes everything a trader could know at the close of H1 bar i.
"""
from __future__ import annotations

import pickle
import time

import numpy as np
import pandas as pd

from . import data as D
from .config import CACHE, SPLITS, SPLIT_ORDER
from .features import add_core, add_intraday
from .structure import add_structure
from .regimes import classify_daily, classify_h4

D1_COLS = ["d_atr", "d_ema50", "d_ema200", "d_ema50_slope", "d_dist_ema50", "d_dist_ema200",
           "d_er20", "d_mom20", "d_volpct", "regime_trend", "regime_vol", "regime_char", "regime",
           "d_dir", "d_prev_high", "d_prev_low", "d_prev_close", "real_yield_chg20", "usd_chg20", "vix",
           "d_structure"]
H4_COLS = ["h4_trend", "h4_dist_ema20", "h4_mom6", "h4_dir", "h4_atr", "h4_structure"]


def split_of(t: pd.Series) -> pd.Series:
    out = pd.Series("", index=t.index, dtype=object)
    for name in SPLIT_ORDER:
        a, b = SPLITS[name]
        out[(t >= pd.Timestamp(a)) & (t <= pd.Timestamp(b))] = name
    return out


def build_frame(h1: pd.DataFrame | None = None, verbose: bool = True) -> pd.DataFrame:
    t0 = time.time()
    if h1 is None:
        h1 = D.load_h1()
    import warnings
    warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
    f = add_core(h1)
    f = add_intraday(f)
    f = add_structure(f, left=3, right=3, keep_levels=12)
    # higher timeframes, each with its own structure (larger pivots)
    h4 = classify_h4(add_core(D.resample(h1, 4)))
    h4 = add_structure(h4, left=3, right=3, prefix="h4s_")
    h4["h4_structure"] = h4["h4s_structure"]
    d1 = add_core(D.resample(h1, 24))
    d1 = add_structure(d1, left=2, right=2, prefix="ds_")
    d1["d_structure"] = d1["ds_structure"]
    d1 = classify_daily(d1, D.load_macro_daily())
    for col in D1_COLS:
        if col not in d1:
            d1[col] = np.nan
    f = D.attach_htf(f, h4, "", H4_COLS)
    d1["d_prev_close"] = d1["close"]
    f = D.attach_htf(f, d1, "", D1_COLS).copy()
    # MTF alignment summary: +1 all agree up, -1 all agree down, 0 conflict
    h1_tr = np.sign(f["ema20"] - f["ema50"])
    d_tr = np.sign(f["d_ema50_slope"].fillna(0))
    f["h1_trend"] = h1_tr
    f["d_trend"] = d_tr
    f["mtf_align"] = np.where((h1_tr == f["h4_trend"]) & (h1_tr == d_tr), h1_tr, 0)
    f["mtf_votes"] = h1_tr.fillna(0) + f["h4_trend"].fillna(0) + d_tr
    # distance to the previous completed day's high/low
    f["dist_pdh"] = (f["d_prev_high"] - f["close"]) / f["atr"]
    f["dist_pdl"] = (f["close"] - f["d_prev_low"]) / f["atr"]
    f["d_ext"] = (f["close"] - f["d_ema50"]) / f["d_atr"]    # intraday extension vs daily mean
    f["event"] = D.mark_events(f["tc"]).values               # event window active at decision
    f["event_next"] = D.mark_events(f["tc"] + pd.Timedelta(hours=1)).values
    f["split"] = split_of(f["tc"]).values
    f["year"] = f["tc"].dt.year
    f = f.reset_index(drop=True)
    if verbose:
        print(f"[frame] {len(f):,} H1 rows, {f.shape[1]} columns in {time.time()-t0:.1f}s")
    return f


def load_frame(rebuild: bool = False) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / "frame_h1.pkl"
    if p.exists() and not rebuild:
        return pickle.loads(p.read_bytes())
    f = build_frame()
    p.write_bytes(pickle.dumps(f))
    return f


def load_m15_cached(rebuild: bool = False) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / "m15.pkl"
    if p.exists() and not rebuild:
        return pickle.loads(p.read_bytes())
    m = D.load_m15()
    p.write_bytes(pickle.dumps(m))
    return m
