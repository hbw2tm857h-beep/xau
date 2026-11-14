"""
Strategy research harness for XAUUSD H1.

Walk-forward discipline:
  TUNE     2016-01-01 .. 2022-12-31   pick settings here only
  VALIDATE 2023-01-01 .. 2024-12-31   confirm the pick, no re-tuning
  HOLDOUT  2025-01-01 .. end          looked at once, for the final pick

Every combination tried is logged to research/results.csv so nothing hides.
Costs: a fixed $ amount per round trip (spread + slippage) is charged on every trade.
"""

import csv
import itertools
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import signals as S  # noqa: E402

UTC = timezone.utc
UK = S.UK
H1 = S.H1

TUNE_END = datetime(2023, 1, 1, tzinfo=UTC)
VAL_END = datetime(2025, 1, 1, tzinfo=UTC)
COST = 0.35


# --------------------------------------------------------------------------
def load(path):
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            if not S.market_open(t):
                continue
            o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            if h - l <= 0 and o == c:
                continue  # flat placeholder candle
            bars.append({"t": t, "o": o, "h": h, "l": l, "c": c})
    return bars


def ema_series(vals, p):
    out, e, k = [None] * len(vals), None, 2.0 / (p + 1)
    for i, v in enumerate(vals):
        if i == p - 1:
            e = sum(vals[:p]) / p
        elif i >= p:
            e = v * k + e * (1 - k)
        out[i] = e
    return out


class Lab:
    def __init__(self, bars):
        self.cfg = dict(S.CONFIG)
        self.F = S.Features(bars, self.cfg)
        self.b = bars
        closes = [x["c"] for x in bars]
        self.ema20 = ema_series(closes, 20)
        self.ema50 = ema_series(closes, 50)
        self.uk = [x["t"].astimezone(UK) for x in bars]
        self._trend = {}

    def trend(self, i):
        k = self.F.d_idx[i]
        if k not in self._trend:
            dc = self.F.daily_ctx(i)
            self._trend[k] = dc["trend"] if dc else 0
        return self._trend[k]


# --------------------------------------------------------------------------
# Trade management
# --------------------------------------------------------------------------
def manage(lab, i0, d, entry, stop, mg):
    """Simulate a position filled at `entry` during bar i0.

    mg keys:
      target_r   fixed take-profit in R (None = no fixed target)
      part_r     take `part_frac` off at this R, then stop -> entry (None = off)
      part_frac  fraction closed at part_r
      ha_exit    exit remainder on first opposite-colour HA close
      max_bars   time stop (exit at close)
    Returns (R after costs, bars held, exit index).
    """
    b, ha = lab.b, lab.F.ha
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    cur_stop = stop
    done_frac, booked = 0.0, 0.0
    tgt = entry + d * mg["target_r"] * risk if mg.get("target_r") else None
    part = entry + d * mg["part_r"] * risk if mg.get("part_r") else None
    n = len(b)
    for i in range(i0, min(n, i0 + mg.get("max_bars", 10 ** 9) + 1)):
        x = b[i]
        hi, lo = x["h"], x["l"]
        # stop first (conservative)
        if (lo <= cur_stop) if d == 1 else (hi >= cur_stop):
            r = booked + (1 - done_frac) * (cur_stop - entry) * d / risk
            return r - COST / risk, i - i0, i
        if i == i0:
            continue  # fill bar: only the stop is checked
        if part is not None and done_frac == 0 and ((hi >= part) if d == 1 else (lo <= part)):
            done_frac = mg["part_frac"]
            booked += done_frac * mg["part_r"]
            cur_stop = entry
        if tgt is not None and ((hi >= tgt) if d == 1 else (lo <= tgt)):
            r = booked + (1 - done_frac) * mg["target_r"]
            return r - COST / risk, i - i0, i
        if mg.get("ha_exit") and ((d == 1 and S.bear(ha[i])) or (d == -1 and S.bull(ha[i]))):
            r = booked + (1 - done_frac) * (x["c"] - entry) * d / risk
            return r - COST / risk, i - i0, i
    i = min(n - 1, i0 + mg.get("max_bars", 10 ** 9))
    r = booked + (1 - done_frac) * (b[i]["c"] - entry) * d / risk
    return r - COST / risk, i - i0, i


def fill(lab, i_sig, d, entry, expiry, cancel_on_flip=False):
    """Stop-order fill after signal bar i_sig. Returns fill bar index or None."""
    b, ha = lab.b, lab.F.ha
    for i in range(i_sig + 1, min(len(b), i_sig + 1 + expiry)):
        if (b[i]["h"] >= entry) if d == 1 else (b[i]["l"] <= entry):
            return i
        if cancel_on_flip and ((d == 1 and S.bear(ha[i])) or (d == -1 and S.bull(ha[i]))):
            return None
    return None


# --------------------------------------------------------------------------
# Strategy families: each yields (signal bar i, dir, entry, stop, expiry, cancel_on_flip)
# --------------------------------------------------------------------------
def gen_ha(lab, p):
    """Video rules (shared evaluate), optional extra filters."""
    cfg = dict(lab.cfg)
    cfg["filters"] = dict(cfg["filters"])
    for k in ("session", "adx", "h4", "atr_band"):
        cfg["filters"][k] = bool(p.get(k))
    cfg["require_breakout"] = p.get("breakout", True)
    cfg["stop_swing_bars"] = p.get("swing", 5)
    for i in range(len(lab.b)):
        if not lab.F.warm(i):
            continue
        for d in (1, -1):
            s = S.evaluate(lab.F, i, d, cfg)
            if s:
                yield i, d, s["entry"], s["stop"], 12, True
                break


def gen_asia(lab, p):
    """Asia range (00:00-07:00 UK) breakout at the London session.

    p: mode 'break' | 'fade', trend (bool), min_rng/max_rng (x daily ATR),
       stop 'opp' (other side) | 'mid' (range middle)
    """
    b, uk = lab.b, lab.uk
    day_hi = day_lo = None
    cur_day = None
    traded = None
    for i in range(len(b)):
        t = uk[i]
        day = t.date()
        if day != cur_day:
            cur_day, day_hi, day_lo, traded = day, None, None, False
        if t.hour < 7:
            day_hi = b[i]["h"] if day_hi is None else max(day_hi, b[i]["h"])
            day_lo = b[i]["l"] if day_lo is None else min(day_lo, b[i]["l"])
            continue
        if traded or day_hi is None or not lab.F.warm(i):
            continue
        if not (7 <= t.hour < p.get("last_hour", 11)):
            continue
        dc = lab.F.daily_ctx(i)
        datr = dc["datr"] if dc else None
        if not datr:
            continue
        rng = day_hi - day_lo
        if not (p["min_rng"] * datr <= rng <= p["max_rng"] * datr):
            continue
        tr = lab.trend(i)
        c = b[i]["c"]
        if p["mode"] == "break":
            # signal: H1 closes outside the range; enter on a stop beyond that candle
            for d in (1, -1):
                if p["trend"] and tr != d:
                    continue
                if (d == 1 and c > day_hi) or (d == -1 and c < day_lo):
                    entry = b[i]["h"] + 0.3 if d == 1 else b[i]["l"] - 0.3
                    mid = (day_hi + day_lo) / 2
                    stop = (day_lo if d == 1 else day_hi) if p["stop"] == "opp" else mid
                    traded = True
                    yield i, d, entry, stop, 3, False
                    break
        else:
            # fade: price poked outside then this H1 closed back inside the range
            for d in (1, -1):
                if p["trend"] and tr != d:
                    continue
                poked = (b[i]["l"] < day_lo and c > day_lo) if d == 1 else (b[i]["h"] > day_hi and c < day_hi)
                if poked:
                    entry = b[i]["h"] + 0.3 if d == 1 else b[i]["l"] - 0.3
                    stop = b[i]["l"] - 0.5 if d == 1 else b[i]["h"] + 0.5
                    traded = True
                    yield i, d, entry, stop, 3, False
                    break


def gen_pullback(lab, p):
    """Trend pullback: daily trend + H1 above/below EMA50, dip to EMA20, then a
    strong HA candle back in the trend direction.

    p: touch ('ema20'), confirm 'ha_nowick' | 'ha', swing (stop bars), session(bool)
    """
    b, ha, e20, e50 = lab.b, lab.F.ha, lab.ema20, lab.ema50
    tol = 0.0
    for i in range(2, len(b)):
        if not lab.F.warm(i) or e50[i] is None:
            continue
        if p.get("session") and not (7 <= lab.uk[i].hour < 20):
            continue
        tr = lab.trend(i)
        for d in (1, -1):
            if tr != d:
                continue
            if d == 1 and not (b[i]["c"] > e50[i] and e20[i] > e50[i]):
                continue
            if d == -1 and not (b[i]["c"] < e50[i] and e20[i] < e50[i]):
                continue
            look = range(max(0, i - p.get("touch_bars", 3)), i + 1)
            touched = any(b[j]["l"] <= e20[j] for j in look) if d == 1 else any(b[j]["h"] >= e20[j] for j in look)
            if not touched:
                continue
            x, prev = ha[i], ha[i - 1]
            if d == 1:
                ok = S.bull(x) and S.bear(prev) if p["confirm"] == "flip" else S.bull(x)
                if p.get("nowick"):
                    ok = ok and S.no_lower_wick(x, tol)
            else:
                ok = S.bear(x) and S.bull(prev) if p["confirm"] == "flip" else S.bear(x)
                if p.get("nowick"):
                    ok = ok and S.no_upper_wick(x, tol)
            if not ok or b[i]["c"] * d < e20[i] * d:
                continue
            sw = b[max(0, i - p.get("swing", 5) + 1):i + 1]
            hatr = lab.F.hatr[i] or 0
            if d == 1:
                entry = b[i]["h"] + 0.3
                stop = min(z["l"] for z in sw) - 0.2 * hatr
            else:
                entry = b[i]["l"] - 0.3
                stop = max(z["h"] for z in sw) + 0.2 * hatr
            yield i, d, entry, stop, 3, False
            break


FAMILIES = {"ha": gen_ha, "asia": gen_asia, "pullback": gen_pullback}


# --------------------------------------------------------------------------
def backtest(lab, family, p, mg):
    trades = []
    busy_until = -1
    for i, d, entry, stop, expiry, cof in FAMILIES[family](lab, p):
        if i <= busy_until:
            continue
        fi = fill(lab, i, d, entry, expiry, cof)
        if fi is None:
            continue
        res = manage(lab, fi, d, entry, stop, mg)
        if res is None:
            continue
        r, held, xi = res
        busy_until = xi
        trades.append({"t": lab.b[i]["t"], "d": d, "r": r, "held": held,
                       "risk": abs(entry - stop)})
    return trades


def summarise(trades):
    s = S.stats([t["r"] for t in trades])
    return s


def split(trades):
    tune = [t for t in trades if t["t"] < TUNE_END]
    val = [t for t in trades if TUNE_END <= t["t"] < VAL_END]
    hold = [t for t in trades if t["t"] >= VAL_END]
    return tune, val, hold


def fmt(s):
    if not s.get("n"):
        return "n=0"
    return f"n={s['n']:4d} win={s['win']:5.1f}% avgR={s['avg']:+.3f} PF={s['pf']:.2f} DD={s['dd']:.1f}"


def grid(d):
    keys = list(d)
    for combo in itertools.product(*[d[k] for k in keys]):
        yield dict(zip(keys, combo))
