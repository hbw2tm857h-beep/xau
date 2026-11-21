"""Round 29: does round 28's 52-week breakout hold across other markets?
(pre-registered 21 Nov 2026; committed before it was run on any market but gold)

Round 28's 52-week breakout made over 1R a trade on gold in both 2004-15 and
2016-26, drift-adjusted, but only 37 trades in 22 years, so it could not pass.
This is the same slow-trend pattern seen in rounds 5, 25 and 27. Bradley asked
for the cross-market test, on the condition that the live system is not
touched: this round is research only. signals.py, nursery.json, the EA and the
workflows are unchanged whatever the result.

Rule: exactly round28_new_edge.n1_52wk, nothing changed. A daily close above
every close of the previous 252 days, with no such close in the previous 20
days -> buy at the next open (mirror for lows). Stop 2 x Wilder 20-day ATR.
Exit at the next open after a close beyond the 20-day low (high) of closes.
Daily candles close at 17:00 New York (signals.aggregate, as the live bot).

Markets: every non-gold market with a cost in rounds 10, 16 and 17. Cost
is each market's round-trip basis points from those rounds, charged on the
entry price. FX, indices and commodities use round 10's weekday loader; the six
cryptocurrencies keep weekend candles (round10_btc_checks.load_247). Gold is
not in the pooled test (it generated the idea) and is reported separately.

Drift: each trade's R minus direction x mu x entry x days held / risk, where mu
is that market's average daily close-to-close change over its whole history,
so an index that rises over time or a currency that trends cannot pass simply
by holding it.

Pass, all of:
  1. One-sided t-test across markets (each market's average drift-adjusted R is
     one observation, markets with 5+ trades): p < 0.05.
  2. One-sided t-test on calendar months (the sum of drift-adjusted R over all
     markets' trades signalled in each month, months with any trade), which
     allows for trades on many markets firing together: p < 0.05.
  3. Pooled drift-adjusted average positive in both halves (signals before and
     from 1 Jan 2017) and in at least 3 of the 4 asset classes (FX, indices,
     commodities, crypto).
  4. Still positive pooled at double costs.
hypotheses_tested rises by 1 (recorded in this file and research/README.md;
the counter in signals.py is part of the live system and is left alone, as
Bradley asked). A pass would go to Bradley as a proposal; it changes nothing.
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
import round10_btc_checks as B  # noqa: E402
import round16_commodities_crypto as R16  # noqa: E402
import round17_more_fx_indices as R17  # noqa: E402
import round28_new_edge as R28  # noqa: E402

UTC = timezone.utc
HALF = datetime(2017, 1, 1, tzinfo=UTC)
CRYPTO = {"BTCUSD", "Ether", "Litecoin", "Bitcoin Cash", "Stellar", "Cardano"}
COMMOD = {"XAGUSD", "WTI oil", "Brent oil", "Copper", "Platinum", "Palladium", "Natural gas", "Cocoa", "Coffee",
          "Sugar", "Cotton", "Soybeans", "Orange juice", "Diesel"}
INDEX = {"S&P 500", "Nasdaq 100", "Dow", "DAX", "FTSE 100", "Nikkei 225", "Russell 2000", "Euro Stoxx 50", "IBEX 35",
         "AEX", "FTSE MIB", "ASX 200", "Hang Seng", "China A50", "Singapore", "WIG 20"}


def cls(name):
    return "crypto" if name in CRYPTO else "commodities" if name in COMMOD else "indices" if name in INDEX else "FX"


def markets():
    m = {k: v for k, v in R10.MARKETS.items() if not k.startswith("XAUUSD")}
    for src in (R16.NEW, R17.NEW):
        for name, (iid, bps) in src.items():
            m[name] = ([f"markets/{iid}_h1.csv.gz"], bps)
    return m


def load(name, files):
    bars = {}
    for f in files:
        path = os.path.join(ROOT, "data", f)
        for b in (B.load_247(path) if name in CRYPTO else R10.load(path)):
            bars[b["t"]] = b
    return [bars[t] for t in sorted(bars)]


def run(db, bps):
    """round 28's N1 with cost in basis points of the entry price."""
    out = []
    saved = R28.COST
    try:
        atr = R28.wilder_atr(db, 20)
        R28.COST = 0.0
        for t in R28.n1_52wk(db, atr):
            t["r"] -= bps * 1e-4 * t["entry"] / t["risk"]
            out.append(t)
    finally:
        R28.COST = saved
    return out


def tt(xs):
    if len(xs) < 3 or st.stdev(xs) == 0:
        return 0.0, 1.0
    t = st.mean(xs) / (st.stdev(xs) / math.sqrt(len(xs)))
    return t, 0.5 * math.erfc(t / math.sqrt(2))


def main():
    rows, alltr = [], []
    for name, (files, bps) in markets().items():
        bars = load(name, files)
        if len(bars) < 5000:
            print(f"  {name}: too little data"); continue
        db = S.aggregate(bars, S.trading_day, S.day_end)
        ch = [db[k]["c"] / db[k - 1]["c"] - 1 for k in range(1, len(db))]
        mu = st.mean(ch)
        res = {}
        for mult in (1, 2):
            tr = run(db, bps * mult)
            for t in tr:
                t["adj"] = R28.adj(t, mu); t["m"] = name; t["cls"] = cls(name)
            res[mult] = tr
        tr = res[1]
        alltr += tr
        a = [t["adj"] for t in tr]
        row = {"market": name, "class": cls(name), "bps": bps, "from": f"{db[0]['end']:%Y}", "n": len(tr),
               "raw": round(st.mean(t["r"] for t in tr), 3) if tr else None,
               "adj": round(st.mean(a), 3) if tr else None,
               "adj_2x": round(st.mean(t["adj"] for t in res[2]), 3) if res[2] else None,
               "_dbl": [t["adj"] for t in res[2]]}
        rows.append(row)
        print(f"  {name:14s} {row['class']:11s} {row['from']} n={row['n']:3d} raw {row['raw'] if row['raw'] is not None else '-':>7} "
              f"adj {row['adj'] if row['adj'] is not None else '-':>7}", flush=True)

    per = [r["adj"] for r in rows if r["n"] >= 5]
    t1, p1 = tt(per)
    month = {}
    for t in alltr:
        k = t["t"].strftime("%Y-%m"); month[k] = month.get(k, 0) + t["adj"]
    t2, p2 = tt(list(month.values()))
    h1 = [t["adj"] for t in alltr if t["t"] < HALF]; h2 = [t["adj"] for t in alltr if t["t"] >= HALF]
    by = {c: [t["adj"] for t in alltr if t["cls"] == c] for c in ("FX", "indices", "commodities", "crypto")}
    dbl = [x for r in rows for x in r["_dbl"]]
    long_ = [t["adj"] for t in alltr if t["d"] == 1]; short = [t["adj"] for t in alltr if t["d"] == -1]
    print(f"\n{len(rows)} markets, {len(alltr)} trades, pooled raw {st.mean(t['r'] for t in alltr):+.3f}R, "
          f"drift-adjusted {st.mean(t['adj'] for t in alltr):+.3f}R, win {100 * sum(t['r'] > 0 for t in alltr) / len(alltr):.0f}%")
    print(f"  1. across markets ({len(per)} with 5+ trades): mean {st.mean(per):+.3f}R, {sum(x > 0 for x in per)} positive, "
          f"t={t1:+.2f} p={p1:.2g}")
    print(f"  2. across months ({len(month)}): mean {st.mean(month.values()):+.3f}R a month, t={t2:+.2f} p={p2:.2g}")
    print(f"  3. before 2017 {st.mean(h1):+.3f}R ({len(h1)}), from 2017 {st.mean(h2):+.3f}R ({len(h2)}) | "
          + " ".join(f"{c} {st.mean(v):+.3f}R ({len(v)})" for c, v in by.items() if v))
    print(f"  4. double costs: {st.mean(dbl):+.3f}R")
    print(f"  longs {st.mean(long_):+.3f}R ({len(long_)}), shorts {st.mean(short):+.3f}R ({len(short)})")
    ok = (p1 < 0.05 and p2 < 0.05 and st.mean(h1) > 0 and st.mean(h2) > 0
          and sum(st.mean(v) > 0 for v in by.values() if v) >= 3 and st.mean(dbl) > 0)
    print(f"\nVERDICT: {'PASS' if ok else 'fail'}")
    for r in rows:
        r.pop("_dbl")
    json.dump({"markets": rows, "p_markets": f"{p1:.2g}", "p_months": f"{p2:.2g}", "verdict": "PASS" if ok else "fail"},
              open(os.path.join(HERE, "round29_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
