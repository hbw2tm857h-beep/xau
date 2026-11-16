"""Popular open-source TradingView indicators, ported from their published Pine
source with the authors' DEFAULT settings (nothing tuned on gold).

Every function takes lists/arrays of o, h, l, c (closed bars, oldest first) and
returns a direction array: +1 bullish, -1 bearish, 0 neutral/undefined.
Value at index i only uses bars 0..i (no lookahead, no repainting).

Excluded on purpose:
  - VWAP, MFI, OBV, Cipher B's money flow: need real volume (spot gold has none)
  - Nadaraya-Watson Envelope (LuxAlgo): default mode repaints, can't be tested honestly
  - Lorentzian Classification (jdehorty): a kNN model with dozens of settings; not an
    "indicator logic" you can bolt on without fitting it
  - Protected / invite-only scripts: source not published
"""
import math
import numpy as np

NAN = np.nan


def _arr(x):
    return np.asarray(x, dtype=float)


def sma(x, p):
    x = _arr(x); out = np.full(len(x), NAN)
    if len(x) >= p:
        bad = np.isnan(x)
        cs = np.cumsum(np.insert(np.where(bad, 0.0, x), 0, 0.0))
        cb = np.cumsum(np.insert(bad.astype(int), 0, 0))
        out[p - 1:] = (cs[p:] - cs[:-p]) / p
        out[p - 1:][(cb[p:] - cb[:-p]) > 0] = NAN  # window touches a gap
    return out


def ema(x, p, seed_sma=False):
    """Pine ta.ema (seeded with the first value)."""
    x = _arr(x); out = np.full(len(x), NAN); a = 2.0 / (p + 1); e = NAN
    for i, v in enumerate(x):
        if math.isnan(v):
            out[i] = e; continue
        e = v if math.isnan(e) else a * v + (1 - a) * e
        out[i] = e
    return out


def rma(x, p):
    """Pine ta.rma (Wilder), seeded with an SMA."""
    x = _arr(x); out = np.full(len(x), NAN); r = NAN; buf = []
    for i, v in enumerate(x):
        if math.isnan(v):
            out[i] = r; continue
        if math.isnan(r):
            buf.append(v)
            if len(buf) == p:
                r = sum(buf) / p
        else:
            r = (r * (p - 1) + v) / p
        out[i] = r
    return out


def wma(x, p):
    x = _arr(x); out = np.full(len(x), NAN); w = np.arange(1, p + 1, dtype=float); ws = w.sum()
    for i in range(p - 1, len(x)):
        seg = x[i - p + 1:i + 1]
        if not np.isnan(seg).any():
            out[i] = (seg * w).sum() / ws
    return out


def highest(x, p):
    x = _arr(x); out = np.full(len(x), NAN)
    for i in range(p - 1, len(x)):
        out[i] = x[i - p + 1:i + 1].max()
    return out


def lowest(x, p):
    x = _arr(x); out = np.full(len(x), NAN)
    for i in range(p - 1, len(x)):
        out[i] = x[i - p + 1:i + 1].min()
    return out


def stdev(x, p):
    x = _arr(x); out = np.full(len(x), NAN)
    for i in range(p - 1, len(x)):
        seg = x[i - p + 1:i + 1]
        if not np.isnan(seg).any():
            out[i] = seg.std()  # Pine ta.stdev = population stdev
    return out


def true_range(h, l, c):
    h, l, c = _arr(h), _arr(l), _arr(c)
    pc = np.roll(c, 1); pc[0] = c[0]
    return np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))


def atr(h, l, c, p):
    return rma(true_range(h, l, c), p)


def rsi(c, p):
    c = _arr(c); d = np.diff(c, prepend=c[0])
    up, dn = rma(np.maximum(d, 0), p), rma(np.maximum(-d, 0), p)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(dn == 0, 100.0, np.where(up == 0, 0.0, 100 - 100 / (1 + up / dn)))
    r[np.isnan(up) | np.isnan(dn)] = NAN
    return r


def linreg(x, p):
    """Pine ta.linreg(src, p, 0): least-squares line value at the last bar."""
    x = _arr(x); out = np.full(len(x), NAN); t = np.arange(p, dtype=float); tm = t.mean()
    den = ((t - tm) ** 2).sum()
    for i in range(p - 1, len(x)):
        seg = x[i - p + 1:i + 1]
        if np.isnan(seg).any():
            continue
        slope = ((t - tm) * (seg - seg.mean())).sum() / den
        out[i] = seg.mean() + slope * (p - 1 - tm)
    return out


def _sign(x):
    return np.where(np.isnan(x), 0, np.sign(x)).astype(int)


# ---------------------------------------------------------------------------
# The indicators
# ---------------------------------------------------------------------------
def supertrend(o, h, l, c, period=10, mult=3.0):
    """SuperTrend by KivancOzbulut."""
    h, l, c = _arr(h), _arr(l), _arr(c); n = len(c)
    a = atr(h, l, c, period); hl2 = (h + l) / 2
    out = np.zeros(n, int); up1 = dn1 = NAN; tr = 1
    for i in range(n):
        if math.isnan(a[i]):
            continue
        up = hl2[i] - mult * a[i]; dn = hl2[i] + mult * a[i]
        if not math.isnan(up1) and c[i - 1] > up1:
            up = max(up, up1)
        if not math.isnan(dn1) and c[i - 1] < dn1:
            dn = min(dn, dn1)
        if not math.isnan(dn1):
            if tr == -1 and c[i] > dn1:
                tr = 1
            elif tr == 1 and c[i] < up1:
                tr = -1
        up1, dn1 = up, dn
        out[i] = tr
    return out


def ut_bot(o, h, l, c, key=1.0, period=10):
    """UT Bot Alerts by QuantNomad."""
    h, l, c = _arr(h), _arr(l), _arr(c); n = len(c)
    a = atr(h, l, c, period); out = np.zeros(n, int); ts = 0.0; pos = 0
    for i in range(1, n):
        if math.isnan(a[i]):
            continue
        nl = key * a[i]; s, s1, t1 = c[i], c[i - 1], ts
        if s > t1 and s1 > t1:
            ts = max(t1, s - nl)
        elif s < t1 and s1 < t1:
            ts = min(t1, s + nl)
        else:
            ts = s - nl if s > t1 else s + nl
        if s1 < t1 and s > t1:
            pos = 1
        elif s1 > t1 and s < t1:
            pos = -1
        out[i] = pos
    return out


def ssl_channel(o, h, l, c, period=10):
    """SSL Channel by ErwinBeckers."""
    c = _arr(c); sh, sl = sma(h, period), sma(l, period); out = np.zeros(len(c), int); hlv = 0
    for i in range(len(c)):
        if math.isnan(sh[i]):
            continue
        hlv = 1 if c[i] > sh[i] else -1 if c[i] < sl[i] else hlv
        out[i] = hlv
    return out


def squeeze_momentum(o, h, l, c, length=20):
    """Squeeze Momentum Indicator by LazyBear: sign of the momentum histogram."""
    c = _arr(c)
    mid = ((highest(h, length) + lowest(l, length)) / 2 + sma(c, length)) / 2
    return _sign(linreg(c - mid, length))


def wavetrend(o, h, l, c, n1=10, n2=21):
    """WaveTrend Oscillator by LazyBear: wt1 above/below wt2."""
    ap = (_arr(h) + _arr(l) + _arr(c)) / 3
    esa = ema(ap, n1); d = ema(abs(ap - esa), n1)
    with np.errstate(divide="ignore", invalid="ignore"):
        ci = (ap - esa) / (0.015 * d)
    ci[~np.isfinite(ci)] = 0.0
    wt1 = ema(ci, n2); wt2 = sma(wt1, 4)
    return _sign(wt1 - wt2)


def _qqe_line(c, rsi_p, sf, qqe):
    r = rsi(c, rsi_p); rma_ = ema(r, sf)
    atr_rsi = np.abs(np.diff(rma_, prepend=NAN))
    wp = rsi_p * 2 - 1
    dar = ema(ema(atr_rsi, wp), wp) * qqe
    n = len(c); lb = np.full(n, NAN); sb = np.full(n, NAN); trend = np.ones(n, int); tl = np.full(n, NAN)
    for i in range(1, n):
        x, x1 = rma_[i], rma_[i - 1]
        if math.isnan(x) or math.isnan(dar[i]):
            continue
        nl, ns = x - dar[i], x + dar[i]
        lb1 = lb[i - 1] if not math.isnan(lb[i - 1]) else nl
        sb1 = sb[i - 1] if not math.isnan(sb[i - 1]) else ns
        lb[i] = max(lb1, nl) if (x1 > lb1 and x > lb1) else nl
        sb[i] = min(sb1, ns) if (x1 < sb1 and x < sb1) else ns
        cross_short = (x1 - sb1) * (x - sb1) < 0 or (x1 <= sb1 < x) or (x1 >= sb1 > x)
        cross_long = (x1 - lb1) * (x - lb1) < 0 or (x1 <= lb1 < x) or (x1 >= lb1 > x)
        trend[i] = 1 if cross_short else -1 if cross_long else trend[i - 1]
        tl[i] = lb[i] if trend[i] == 1 else sb[i]
    return rma_, tl


def qqe_mod(o, h, l, c):
    """QQE MOD by Mihkel00: blue (+1) / red (-1) bars, else 0."""
    c = _arr(c)
    rma1, tl1 = _qqe_line(c, 6, 5, 3.0)
    rma2, _ = _qqe_line(c, 6, 5, 1.61)
    basis = sma(tl1 - 50, 50); dev = 0.35 * stdev(tl1 - 50, 50)
    up = (rma2 - 50 > 3) & (rma1 - 50 > basis + dev)
    dn = (rma2 - 50 < -3) & (rma1 - 50 < basis - dev)
    return np.where(up, 1, np.where(dn, -1, 0))


def chandelier_exit(o, h, l, c, length=22, mult=3.0):
    """Chandelier Exit by everget (use close for extremums)."""
    h, l, c = _arr(h), _arr(l), _arr(c); n = len(c)
    a = mult * atr(h, l, c, length); hc, lc = highest(c, length), lowest(c, length)
    out = np.zeros(n, int); ls1 = ss1 = NAN; d = 1
    for i in range(n):
        if math.isnan(a[i]) or math.isnan(hc[i]):
            continue
        ls, ss = hc[i] - a[i], lc[i] + a[i]
        lsp = ls if math.isnan(ls1) else ls1
        ssp = ss if math.isnan(ss1) else ss1
        if c[i - 1] > lsp:
            ls = max(ls, lsp)
        if c[i - 1] < ssp:
            ss = min(ss, ssp)
        d = 1 if c[i] > ssp else -1 if c[i] < lsp else d
        ls1, ss1 = ls, ss
        out[i] = d
    return out


def range_filter(o, h, l, c, per=100, mult=3.0):
    """Range Filter Buy and Sell by DonovanWall / guikroth."""
    c = _arr(c); n = len(c)
    avr = ema(np.abs(np.diff(c, prepend=c[0])), per)
    rng = ema(avr, per * 2 - 1) * mult
    out = np.zeros(n, int); f = c[0]; up = dn = 0; cond = 0
    for i in range(1, n):
        r = rng[i]; f1 = f
        if c[i] > f1:
            f = f1 if c[i] - r < f1 else c[i] - r
        else:
            f = f1 if c[i] + r > f1 else c[i] + r
        up = up + 1 if f > f1 else 0 if f < f1 else up
        dn = dn + 1 if f < f1 else 0 if f > f1 else dn
        if c[i] > f and up > 0:
            cond = 1
        elif c[i] < f and dn > 0:
            cond = -1
        if i > per * 3:
            out[i] = cond
    return out


def hull_suite(o, h, l, c, length=55):
    """Hull Suite by InSilico: HMA rising/falling vs 2 bars ago."""
    c = _arr(c)
    hma = wma(2 * wma(c, length // 2) - wma(c, length), int(round(math.sqrt(length))))
    prev = np.roll(hma, 2); prev[:2] = NAN
    return _sign(hma - prev)


def half_trend(o, h, l, c, amplitude=2, deviation=2):
    """HalfTrend by everget."""
    h, l, c = _arr(h), _arr(l), _arr(c); n = len(c)
    hp, lp = highest(h, amplitude), lowest(l, amplitude)
    hma_, lma_ = sma(h, amplitude), sma(l, amplitude)
    trend, nxt = 0, 0
    maxlow, minhigh = l[0], h[0]
    out = np.zeros(n, int)
    for i in range(1, n):
        if math.isnan(hp[i]):
            continue
        if nxt == 1:
            maxlow = max(lp[i], maxlow)
            if hma_[i] < maxlow and c[i] < l[i - 1]:
                trend, nxt, minhigh = 1, 0, hp[i]
        else:
            minhigh = min(hp[i], minhigh)
            if lma_[i] > minhigh and c[i] > h[i - 1]:
                trend, nxt, maxlow = 0, 1, lp[i]
        out[i] = 1 if trend == 0 else -1
    return out


def macd(o, h, l, c):
    m = ema(c, 12) - ema(c, 26)
    return _sign(m - ema(m, 9))


def rsi50(o, h, l, c):
    return _sign(rsi(c, 14) - 50)


def ema200(o, h, l, c):
    return _sign(_arr(c) - ema(c, 200))


def ichimoku_cloud(o, h, l, c):
    """Price above (+1) / below (-1) the Kumo, else 0. Defaults 9/26/52/26."""
    c = _arr(c)
    ten = (highest(h, 9) + lowest(l, 9)) / 2; kij = (highest(h, 26) + lowest(l, 26)) / 2
    sa = (ten + kij) / 2; sb = (highest(h, 52) + lowest(l, 52)) / 2
    sa = np.roll(sa, 25); sb = np.roll(sb, 25); sa[:25] = NAN; sb[:25] = NAN
    top, bot = np.fmax(sa, sb), np.fmin(sa, sb)
    out = np.where(c > top, 1, np.where(c < bot, -1, 0))
    out[np.isnan(top)] = 0
    return out


def parabolic_sar(o, h, l, c, start=0.02, inc=0.02, mx=0.2):
    h, l = _arr(h), _arr(l); n = len(h); out = np.zeros(n, int)
    up = True; sar = l[0]; ep = h[0]; af = start
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < sar:
                up, sar, ep, af = False, ep, l[i], start
            elif h[i] > ep:
                ep, af = h[i], min(af + inc, mx)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > sar:
                up, sar, ep, af = True, ep, h[i], start
            elif l[i] < ep:
                ep, af = l[i], min(af + inc, mx)
        out[i] = 1 if up else -1
    return out


def stoch_rsi(o, h, l, c):
    r = rsi(c, 14); lo, hi = lowest(r, 14), highest(r, 14)
    with np.errstate(divide="ignore", invalid="ignore"):
        st = np.where(hi - lo > 0, 100 * (r - lo) / (hi - lo), 50.0)
    st[np.isnan(lo)] = NAN
    k = sma(st, 3); d = sma(k, 3)
    return _sign(k - d)


def dmi(o, h, l, c, p=14):
    h, l = _arr(h), _arr(l)
    upm = np.diff(h, prepend=h[0]); dnm = -np.diff(l, prepend=l[0])
    pdm = np.where((upm > dnm) & (upm > 0), upm, 0.0); mdm = np.where((dnm > upm) & (dnm > 0), dnm, 0.0)
    return _sign(rma(pdm, p) - rma(mdm, p))


def donchian_mid(o, h, l, c, p=20):
    return _sign(_arr(c) - (highest(h, p) + lowest(l, p)) / 2)


def smc_structure(o, h, l, c, length=5):
    """Market structure (BOS/CHoCH) as in LuxAlgo Smart Money Concepts.
    length=5 is LuxAlgo's internal structure, 50 its swing structure."""
    h, l, c = _arr(h), _arr(l), _arr(c); n = len(c)
    up, lo = highest(h, length), lowest(l, length)
    os_ = 0; top = bot = NAN; top_x = bot_x = True; trend = 0
    out = np.zeros(n, int)
    for i in range(length, n):
        prev = os_
        # swing at bar i-length confirmed when the next `length` bars stay inside it
        if h[i - length] > up[i]:
            os_ = 0
        elif l[i - length] < lo[i]:
            os_ = 1
        if os_ == 0 and prev != 0:
            top, top_x = h[i - length], False
        if os_ == 1 and prev != 1:
            bot, bot_x = l[i - length], False
        if not top_x and c[i] > top:
            trend, top_x = 1, True
        if not bot_x and c[i] < bot:
            trend, bot_x = -1, True
        out[i] = trend
    return out


def smc_swing(o, h, l, c):
    return smc_structure(o, h, l, c, 50)


INDICATORS = {
    # name: (function, author / source, is a trend-flip signal usable as a trigger)
    "SuperTrend (10, 3)": (supertrend, "KivancOzbulut", True),
    "UT Bot Alerts (1, 10)": (ut_bot, "QuantNomad", True),
    "SSL Channel (10)": (ssl_channel, "ErwinBeckers", True),
    "Squeeze Momentum (20)": (squeeze_momentum, "LazyBear", True),
    "WaveTrend (10, 21)": (wavetrend, "LazyBear", True),
    "QQE MOD": (qqe_mod, "Mihkel00", True),
    "Chandelier Exit (22, 3)": (chandelier_exit, "everget", True),
    "Range Filter (100, 3)": (range_filter, "DonovanWall", True),
    "Hull Suite (55)": (hull_suite, "InSilico", True),
    "HalfTrend (2, 2)": (half_trend, "everget", True),
    "SMC internal structure (5)": (smc_structure, "LuxAlgo", True),
    "SMC swing structure (50)": (smc_swing, "LuxAlgo", True),
    "MACD (12, 26, 9)": (macd, "built-in", True),
    "RSI 14 vs 50": (rsi50, "built-in", True),
    "EMA 200": (ema200, "built-in", True),
    "Ichimoku cloud": (ichimoku_cloud, "built-in", True),
    "Parabolic SAR": (parabolic_sar, "built-in", True),
    "Stoch RSI K vs D": (stoch_rsi, "built-in", True),
    "DMI +DI vs -DI": (dmi, "built-in", True),
    "Donchian (20) midline": (donchian_mid, "built-in", True),
}


def compute(bars, fn):
    o = [b["o"] for b in bars]; h = [b["h"] for b in bars]
    l = [b["l"] for b in bars]; c = [b["c"] for b in bars]
    return fn(o, h, l, c)
