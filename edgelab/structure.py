"""Market structure: confirmed swing points, trend structure, S/R levels, liquidity.

A swing high at bar p needs ``right`` later bars to confirm it, so it becomes
*known* only at bar p + right. All outputs are aligned to the bar at which the
information is known — never to the pivot bar itself.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def pivots(high: np.ndarray, low: np.ndarray, left: int, right: int):
    n = len(high)
    ph = np.zeros(n, bool)
    pl = np.zeros(n, bool)
    w = left + right + 1
    if n >= w:
        from numpy.lib.stride_tricks import sliding_window_view as swv
        hmax = swv(high, w).max(axis=1)
        lmin = swv(low, w).min(axis=1)
        centre = np.arange(left, n - right)
        ph[centre] = high[centre] >= hmax
        pl[centre] = low[centre] <= lmin
    return ph, pl


def add_structure(df: pd.DataFrame, left: int = 3, right: int = 3, keep_levels: int = 40,
                  prefix: str = "") -> pd.DataFrame:
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["atr"].values
    n = len(df)
    ph, pl = pivots(h, l, left, right)

    sh1 = np.full(n, np.nan); sh2 = np.full(n, np.nan)   # last / previous confirmed swing high
    sl1 = np.full(n, np.nan); sl2 = np.full(n, np.nan)
    sh1_age = np.full(n, np.nan); sl1_age = np.full(n, np.nan)
    sh1_swept = np.zeros(n, bool); sl1_swept = np.zeros(n, bool)
    lvl_above = np.full(n, np.nan); lvl_below = np.full(n, np.nan)
    lvl_above_touches = np.zeros(n); lvl_below_touches = np.zeros(n)
    eqh = np.zeros(n, bool); eql = np.zeros(n, bool)

    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    levels = np.empty(0); level_touch = np.empty(0)
    cur_sh = cur_sh2 = cur_sl = cur_sl2 = np.nan
    sh_bar = sl_bar = -1
    swept_h = swept_l = False
    for i in range(n):
        p = i - right
        new = False
        if p >= 0 and ph[p]:
            cur_sh2, cur_sh, sh_bar, swept_h = cur_sh, h[p], p, False
            highs.append((p, h[p])); new = True
        if p >= 0 and pl[p]:
            cur_sl2, cur_sl, sl_bar, swept_l = cur_sl, l[p], p, False
            lows.append((p, l[p])); new = True
        if new:
            pts = [x[1] for x in highs[-keep_levels:]] + [x[1] for x in lows[-keep_levels:]]
            levels = np.array(pts)
            level_touch = np.zeros(len(levels))
        # liquidity sweep state of the last swing: traded through it at some bar after confirm
        if not np.isnan(cur_sh) and h[i] > cur_sh and i > sh_bar + right:
            swept_h = True
        if not np.isnan(cur_sl) and l[i] < cur_sl and i > sl_bar + right:
            swept_l = True
        sh1[i], sh2[i], sl1[i], sl2[i] = cur_sh, cur_sh2, cur_sl, cur_sl2
        sh1_age[i] = i - sh_bar if sh_bar >= 0 else np.nan
        sl1_age[i] = i - sl_bar if sl_bar >= 0 else np.nan
        sh1_swept[i], sl1_swept[i] = swept_h, swept_l
        if len(levels) and not np.isnan(atr[i]):
            tol = 0.25 * atr[i]
            touched = (h[i] >= levels - tol) & (l[i] <= levels + tol)
            level_touch += touched
            above = levels > c[i]
            if above.any():
                j = np.argmin(np.where(above, levels, np.inf))
                lvl_above[i], lvl_above_touches[i] = levels[j], level_touch[j]
            below = levels < c[i]
            if below.any():
                j = np.argmax(np.where(below, levels, -np.inf))
                lvl_below[i], lvl_below_touches[i] = levels[j], level_touch[j]
            if not np.isnan(cur_sh2):
                eqh[i] = abs(cur_sh - cur_sh2) < 0.15 * atr[i]
            if not np.isnan(cur_sl2):
                eql[i] = abs(cur_sl - cur_sl2) < 0.15 * atr[i]

    out = df
    P = prefix
    out[P + "sh1"], out[P + "sh2"], out[P + "sl1"], out[P + "sl2"] = sh1, sh2, sl1, sl2
    out[P + "sh1_age"], out[P + "sl1_age"] = sh1_age, sl1_age
    out[P + "sh1_swept"], out[P + "sl1_swept"] = sh1_swept, sl1_swept
    hh = sh1 > sh2; hl = sl1 > sl2; lh = sh1 < sh2; ll = sl1 < sl2
    out[P + "structure"] = np.where(hh & hl, 1, np.where(lh & ll, -1, 0))
    out[P + "lvl_above"], out[P + "lvl_below"] = lvl_above, lvl_below
    out[P + "room_up"] = (lvl_above - c) / atr
    out[P + "room_dn"] = (c - lvl_below) / atr
    out[P + "lvl_above_touches"], out[P + "lvl_below_touches"] = lvl_above_touches, lvl_below_touches
    out[P + "eq_highs"], out[P + "eq_lows"] = eqh, eql
    out[P + "dist_sh1"] = (sh1 - c) / atr
    out[P + "dist_sl1"] = (c - sl1) / atr
    return out
