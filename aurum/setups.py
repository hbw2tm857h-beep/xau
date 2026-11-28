"""Discretionary setup archetypes, reconstructed as decision points.

Each detector looks ONLY at the decision frame row i (and earlier rows) and emits
"a trader could reasonably take this trade at the close of bar i". The point is
not that these are good trades — most are not — but that they are the trades a
discretionary trader is tempted by. Their failures feed the mistake taxonomy.

Every setup records the conventional claim it embodies, so the lab can test
whether that claim survives contact with data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .config import DEFAULT, TradeDefaults


@dataclass
class Setup:
    name: str
    family: str          # continuation | reversal | mean_reversion
    claim: str           # the conventional TA belief this setup encodes
    detect: Callable[[pd.DataFrame], tuple[np.ndarray, np.ndarray, np.ndarray]]
    # detect returns (long_mask, short_mask, ref_level) ; ref_level may be NaN


def _a(f, c):
    return f[c].values


def _prev(x, k=1):
    out = np.empty_like(x, dtype=float)
    out[:k] = np.nan
    out[k:] = x[:-k]
    return out


def det_breakout(f):
    c, sh, sl = _a(f, "close"), _a(f, "sh1"), _a(f, "sl1")
    pc = _prev(c)
    L = (c > sh) & (pc <= sh)
    S = (c < sl) & (pc >= sl)
    return L, S, np.where(L, sh, sl)


def det_range_breakout(f):
    c, h, l = _a(f, "close"), _a(f, "high"), _a(f, "low")
    hh = _prev(pd.Series(h).rolling(20).max().values)
    ll = _prev(pd.Series(l).rolling(20).min().values)
    tight = _prev(_a(f, "range20_atr")) < 4.0
    L = tight & (c > hh)
    S = tight & (c < ll)
    return L, S, np.where(L, hh, ll)


def det_sweep_reversal(f):
    h, l, c = _a(f, "high"), _a(f, "low"), _a(f, "close")
    sh, sl = _a(f, "sh1"), _a(f, "sl1")
    sw_h, sw_l = _prev(_a(f, "sh1_swept").astype(float)), _prev(_a(f, "sl1_swept").astype(float))
    S = (h > sh) & (c < sh) & (sw_h == 0)
    L = (l < sl) & (c > sl) & (sw_l == 0)
    return L, S, np.where(L, sl, sh)


def det_pullback_ema(f):
    c, o, h, l, e = _a(f, "close"), _a(f, "open"), _a(f, "high"), _a(f, "low"), _a(f, "ema20")
    tr, sl = _a(f, "h1_trend"), _a(f, "ema20_slope")
    L = (tr == 1) & (sl > 0) & (l <= e) & (c > e) & (c > o)
    S = (tr == -1) & (sl < 0) & (h >= e) & (c < e) & (c < o)
    return L, S, e


def det_bb_fade(f):
    c, up, lo = _a(f, "close"), _a(f, "bb_up"), _a(f, "bb_lo")
    pc, pup, plo = _prev(c), _prev(up), _prev(lo)
    S = (c > up) & (pc <= pup)
    L = (c < lo) & (pc >= plo)
    return L, S, np.where(L, lo, up)


def det_bb_squeeze_breakout(f):
    c, up, lo = _a(f, "close"), _a(f, "bb_up"), _a(f, "bb_lo")
    sq = _prev(_a(f, "bb_width_pct")) < 0.20
    L = sq & (c > up)
    S = sq & (c < lo)
    return L, S, np.where(L, up, lo)


def det_ma_cross(f):
    e20, e50 = _a(f, "ema20"), _a(f, "ema50")
    d, pd_ = e20 - e50, _prev(e20 - e50)
    L = (d > 0) & (pd_ <= 0)
    S = (d < 0) & (pd_ >= 0)
    return L, S, e50


def det_wick_rejection(f):
    lw, uw, ra = _a(f, "lower_wick_frac"), _a(f, "upper_wick_frac"), _a(f, "range_atr")
    l, h, a = _a(f, "low"), _a(f, "high"), _a(f, "atr")
    sl, sh = _a(f, "sl1"), _a(f, "sh1")
    near_s = np.abs(l - sl) / a < 0.5
    near_r = np.abs(h - sh) / a < 0.5
    L = (lw >= 0.6) & (ra >= 0.8) & near_s
    S = (uw >= 0.6) & (ra >= 0.8) & near_r
    return L, S, np.where(L, sl, sh)


def _breakout_state(f, lookback=12):
    """For each bar: level & age of the most recent swing breakout (long / short)."""
    c, sh, sl = _a(f, "close"), _a(f, "sh1"), _a(f, "sl1")
    pc = _prev(c)
    up = (c > sh) & (pc <= sh)
    dn = (c < sl) & (pc >= sl)
    n = len(c)
    up_lvl = np.full(n, np.nan); up_age = np.full(n, np.nan)
    dn_lvl = np.full(n, np.nan); dn_age = np.full(n, np.nan)
    lu = ld = np.nan; iu = idd = -10**9
    for i in range(n):
        if up[i]:
            lu, iu = sh[i], i
        if dn[i]:
            ld, idd = sl[i], i
        if i - iu <= lookback:
            up_lvl[i], up_age[i] = lu, i - iu
        if i - idd <= lookback:
            dn_lvl[i], dn_age[i] = ld, i - idd
    return up_lvl, up_age, dn_lvl, dn_age


def det_retest(f):
    l, h, c, a = _a(f, "low"), _a(f, "high"), _a(f, "close"), _a(f, "atr")
    ul, ua, dl, da = _breakout_state(f)
    L = (ua >= 2) & (l <= ul + 0.2 * a) & (c > ul)
    S = (da >= 2) & (h >= dl - 0.2 * a) & (c < dl)
    return L, S, np.where(L, ul, dl)


def det_failed_break(f):
    """Failed breakdown -> long (bear trap); failed breakout -> short (bull trap)."""
    c = _a(f, "close")
    ul, ua, dl, da = _breakout_state(f, lookback=3)
    L = (da >= 1) & (c > dl)
    S = (ua >= 1) & (c < ul)
    return L, S, np.where(L, dl, ul)


def det_exhaustion_fade(f):
    m6, r, rl = _a(f, "mom6"), _a(f, "rsi"), _a(f, "run_len")
    S = (m6 > 3.0) & (r > 75) & (rl >= 3)
    L = (m6 < -3.0) & (r < 25) & (rl <= -3)
    return L, S, _a(f, "close")


def det_momentum(f):
    ra, clv, b = _a(f, "range_atr"), _a(f, "clv"), _a(f, "body")
    L = (ra > 1.8) & (clv > 0.6) & (b > 1.0)
    S = (ra > 1.8) & (clv < -0.6) & (b < -1.0)
    return L, S, _a(f, "close")


def det_rsi_extreme(f):
    r = _a(f, "rsi"); pr = _prev(r)
    S = (r > 70) & (pr <= 70)
    L = (r < 30) & (pr >= 30)
    return L, S, _a(f, "close")


def det_session_breakout(f):
    c, hr = _a(f, "close"), _a(f, "hour")
    ah, al = _a(f, "asia_high"), _a(f, "asia_low")
    pc = _prev(c)
    win = (hr >= 7) & (hr <= 10)
    L = win & (c > ah) & (pc <= ah)
    S = win & (c < al) & (pc >= al)
    return L, S, np.where(L, ah, al)


def det_double_top_bottom(f):
    h, l, a, clv = _a(f, "high"), _a(f, "low"), _a(f, "atr"), _a(f, "clv")
    S = _a(f, "eq_highs") & (np.abs(h - _a(f, "sh1")) < 0.3 * a) & (clv < -0.3)
    L = _a(f, "eq_lows") & (np.abs(l - _a(f, "sl1")) < 0.3 * a) & (clv > 0.3)
    return L, S, np.where(L, _a(f, "sl1"), _a(f, "sh1"))


def det_engulfing(f):
    o, c = _a(f, "open"), _a(f, "close")
    po, pc = _prev(o), _prev(c)
    m6 = _a(f, "mom6")
    L = (pc < po) & (c > o) & (c > po) & (o <= pc) & (m6 < -1.5)
    S = (pc > po) & (c < o) & (c < po) & (o >= pc) & (m6 > 1.5)
    return L, S, np.where(L, np.minimum(_a(f, "low"), _prev(_a(f, "low"))),
                          np.maximum(_a(f, "high"), _prev(_a(f, "high"))))


def det_momentum_burst(f):
    """Follow a fast 6-hour move that closes near its extreme (the 'late entry' the taxonomy contradicted)."""
    m6, clv = _a(f, "mom6"), _a(f, "clv")
    pm6 = _prev(m6)
    L = (m6 > 2.5) & (pm6 <= 2.5) & (clv > 0.3)
    S = (m6 < -2.5) & (pm6 >= -2.5) & (clv < -0.3)
    return L, S, _a(f, "close")


def det_burst_pullback(f, lookback: int = 12):
    """After a burst (> 3 ATR in 6h), wait for a 30-70% retracement, enter when a bar closes back in the burst direction."""
    h, l, c, o, m6 = _a(f, "high"), _a(f, "low"), _a(f, "close"), _a(f, "open"), _a(f, "mom6")
    n = len(c)
    L = np.zeros(n, bool); S = np.zeros(n, bool); ref = np.full(n, np.nan)
    up_i = dn_i = -10**9
    up_hi = up_lo = dn_hi = dn_lo = np.nan
    for i in range(6, n):
        if m6[i] > 3.0:
            up_i, up_hi, up_lo = i, h[i], np.nanmin(l[i - 6:i + 1])
        elif up_i > 0 and i - up_i <= lookback:
            up_hi = max(up_hi, h[i]) if i - up_i <= 1 else up_hi
            rng = up_hi - up_lo
            retr = (up_hi - np.nanmin(l[up_i + 1:i + 1])) / rng if rng > 0 else 0
            if 0.3 <= retr <= 0.7 and c[i] > o[i] and c[i - 1] <= o[i - 1]:
                L[i] = True; ref[i] = up_lo; up_i = -10**9
        if m6[i] < -3.0:
            dn_i, dn_lo, dn_hi = i, l[i], np.nanmax(h[i - 6:i + 1])
        elif dn_i > 0 and i - dn_i <= lookback:
            dn_lo = min(dn_lo, l[i]) if i - dn_i <= 1 else dn_lo
            rng = dn_hi - dn_lo
            retr = (np.nanmax(h[dn_i + 1:i + 1]) - dn_lo) / rng if rng > 0 else 0
            if 0.3 <= retr <= 0.7 and c[i] < o[i] and c[i - 1] >= o[i - 1]:
                S[i] = True; ref[i] = dn_hi; dn_i = -10**9
    return L, S, ref


SETUPS: dict[str, Setup] = {s.name: s for s in [
    Setup("breakout", "continuation", "A close beyond the last swing point starts a move in that direction.", det_breakout),
    Setup("range_breakout", "continuation", "A breakout from a tight consolidation leads to expansion.", det_range_breakout),
    Setup("sweep_reversal", "reversal", "A wick through a swing level that closes back inside is a stop hunt; fade it.", det_sweep_reversal),
    Setup("pullback_ema", "continuation", "In a trend, the 20 EMA acts as dynamic support/resistance.", det_pullback_ema),
    Setup("bb_fade", "mean_reversion", "A close outside the Bollinger Band is overextended and reverts.", det_bb_fade),
    Setup("bb_squeeze_breakout", "continuation", "Volatility contraction (squeeze) precedes a directional expansion.", det_bb_squeeze_breakout),
    Setup("ma_cross", "continuation", "A 20/50 EMA cross signals a new trend.", det_ma_cross),
    Setup("wick_rejection", "reversal", "A long wick at a level shows rejection; price reverses.", det_wick_rejection),
    Setup("retest", "continuation", "A broken level retested from the other side holds (role reversal).", det_retest),
    Setup("failed_break", "reversal", "A breakout that closes back inside within 3 bars traps traders; trade the other way.", det_failed_break),
    Setup("exhaustion_fade", "reversal", "Extended runs with RSI extremes are exhausted and reverse.", det_exhaustion_fade),
    Setup("momentum_bar", "continuation", "A large-range bar closing at its extreme shows intent; follow it.", det_momentum),
    Setup("rsi_extreme", "mean_reversion", "RSI above 70 is overbought (sell), below 30 oversold (buy).", det_rsi_extreme),
    Setup("session_breakout", "continuation", "London breaking the Asia range sets the day's direction.", det_session_breakout),
    Setup("double_top_bottom", "reversal", "Equal highs/lows with rejection form a reversal pattern.", det_double_top_bottom),
    Setup("engulfing", "reversal", "An engulfing candle after a move marks a reversal.", det_engulfing),
    Setup("momentum_burst", "continuation", "(Lab hypothesis) Fast moves keep going: chasing is not a mistake in gold.", det_momentum_burst),
    Setup("burst_pullback", "continuation", "After an impulse, the first 30-70% pullback is bought (sold) by late participants.", det_burst_pullback),
]}


def structural_stop(f: pd.DataFrame, idx: np.ndarray, direction: np.ndarray, setup: str,
                    td: TradeDefaults = DEFAULT.trade) -> np.ndarray:
    """Where a discretionary trader would put the stop: beyond the recent extreme."""
    h, l, a = _a(f, "high"), _a(f, "low"), _a(f, "atr")
    lo3 = pd.Series(l).rolling(3).min().values
    hi3 = pd.Series(h).rolling(3).max().values
    if setup in ("sweep_reversal", "wick_rejection", "engulfing", "double_top_bottom"):
        lo3 = pd.Series(l).rolling(2).min().values     # beyond the rejection wick
        hi3 = pd.Series(h).rolling(2).max().values
    buf = td.stop_buffer_atr * a[idx]
    return np.where(direction > 0, lo3[idx] - buf, hi3[idx] + buf)


def generate_decisions(f: pd.DataFrame, setups: list[str] | None = None,
                       td: TradeDefaults = DEFAULT.trade) -> pd.DataFrame:
    """All candidate decisions across setups, with planned stop and target."""
    rows = []
    a, c = _a(f, "atr"), _a(f, "close")
    valid = ~np.isnan(a) & ~np.isnan(_a(f, "ema200"))
    for name in (setups or list(SETUPS)):
        s = SETUPS[name]
        L, S, ref = s.detect(f)
        for d, mask in ((1, L), (-1, S)):
            m = np.nan_to_num(mask.astype(float)).astype(bool) & valid
            idx = np.flatnonzero(m)
            if td.cooldown_bars > 0 and len(idx):
                keep, last = [], -10**9
                for i in idx:
                    if i - last > td.cooldown_bars:
                        keep.append(i); last = i
                idx = np.array(keep, dtype=int)
            if not len(idx):
                continue
            dirs = np.full(len(idx), d)
            stop = structural_stop(f, idx, dirs, name, td)
            dist = np.abs(c[idx] - stop) / a[idx]
            # widen too-tight stops to the minimum, skip setups needing a huge stop
            stop = np.where(dist < td.min_stop_atr, c[idx] - d * td.min_stop_atr * a[idx], stop)
            ok = dist <= td.max_stop_atr
            idx, stop = idx[ok], stop[ok]
            risk = np.abs(c[idx] - stop)
            rows.append(pd.DataFrame({
                "idx": idx, "setup": name, "family": s.family, "direction": d,
                "ref_level": ref[idx], "plan_entry": c[idx], "stop": stop,
                "target": c[idx] + d * td.target_r * risk, "stop_atr": risk / a[idx],
            }))
    dec = pd.concat(rows, ignore_index=True).sort_values(["idx", "setup"]).reset_index(drop=True)
    return dec
