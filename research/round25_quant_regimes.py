"""Round 25: quantitative-finance regime filters on the trend strategies
(pre-registered 20 Nov 2026, before any of these splits was looked at).

Bradley asked whether anything from quantitative finance would help. The
time-series momentum literature says trend profits come from returns being
positively autocorrelated, and that this varies over time: Moskowitz, Ooi and
Pedersen (2012), Georgopoulou and Wang (Review of Finance 2016), Baltas and
Kosowski (SSRN 2140091), Levine and Pedersen "Which Trend Is Your Friend?"
(2016), and Liu and Tsyvinski (2021) for crypto's short-horizon momentum. Round
12 tested monthly time-series momentum as a strategy of its own; round 6 tested
ADX as a regime filter. These four tests ask instead whether the hourly trend
trades do better when slower measures say the market is trending. Four tests;
hypotheses_tested rises by 4 and the bar is p < 0.05 / 4 = 0.0125.

Daily closes are the last hourly close of each UTC date, from the same bars the
live rules use; every measure uses only days that finished before the signal.

  Q1 Gold trend, the year agrees (time-series momentum): favoured = the trade's
     direction matches the sign of gold's return over the previous 252 daily
     closes.
  Q2 Gold trend, trending regime (Lo-MacKinlay variance ratio): favoured = the
     5-day variance ratio of the previous 60 daily returns is above 1
     (variance of overlapping 5-day returns / 5 x variance of 1-day returns).
  Q3 Gold trend, hourly returns persist (autocorrelation): favoured = the lag-1
     autocorrelation of the previous 240 hourly returns is above 0.
  Q4 BTC/USD trend, the month agrees (Liu and Tsyvinski's short-horizon crypto
     momentum): favoured = the trade's direction matches the sign of Bitcoin's
     return over the previous 28 daily closes.

Pass, as rounds 20, 21 and 23: the favoured group has 100+ trades and a positive
average in every period with 10+ trades; it beats the rest in at least three of
the periods where both have 10+ trades (two if only two qualify); and a one-sided
Welch t-test gives p < 0.0125. A pass goes into nursery.json as a candidate;
nothing changes the live alerts without Bradley's decision.
"""
import json
import os
import statistics as st
import sys
from bisect import bisect_left
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import round10_btc_checks as B  # noqa: E402
import round12_beyond_gold as M  # noqa: E402
import round21_positioning_and_market_filters as R21  # noqa: E402
import round23_events_funding_metalabel as R23  # noqa: E402
import similar_setups as SS  # noqa: E402

UTC = timezone.utc
R23.ALPHA = 0.05 / 4


def daily(bars):
    out = {}
    for b in bars:
        out[b["t"].date()] = b["c"]
    days = sorted(out)
    return days, [out[d] for d in days]


def before(days, t):
    """Number of daily closes on dates strictly before the signal's date."""
    return bisect_left(days, t.date())


def main():
    now = datetime.now(UTC)
    gb = S.closed_h1(S.load_history(S.CONFIG), now)
    jg = SS.replay(S.CONFIG, gb)
    gold = [{"t": datetime.fromisoformat(j["sig_time"]), "d": j["dir"], "r": j["r"]}
            for j in jg if j.get("strategy", "trend") == "trend"]
    gd, gc = daily(gb)
    lr = np.diff(np.log(gc))
    hidx = {b["t"] + timedelta(hours=1): i for i, b in enumerate(gb)}
    hl = np.diff(np.log([b["c"] for b in gb]))

    def year_agrees(t):
        n = before(gd, t["t"])
        if n < 253:
            return None
        r = gc[n - 1] / gc[n - 253] - 1
        return None if r == 0 else (r > 0) == (t["d"] == 1)

    def trending(t):
        n = before(gd, t["t"])
        if n < 66:
            return None
        x = lr[n - 61:n - 1]                       # the 60 returns ending at close n-1
        v1 = x.var(ddof=1)
        v5 = np.array([x[i:i + 5].sum() for i in range(len(x) - 4)]).var(ddof=1)
        return v5 / (5 * v1) > 1 if v1 > 0 else None

    def persists(t):
        i = hidx.get(t["t"])
        if i is None or i < 242:
            return None
        x = hl[i - 240:i]                          # returns into bars i-239 .. i
        a, b = x[:-1] - x[:-1].mean(), x[1:] - x[1:].mean()
        den = np.sqrt((a * a).sum() * (b * b).sum())
        return None if den == 0 else (a * b).sum() / den > 0

    print(f"Gold trend trades: {len(gold)}")
    rows = [R23.split("Q1 gold trend, the year agrees", gold, year_agrees, M.PERIODS),
            R23.split("Q2 gold trend, variance ratio above 1", gold, trending, M.PERIODS),
            R23.split("Q3 gold trend, hourly autocorrelation above 0", gold, persists, M.PERIODS)]

    bb = B.load_247("data/markets/btcusd_h1.csv.gz")
    jb = SS.replay(S.market_cfg("btc"), bb, scale=True)
    btc = [{"t": datetime.fromisoformat(j["sig_time"]), "d": j["dir"], "r": j["r"]}
           for j in jb if j.get("strategy") == "btc_trend"]
    bd, bc = daily(bb)

    def month_agrees(t):
        n = before(bd, t["t"])
        if n < 29:
            return None
        r = bc[n - 1] / bc[n - 29] - 1
        return None if r == 0 else (r > 0) == (t["d"] == 1)

    rows.append(R23.split("Q4 BTC/USD trend, the month agrees", btc, month_agrees, R21.PERIODS))
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round25_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
