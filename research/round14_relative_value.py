"""Round 14: relative value and cross-sectional ideas (pre-registered 19 Nov 2026).

Rounds 12-13 tested single-market timing rules: one of sixteen passed (IBS on
stock indices). This round tests a different family, trades on the *difference*
between related markets, which need no market direction and so could add a stream
uncorrelated with everything live. Rules are textbook defaults, fixed before any
result was seen.

  P1 FX cross-sectional momentum, Menkhoff, Sarno, Schmeling & Schrimpf (JFE 2012).
     Eight currencies (USD, EUR, GBP, JPY, CHF, AUD, CAD, NZD). At each month end,
     rank them by the month's return against the dollar (USD = 0). Long the top
     two, short the bottom two, equal weight, for the next month. Cost: each leg
     pays its pair's round-trip cost every month.
  P2-P5 Pairs, distance/z-score method (Gatev, Goetzmann & Rouwenhorst, RFS
     2006 rule of thumb). Spread = log(A) - log(B) on daily closes. z = (spread -
     20-day mean) / 20-day stdev. When z > 2, short A and long B; when z < -2, the
     reverse; exit at the first close where z crosses 0, or after 20 days. Equal
     notional legs; a trade's return is the average of the two legs, after both
     legs' costs and financing.
     P2 Brent vs WTI.           Daily closes at the 17:00 New York roll.
     P3 AUDUSD vs NZDUSD.       Same.
     P4 Nasdaq 100 vs Dow.      Cash-session closes (round 12 sessions).
     P5 Gold vs silver.         17:00 New York roll.
  P6 Weekly reversal across six stock indices (short-term reversal, Lo &
     MacKinlay 1990; country-index evidence, Balvers, Wu & Gilliland 2000). Each
     Friday cash close, long the index with the worst week and short the best, for
     one week.

Financing: index and commodity longs pay (policy rate + 2.5%)/365 a night, shorts
max(0, 2.5% - policy rate)/365; FX legs pay a 1%/year swap markup. Costs: round
10's per-market round-trip costs.

Pass: 150+ observations, positive in every period with 10+, one-sided
p < 0.05 / 6 = 0.0083.
"""
import csv
import math
import os
import statistics as st
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import round12_beyond_gold as M  # noqa: E402
import round13_more_markets as R13  # noqa: E402

UTC = timezone.utc
N_TESTS = 6
M.ALPHA = 0.05 / N_TESTS
# currency -> (pair, +1 if the pair is XXXUSD so its return is the currency's return vs USD)
CCY = {"EUR": ("EURUSD", 1), "GBP": ("GBPUSD", 1), "JPY": ("USDJPY", -1), "CHF": ("USDCHF", -1),
       "AUD": ("AUDUSD", 1), "CAD": ("USDCAD", -1), "NZD": ("NZDUSD", 1)}


def fin(kind, t0, t1, side):
    if kind == "fx":
        return R13.fx_swap(t0, t1, side)
    return R13.commod_fin(t0, t1, side)


def p1():
    closes = {c: R13.fx_days(p) for c, (p, q) in CCY.items()}
    month_end = {}
    for c, s in closes.items():
        for d in sorted(s):
            month_end.setdefault(c, {})[(d.year, d.month)] = d
    months = sorted(set.intersection(*(set(v) for v in month_end.values())))
    out = []
    for a, b, c in zip(months, months[1:], months[2:]):
        def ret(ccy, m0, m1):
            if ccy == "USD":
                return 0.0
            pair, q = CCY[ccy]
            s, me = closes[ccy], month_end[ccy]
            r = s[me[m1]]["c"] / s[me[m0]]["c"]
            return (r if q == 1 else 1 / r) - 1
        rank = sorted(["USD"] + list(CCY), key=lambda k: ret(k, a, b))
        longs, shorts = rank[-2:], rank[:2]
        legs = [ret(k, b, c) * 1e4 for k in longs] + [-ret(k, b, c) * 1e4 for k in shorts]
        costs = [M.cost(CCY[k][0]) for k in longs + shorts if k != "USD"]
        t0 = closes["EUR"][month_end["EUR"][b]]["t"]
        t1 = closes["EUR"][month_end["EUR"][c]]["t"]
        out.append({"t": t0, "bps": st.mean(legs) - sum(costs) / 4 - R13.fx_swap(t0, t1, 1)})
    return out


def pairs(a, b, sa, sb, kind_a, kind_b):
    days = sorted(set(sa) & set(sb))
    spread = [math.log(sa[d]["c"]) - math.log(sb[d]["c"]) for d in days]
    out, i = [], 20
    while i < len(days) - 1:
        w = spread[i - 19:i + 1]
        sd = st.stdev(w)
        if sd == 0:
            i += 1; continue
        z = (spread[i] - st.mean(w)) / sd
        if abs(z) > 2:
            side = -1 if z > 2 else 1            # side on A; B gets the opposite
            mu = st.mean(w)
            j = i + 1
            while j < len(days) and j - i < 20:
                if (spread[j] - mu) * (spread[i] - mu) <= 0:
                    break
                j += 1
            if j >= len(days):
                break
            d0, d1 = days[i], days[j]
            ra = side * (sa[d1]["c"] / sa[d0]["c"] - 1) * 1e4 - M.cost(a) - fin(kind_a, sa[d0]["t"], sa[d1]["t"], side)
            rb = -side * (sb[d1]["c"] / sb[d0]["c"] - 1) * 1e4 - M.cost(b) - fin(kind_b, sb[d0]["t"], sb[d1]["t"], -side)
            out.append({"t": sa[d0]["t"], "bps": (ra + rb) / 2})
            i = j + 1
            continue
        i += 1
    return out


def p6():
    names = list(M.SESSION)
    s = {n: M.sessions(n) for n in names}
    fridays = {}
    for n in names:
        for d in s[n]:
            if d.weekday() == 4:
                fridays.setdefault(d, set()).add(n)
    ks = sorted(d for d, v in fridays.items() if len(v) == len(names))
    out = []
    for a, b, c in zip(ks, ks[1:], ks[2:]):
        if (b - a).days != 7 or (c - b).days != 7:
            continue
        wk = {n: s[n][b]["c"] / s[n][a]["c"] - 1 for n in names}
        worst, best = min(wk, key=wk.get), max(wk, key=wk.get)
        rl = (s[worst][c]["c"] / s[worst][b]["c"] - 1) * 1e4 - M.cost(worst) - R13.commod_fin(s[worst][b]["t"], s[worst][c]["t"], 1)
        rs = -(s[best][c]["c"] / s[best][b]["c"] - 1) * 1e4 - M.cost(best) - R13.commod_fin(s[best][b]["t"], s[best][c]["t"], -1)
        out.append({"t": s[worst][b]["t"], "bps": (rl + rs) / 2})
    return out


TESTS = [
    ("P1 FX cross-sectional momentum", p1),
    ("P2 Pairs: Brent vs WTI", lambda: pairs("Brent oil", "WTI oil", R13.fx_days("Brent oil"), R13.fx_days("WTI oil"), "c", "c")),
    ("P3 Pairs: AUDUSD vs NZDUSD", lambda: pairs("AUDUSD", "NZDUSD", R13.fx_days("AUDUSD"), R13.fx_days("NZDUSD"), "fx", "fx")),
    ("P4 Pairs: Nasdaq 100 vs Dow", lambda: pairs("Nasdaq 100", "Dow", M.sessions("Nasdaq 100"), M.sessions("Dow"), "c", "c")),
    ("P5 Pairs: gold vs silver", lambda: pairs("XAUUSD", "XAGUSD", R13.fx_days("XAUUSD"), R13.fx_days("XAGUSD"), "c", "c")),
    ("P6 Weekly reversal, 6 indices", p6),
]


def main():
    rows = []
    for name, fn in TESTS:
        o = sorted(fn(), key=lambda t: t["t"])
        s = M.judge(o)
        if s["n"] < 3:
            print(f"{name}: too few ({s['n']})"); continue
        row = {"test": name, "n": s["n"], "win": round(s["win"], 1), "avg_bps_net": round(s["avg"], 2),
               "t": round(s["t"], 2), "p": f"{s['p']:.2g}",
               **{f"{pn}_bps": (round(v, 2) if v is not None else "") for pn, (k, v) in s["per"].items()},
               **{f"{pn}_n": k for pn, (k, v) in s["per"].items()},
               "pos_years": f"{s['pos_years']}/{s['years']}", "verdict": "PASS" if s["ok"] else ""}
        rows.append(row)
        print(f"{name:34s} n={s['n']:5d} win={s['win']:4.1f}% net={s['avg']:+7.2f}bp t={s['t']:+5.2f} | "
              + " ".join(f"{pn} {('%+.2f' % v) if v is not None else '  -  '}({k})" for pn, (k, v) in s["per"].items())
              + f" | yrs+ {s['pos_years']}/{s['years']} | p={s['p']:.2g} {row['verdict']}", flush=True)
    with open(os.path.join(HERE, "results_round14_relative_value.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
