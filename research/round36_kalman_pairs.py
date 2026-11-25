"""Round 36: Kalman-filter pairs trading (pre-registered 25 Nov 2026; committed
before it was run).

Bradley asked whether HP, band-pass or Kalman filters would work. HP is
two-sided (it uses future prices), and a one-sided HP or Kalman price smoother
is an adaptive moving average, which the trend rounds already cover. The one
genuinely new use is the Kalman filter's standard job in trading: tracking a
moving hedge ratio between two linked markets and trading the gap when it
stretches. No round so far has traded a spread between two markets.

Pairs, fixed in advance (economically linked, both legs in the data):
  gold/silver, gold/platinum, WTI/Brent, EURUSD/GBPUSD, AUDUSD/NZDUSD,
  EURUSD/USDCHF, AUDJPY/NZDJPY, S&P 500/Dow, S&P 500/Nasdaq 100,
  DAX/Euro Stoxx 50.

Data: hourly Dukascopy candles grouped into days at 17:00 New York
(signals.aggregate), both legs joined on the same day end; natural logs of
daily closes.

Filter: y = a + b x (y the first leg, x the second, log prices), state (a, b)
a random walk with delta 1e-4 (Vw = delta / (1 - delta) x I) and observation
variance Ve = 1e-3 -- the textbook setting (Chan, Algorithmic Trading, ch. 3),
not tuned. Each day: the one-step forecast error e and its variance Q are
taken BEFORE that day's update, z = e / sqrt(Q). First 250 days are warm-up.

Trade: at a daily close with |z| > 2 and no open trade on that pair, take the
spread the other way (z > 2: sell y, buy b units of x by value; mirror) at the
next day's open of both legs, the hedge ratio b frozen at the signal. Exit at
the next open after the first close where z crosses 0 (z computed by the
running filter), or the spread (log y - b log x, b frozen) has moved 2 x
sqrt(Q at signal) against the entry (the stop), or after 20 trading days.
One trade at a time per pair.

R: risk = 2 x sqrt(Q at signal) in log units of the y leg's notional, so the
stop is 1R (checked on closes and filled at the next open, so it can be worse).
R = d x (change in log y - b x change in log x) / risk, minus costs: each leg's
round-trip basis points (rounds 10, 16, 17; gold 1.75) on its notional, i.e.
(bps_y + |b| bps_x) x 1e-4 / risk. Spreads have no lasting direction, so no
drift adjustment.

Pass (one test, alpha 0.05):
  1. 300+ trades.
  2. One-sided t-test across the 10 pairs (each pair's average R): p < 0.05.
  3. One-sided t-test across calendar months (sum of R of trades signalled
     that month): p < 0.05.
  4. Pooled average positive before and from 1 Jan 2017.
  5. Still positive at double costs.
hypotheses_tested rises by 1 (1,401 -> 1,402), recorded here and in
research/README.md. A pass goes to Bradley as a proposal for a candidate;
nothing reaches members on this alone.
"""
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
import round10_markets as R10  # noqa: E402
import round28_new_edge as R28  # noqa: E402
import round29_52wk_markets as R29  # noqa: E402

UTC = timezone.utc
HALF = datetime(2017, 1, 1, tzinfo=UTC)
ALPHA = 0.05
DELTA, VE = 1e-4, 1e-3
WARMUP, ENTRY_Z, STOP_K, MAX_DAYS = 250, 2.0, 2.0, 20
PAIRS = [("XAUUSD", "XAGUSD"), ("XAUUSD", "Platinum"), ("WTI oil", "Brent oil"), ("EURUSD", "GBPUSD"),
         ("AUDUSD", "NZDUSD"), ("EURUSD", "USDCHF"), ("AUDJPY", "NZDJPY"), ("S&P 500", "Dow"),
         ("S&P 500", "Nasdaq 100"), ("DAX", "Euro Stoxx 50")]


def daily(name, mk):
    files, bps = (R10.MARKETS["XAUUSD (reference)"] if name == "XAUUSD" else mk[name])
    db = S.aggregate(R29.load(name, files), S.trading_day, S.day_end)
    return {b["end"]: b for b in db}, bps


def kalman(ys, xs):
    """Per day: (e, Q, a, b) before that day's update."""
    vw = DELTA / (1 - DELTA)
    th = [0.0, 0.0]
    P = [[0.0, 0.0], [0.0, 0.0]]
    out = []
    for y, x in zip(ys, xs):
        R = [[P[0][0] + vw, P[0][1]], [P[1][0], P[1][1] + vw]]
        F = [1.0, x]
        yhat = th[0] + th[1] * x
        RF = [R[0][0] + R[0][1] * x, R[1][0] + R[1][1] * x]
        Q = F[0] * RF[0] + F[1] * RF[1] + VE
        e = y - yhat
        out.append((e, Q, th[0], th[1]))
        K = [RF[0] / Q, RF[1] / Q]
        th = [th[0] + K[0] * e, th[1] + K[1] * e]
        P = [[R[0][0] - K[0] * RF[0], R[0][1] - K[0] * RF[1]],
             [R[1][0] - K[1] * RF[0], R[1][1] - K[1] * RF[1]]]
    return out


def run(dy, dx, by, bx, cost_mult=1.0):
    days = sorted(set(dy) & set(dx))
    oy = [dy[t] for t in days]; ox = [dx[t] for t in days]
    ly = [math.log(b["c"]) for b in oy]; lx = [math.log(b["c"]) for b in ox]
    kf = kalman(ly, lx)
    out, k = [], WARMUP
    while k < len(days) - 1:
        e, Q, a, b = kf[k]
        z = e / math.sqrt(Q)
        if abs(z) <= ENTRY_Z:
            k += 1; continue
        d = -1 if z > 0 else 1                       # trade the spread back
        risk = STOP_K * math.sqrt(Q)
        ey, ex = math.log(oy[k + 1]["o"]), math.log(ox[k + 1]["o"])
        s0 = ey - b * ex
        j, exit_k = k + 1, None
        while j < len(days) - 1:
            sj = ly[j] - b * lx[j]
            zj = kf[j][0] / math.sqrt(kf[j][1])
            if (d * (s0 - sj) >= risk or (zj <= 0 if d == -1 else zj >= 0)
                    or j - (k + 1) >= MAX_DAYS):
                exit_k = j + 1; break
            j += 1
        if exit_k is None:
            break
        xy, xx = math.log(oy[exit_k]["o"]), math.log(ox[exit_k]["o"])
        pnl = d * ((xy - ey) - b * (xx - ex))
        cost = cost_mult * (by + abs(b) * bx) * 1e-4
        out.append({"t": days[k], "r": (pnl - cost) / risk, "b": b, "days": exit_k - k - 1})
        k = exit_k
    return out


def main():
    mk = R29.markets()
    allt, per, dbl, rows = [], [], [], []
    for yn, xn in PAIRS:
        (dy, by), (dx, bx) = daily(yn, mk), daily(xn, mk)
        tr = run(dy, dx, by, bx)
        d2 = run(dy, dx, by, bx, 2.0)
        for t in tr:
            t["pair"] = f"{yn}/{xn}"
        allt += tr; dbl += [t["r"] for t in d2]
        m = st.mean(t["r"] for t in tr) if tr else float("nan")
        if tr:
            per.append(m)
        win = 100 * sum(t["r"] > 0 for t in tr) / len(tr) if tr else 0
        print(f"  {yn + '/' + xn:24s} n={len(tr):4d} avg {m:+.3f}R win {win:.0f}% "
              f"from {min(t['t'] for t in tr):%Y}", flush=True)
        rows.append({"pair": f"{yn}/{xn}", "n": len(tr), "avg_r": round(m, 3), "win_pct": round(win)})
    a = [t["r"] for t in allt]
    t1, p1 = R28.tt(per)
    month = {}
    for t in allt:
        key = t["t"].strftime("%Y-%m"); month[key] = month.get(key, 0) + t["r"]
    t2, p2 = R28.tt(list(month.values()))
    h1 = [t["r"] for t in allt if t["t"] < HALF]; h2 = [t["r"] for t in allt if t["t"] >= HALF]
    yrs = (max(t["t"] for t in allt) - min(t["t"] for t in allt)).days / 365.25
    ok = (len(a) >= 300 and p1 < ALPHA and p2 < ALPHA and h1 and h2 and st.mean(h1) > 0 and st.mean(h2) > 0
          and st.mean(dbl) > 0)
    print(f"\nKalman pairs: {len(a)} trades ({len(a) / yrs / 52:.1f}/week), avg {st.mean(a):+.3f}R, "
          f"win {100 * sum(x > 0 for x in a) / len(a):.0f}%, total {sum(a):+.1f}R")
    print(f"  across pairs: {sum(x > 0 for x in per)} of {len(per)} positive, t={t1:+.2f} p={p1:.2g}")
    print(f"  across months ({len(month)}): t={t2:+.2f} p={p2:.2g}")
    print(f"  before 2017 {st.mean(h1):+.3f}R ({len(h1)}), from 2017 {st.mean(h2):+.3f}R ({len(h2)}), "
          f"double costs {st.mean(dbl):+.3f}R | {'PASS' if ok else 'fail'}")
    summary = {"n": len(a), "per_week": round(len(a) / yrs / 52, 1), "avg_r": round(st.mean(a), 3),
               "pairs_positive": f"{sum(x > 0 for x in per)}/{len(per)}", "p_pairs": f"{p1:.2g}",
               "p_months": f"{p2:.2g}", "before_2017": round(st.mean(h1), 3), "from_2017": round(st.mean(h2), 3),
               "double_costs": round(st.mean(dbl), 3), "verdict": "PASS" if ok else "fail", "pairs": rows}
    json.dump(summary, open(os.path.join(HERE, "round36_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
