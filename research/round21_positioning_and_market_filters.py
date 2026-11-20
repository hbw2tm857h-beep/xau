"""Round 21: futures positioning (CFTC) and one market-specific filter per market
(pre-registered 20 Nov 2026, before any of the financial-futures positioning data
was downloaded and before any of these splits was looked at).

Bradley asked for two things: use the weekly CFTC Commitments of Traders report
where it helps the edge, and look for rules that favour each market's own setups
the way gold's context checks do. Eight tests; hypotheses_tested rises by 8.

Positioning data: CFTC Traders in Financial Futures, futures only (dataset
gpe5-46if on publicreporting.cftc.gov), leveraged funds net = long - short.
A report covers positions on a Tuesday and is published the Friday after; to be
safe with holiday delays a report is treated as known from 00:00 UTC on the
Monday six days after its date. Gold's positioning was already tested (round 20,
B3, failed), so it is not retested here.

  P1 BTC/USD trend (CME Bitcoin, 133741): favoured = trades in the direction of the
     latest weekly change in the leveraged-funds net (follow the funds).
  P2 BTC/USD trend: favoured = every trade except buys when the net is in its top
     10% of the previous 104 weeks and sells when it is in its bottom 10%
     (not with an extreme crowd; 104 weeks because the contract only began in 2017).
  P3 ETH/USD inside-day (CME Ether, 146021): as P1.
  P4 US index rebounds (E-mini S&P 500 13874A for the S&P 500, Nasdaq mini 209742,
     Dow mini 124603, Russell mini 239742): favoured = the net is below its median
     of the previous 52 weeks (funds lean short, the strategy buys).
  P5 US index rebounds: favoured = the latest weekly change in the net is negative
     (funds were selling into the dip).

Market-specific filters, each from the market's own price data:
  F1 BTC/USD trend: favoured = signals on candles that close 14:00-21:00 UTC
     (US hours), against the rest.
  F2 ETH/USD inside-day: favoured = the inside day's range / ATR is below the median
     of all earlier ETH inside-day setups (at least 20 earlier), as gold's "tight
     inside day" note does.
  F3 US index rebounds: favoured = the signal day closes below the lowest low of the
     previous five sessions (a fresh short-term low).

Pass, as round 20's group B: the favoured group has 100+ trades and a positive
average in every period with 10+ trades; it beats the rest in at least three of
the periods where both have 10+ trades (at least two where only two qualify);
and a one-sided Welch t-test gives p < 0.05 / 8 = 0.00625.

Anything that passes goes into nursery.json as a candidate. Nothing changes the
live alerts without Bradley's decision and a separate end-to-end-checked change.
"""
import json
import math
import os
import statistics as st
import sys
import urllib.request
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import round10_btc_checks as B  # noqa: E402
import round12_beyond_gold as M  # noqa: E402
import similar_setups as SS  # noqa: E402

UTC = timezone.utc
ALPHA = 0.05 / 8
COT_DIR = os.path.join(ROOT, "data", "macro", "cot")
M.R10.MARKETS["Russell 2000"] = (["markets/ussc2000idxusd_h1.csv.gz"], 2.0)
M.SESSION["Russell 2000"] = (ZoneInfo("America/New_York"), 9, 15)
US4 = {"S&P 500": "13874A", "Nasdaq 100": "209742", "Dow": "124603", "Russell 2000": "239742"}
PERIODS = [("2012-17", datetime(2012, 1, 1, tzinfo=UTC), datetime(2018, 1, 1, tzinfo=UTC)),
           ("2018-20", datetime(2018, 1, 1, tzinfo=UTC), datetime(2021, 1, 1, tzinfo=UTC)),
           ("2021-23", datetime(2021, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC)),
           ("2024-26", datetime(2024, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))]


def tff(code):
    """Weekly leveraged-funds net for one contract: sorted [(known_from, net)]."""
    os.makedirs(COT_DIR, exist_ok=True)
    path = os.path.join(COT_DIR, f"tff_{code}.json")
    if not os.path.exists(path):
        url = ("https://publicreporting.cftc.gov/resource/gpe5-46if.json?$limit=5000"
               f"&$order=report_date_as_yyyy_mm_dd&cftc_contract_market_code={code}")
        rows = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research"}),
                                                timeout=60))
        json.dump([{"d": r["report_date_as_yyyy_mm_dd"][:10], "long": r["lev_money_positions_long"],
                    "short": r["lev_money_positions_short"]} for r in rows], open(path, "w"))
    out = []
    for r in json.load(open(path)):
        d = datetime.fromisoformat(r["d"]).replace(tzinfo=UTC)
        out.append((d + timedelta(days=6), float(r["long"]) - float(r["short"])))
    return sorted(out)


def known(series, t):
    """Index of the latest report known at time t, or None."""
    i = bisect_right([k for k, _ in series], t) - 1
    return i if i >= 0 else None


def follow(series, t, d):
    i = known(series, t)
    if i is None or i < 1:
        return None
    ch = series[i][1] - series[i - 1][1]
    return None if ch == 0 else (ch > 0) == (d == 1)


def not_extreme(series, t, d, weeks=104):
    i = known(series, t)
    if i is None or i < weeks:
        return None
    hist = sorted(v for _, v in series[i - weeks:i])
    lo, hi = hist[int(0.1 * weeks)], hist[int(0.9 * weeks) - 1]
    v = series[i][1]
    return not ((d == 1 and v >= hi) or (d == -1 and v <= lo))


def judge(name, trades, fn):
    tr = [dict(t, flag=fn(t)) for t in trades]
    tr = [t for t in tr if t["flag"] is not None]
    a = [t for t in tr if t["flag"]]; b = [t for t in tr if not t["flag"]]
    if len(a) < 2 or len(b) < 2:
        print(f"  {name:44s} too few trades (favoured {len(a)}, rest {len(b)}) | fail")
        return {"test": name, "n_fav": len(a), "n_rest": len(b), "verdict": "fail"}
    ra, rb = [t["r"] for t in a], [t["r"] for t in b]
    tstat = (st.mean(ra) - st.mean(rb)) / math.sqrt(st.variance(ra) / len(ra) + st.variance(rb) / len(rb))
    p = 0.5 * math.erfc(tstat / math.sqrt(2))
    wins, both, pos = 0, 0, True
    for _pn, lo, hi in PERIODS:
        xa = [t["r"] for t in a if lo <= t["t"] < hi]; xb = [t["r"] for t in b if lo <= t["t"] < hi]
        if len(xa) >= 10:
            pos = pos and st.mean(xa) > 0
        if len(xa) >= 10 and len(xb) >= 10:
            both += 1; wins += st.mean(xa) > st.mean(xb)
    need = 3 if both >= 3 else 2
    ok = len(a) >= 100 and pos and both >= 2 and wins >= need and p < ALPHA
    print(f"  {name:44s} favoured n={len(a):3d} avg={st.mean(ra):+.3f}R | rest n={len(b):3d} avg={st.mean(rb):+.3f}R | "
          f"t={tstat:+.2f} p={p:.2g} | ahead in {wins}/{both} periods | {'PASS' if ok else 'fail'}")
    return {"test": name, "n_fav": len(a), "avg_fav": round(st.mean(ra), 3), "n_rest": len(b),
            "avg_rest": round(st.mean(rb), 3), "t": round(tstat, 2), "p": f"{p:.2g}",
            "periods": f"{wins}/{both}", "verdict": "PASS" if ok else "fail"}


def main():
    rows = []
    jb = SS.replay(S.market_cfg("btc"), B.load_247("data/markets/btcusd_h1.csv.gz"), scale=True)
    je = SS.replay(S.market_cfg("eth"), B.load_247("data/markets/ethusd_h1.csv.gz"), scale=True)
    btc = [{"t": datetime.fromisoformat(j["sig_time"]), "d": j["dir"], "r": j["r"]}
           for j in jb if j.get("strategy") == "btc_trend"]
    eth = [{"t": datetime.fromisoformat(j["sig_time"]), "d": j["dir"], "r": j["r"],
            "ra": (j.get("idea") or {}).get("range_atr")} for j in je if j.get("strategy") == "eth_inside_day"]
    us = []
    for name, code in US4.items():
        s = M.sessions(name)
        days = [dict(s[d], t_close=s[d]["t"]) for d in sorted(s)]
        lows = {d["t_close"]: min(x["l"] for x in days[max(0, i - 5):i]) if i >= 5 else None
                for i, d in enumerate(days)}
        closes = {d["t_close"]: d["c"] for d in days}
        for t in S.ibs_trades(days, 1.0):
            us.append({"t": t["t"], "d": 1, "r": t["r"], "code": code,
                       "fresh_low": None if lows.get(t["t"]) is None else closes[t["t"]] < lows[t["t"]]})
    print(f"Trades: BTC/USD trend {len(btc)}, ETH/USD inside-day {len(eth)}, US index rebounds {len(us)}")
    cb, ce = tff("133741"), tff("146021")
    cu = {code: tff(code) for code in US4.values()}
    print("Positioning (CFTC leveraged funds)")
    rows.append(judge("P1 BTC/USD trend follows the funds", btc, lambda t: follow(cb, t["t"], t["d"])))
    rows.append(judge("P2 BTC/USD trend not with an extreme crowd", btc, lambda t: not_extreme(cb, t["t"], t["d"])))
    rows.append(judge("P3 ETH/USD inside-day follows the funds", eth, lambda t: follow(ce, t["t"], t["d"])))

    def below_median(t):
        c = cu[t["code"]]; i = known(c, t["t"])
        if i is None or i < 52:
            return None
        return c[i][1] < st.median(v for _, v in c[i - 52:i])

    def funds_selling(t):
        c = cu[t["code"]]; i = known(c, t["t"])
        if i is None or i < 1 or c[i][1] == c[i - 1][1]:
            return None
        return c[i][1] < c[i - 1][1]

    rows.append(judge("P4 US rebounds when funds lean short", us, below_median))
    rows.append(judge("P5 US rebounds when funds were selling", us, funds_selling))
    print("Market-specific filters")
    rows.append(judge("F1 BTC/USD trend in US hours", btc, lambda t: 14 <= (t["t"] + timedelta(hours=1)).hour <= 21))

    def tight(t):
        prev = [x["ra"] for x in eth if x["t"] < t["t"] and x["ra"] is not None]
        return None if len(prev) < 20 or t["ra"] is None else t["ra"] < st.median(prev)

    rows.append(judge("F2 ETH/USD tight inside day", eth, tight))
    rows.append(judge("F3 US rebounds from a fresh 5-day low", us, lambda t: t["fresh_low"]))
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round21_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
