"""Round 35: swing high/low strategies on forex (pre-registered 24 Nov 2026;
committed before it was run).

Bradley asked whether a swing high/low strategy would work on forex pairs. FX
has failed every family tested so far (rounds 3, 10, 12, 13, 14, 17, 29), and
swing setups failed on gold (rounds 5, 9, 22), but swing setups have never been
run on the FX pairs themselves. This tests the two standard versions.

Markets: the 31 FX pairs with a cost in rounds 10 and 17 (round29.markets(),
class FX), hourly Dukascopy candles, grouped into days at 17:00 New York exactly
as live (signals.aggregate). Cost: each pair's round-trip basis points from
those rounds, charged on the entry price.

Swing points: a daily high above the two highs before it and the two after it
(swing high; mirror for lows). It is only known at the close of the second day
after it, and only used from then on. Each swing level is traded at most once.

  W1 Breakout with the trend. Daily close above the latest confirmed swing high,
     the first close above it, with the close above the 50-day EMA -> buy at the
     open of the next hourly candle. Stop at the latest confirmed swing low.
     Mirror for sells.
  W2 Sweep and reclaim. A day trades above the latest confirmed swing high
     (confirmed by the day before) and closes back below it -> sell at the next
     hourly open, stop at that day's high. Mirror for buys. No trend filter.

Both: skip the setup if the risk is under 0.5 or over 4 x the 20-day Wilder
ATR (no usable stop). Target 2R, stop as above, checked on hourly candles (the
stop first if both fall in one candle), otherwise out at the close of the 20th
day. One trade at a time per pair per test.

Drift: as round 29, each trade's R minus direction x mu x entry x days held /
risk, mu being that pair's average daily close-to-close change, days held in
trading days (calendar time x 5/7).

Pass, per test (two tests, so each p < 0.05 / 2):
  1. 300+ trades.
  2. One-sided t-test across pairs (each pair's average drift-adjusted R, pairs
     with 5+ trades): p < 0.025.
  3. One-sided t-test across calendar months (sum of drift-adjusted R of trades
     signalled that month): p < 0.025.
  4. Pooled drift-adjusted average positive before and from 1 Jan 2017.
  5. Still positive pooled at double costs.
hypotheses_tested rises by 2 (1,399 -> 1,401), recorded here and in
research/README.md. A pass goes to Bradley as a proposal for a candidate
(tracked, staff channel only); nothing reaches members on this alone.
"""
import bisect
import json
import math
import os
import statistics as st
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import round28_new_edge as R28  # noqa: E402
import round29_52wk_markets as R29  # noqa: E402

UTC = timezone.utc
HALF = datetime(2017, 1, 1, tzinfo=UTC)
ALPHA = 0.05 / 2
N = 2            # candles each side of a swing point
TARGET_R = 2.0
MAX_DAYS = 20


def ema(xs, p):
    out, e, k = [None] * len(xs), None, 2 / (p + 1)
    for i, x in enumerate(xs):
        if i + 1 < p:
            continue
        e = sum(xs[i + 1 - p:i + 1]) / p if e is None else x * k + e * (1 - k)
        out[i] = e
    return out


def swings(db):
    """(confirmed_at_index, level) lists for highs and lows."""
    hi, lo = [], []
    for j in range(N, len(db) - N):
        nb = [db[j + d] for d in range(-N, N + 1) if d]
        if all(db[j]["h"] > b["h"] for b in nb):
            hi.append((j + N, db[j]["h"]))
        if all(db[j]["l"] < b["l"] for b in nb):
            lo.append((j + N, db[j]["l"]))
    return hi, lo


def simulate(bars, times, start_t, d, stop, bps, max_end):
    """Entry at the first hourly open at or after start_t. Returns the trade or None."""
    i = bisect.bisect_left(times, start_t)
    if i >= len(bars):
        return None
    entry = bars[i]["o"]
    risk = (entry - stop) * d
    if risk <= 0:
        return None
    tgt = entry + d * TARGET_R * risk
    exit_px, exit_t, prev = None, None, None
    for b in bars[i:]:
        if b["t"] >= max_end:
            if prev is None:
                return None
            exit_px, exit_t = prev["c"], prev["t"]
            break
        lo, hi = b["l"], b["h"]
        if (lo <= stop) if d == 1 else (hi >= stop):
            exit_px, exit_t = stop, b["t"]; break
        if (hi >= tgt) if d == 1 else (lo <= tgt):
            exit_px, exit_t = tgt, b["t"]; break
        prev = b
    if exit_px is None:
        return None
    r = (exit_px - entry) * d / risk - bps * 1e-4 * entry / risk
    days = (exit_t - bars[i]["t"]).total_seconds() / 86400 * 5 / 7
    return {"entry": entry, "risk": risk, "r": r, "days": days, "exit_t": exit_t}


def run(bars, db, test, bps):
    times = [b["t"] for b in bars]
    atr = R28.wilder_atr(db, 20)
    e50 = ema([x["c"] for x in db], 50)
    hi, lo = swings(db)
    out, busy_until, used = [], None, set()
    for k in range(1, len(db)):
        if atr[k] is None or e50[k] is None:
            continue
        if busy_until is not None and db[k]["end"] <= busy_until:
            continue
        lag = 0 if test == "W1" else 1          # W2: swing confirmed by the day before
        sh = [x for x in hi if x[0] <= k - lag]
        sl = [x for x in lo if x[0] <= k - lag]
        if not sh or not sl:
            continue
        (hk, hl), (lk, ll) = sh[-1], sl[-1]
        b = db[k]
        sig = None
        if test == "W1":
            if b["c"] > hl and db[k - 1]["c"] <= hl and b["c"] > e50[k] and ("h", hk) not in used:
                sig, stop, key = 1, ll, ("h", hk)
            elif b["c"] < ll and db[k - 1]["c"] >= ll and b["c"] < e50[k] and ("l", lk) not in used:
                sig, stop, key = -1, hl, ("l", lk)
        else:
            if b["h"] > hl and b["c"] < hl and ("h", hk) not in used:
                sig, stop, key = -1, b["h"], ("h", hk)
            elif b["l"] < ll and b["c"] > ll and ("l", lk) not in used:
                sig, stop, key = 1, b["l"], ("l", lk)
        if sig is None:
            continue
        used.add(key)
        risk_est = (b["c"] - stop) * sig
        if not (0.5 * atr[k] <= risk_est <= 4 * atr[k]):
            continue
        end_k = min(k + MAX_DAYS, len(db) - 1)
        t = simulate(bars, times, b["end"], sig, stop, bps, db[end_k]["end"])
        if t is None:
            continue
        t.update({"t": b["end"], "d": sig})
        out.append(t)
        busy_until = t["exit_t"]
    return out


def main():
    pairs = {k: v for k, v in R29.markets().items() if R29.cls(k) == "FX"}
    res = {"W1": [], "W2": []}
    per = {"W1": [], "W2": []}
    dbl = {"W1": [], "W2": []}
    for name, (files, bps) in pairs.items():
        bars = R29.load(name, files)
        db = S.aggregate(bars, S.trading_day, S.day_end)
        mu = st.mean(db[k]["c"] / db[k - 1]["c"] - 1 for k in range(1, len(db)))
        line = []
        for test in ("W1", "W2"):
            tr = run(bars, db, test, bps)
            for t in tr:
                t["adj"] = R28.adj(t, mu); t["m"] = name
            for t in run(bars, db, test, 2 * bps):
                dbl[test].append(R28.adj(t, mu))
            res[test] += tr
            if len(tr) >= 5:
                per[test].append(st.mean(t["adj"] for t in tr))
            line.append(f"{test} n={len(tr):3d} adj {st.mean(t['adj'] for t in tr) if tr else float('nan'):+.3f}")
        print(f"  {name:7s} {db[0]['end']:%Y} " + " | ".join(line), flush=True)

    rows = []
    for test, label in (("W1", "W1 swing breakout with the trend"), ("W2", "W2 swing sweep and reclaim")):
        tr = res[test]
        a = [t["adj"] for t in tr]
        t1, p1 = R28.tt(per[test])
        month = {}
        for t in tr:
            k = t["t"].strftime("%Y-%m"); month[k] = month.get(k, 0) + t["adj"]
        t2, p2 = R28.tt(list(month.values()))
        h1 = [t["adj"] for t in tr if t["t"] < HALF]; h2 = [t["adj"] for t in tr if t["t"] >= HALF]
        yrs = (max(t["t"] for t in tr) - min(t["t"] for t in tr)).days / 365.25
        ok = (len(tr) >= 300 and p1 < ALPHA and p2 < ALPHA and h1 and h2 and st.mean(h1) > 0 and st.mean(h2) > 0
              and st.mean(dbl[test]) > 0)
        print(f"\n{label}: {len(tr)} trades ({len(tr) / yrs / 52:.1f}/week across 31 pairs), raw {st.mean(t['r'] for t in tr):+.3f}R, "
              f"drift-adjusted {st.mean(a):+.3f}R, win {100 * sum(t['r'] > 0 for t in tr) / len(tr):.0f}%")
        print(f"  across pairs: {sum(x > 0 for x in per[test])} of {len(per[test])} positive, t={t1:+.2f} p={p1:.2g}")
        print(f"  across months ({len(month)}): t={t2:+.2f} p={p2:.2g}")
        print(f"  before 2017 {st.mean(h1):+.3f}R ({len(h1)}), from 2017 {st.mean(h2):+.3f}R ({len(h2)}), "
              f"double costs {st.mean(dbl[test]):+.3f}R | {'PASS' if ok else 'fail'}")
        rows.append({"test": label, "n": len(tr), "per_week": round(len(tr) / yrs / 52, 1),
                     "raw": round(st.mean(t["r"] for t in tr), 3), "adj": round(st.mean(a), 3),
                     "pairs_positive": f"{sum(x > 0 for x in per[test])}/{len(per[test])}",
                     "p_pairs": f"{p1:.2g}", "p_months": f"{p2:.2g}",
                     "before_2017": round(st.mean(h1), 3), "from_2017": round(st.mean(h2), 3),
                     "double_costs": round(st.mean(dbl[test]), 3), "verdict": "PASS" if ok else "fail"})
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round35_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
