"""Round 13: does the IBS edge travel, and four more ideas (pre-registered 19 Nov 2026).

Round 12 found one pass, IBS band reversion on stock indices. This round asks
whether the same mechanism works on FX, commodities and Bitcoin, which would make
it a multi-market stream, and tests four more fully specified ideas. Rules,
costs, financing and the pass mark were committed before any result was seen.

Shared IBS band rule (round 12 M8): band = 10-day highest high - 2.5 x 25-day
average range; IBS = (close - low) / (high - low). Long at the close when close <
band and IBS < 0.3, out at the first close above the previous day's high. The
mirror for shorts: close > 10-day lowest low + 2.5 x 25-day average range and
IBS > 0.7, out at the first close below the previous day's low. One position per
market at a time.

  N1 IBS band, 11 FX pairs, both sides. Daily candles roll at 17:00 New York.
     Swap: a 1%/year broker markup (0.27 bp a night) on either side.
  N2 IBS band, gold, silver, WTI and Brent, both sides. Daily candles roll at
     17:00 New York. Financing: longs (policy rate + 2.5%)/365 a night, shorts
     max(0, 2.5% - policy rate)/365.
  N3 IBS band, Bitcoin, long only (as published). UTC days. Financing 10%/year
     (2.7 bp a night), roughly perpetual-futures funding.
  N4 Nasdaq intraday momentum, Gao, Han, Li & Zhou (JFE 2018). 09:30-aligned
     candles (round 11). The return from the previous 16:00 close to 10:30 sets the
     side of the 15:30-16:00 candle. One trade a day.
  N5 Bitcoin weekly time-series momentum, Liu & Tsyvinski (RFS 2021). Long next
     week (Monday 00:00 UTC) if last week rose, short if it fell. Longs pay 10%/year
     financing.
  N6 Lower-low, lower-high reversal (Reddit catalogue #3), S&P 500, Nasdaq 100,
     Dow. After a cash session with a lower low and lower high than the one
     before, buy-stop at its high the next session (at the open if it gaps above),
     out at that session's close. Intraday, so no financing.
  N7 Daily gap fill (Reddit catalogue #12), same three indices. Three sessions
     with session 3's low above session 1's high, session 2's low below session
     3's low and session 2's high above session 1's high. If the next session
     opens below session 3's low, buy the open. Out at the first close at or
     above session 3's low, or a close below entry - 5 x ATR(14). Financing as in
     round 12.

FOMC pre-announcement drift (Lucca & Moench 2015) was considered and dropped:
about 120 meetings since 2011, under the 150-observation minimum.

Costs: round 10's per-market round-trip costs. Pass: 150+ observations, positive
in every period with 10+, one-sided p < 0.05 / 7 = 0.0071.
"""
import math
import os
import statistics as st
import sys
import csv
from datetime import datetime, time, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import round11_noise_30 as N30  # noqa: E402
import round12_beyond_gold as M  # noqa: E402

UTC, NY = timezone.utc, M.NY
N_TESTS = 7
M.ALPHA = 0.05 / N_TESTS        # judge() reads this
FX11 = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP", "AUDJPY"]
COMMOD = ["XAUUSD", "XAGUSD", "WTI oil", "Brent oil"]


def fx_days(name, roll_ny=True):
    """Daily candles: 17:00 New York roll (FX, commodities) or UTC days (Bitcoin)."""
    days = {}
    for b in M.bars(name)[1]:
        d = (b["t"].astimezone(NY) + timedelta(hours=7)).date() if roll_ny else b["t"].date()
        if roll_ny and d.weekday() >= 5:
            continue
        days.setdefault(d, []).append(b)
    out = {}
    for d, bs in days.items():
        if len(bs) < (20 if roll_ny else 22):
            continue
        bs.sort(key=lambda x: x["t"])
        out[d] = {"o": bs[0]["o"], "h": max(x["h"] for x in bs), "l": min(x["l"] for x in bs),
                  "c": bs[-1]["c"], "t": bs[-1]["t"] + timedelta(hours=1)}
    return out


def ibs_band(name, s, sides, night_bps):
    """night_bps(t0, t1, side) -> financing in bp for the hold."""
    days = sorted(s)
    out, i = [], 25
    while i < len(days) - 1:
        hi10 = max(s[d]["h"] for d in days[i - 9:i + 1])
        lo10 = min(s[d]["l"] for d in days[i - 9:i + 1])
        ar = st.mean(s[d]["h"] - s[d]["l"] for d in days[i - 24:i + 1])
        c = s[days[i]]
        rng = c["h"] - c["l"]
        side = 0
        if rng > 0:
            ibs = (c["c"] - c["l"]) / rng
            if 1 in sides and c["c"] < hi10 - 2.5 * ar and ibs < 0.3:
                side = 1
            elif -1 in sides and c["c"] > lo10 + 2.5 * ar and ibs > 0.7:
                side = -1
        if side:
            j = i + 1
            while j < len(days) and not (s[days[j]]["c"] > s[days[j - 1]]["h"] if side == 1 else s[days[j]]["c"] < s[days[j - 1]]["l"]):
                j += 1
            if j >= len(days):
                break
            x = s[days[j]]
            bps = side * (x["c"] / c["c"] - 1) * 1e4 - M.cost(name) - night_bps(c["t"], x["t"], side)
            out.append({"t": c["t"], "bps": bps, "mkt": name, "d": side})
            i = j + 1
            continue
        i += 1
    return out


def nights(t0, t1):
    return max(0, (t1.date() - t0.date()).days)


def fx_swap(t0, t1, side):
    return nights(t0, t1) * 1.0 / 365 * 100


def commod_fin(t0, t1, side):
    total = 0.0
    for k in range(nights(t0, t1)):
        r = M.FED[(t0 + timedelta(days=k)).year]
        total += ((r + 2.5) if side == 1 else max(0.0, 2.5 - r)) / 365 * 100
    return total


def btc_fin(t0, t1, side):
    return nights(t0, t1) * 10.0 / 365 * 100 if side == 1 else 0.0


def n1():
    return [t for n in FX11 for t in ibs_band(n, fx_days(n), (1, -1), fx_swap)]


def n2():
    return [t for n in COMMOD for t in ibs_band(n, fx_days(n), (1, -1), commod_fin)]


def n3():
    return ibs_band("BTCUSD", fx_days("BTCUSD", roll_ny=False), (1,), btc_fin)


def n4():
    bars = N30.cash_hours()
    by = {}
    for b in bars:
        by.setdefault(b["t"].astimezone(NY).date(), []).append(b)
    days = sorted(by)
    out = []
    for d0, d1 in zip(days, days[1:]):
        prev_close, first, last = by[d0][-1]["c"], by[d1][0], by[d1][-1]
        r = first["c"] / prev_close - 1
        if r == 0:
            continue
        side = 1 if r > 0 else -1
        out.append({"t": last["t"], "bps": side * (last["c"] / last["o"] - 1) * 1e4 - M.cost("Nasdaq 100")})
    return out


def n5():
    idx, lst, cost = M.bars("BTCUSD")
    mondays = {}
    for b in lst:
        if b["t"].weekday() == 0 and b["t"].hour == 0:
            mondays[b["t"]] = b["o"]
    ks = sorted(mondays)
    out = []
    for a, b, c in zip(ks, ks[1:], ks[2:]):
        if (b - a).days != 7 or (c - b).days != 7:
            continue
        side = 1 if mondays[b] > mondays[a] else -1
        out.append({"t": b, "bps": side * (mondays[c] / mondays[b] - 1) * 1e4 - cost - btc_fin(b, c, side)})
    return out


def n6():
    out = []
    for n in M.US3:
        s = M.sessions(n)
        days = sorted(s)
        for a, b, c in zip(days, days[1:], days[2:]):
            if (c - b).days > 4:
                continue
            pa, pb, nx = s[a], s[b], s[c]
            if pb["l"] < pa["l"] and pb["h"] < pa["h"] and nx["h"] >= pb["h"]:
                entry = max(nx["o"], pb["h"])
                out.append({"t": nx["t"], "bps": (nx["c"] / entry - 1) * 1e4 - M.cost(n)})
    return out


def n7():
    out = []
    for n in M.US3:
        s = M.sessions(n)
        days = sorted(s)
        tr = [max(s[days[k]]["h"], s[days[k - 1]]["c"]) - min(s[days[k]]["l"], s[days[k - 1]]["c"]) for k in range(1, len(days))]
        i = 16
        while i < len(days) - 1:
            c1, c2, c3 = s[days[i - 2]], s[days[i - 1]], s[days[i]]
            nx = s[days[i + 1]]
            if c3["l"] > c1["h"] and c2["l"] < c3["l"] and c2["h"] > c1["h"] and nx["o"] < c3["l"]:
                atr = st.mean(tr[i - 14:i])
                entry, j, x = nx["o"], i + 1, None
                while j < len(days):
                    cj = s[days[j]]["c"]
                    if cj >= c3["l"] or cj < entry - 5 * atr:
                        x = s[days[j]]
                        break
                    j += 1
                if x is None:
                    break
                t0 = nx["t"] - timedelta(hours=7)
                out.append({"t": nx["t"], "bps": (x["c"] / entry - 1) * 1e4 - M.cost(n) - M.finance_bps(t0, x["t"])})
                i = j + 1
                continue
            i += 1
    return out


TESTS = [
    ("N1 IBS band, 11 FX pairs, both sides", n1),
    ("N2 IBS band, gold/silver/oil, both sides", n2),
    ("N3 IBS band, Bitcoin, long only", n3),
    ("N4 Nasdaq intraday momentum (Gao 2018)", n4),
    ("N5 Bitcoin weekly momentum", n5),
    ("N6 Lower-low/high reversal, US indices", n6),
    ("N7 Daily gap fill, US indices", n7),
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
        print(f"{name:42s} n={s['n']:5d} win={s['win']:4.1f}% net={s['avg']:+7.2f}bp t={s['t']:+5.2f} | "
              + " ".join(f"{pn} {('%+.2f' % v) if v is not None else '  -  '}({k})" for pn, (k, v) in s["per"].items())
              + f" | yrs+ {s['pos_years']}/{s['years']} | p={s['p']:.2g} {row['verdict']}", flush=True)
        if "mkt" in (o[0] if o else {}):
            for mk in sorted({t["mkt"] for t in o}):
                x = [t["bps"] for t in o if t["mkt"] == mk]
                print(f"      {mk:10s} n={len(x):4d} avg={st.mean(x):+7.2f}bp")
    with open(os.path.join(HERE, "results_round13_more_markets.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
