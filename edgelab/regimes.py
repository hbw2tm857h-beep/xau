"""Causal market-regime classification on daily bars.

Thresholds use expanding-window percentiles (only the past), so the regime label
on a given day never depends on later data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import ema, atr, efficiency_ratio


def expanding_pct(s: pd.Series, min_periods: int = 250) -> pd.Series:
    return s.expanding(min_periods=min_periods).rank(pct=True)


def classify_daily(d: pd.DataFrame, macro: pd.DataFrame | None = None) -> pd.DataFrame:
    d = d.copy()
    c = d["close"]
    d["d_atr"] = atr(d, 14)
    d["d_ema50"] = ema(c, 50)
    d["d_ema200"] = ema(c, 200)
    d["d_ema50_slope"] = (d["d_ema50"] - d["d_ema50"].shift(10)) / d["d_atr"]
    d["d_dist_ema50"] = (c - d["d_ema50"]) / d["d_atr"]
    d["d_dist_ema200"] = (c - d["d_ema200"]) / d["d_atr"]
    d["d_er20"] = efficiency_ratio(c, 20)
    d["d_mom20"] = (c - c.shift(20)) / d["d_atr"]
    d["d_ret5"] = c.pct_change(5)
    d["d_volpct"] = expanding_pct(d["d_atr"] / c)
    d["d_er_pct"] = expanding_pct(d["d_er20"])
    trend = np.where((c > d["d_ema200"]) & (d["d_ema50_slope"] > 0.5), "bull",
                     np.where((c < d["d_ema200"]) & (d["d_ema50_slope"] < -0.5), "bear", "neutral"))
    vol = np.where(d["d_volpct"] > 0.67, "highvol", np.where(d["d_volpct"] < 0.33, "lowvol", "midvol"))
    char = np.where(d["d_er20"] > 0.30, "trending", "ranging")
    d["regime_trend"], d["regime_vol"], d["regime_char"] = trend, vol, char
    d.loc[d["d_ema200"].isna(), ["regime_trend"]] = "unknown"
    d["regime"] = d["regime_trend"] + "/" + d["regime_vol"]
    d["d_dir"] = np.sign(c - d["open"])
    d["d_prev_high"], d["d_prev_low"] = d["high"], d["low"]   # attached as "last completed day"
    if macro is not None and len(macro):
        m = macro.reindex(pd.to_datetime(d["tc"]).dt.floor("D"), method="ffill")
        if "DFII10" in m:
            d["real_yield_chg20"] = (m["DFII10"] - m["DFII10"].shift(20)).values
        if "DTWEXBGS" in m:
            d["usd_chg20"] = (m["DTWEXBGS"].pct_change(20)).values
        if "VIXCLS" in m:
            d["vix"] = m["VIXCLS"].values
    return d


def classify_h4(h4: pd.DataFrame) -> pd.DataFrame:
    h4 = h4.copy()
    c = h4["close"]
    h4["h4_atr"] = atr(h4, 14)
    h4["h4_ema20"], h4["h4_ema50"] = ema(c, 20), ema(c, 50)
    h4["h4_trend"] = np.sign(h4["h4_ema20"] - h4["h4_ema50"])
    h4["h4_dist_ema20"] = (c - h4["h4_ema20"]) / h4["h4_atr"]
    h4["h4_mom6"] = (c - c.shift(6)) / h4["h4_atr"]
    h4["h4_dir"] = np.sign(c - h4["open"])
    return h4
