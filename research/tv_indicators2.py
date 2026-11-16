"""Round 5: more popular open-source TradingView indicators, ported from their
published Pine source with the authors' DEFAULT settings (nothing tuned on gold).

Same contract as tv_indicators.py: each function takes o, h, l, c lists (closed
bars, oldest first) and returns +1 bullish / -1 bearish / 0 neutral per bar,
using only bars 0..i at bar i (no lookahead, no repainting).

NONDIR holds non-directional "regime" filters (+1 = OK to trade, 0 = not).

Left out on purpose:
  - Trend Magic (CCI 20 + ATR): its colour is just CCI >= 0, so it duplicates CCI
  - Bollinger %B / basis: identical to close vs SMA 20, already covered by SSL/Donchian
"""
import math
import numpy as np
from tv_indicators import (NAN, _arr, _sign, sma, ema, rma, wma, highest, lowest,
                           stdev, true_range, atr, rsi)


def smma(x, p):
    """Bill Williams SMMA = Wilder RMA seeded with an SMA."""
    return rma(x, p)


def shift(x, k):
    """Value plotted k bars forward (Pine `offset=k`): at bar i we see x[i-k]."""
    x = _arr(x); out = np.full(len(x), NAN)
    if k < len(x):
        out[k:] = x[:len(x) - k]
    return out


def change(x, k=1):
    x = _arr(x); out = np.full(len(x), NAN); out[k:] = x[k:] - x[:-k]
    return out


# ---------------------------------------------------------------------------
def aroon(o, h, l, c, p=14):
    """Aroon (built-in, 14): Aroon Up above Aroon Down."""
    h, l = _arr(h), _arr(l); n = len(h); out = np.zeros(n, int)
    for i in range(p, n):
        wh, wl = h[i - p:i + 1], l[i - p:i + 1]
        # bars since the highest high / lowest low inside the p+1 window
        since_h = p - int(np.flatnonzero(wh == wh.max())[-1])
        since_l = p - int(np.flatnonzero(wl == wl.min())[-1])
        up, dn = 100 * (p - since_h) / p, 100 * (p - since_l) / p
        out[i] = 1 if up > dn else -1 if dn > up else 0
    return out


def cci(o, h, l, c, p=20):
    """CCI (built-in, 20, source hlc3) above / below zero."""
    tp = (_arr(h) + _arr(l) + _arr(c)) / 3; n = len(tp); out = np.zeros(n, int)
    for i in range(p - 1, n):
        seg = tp[i - p + 1:i + 1]; m = seg.mean(); md = np.abs(seg - m).mean()
        if md > 0:
            v = (tp[i] - m) / (0.015 * md)
            out[i] = 1 if v > 0 else -1 if v < 0 else 0
    return out


def williams_r(o, h, l, c, p=14):
    """Williams %R (built-in, 14) above / below -50."""
    hh, ll = highest(h, p), lowest(l, p)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = -100 * (hh - _arr(c)) / (hh - ll)
    return _sign(r + 50)


def vortex(o, h, l, c, p=14):
    """Vortex Indicator (built-in, 14): VI+ above VI-."""
    h, l = _arr(h), _arr(l)
    vmp = np.abs(h - np.roll(l, 1)); vmm = np.abs(l - np.roll(h, 1)); vmp[0] = vmm[0] = NAN
    tr = true_range(h, l, c); tr[0] = NAN
    s = lambda x: np.convolve(np.nan_to_num(x), np.ones(p), "full")[:len(x)]
    vip, vim = s(vmp), s(vmm)
    out = _sign(vip - vim); out[:p] = 0
    return out


def trix(o, h, l, c, p=18):
    """TRIX (built-in, 18): 10000 x change of triple EMA of log(close), sign."""
    e = ema(ema(ema(np.log(_arr(c)), p), p), p)
    out = _sign(change(e) * 10000); out[:3 * p] = 0
    return out


def fisher(o, h, l, c, p=9):
    """Fisher Transform (built-in, 9): Fisher above its trigger (previous value)."""
    hl2 = (_arr(h) + _arr(l)) / 2; hh, ll = highest(hl2, p), lowest(hl2, p)
    n = len(hl2); val = fish = 0.0; prev_fish = 0.0; out = np.zeros(n, int)
    for i in range(n):
        if math.isnan(hh[i]):
            continue
        rngv = hh[i] - ll[i]
        x = 0.66 * ((hl2[i] - ll[i]) / rngv - 0.5) + 0.67 * val if rngv > 0 else 0.67 * val
        val = max(-0.999, min(0.999, x))
        prev_fish = fish
        fish = 0.5 * math.log((1 + val) / (1 - val)) + 0.5 * fish
        out[i] = 1 if fish > prev_fish else -1 if fish < prev_fish else 0
    return out


def elder_impulse(o, h, l, c):
    """Elder Impulse System (13 EMA + MACD 12/26/9 histogram): green when both
    rise, red when both fall, otherwise blue (0)."""
    e = ema(c, 13); m = ema(c, 12) - ema(c, 26); hist = m - ema(m, 9)
    de, dh = change(e), change(hist)
    out = np.where((de > 0) & (dh > 0), 1, np.where((de < 0) & (dh < 0), -1, 0))
    out[:35] = 0
    return out


def kama(o, h, l, c, p=10, fast=2, slow=30):
    """Kaufman Adaptive Moving Average (10, 2, 30): close above / below KAMA."""
    c = _arr(c); n = len(c); k = np.full(n, NAN); fs, ss = 2 / (fast + 1), 2 / (slow + 1)
    for i in range(p, n):
        er_den = np.abs(np.diff(c[i - p:i + 1])).sum()
        er = abs(c[i] - c[i - p]) / er_den if er_den > 0 else 0
        sc = (er * (fs - ss) + ss) ** 2
        prev = k[i - 1] if not math.isnan(k[i - 1]) else c[i - 1]
        k[i] = prev + sc * (c[i] - prev)
    return _sign(c - k)


def schaff(o, h, l, c, length=10, fast=23, slow=50, factor=0.5):
    """Schaff Trend Cycle (LazyBear: 10, 23, 50): STC rising / falling."""
    c = _arr(c); n = len(c); m = ema(c, fast) - ema(c, slow)
    v1 = lowest(m, length); v2 = highest(m, length) - v1
    f1 = np.full(n, NAN); pf = np.full(n, NAN); f2 = np.full(n, NAN); pff = np.full(n, NAN)
    for i in range(n):
        if math.isnan(v1[i]):
            continue
        f1[i] = (m[i] - v1[i]) / v2[i] * 100 if v2[i] > 0 else (f1[i - 1] if i and not math.isnan(f1[i - 1]) else 0)
        pf[i] = f1[i] if i == 0 or math.isnan(pf[i - 1]) else pf[i - 1] + factor * (f1[i] - pf[i - 1])
    v3 = lowest(pf, length); v4 = highest(pf, length) - v3
    for i in range(n):
        if math.isnan(v3[i]):
            continue
        f2[i] = (pf[i] - v3[i]) / v4[i] * 100 if v4[i] > 0 else (f2[i - 1] if i and not math.isnan(f2[i - 1]) else 0)
        pff[i] = f2[i] if i == 0 or math.isnan(pff[i - 1]) else pff[i - 1] + factor * (f2[i] - pff[i - 1])
    return _sign(change(pff))


def alligator(o, h, l, c):
    """Williams Alligator (jaw 13/8, teeth 8/5, lips 5/3 SMMA of hl2):
    +1 lips > teeth > jaw, -1 the reverse, 0 when tangled."""
    hl2 = (_arr(h) + _arr(l)) / 2
    jaw, teeth, lips = shift(smma(hl2, 13), 8), shift(smma(hl2, 8), 5), shift(smma(hl2, 5), 3)
    return np.where((lips > teeth) & (teeth > jaw), 1, np.where((lips < teeth) & (teeth < jaw), -1, 0))


def awesome(o, h, l, c):
    """Awesome Oscillator (SMA 5 - SMA 34 of hl2): above / below zero."""
    hl2 = (_arr(h) + _arr(l)) / 2
    return _sign(sma(hl2, 5) - sma(hl2, 34))


def ultimate(o, h, l, c, a=7, b=14, d=28):
    """Ultimate Oscillator (built-in, 7/14/28) above / below 50."""
    h, l, c = _arr(h), _arr(l), _arr(c)
    pc = np.roll(c, 1); pc[0] = c[0]
    bp = c - np.minimum(l, pc); tr = np.maximum(h, pc) - np.minimum(l, pc)
    s = lambda x, p: np.convolve(x, np.ones(p), "full")[:len(x)]
    with np.errstate(divide="ignore", invalid="ignore"):
        uo = 100 * (4 * s(bp, a) / s(tr, a) + 2 * s(bp, b) / s(tr, b) + s(bp, d) / s(tr, d)) / 7
    out = _sign(uo - 50); out[:d] = 0
    return out


def _var_ma(src, length=2):
    """VAR / VIDYA moving average used by OTT (CMO over 9 bars)."""
    src = _arr(src); n = len(src); alpha = 2 / (length + 1); out = np.zeros(n)
    d = np.diff(src, prepend=src[0]); up = np.where(d > 0, d, 0); dn = np.where(d < 0, -d, 0)
    for i in range(n):
        su = up[max(0, i - 8):i + 1].sum(); sd = dn[max(0, i - 8):i + 1].sum()
        cmo = abs((su - sd) / (su + sd)) if su + sd > 0 else 0
        prev = out[i - 1] if i else src[0]
        out[i] = alpha * cmo * src[i] + (1 - alpha * cmo) * prev
    return out


def ott(o, h, l, c, length=2, percent=1.4):
    """Optimized Trend Tracker by KivancOzbulut (2, 1.4%, VAR): MAvg above OTT."""
    mav = _var_ma(c, length); n = len(mav); out = np.zeros(n, int)
    ls = ss = None; d = 1; ott_prev2 = ott_prev1 = None; ott_hist = []
    for i in range(n):
        fark = mav[i] * percent * 0.01
        l_ = mav[i] - fark; s_ = mav[i] + fark
        if ls is not None:
            l_ = max(l_, ls) if mav[i] > ls else l_
            s_ = min(s_, ss) if mav[i] < ss else s_
            if d == -1 and mav[i] > ss:
                d = 1
            elif d == 1 and mav[i] < ls:
                d = -1
        ls, ss = l_, s_
        mt = l_ if d == 1 else s_
        o_ = mt * (200 + percent) / 200 if mav[i] > mt else mt * (200 - percent) / 200
        ott_hist.append(o_)
        if i >= 2 and i > 30:
            ref = ott_hist[i - 2]  # OTT is plotted 2 bars back
            out[i] = 1 if mav[i] > ref else -1 if mav[i] < ref else 0
    return out


def mcginley(o, h, l, c, p=14):
    """McGinley Dynamic (14): close above / below the line."""
    c = _arr(c); n = len(c); md = np.full(n, NAN)
    for i in range(n):
        if i < p:
            continue
        prev = md[i - 1] if not math.isnan(md[i - 1]) else c[i - p:i].mean()
        md[i] = prev + (c[i] - prev) / (p * (c[i] / prev) ** 4)
    return _sign(c - md)


def coral(o, h, l, c, sm=21, cd=0.4):
    """Coral Trend Indicator by LazyBear (21, 0.4): line rising / falling."""
    c = _arr(c); n = len(c)
    di = (sm - 1.0) / 2.0 + 1.0; c1 = 2 / (di + 1.0); c2 = 1 - c1
    c3 = 3.0 * (cd * cd + cd * cd * cd); c4 = -3.0 * (2.0 * cd * cd + cd + cd * cd * cd)
    c5 = 3.0 * cd + 1.0 + cd * cd * cd + 3.0 * cd * cd
    i1 = i2 = i3 = i4 = i5 = i6 = 0.0; bfr = np.zeros(n); out = np.zeros(n, int)
    for i in range(n):
        i1 = c1 * c[i] + c2 * i1; i2 = c1 * i1 + c2 * i2; i3 = c1 * i2 + c2 * i3
        i4 = c1 * i3 + c2 * i4; i5 = c1 * i4 + c2 * i5; i6 = c1 * i5 + c2 * i6
        bfr[i] = -cd * cd * cd * i6 + c3 * i5 + c4 * i4 + c5 * i3
        if i > 6 * sm:
            out[i] = 1 if bfr[i] > bfr[i - 1] else -1 if bfr[i] < bfr[i - 1] else out[i - 1]
    return out


def laguerre_rsi(o, h, l, c, gamma=0.5):
    """Laguerre RSI (Ehlers, gamma 0.5) above / below 0.5."""
    c = _arr(c); n = len(c); L0 = L1 = L2 = L3 = 0.0; out = np.zeros(n, int)
    for i in range(n):
        p0, p1, p2 = L0, L1, L2
        L0 = (1 - gamma) * c[i] + gamma * L0
        L1 = -gamma * L0 + p0 + gamma * L1
        L2 = -gamma * L1 + p1 + gamma * L2
        L3 = -gamma * L2 + p2 + gamma * L3
        cu = max(L0 - L1, 0) + max(L1 - L2, 0) + max(L2 - L3, 0)
        cdn = max(L1 - L0, 0) + max(L2 - L1, 0) + max(L3 - L2, 0)
        if i > 20 and cu + cdn > 0:
            v = cu / (cu + cdn)
            out[i] = 1 if v > 0.5 else -1 if v < 0.5 else 0
    return out


def _pivots(x, left, right, high=True):
    """Pivot confirmed at bar i (pivot bar is i-right). Returns value or NaN."""
    x = _arr(x); n = len(x); out = np.full(n, NAN)
    for i in range(left + right, n):
        j = i - right; seg = x[j - left:i + 1]
        if (high and x[j] == seg.max() and (seg[:left] < x[j]).all()) or \
           (not high and x[j] == seg.min() and (seg[:left] > x[j]).all()):
            out[i] = x[j]
    return out


def pivot_supertrend(o, h, l, c, prd=2, factor=3.0, atr_p=10):
    """Pivot Point SuperTrend by LonesomeTheBlue (2, 3, 10)."""
    h, l, c = _arr(h), _arr(l), _arr(c); n = len(c)
    ph, pl = _pivots(h, prd, prd, True), _pivots(l, prd, prd, False)
    a = atr(h, l, c, atr_p); center = NAN; tup = tdn = NAN; trend = 0; out = np.zeros(n, int)
    for i in range(n):
        lastpp = ph[i] if not math.isnan(ph[i]) else pl[i] if not math.isnan(pl[i]) else NAN
        if not math.isnan(lastpp):
            center = lastpp if math.isnan(center) else (center * 2 + lastpp) / 3
        if math.isnan(center) or math.isnan(a[i]):
            continue
        up, dn = center - factor * a[i], center + factor * a[i]
        nup = max(up, tup) if not math.isnan(tup) and c[i - 1] > tup else up
        ndn = min(dn, tdn) if not math.isnan(tdn) and c[i - 1] < tdn else dn
        if trend == 0:
            trend = 1
        elif not math.isnan(tdn) and c[i] > tdn:
            trend = 1
        elif not math.isnan(tup) and c[i] < tup:
            trend = -1
        tup, tdn = nup, ndn
        out[i] = trend
    return out


def lux_sr_breaks(o, h, l, c, left=15, right=15):
    """Support and Resistance Levels with Breaks [LuxAlgo] (15, 15): +1 after
    the close breaks the last pivot-high resistance, -1 after it breaks the last
    pivot-low support. The script's volume condition is dropped (no volume)."""
    c = _arr(c); ph, pl = _pivots(h, left, right, True), _pivots(l, left, right, False)
    res = sup = NAN; st = 0; out = np.zeros(len(c), int)
    for i in range(len(c)):
        if not math.isnan(ph[i]):
            res = ph[i]
        if not math.isnan(pl[i]):
            sup = pl[i]
        if i and not math.isnan(res) and c[i] > res >= c[i - 1]:
            st = 1
        if i and not math.isnan(sup) and c[i] < sup <= c[i - 1]:
            st = -1
        out[i] = st
    return out


def ema_cross(o, h, l, c, fast=9, slow=21):
    """EMA 9 / 21 cross: fast above / below slow."""
    return _sign(ema(c, fast) - ema(c, slow))


def zlsma(o, h, l, c, p=32):
    """ZLSMA - Zero Lag LSMA (32): close above / below the line."""
    from tv_indicators import linreg
    lsma = linreg(c, p)
    return _sign(_arr(c) - (2 * lsma - linreg(lsma, p)))


def kijun(o, h, l, c, p=26):
    """Ichimoku base line (Kijun-sen, 26): close above / below."""
    return _sign(_arr(c) - (highest(h, p) + lowest(l, p)) / 2)


# --------------------------- non-directional --------------------------------
def chop_ok(o, h, l, c, p=14):
    """Choppiness Index (built-in, 14) below 61.8 = trending, OK to trade."""
    tr = true_range(h, l, c); hh, ll = highest(h, p), lowest(l, p)
    s = np.convolve(tr, np.ones(p), "full")[:len(tr)]
    with np.errstate(divide="ignore", invalid="ignore"):
        ci = 100 * np.log10(s / (hh - ll)) / math.log10(p)
    out = np.where(ci < 61.8, 1, 0); out[np.isnan(ci)] = 0
    return out


def squeeze_off(o, h, l, c, p=20):
    """TTM / LazyBear squeeze released: Bollinger (20, 2) outside Keltner (20, 1.5)."""
    c = _arr(c); basis = sma(c, p); dev = 2 * stdev(c, p)
    rng = sma(true_range(h, l, c), p)
    off = (basis - dev < basis - 1.5 * rng) & (basis + dev > basis + 1.5 * rng)
    out = np.where(off, 1, 0); out[np.isnan(basis) | np.isnan(rng)] = 0
    return out


INDICATORS = {
    "Aroon (14)": aroon,
    "CCI (20)": cci,
    "Williams %R (14)": williams_r,
    "Vortex (14)": vortex,
    "TRIX (18)": trix,
    "Fisher Transform (9)": fisher,
    "Elder Impulse": elder_impulse,
    "KAMA (10, 2, 30)": kama,
    "Schaff Trend Cycle": schaff,
    "Williams Alligator": alligator,
    "Awesome Oscillator": awesome,
    "Ultimate Oscillator": ultimate,
    "OTT (2, 1.4)": ott,
    "McGinley Dynamic (14)": mcginley,
    "Coral Trend (21, 0.4)": coral,
    "Laguerre RSI (0.5)": laguerre_rsi,
    "Pivot Point SuperTrend": pivot_supertrend,
    "LuxAlgo S/R with Breaks": lux_sr_breaks,
    "EMA 9/21 cross": ema_cross,
    "ZLSMA (32)": zlsma,
    "Kijun-sen (26)": kijun,
}

NONDIR = {
    "Choppiness < 61.8": chop_ok,
    "Squeeze released (BB outside KC)": squeeze_off,
}
