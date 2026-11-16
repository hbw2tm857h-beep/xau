"""Round 5, part D: well-known open-source strategies run on gold on their own.

Each uses its published rules and default settings, fixed before any result
was seen. Costs: $0.35 per round trip, as everywhere else. A strategy whose
rules have a stop is measured in R (multiples of that stop). One without a stop
(RSI-2, Bollinger reversion, MA cross, the eastern-hours trade) is measured in
units of the 14-day ATR at entry.

  Turtle System 1      20-day breakout entry, 10-day opposite breakout exit, 2N stop
  Turtle System 2      55-day breakout, 20-day exit, 2N stop
  Connors RSI-2        above 200-day SMA and RSI(2) < 10: buy the close, sell the
                       first close above the 5-day SMA (shorts mirrored)
  Bollinger reversion  close outside the 20/2 band, exit at the middle band
  NR7 breakout         day after the narrowest range of 7 days: stop orders at
                       its high and low, stop at the other side, exit at the close
  Inside-day breakout  same, after an inside day
  Turtle Soup          new 20-day low at least 4 days after the previous one: buy
                       back at the old low next day, stop under today's low,
                       exit at the close of day 3 (shorts mirrored)
  Golden/death cross   50/200-day SMA, always in the market
  London opening range first London hour's range; stop orders on both sides
                       until 16:00 UK, stop at the other side, 2R target, out at 20:00 UK
  Eastern-hours long   the CBS thesis "hat" pattern: buy 00:00 UTC, sell 08:00 UTC

Pass mark: positive average in all four periods (2008-15, 2016-22, 2023-24,
2025-26), profit factor above 1.15 and at least 100 trades over 2008-26.
"""
import csv
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import signals as S  # noqa: E402
import tv_indicators as T1  # noqa: E402

UTC = timezone.utc
COST = 0.35
D = lambda y: datetime(y, 1, 1, tzinfo=UTC)
PERIODS = [("2008-15", D(2008), D(2016)), ("2016-22", D(2016), D(2023)),
           ("2023-24", D(2023), D(2025)), ("2025-26", D(2025), D(2030))]


def wilder_atr(bars, p):
    tr = T1.true_range([b["h"] for b in bars], [b["l"] for b in bars], [b["c"] for b in bars])
    return T1.rma(tr, p)


def rec(trades, t, d, entry, exit_, unit):
    if unit and unit > 0 and not math.isnan(unit):
        trades.append({"t": t, "r": ((exit_ - entry) * d - COST) / unit})


# ----------------------------- daily strategies -----------------------------
def turtle(db, n_in, n_out):
    o, h, l, c = ([b[k] for b in db] for k in "ohlc")
    N = wilder_atr(db, 20); out = []; k = max(n_in, n_out) + 21
    while k < len(db):
        hh, ll = max(h[k - n_in:k]), min(l[k - n_in:k])
        up, dn = h[k] > hh, l[k] < ll
        if up == dn or math.isnan(N[k - 1]):
            k += 1; continue
        d = 1 if up else -1
        entry = max(o[k], hh) if d == 1 else min(o[k], ll)
        stop = entry - d * 2 * N[k - 1]; unit = 2 * N[k - 1]
        if (l[k] <= stop) if d == 1 else (h[k] >= stop):
            rec(out, db[k]["end"], d, entry, stop, unit); k += 1; continue
        j = k + 1
        while j < len(db):
            lvl = max(stop, min(l[j - n_out:j])) if d == 1 else min(stop, max(h[j - n_out:j]))
            if (o[j] <= lvl) if d == 1 else (o[j] >= lvl):
                rec(out, db[k]["end"], d, entry, o[j], unit); break
            if (l[j] <= lvl) if d == 1 else (h[j] >= lvl):
                rec(out, db[k]["end"], d, entry, lvl, unit); break
            j += 1
        k = j + 1
    return out


def rsi2(db):
    c = np.array([b["c"] for b in db]); r = T1.rsi(c, 2); s200, s5 = T1.sma(c, 200), T1.sma(c, 5)
    atr = wilder_atr(db, 14); out = []; k = 200
    while k < len(db) - 1:
        d = 1 if (c[k] > s200[k] and r[k] < 10) else -1 if (c[k] < s200[k] and r[k] > 90) else 0
        if not d:
            k += 1; continue
        j = k + 1
        while j < len(db) - 1 and not ((c[j] > s5[j]) if d == 1 else (c[j] < s5[j])):
            j += 1
        rec(out, db[k]["end"], d, c[k], c[j], atr[k]); k = j + 1
    return out


def bb_revert(db):
    c = np.array([b["c"] for b in db]); basis = T1.sma(c, 20); dev = 2 * T1.stdev(c, 20)
    atr = wilder_atr(db, 14); out = []; k = 20
    while k < len(db) - 1:
        if math.isnan(basis[k]):
            k += 1; continue
        d = 1 if c[k] < basis[k] - dev[k] else -1 if c[k] > basis[k] + dev[k] else 0
        if not d:
            k += 1; continue
        j = k + 1
        while j < len(db) - 1 and not ((c[j] >= basis[j]) if d == 1 else (c[j] <= basis[j])):
            j += 1
        rec(out, db[k]["end"], d, c[k], c[j], atr[k]); k = j + 1
    return out


def range_break(db, setup):
    o, h, l, c = ([b[k] for b in db] for k in "ohlc"); out = []
    for k in range(7, len(db) - 1):
        if not setup(h, l, k):
            continue
        j = k + 1; hi, lo = h[k], l[k]
        up, dn = h[j] > hi, l[j] < lo
        if not (up or dn):
            continue
        if up and dn:  # both sides hit the same day: assume the losing order came first
            d = 1 if o[j] >= (hi + lo) / 2 else -1
            entry = max(o[j], hi) if d == 1 else min(o[j], lo)
            rec(out, db[k]["end"], d, entry, lo if d == 1 else hi, abs(entry - (lo if d == 1 else hi)))
            continue
        d = 1 if up else -1
        entry = max(o[j], hi) if d == 1 else min(o[j], lo)
        stop = lo if d == 1 else hi
        rec(out, db[k]["end"], d, entry, c[j], abs(entry - stop))
    return out


def nr7(h, l, k):
    r = [h[x] - l[x] for x in range(k - 6, k + 1)]
    return r[-1] == min(r) and r.count(r[-1]) == 1


def inside(h, l, k):
    return h[k] < h[k - 1] and l[k] > l[k - 1]


def turtle_soup(db):
    o, h, l, c = ([b[k] for b in db] for k in "ohlc"); out = []; k = 21
    while k < len(db) - 3:
        done = False
        for d in (1, -1):
            win = l[k - 20:k] if d == 1 else h[k - 20:k]
            ext = min(win) if d == 1 else max(win)
            pos = (len(win) - 1 - win[::-1].index(ext))
            new_ext = (l[k] < ext) if d == 1 else (h[k] > ext)
            if not new_ext or pos > 20 - 4:  # previous extreme must be >= 4 days old
                continue
            j = k + 1
            if not ((h[j] >= ext) if d == 1 else (l[j] <= ext)):
                continue
            entry = max(o[j], ext) if d == 1 else min(o[j], ext)
            stop = l[k] if d == 1 else h[k]
            unit = abs(entry - stop); x = None
            for m in range(j, min(j + 3, len(db))):
                if (l[m] <= stop) if d == 1 else (h[m] >= stop):
                    x = stop; break
            if x is None:
                x = c[min(j + 2, len(db) - 1)]
            rec(out, db[k]["end"], d, entry, x, unit)
            k = j + 3; done = True; break
        if not done:
            k += 1
    return out


def ma_cross(db):
    c = np.array([b["c"] for b in db]); f, s = T1.sma(c, 50), T1.sma(c, 200)
    atr = wilder_atr(db, 14); out = []; pos = 0; e = t0 = u = None
    for k in range(200, len(db)):
        d = 1 if f[k] > s[k] else -1
        if d != pos:
            if pos:
                rec(out, t0, pos, e, c[k], u)
            pos, e, t0, u = d, c[k], db[k]["end"], atr[k]
    return out


# ----------------------------- H1 strategies --------------------------------
def london_orb(lab):
    b = lab.b; uk = lab.uk; out = []; i = 0; n = len(b)
    while i < n:
        if uk[i].hour != 8:
            i += 1; continue
        hi, lo, day = b[i]["h"], b[i]["l"], uk[i].date(); j = i + 1; pos = None
        while j < n and uk[j].date() == day and uk[j].hour < 20:
            x = b[j]
            if pos is None:
                if uk[j].hour >= 16:
                    break
                up, dn = x["h"] > hi, x["l"] < lo
                if up and dn:
                    rec(out, b[i]["t"], 1, hi, lo, hi - lo); pos = "done"; break
                if up or dn:
                    d = 1 if up else -1
                    entry = max(x["o"], hi) if d == 1 else min(x["o"], lo)
                    stop = lo if d == 1 else hi; risk = abs(entry - stop); tgt = entry + d * 2 * risk
                    pos = (d, entry, stop, tgt, risk)
                    if (x["l"] <= stop) if d == 1 else (x["h"] >= stop):
                        rec(out, b[i]["t"], d, entry, stop, risk); pos = "done"; break
                j += 1; continue
            d, entry, stop, tgt, risk = pos
            if (x["l"] <= stop) if d == 1 else (x["h"] >= stop):
                rec(out, b[i]["t"], d, entry, stop, risk); pos = "done"; break
            if (x["h"] >= tgt) if d == 1 else (x["l"] <= tgt):
                rec(out, b[i]["t"], d, entry, tgt, risk); pos = "done"; break
            j += 1
        if isinstance(pos, tuple):
            d, entry, stop, tgt, risk = pos
            rec(out, b[i]["t"], d, entry, b[min(j, n - 1) - 1]["c"], risk)
        i = j if j > i else i + 1
    return out


def eastern_long(lab):
    b = lab.b; F = lab.F; out = []; i = 0; n = len(b)
    while i < n:
        t = b[i]["t"]
        if t.hour != 0 or t.weekday() >= 5:
            i += 1; continue
        j = i
        while j + 1 < n and b[j + 1]["t"].date() == t.date() and b[j + 1]["t"].hour < 8:
            j += 1
        dc = F.daily_ctx(i) if F.d_idx[i] > 20 else None
        if dc and dc["datr"]:
            rec(out, t, 1, b[i]["o"], b[j]["c"], dc["datr"])
        i = j + 1
    return out


STRATS = {
    "Turtle System 1 (20/10)": ("d", lambda db: turtle(db, 20, 10)),
    "Turtle System 2 (55/20)": ("d", lambda db: turtle(db, 55, 20)),
    "Connors RSI-2": ("d", rsi2),
    "Bollinger reversion (20, 2)": ("d", bb_revert),
    "NR7 breakout": ("d", lambda db: range_break(db, nr7)),
    "Inside-day breakout": ("d", lambda db: range_break(db, inside)),
    "Turtle Soup": ("d", turtle_soup),
    "Golden/death cross (50/200)": ("d", ma_cross),
    "London opening range breakout": ("h", london_orb),
    "Eastern-hours long (00-08 UTC)": ("h", eastern_long),
}


def main():
    labs = {"old": L.Lab(L.load(os.path.join(HERE, "..", "data", "xauusd_h1_2008_2015.csv"))),
            "new": L.Lab(L.load(os.path.join(HERE, "..", "data", "xauusd_h1.csv")))}
    rows = []
    for name, (kind, fn) in STRATS.items():
        trades = []
        for k, lab in labs.items():
            tr = fn(lab.F.daily if kind == "d" else lab)
            lo, hi = (D(2008), D(2016)) if k == "old" else (D(2016), D(2030))
            trades += [t for t in tr if lo <= t["t"] < hi]
        allst = S.stats([t["r"] for t in trades])
        per = {p: S.stats([t["r"] for t in trades if a <= t["t"] < b]) for p, a, b in PERIODS}
        ok = (all(s.get("n") and s["avg"] > 0 for s in per.values()) and allst.get("pf", 0) > 1.15
              and allst.get("n", 0) >= 100)
        row = {"strategy": name, "n": allst.get("n", 0), "win": round(allst.get("win", 0), 1),
               "avg": round(allst.get("avg", 0), 3), "total": round(allst.get("total", 0), 1),
               "pf": round(allst.get("pf", 0), 2),
               **{f"{p}_avg": round(s.get("avg", 0), 3) for p, s in per.items()},
               "verdict": "PASS" if ok else "fail"}
        rows.append(row)
        print(f"{name:34s} n={row['n']:5d} win={row['win']:5.1f}% avg={row['avg']:+.3f} PF={row['pf']:.2f} | "
              + " ".join(f"{p} {row[p + '_avg']:+.3f}" for p, _, _ in PERIODS) + f" | {row['verdict']}", flush=True)
    with open(os.path.join(HERE, "results_round5_standalone.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
