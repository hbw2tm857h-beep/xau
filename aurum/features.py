"""Causal technical features.

Every function here uses only bars <= i to produce the value at row i (verified
by ``validation.truncation_audit``). Values describe the market *at the close of
bar i*, which is the decision moment.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()],
                     axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder(true_range(df), n)


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = wilder(d.clip(lower=0), n)
    dn = wilder((-d).clip(lower=0), n)
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    dn = -df["low"].diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = wilder(true_range(df), n)
    pdi = 100 * wilder(pd.Series(pdm, index=df.index), n) / tr
    ndi = 100 * wilder(pd.Series(ndm, index=df.index), n) / tr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return wilder(dx, n)


def efficiency_ratio(s: pd.Series, n: int = 10) -> pd.Series:
    """Kaufman ER: |net move| / sum |moves|. 1 = straight line, 0 = pure chop."""
    return (s - s.shift(n)).abs() / s.diff().abs().rolling(n).sum()


def rolling_pct_rank(s: pd.Series, n: int) -> pd.Series:
    """Percentile of the current value within the trailing n values (inclusive)."""
    return s.rolling(n, min_periods=max(20, n // 4)).rank(pct=True)


def run_length(sign: np.ndarray) -> np.ndarray:
    """Number of consecutive bars (ending at i) with the same non-zero sign."""
    out = np.zeros(len(sign), dtype=np.int32)
    for i in range(len(sign)):
        if sign[i] != 0 and i > 0 and sign[i] == sign[i - 1]:
            out[i] = out[i - 1] + 1
        elif sign[i] != 0:
            out[i] = 1
    return out


def session_of(hour: pd.Series) -> pd.Series:
    """UTC hour -> session label."""
    bins = np.select(
        [(hour >= 22) | (hour < 7), hour < 12, hour < 16, hour < 21],
        ["asia", "london", "ny_overlap", "ny_late"], default="rollover")
    return pd.Series(bins, index=hour.index)


def add_core(df: pd.DataFrame) -> pd.DataFrame:
    """Indicators shared by every timeframe."""
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    out = df.copy()
    out["atr"] = atr(df, 14)
    out["atr_fast"] = atr(df, 5)
    rng = (h - l).replace(0, np.nan)
    out["range_atr"] = (h - l) / out["atr"]
    out["body"] = (c - o) / out["atr"]                       # signed body in ATR
    out["body_frac"] = (c - o).abs() / rng
    out["upper_wick_frac"] = (h - np.maximum(o, c)) / rng
    out["lower_wick_frac"] = (np.minimum(o, c) - l) / rng
    out["clv"] = ((c - l) - (h - c)) / rng                   # close location -1..1
    for n in (20, 50, 200):
        out[f"ema{n}"] = ema(c, n)
        out[f"dist_ema{n}"] = (c - out[f"ema{n}"]) / out["atr"]
    out["ema20_slope"] = (out["ema20"] - out["ema20"].shift(5)) / out["atr"]
    out["ema50_slope"] = (out["ema50"] - out["ema50"].shift(10)) / out["atr"]
    out["rsi"] = rsi(c, 14)
    out["adx"] = adx(df, 14)
    out["er10"] = efficiency_ratio(c, 10)
    out["er30"] = efficiency_ratio(c, 30)
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    out["bb_up"], out["bb_lo"], out["bb_mid"] = mid + 2 * sd, mid - 2 * sd, mid
    out["bb_pctb"] = (c - out["bb_lo"]) / (out["bb_up"] - out["bb_lo"])
    out["bb_width"] = (out["bb_up"] - out["bb_lo"]) / out["atr"]
    out["bb_width_pct"] = rolling_pct_rank(out["bb_width"], 250)
    out["bb_outside_up_10"] = (c > out["bb_up"]).astype(int).rolling(10).sum()
    out["bb_outside_dn_10"] = (c < out["bb_lo"]).astype(int).rolling(10).sum()
    out["atr_pct"] = rolling_pct_rank(out["atr"] / c, 500)   # vol regime, scale-free
    out["atr_ratio"] = out["atr_fast"] / out["atr"]          # >1 = vol expanding
    for k in (1, 3, 6, 12, 24):
        out[f"mom{k}"] = (c - c.shift(k)) / out["atr"]
    out["run_len"] = run_length(np.sign((c - o).values)) * np.sign((c - o).values)
    hh20, ll20 = h.rolling(20).max(), l.rolling(20).min()
    out["range20_atr"] = (hh20 - ll20) / out["atr"]
    out["pos_in_range20"] = (c - ll20) / (hh20 - ll20).replace(0, np.nan)
    hh50, ll50 = h.rolling(50).max(), l.rolling(50).min()
    out["pos_in_range50"] = (c - ll50) / (hh50 - ll50).replace(0, np.nan)
    # momentum divergence: new 20-bar high/low with RSI below/above its value at prior extreme
    out["new_high20"] = (h >= hh20).astype(int)
    out["new_low20"] = (l <= ll20).astype(int)
    rsi_at_high = out["rsi"].where(h >= hh20).ffill()
    rsi_at_low = out["rsi"].where(l <= ll20).ffill()
    out["bear_div"] = ((out["new_high20"] == 1) & (out["rsi"] < rsi_at_high.shift(1) - 3)).astype(int)
    out["bull_div"] = ((out["new_low20"] == 1) & (out["rsi"] > rsi_at_low.shift(1) + 3)).astype(int)
    if "volume" in out:
        v = out["volume"]
        out["vol_rel"] = v / v.rolling(100, min_periods=20).median()
    return out


def add_intraday(df: pd.DataFrame) -> pd.DataFrame:
    """Session context for an intraday (H1) frame. Uses timestamps of the bar's open."""
    out = df
    hour = out["t"].dt.hour
    out["hour"] = hour
    out["dow"] = out["t"].dt.dayofweek
    out["session"] = session_of(hour)
    # Asia range (22:00-07:00 UTC) of the current trading day, known only once closed:
    day = (out["t"] + pd.Timedelta(hours=2)).dt.floor("D")       # day starts 22:00 UTC
    in_asia = (hour >= 22) | (hour < 7)
    ah = out["high"].where(in_asia).groupby(day).cummax()
    al = out["low"].where(in_asia).groupby(day).cummin()
    # value frozen after Asia ends; before then it is "still forming" -> NaN
    out["asia_high"] = ah.groupby(day).ffill().where(~in_asia)
    out["asia_low"] = al.groupby(day).ffill().where(~in_asia)
    out["asia_range_atr"] = (out["asia_high"] - out["asia_low"]) / out["atr"]
    # round numbers ($10 and $50 handles)
    c = out["close"]
    out["dist_round10"] = (c - (c / 10).round() * 10).abs() / out["atr"]
    out["dist_round50"] = (c - (c / 50).round() * 50).abs() / out["atr"]
    return out
