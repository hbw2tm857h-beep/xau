"""Round 28: a new gold edge built from 2004, then enhanced with parts of the
existing one (pre-registered 21 Nov 2026; committed before any of it was run).

Bradley asked for a new edge, tested from 2004, and then for whatever from the
existing strategy improves it. Rounds 5 and 27 point the same way: gold's slow
trend followers (Turtle 55/20, the 50/200 cross) made money in every period but
traded too rarely to prove it, and trades with gold's 12-month trend beat those
against it in all five periods since 2004. With 2004-07 added (round 27's data)
there are 22 years of hourly candles, aggregated to daily candles that close at
17:00 New York, exactly as the live bot builds them.

STAGE 1, four new daily edges, none tested in rounds 1-27 (the Turtles, RSI-2,
Bollinger, NR7, inside-day, golden cross, IBS and noise-area tests are not
repeated). Fixed textbook settings, nothing tuned. Entries at the next day's
open unless stated; ATR is Wilder's 20-day ATR at the signal; cost $0.35 a
round trip as everywhere else. Within a day the stop is assumed to be hit
before any target. One trade at a time per edge.

  N1 52-week breakout (George and Hwang 2004 anchoring): a daily close above
     every close of the previous 252 days, with no such close in the previous
     20 days -> buy. Mirror for a 252-day low. Stop 2 x ATR. Exit at the next
     open after a close beyond the 20-day low (high) of closes.
  N2 Shock continuation: the day's log return is more than 2.5 x the standard
     deviation of the previous 60 daily log returns -> trade its direction.
     Stop 2 x ATR. Exit at the close of the 5th day of the trade.
  N3 Daily Heikin Ashi trend ride (the live method one timeframe up, with a
     slower trend so it does not reuse the live daily filter): the daily Heikin
     Ashi candle turns green after a red one while the close is above the
     100-day SMA -> buy stop at the signal day's high + 0.1 x ATR, valid the
     next day only. Stop below the lowest low of the last 5 days - 0.1 x ATR.
     Half off at 1R with the stop to entry, the rest at 2R. Mirror for sells.
  N4 Keltner breakout (Keltner/Raschke channel, untested so far): a close above
     the 20-day EMA + 2 x ATR -> buy. Stop 2 x ATR. Exit at the next open after
     a close back below the 20-day EMA. Mirror for sells.

Measurement. R = ((exit - entry) x direction - cost) / initial risk. Gold rose
from $400 to $4,000, so a long-only rule makes money by holding gold. Each
trade is therefore judged drift-adjusted: R minus direction x mu x entry x
days held / risk, where mu is gold's average daily close-to-close change (as a
share of price) over the period being judged and days held counts daily
candles from the entry candle to the exit candle (minus one when the exit is
at an open).

Pass, Stage 1: on signals in 2004-2015 (the search period), 60+ trades,
drift-adjusted average above zero with a one-sided t-test p < 0.05 / 4 =
0.0125, raw average above zero. Then, on 2016-2026 (the confirmation period;
not used for any decision above), drift-adjusted average above zero with
p < 0.05, raw average above zero. Only an edge that passes both goes to
Stage 2.

STAGE 2, five parts of the existing edge tried on each Stage 1 survivor:
  E1 the live daily trend (signals.daily_trend at the signal day) agrees
  E2 the last closed 4H Heikin Ashi candle at the signal close agrees
  E3 the 4H Ichimoku cloud side (signals.ichimoku_cloud_dir) agrees
  E4 gold's 12-month return (252 daily closes) agrees (round 25 Q1)
  E5 the live exit (half at 1R, stop to entry, rest at 2R) replaces the native
     exit (N3 already uses it, so it is skipped there)
E1-E4 are filters (a neutral reading - no daily trend, a doji, inside the
cloud - counts as not agreeing): favoured vs rest, one-sided Welch t-test on drift-adjusted
R. E5 is paired: per-trade gain. An enhancement is kept if it is better on
2004-15 with p < 0.05 and the favoured group keeps 40+ trades; a kept one is
confirmed if it is also better on 2016-26 with p < 0.05 / (number kept). The
final rule (survivor + confirmed enhancements) is reported on both periods.

Reported, not tested: each survivor's monthly correlation with the live gold
trend trades, and results at double cost. hypotheses_tested rises by 4, plus 5
(4 for N3) per Stage 1 survivor. A survivor goes to nursery.json as a
candidate (silent); nothing is alerted without Bradley's decision.
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
import similar_setups as SS  # noqa: E402
import round27_lockbox_2004_07 as R27  # noqa: E402

UTC = timezone.utc
COST = 0.35
A1 = 0.05 / 4
D = lambda y: datetime(y, 1, 1, tzinfo=UTC)
DEV, CONF = (D(2004), D(2016)), (D(2016), D(2030))


def load_all():
    old = R27.load()
    new = S.closed_h1(S.load_history(S.CONFIG), datetime.now(UTC))
    first = new[0]["t"]
    return [b for b in old if b["t"] < first] + new


def wilder_atr(db, p=20):
    out, a = [None] * len(db), None
    for k in range(1, len(db)):
        tr = max(db[k]["h"] - db[k]["l"], abs(db[k]["h"] - db[k - 1]["c"]), abs(db[k]["l"] - db[k - 1]["c"]))
        if k < p:
            continue
        if a is None:
            a = st.mean(max(db[j]["h"] - db[j]["l"], abs(db[j]["h"] - db[j - 1]["c"]), abs(db[j]["l"] - db[j - 1]["c"]))
                        for j in range(k - p + 1, k + 1))
        else:
            a = (a * (p - 1) + tr) / p
        out[k] = a
    return out


def ema(vals, p):
    out, e = [None] * len(vals), None
    for k, v in enumerate(vals):
        if k == p - 1:
            e = sum(vals[:p]) / p
        elif k >= p:
            e = (v - e) * 2 / (p + 1) + e
        out[k] = e
    return out


def trade(db, k_sig, k_in, d, entry, stop, exit_fn, partial=False):
    """Walk daily candles from k_in. exit_fn(j) -> ('open'|'close', price) or None,
    checked after the stop. Returns a trade dict or None if unfinished."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    booked, done = 0.0, 0.0
    t1, t2 = entry + d * risk, entry + d * 2 * risk
    for j in range(k_in, len(db)):
        b = db[j]
        if j > k_in:
            x = exit_fn(j, "open") if exit_fn else None
            if x is not None:
                return fin(db, k_sig, k_in, j, d, entry, risk, booked, done, x, at_open=True)
        hit = b["l"] <= stop if d == 1 else b["h"] >= stop
        if hit:
            px = min(stop, b["o"]) if d == 1 and j > k_in else max(stop, b["o"]) if d == -1 and j > k_in else stop
            return fin(db, k_sig, k_in, j, d, entry, risk, booked, done, px)
        if partial:
            if not done and (b["h"] >= t1 if d == 1 else b["l"] <= t1):
                done, booked, stop = 0.5, 0.5, entry
            if b["h"] >= t2 if d == 1 else b["l"] <= t2:
                return fin(db, k_sig, k_in, j, d, entry, risk, booked, done, t2)
        x = exit_fn(j, "close") if exit_fn else None
        if x is not None:
            return fin(db, k_sig, k_in, j, d, entry, risk, booked, done, x)
    return None


def fin(db, k_sig, k_in, j, d, entry, risk, booked, done, px, at_open=False):
    r = booked + (1 - done) * (px - entry) * d / risk - COST / risk
    return {"t": db[k_sig]["end"], "k": k_sig, "k_in": k_in, "k_out": j, "d": d, "entry": entry, "risk": risk,
            "r": r, "days": j - k_in + (0 if at_open else 1)}


# ------------------------------------------------------------------ the edges
def n1_52wk(db, atr, live_exit=False):
    c = [b["c"] for b in db]; out = []
    brk = [0] * len(db)                     # +1 / -1 on a 252-day closing high / low
    for k in range(252, len(db)):
        w = c[k - 252:k]
        brk[k] = 1 if c[k] > max(w) else -1 if c[k] < min(w) else 0
    k = 273
    while k < len(db) - 1:
        d = brk[k]
        if d:
            fresh = d not in brk[k - 20:k]
            if fresh and atr[k]:
                e = db[k + 1]["o"]; stop = e - d * 2 * atr[k]

                def ex(j, when, d=d):
                    if when != "open":
                        return None
                    w = c[j - 21:j - 1]
                    return db[j]["o"] if (c[j - 1] < min(w) if d == 1 else c[j - 1] > max(w)) else None
                t = trade(db, k, k + 1, d, e, stop, None if live_exit else ex, partial=live_exit)
                if t:
                    out.append(t); k = t["k_out"] + 1; continue
        k += 1
    return out


def n2_shock(db, atr, live_exit=False):
    c = [b["c"] for b in db]; lr = [0.0] + [math.log(c[k] / c[k - 1]) for k in range(1, len(c))]
    out = []; k = 61
    while k < len(db) - 1:
        sd = st.stdev(lr[k - 60:k])
        if atr[k] and sd > 0 and abs(lr[k]) > 2.5 * sd:
            d = 1 if lr[k] > 0 else -1
            e = db[k + 1]["o"]; stop = e - d * 2 * atr[k]
            ex = lambda j, when, k0=k + 1: (db[j]["c"] if when == "close" and j - k0 >= 4 else None)
            t = trade(db, k, k + 1, d, e, stop, None if live_exit else ex, partial=live_exit)
            if t:
                out.append(t); k = t["k_out"] + 1; continue
        k += 1
    return out


def n3_daily_ha(db, atr, live_exit=True):
    ha = S.heikin_ashi(db); c = [b["c"] for b in db]; out = []; k = 101
    while k < len(db) - 1:
        sma = sum(c[k - 99:k + 1]) / 100
        g, pg = ha[k]["c"] > ha[k]["o"], ha[k - 1]["c"] > ha[k - 1]["o"]
        d = 1 if (g and not pg and c[k] > sma) else -1 if (not g and pg and ha[k]["c"] < ha[k]["o"] and c[k] < sma) else 0
        if d and atr[k]:
            lvl = db[k]["h"] + 0.1 * atr[k] if d == 1 else db[k]["l"] - 0.1 * atr[k]
            n = db[k + 1]
            if (n["h"] >= lvl) if d == 1 else (n["l"] <= lvl):
                e = max(lvl, n["o"]) if d == 1 else min(lvl, n["o"])
                sw = db[k - 4:k + 1]
                stop = (min(b["l"] for b in sw) - 0.1 * atr[k]) if d == 1 else (max(b["h"] for b in sw) + 0.1 * atr[k])
                if (stop < e) if d == 1 else (stop > e):
                    t = trade(db, k, k + 1, d, e, stop, None, partial=True)
                    if t:
                        out.append(t); k = t["k_out"] + 1; continue
        k += 1
    return out


def n4_keltner(db, atr, live_exit=False):
    c = [b["c"] for b in db]; m = ema(c, 20); out = []; k = 21
    while k < len(db) - 1:
        if atr[k] and m[k]:
            d = 1 if c[k] > m[k] + 2 * atr[k] else -1 if c[k] < m[k] - 2 * atr[k] else 0
            if d:
                e = db[k + 1]["o"]; stop = e - d * 2 * atr[k]

                def ex(j, when, d=d):
                    if when != "open":
                        return None
                    return db[j]["o"] if ((c[j - 1] < m[j - 1]) if d == 1 else (c[j - 1] > m[j - 1])) else None
                t = trade(db, k, k + 1, d, e, stop, None if live_exit else ex, partial=live_exit)
                if t:
                    out.append(t); k = t["k_out"] + 1; continue
        k += 1
    return out


EDGES = {"N1 52-week breakout": n1_52wk, "N2 shock continuation": n2_shock,
         "N3 daily Heikin Ashi trend ride": n3_daily_ha, "N4 Keltner breakout": n4_keltner}


# ------------------------------------------------------------------ statistics
def drift(db, lo, hi):
    ch = [db[k]["c"] / db[k - 1]["c"] - 1 for k in range(1, len(db)) if lo <= db[k]["end"] < hi]
    return st.mean(ch)


def adj(t, mu):
    return t["r"] - t["d"] * mu * t["entry"] * t["days"] / t["risk"]


def tt(xs):
    if len(xs) < 3 or st.stdev(xs) == 0:
        return 0.0, 1.0
    t = st.mean(xs) / (st.stdev(xs) / math.sqrt(len(xs)))
    return t, 0.5 * math.erfc(t / math.sqrt(2))


def welch(a, b):
    if len(a) < 3 or len(b) < 3:
        return 0.0, 1.0
    t = (st.mean(a) - st.mean(b)) / math.sqrt(st.variance(a) / len(a) + st.variance(b) / len(b))
    return t, 0.5 * math.erfc(t / math.sqrt(2))


def judge(trades, lo, hi, mu):
    g = [t for t in trades if lo <= t["t"] < hi]
    if not g:
        return {"n": 0, "raw": 0, "adj": 0, "t": 0, "p": 1, "win": 0, "long": 0, "short": 0}
    a = [adj(t, mu) for t in g]; t, p = tt(a)
    return {"n": len(g), "raw": st.mean(t["r"] for t in g), "adj": st.mean(a), "t": t, "p": p,
            "win": 100 * sum(x["r"] > 0 for x in g) / len(g),
            "long": sum(x["d"] == 1 for x in g), "short": sum(x["d"] == -1 for x in g),
            "years": sorted({x["t"].year for x in g}),
            "yrs_pos": sum(st.mean(adj(x, mu) for x in g if x["t"].year == y) > 0 for y in {x["t"].year for x in g})}


def line(s):
    return (f"n={s['n']} ({s['long']}L/{s['short']}S) raw {s['raw']:+.3f}R adj {s['adj']:+.3f}R win {s['win']:.0f}% "
            f"t={s['t']:+.2f} p={s['p']:.2g} yrs+ {s.get('yrs_pos', 0)}/{len(s.get('years', []))}")


# ------------------------------------------------------------------ main
def main():
    global COST
    bars = load_all()
    F = S.Features(bars, S.CONFIG)
    db = F.daily
    print(f"{len(bars):,} hourly candles -> {len(db):,} daily candles, {db[0]['end']:%Y-%m-%d} -> {db[-1]['end']:%Y-%m-%d}")
    atr = wilder_atr(db, 20)
    mu = {"dev": drift(db, *DEV), "conf": drift(db, *CONF)}
    print(f"gold's drift: {mu['dev'] * 1e4:+.2f} bp/day 2004-15, {mu['conf'] * 1e4:+.2f} bp/day 2016-26\n")
    rows, survivors = [], []
    print("STAGE 1")
    for name, fn in EDGES.items():
        tr = fn(db, atr)
        sd, sc = judge(tr, *DEV, mu["dev"]), judge(tr, *CONF, mu["conf"])
        ok1 = sd["n"] >= 60 and sd["adj"] > 0 and sd["p"] < A1 and sd["raw"] > 0
        ok2 = ok1 and sc["adj"] > 0 and sc["p"] < 0.05 and sc["raw"] > 0
        print(f"  {name}\n     2004-15: {line(sd)} | {'pass' if ok1 else 'fail'}\n     2016-26: {line(sc)} | "
              f"{'CONFIRMED' if ok2 else ('fail' if ok1 else 'not judged (failed search)')}")
        COST = 0.70
        dbl = fn(db, atr); COST = 0.35
        print(f"     at double cost: 2004-15 adj {judge(dbl, *DEV, mu['dev'])['adj']:+.3f}R, "
              f"2016-26 adj {judge(dbl, *CONF, mu['conf'])['adj']:+.3f}R")
        rows.append({"stage": 1, "test": name, "dev_n": sd["n"], "dev_raw": round(sd["raw"], 3), "dev_adj": round(sd["adj"], 3),
                     "dev_p": f"{sd['p']:.2g}", "conf_n": sc["n"], "conf_raw": round(sc["raw"], 3),
                     "conf_adj": round(sc["adj"], 3), "conf_p": f"{sc['p']:.2g}",
                     "verdict": "PASS" if ok2 else "fail"})
        if ok2:
            survivors.append((name, fn, tr))

    if not survivors:
        print("\nNo new edge survived Stage 1; Stage 2 not run.")
    gold_live = None
    for name, fn, tr in survivors:
        print(f"\nSTAGE 2 on {name}")
        h4idx = {}
        hj = -1
        for k, b in enumerate(db):
            while hj + 1 < len(F.h4) and F.h4[hj + 1]["end"] <= b["end"]:
                hj += 1
            h4idx[k] = hj
        closes = [b["c"] for b in db]

        def daily_trend(t):
            return S.daily_trend(db[:t["k"] + 1], S.CONFIG) == t["d"]      # neutral counts as not agreeing

        def h4_ha(t):
            j = h4idx[t["k"]]
            if j < 1:
                return None
            h = F.h4_ha[j]
            return (h["c"] > h["o"]) if t["d"] == 1 else (h["c"] < h["o"])

        def cloud(t):
            return F.h4_cloud[h4idx[t["k"]]] == t["d"]                     # inside the cloud = not agreeing

        def year(t):
            k = t["k"]
            if k < 252:
                return None
            r = closes[k] / closes[k - 252] - 1
            return None if r == 0 else (r > 0) == (t["d"] == 1)

        filters = [("E1 live daily trend agrees", daily_trend), ("E2 4H Heikin Ashi agrees", h4_ha),
                   ("E3 4H Ichimoku cloud agrees", cloud), ("E4 12-month trend agrees", year)]
        kept = []
        for fname, f in filters:
            res = {}
            for per, (lo, hi), m in (("dev", DEV, mu["dev"]), ("conf", CONF, mu["conf"])):
                g = [(f(t), adj(t, m)) for t in tr if lo <= t["t"] < hi]
                a = [x for v, x in g if v is True]; b = [x for v, x in g if v is False]
                tt_, p = welch(a, b)
                res[per] = (len(a), st.mean(a) if a else 0, len(b), st.mean(b) if b else 0, p)
            n_a, m_a, n_b, m_b, p = res["dev"]
            keep = m_a > m_b and p < 0.05 and n_a >= 40
            print(f"  {fname:30s} 2004-15: {m_a:+.3f}R ({n_a}) vs {m_b:+.3f}R ({n_b}) p={p:.2g} | "
                  f"2016-26: {res['conf'][1]:+.3f}R ({res['conf'][0]}) vs {res['conf'][3]:+.3f}R ({res['conf'][2]}) "
                  f"p={res['conf'][4]:.2g} | {'kept' if keep else 'dropped'}")
            if keep:
                kept.append((fname, f, res))
        if fn is not n3_daily_ha:
            alt = fn(db, atr, live_exit=True)
            by = {t["k"]: t for t in tr}
            res = {}
            for per, (lo, hi), m in (("dev", DEV, mu["dev"]), ("conf", CONF, mu["conf"])):
                g = [adj(t, m) - adj(by[t["k"]], m) for t in alt if lo <= t["t"] < hi and t["k"] in by]
                res[per] = (len(g), st.mean(g) if g else 0, tt(g)[1])
            keep = res["dev"][1] > 0 and res["dev"][2] < 0.05 and res["dev"][0] >= 40
            print(f"  {'E5 live 1R/2R exit':30s} 2004-15: gain {res['dev'][1]:+.3f}R ({res['dev'][0]} paired) p={res['dev'][2]:.2g} | "
                  f"2016-26: gain {res['conf'][1]:+.3f}R ({res['conf'][0]}) p={res['conf'][2]:.2g} | {'kept' if keep else 'dropped'}")
            if keep:
                kept.append(("E5 live 1R/2R exit", None, {"dev": res["dev"], "conf": res["conf"], "paired": True}))
        bar = 0.05 / max(1, len(kept))
        confirmed = []
        for fname, f, res in kept:
            if res.get("paired"):
                ok = res["conf"][1] > 0 and res["conf"][2] < bar
            else:
                ok = res["conf"][1] > res["conf"][3] and res["conf"][4] < bar
            print(f"  {fname}: {'CONFIRMED' if ok else 'not confirmed'} on 2016-26 (bar p < {bar:.3g})")
            rows.append({"stage": 2, "test": f"{name} + {fname}", "verdict": "PASS" if ok else "fail"})
            if ok:
                confirmed.append((fname, f))
        final = fn(db, atr, live_exit=any(fn_ is None for _, fn_ in confirmed)) if fn is not n3_daily_ha else tr
        for fname, f in confirmed:
            if f is not None:
                final = [t for t in final if f(t) is True]
        print(f"  FINAL ({name}" + "".join(f" + {n}" for n, _ in confirmed) + ")")
        print(f"     2004-15: {line(judge(final, *DEV, mu['dev']))}\n     2016-26: {line(judge(final, *CONF, mu['conf']))}")
        if gold_live is None:
            jg = SS.replay(S.CONFIG, bars)
            gold_live = {}
            for j in jg:
                if j.get("strategy", "trend") == "trend":
                    m = datetime.fromisoformat(j["sig_time"]).strftime("%Y-%m")
                    gold_live[m] = gold_live.get(m, 0) + j["r"]
        mine = {}
        for t in final:
            m = t["t"].strftime("%Y-%m"); mine[m] = mine.get(m, 0) + t["r"]
        months = sorted(set(gold_live) | set(mine))
        xs, ys = [mine.get(m, 0) for m in months], [gold_live.get(m, 0) for m in months]
        print(f"     monthly correlation with the live gold trend trades: {st.correlation(xs, ys):+.2f}")
    json.dump(rows, open(os.path.join(HERE, "round28_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
