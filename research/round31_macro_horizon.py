"""Round 31: macro context and horizon forecasts, from an FX modeller's write-up
(pre-registered 22 Nov 2026; committed before any new data was downloaded or
any test was run).

Bradley shared a trader's account of what improved their FX models: adding
macro context to price action (US Treasury yields and their changes, inflation
expectations, major US data releases, sentiment, cross-asset moves), and
running "horizon" models that call the direction 3, 6 or 12 hours ahead
(EURUSD 3H and 6H, GBPUSD 12H), with every forecast kept in the record. He
asked for all of it to be explored for this bot. Some of it has been tested
already and is not repeated: real yields, the broad dollar (20-day), gold
volatility and futures positioning (round 20), FOMC and jobs-report timing
(round 23 E2, round 27 L6), and a learned filter built on price alone
(round 23 E7). What is new is tested here. 14 tests; bar p < 0.05 / 14.

A. Context filters on the live gold trend trades (signals.CONFIG through the
   live state machine, similar_setups.replay; signals from 2004 on gold's
   2003-26 history). Daily FRED series use the last value dated before the
   signal's UTC date (never the same day). "5-day change" = the last value
   minus the value five observations earlier.
  A1 10-year Treasury yield (DGS10) 5-day change agrees: falling for buys,
     rising for sells.
  A2 2-year Treasury yield (DGS2) 5-day change agrees, as A1.
  A3 10-year breakeven inflation (T10YIE) 5-day change agrees: rising for
     buys, falling for sells.
  A4 Fear (VIX, VIXCLS) 5-day change agrees: rising for buys, falling for sells.
  A5 Silver's last 24 hours agree with the trade (hourly XAGUSD, from 2008).
  A6 Risk-off: the S&P 500's last 24 hours moved against the trade direction
     (down for gold buys, up for gold sells; hourly, from 2011).
  A7 Big US news in the 24 hours before the signal (round 23's near()): an FOMC
     statement, a jobs report (first Friday 08:30 New York, as round 23) or a
     CPI release (08:30 New York; dates from ALFRED, the first vintage of
     CPIAUCSL that adds a new month).
  Zero changes and missing values are left out. Pass: 30+ favoured trades,
  favoured average above zero and above the rest (one-sided Welch t-test,
  p < 0.05 / 14), and favoured ahead of the rest both before and from 2015.

B. Horizon forecasts, as the write-up describes. One model, fixed in advance:
   sklearn HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05,
   max_depth=3, min_samples_leaf=500, l2_regularization=1.0, no early
   stopping, random_state=0), predicting whether the close H hours later is
   above the current close. Features at each hourly close (all known then):
     price action, multi-timeframe: returns over 1, 3, 6, 12, 24, 72, 120 bars;
       position in the 24-, 120- and 480-bar range; 24/480-bar average range
       ratio; the last closed 4H Heikin Ashi candle's colour; close against
       the 480- and 1,200-bar averages; UTC hour; weekday.
     macro (daily, last value before the UTC date): DGS10 level, 1- and 5-day
       change; DGS2 5-day change; DGS10 - DGS2; T10YIE and DFII10 5-day
       change; DTWEXBGS 5-day % change; VIX level and 5-day change; GVZCLS.
     cross-asset: 6- and 24-hour returns of gold, EURUSD, GBPUSD, USDJPY,
       silver, S&P 500 and WTI oil (the target itself excluded; missing early
       data left as missing, which the model handles).
     events: hours since the last and until the next FOMC statement, jobs
       report or CPI release (capped at 168).
   Walk-forward: for each year 2012-2026, train on every hourly close from
   2008 whose outcome was known before 1 January of that year, then forecast
   that year. Forecasts are scored on a non-overlapping grid (closes at UTC
   hours divisible by H), skipping any whose horizon has no candle in its last
   hour (weekends). Score per forecast, in basis points: direction x move to
   the close H hours later, minus cost (gold $0.35, EURUSD 1.0 bp, GBPUSD
   1.2 bp, round 10's costs), minus direction x the average H-hour move over
   the scored period (so a model that is simply long a rising market gets no
   credit).
  B1 gold 3H   B2 gold 6H   B3 gold 12H
  B4 EURUSD 3H B5 EURUSD 6H B6 GBPUSD 12H   (the write-up's own three models)
  Pass: average score above zero, one-sided t-test p < 0.05 / 14, and above
  zero in both 2012-18 and 2019-26. Hit rate, the raw result and the median
  move against the forecast before the horizon (the weakness the write-up
  names) are reported but not part of the pass.
  B7 Gold trend trades signalled 2012-26 where B3's 12-hour forecast at the
     signal close agrees with the trade. Pass as the A tests, halves 2012-18
     and 2019-26.

hypotheses_tested rises by 14 (1,366 -> 1,380). A pass is a proposal to
Bradley, then a separate change checked end to end; it goes in as a shadow
(paper) strategy or an information line first, never straight to sized alerts.
"""
import json
import math
import os
import statistics as st
import sys
import urllib.parse
from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import similar_setups as SS  # noqa: E402
import round10_markets as R10  # noqa: E402
import round23_events_funding_metalabel as R23  # noqa: E402
import round28_new_edge as R28  # noqa: E402

UTC = timezone.utc
NY = R23.NY
ALPHA = 0.05 / 14
MACRO = R23.MACRO
FRED = ["DGS10", "DGS2", "T10YIE", "DFII10", "DTWEXBGS", "VIXCLS", "GVZCLS"]
HOUR = timedelta(hours=1)


# ---------------------------------------------------------------- data
def fred(sid):
    path = os.path.join(MACRO, f"{sid}.csv")
    if not os.path.exists(path):
        open(path, "w").write(R23.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"))
    days, vals = [], []
    for line in open(path).read().splitlines()[1:]:
        d, v = line.split(",")
        if v not in ("", "."):
            days.append(date.fromisoformat(d)); vals.append(float(v))
    return days, vals


def cpi_dates():
    """First ALFRED vintage of CPIAUCSL that adds a new month = the release date."""
    path = os.path.join(MACRO, "cpi_release_dates.json")
    if os.path.exists(path):
        return [date.fromisoformat(d) for d in json.load(open(path))]
    out, y, m = [], 2003, 6
    last = None
    while (y, m) <= (2026, 11):
        days = [date(y, m, d) for d in range(1, 32) if _ok(y, m, d)]
        for c0 in range(0, len(days), 10):   # ALFRED returns at most 12 vintages per request
            last = _scan(days[c0:c0 + 10], y, out, last)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    json.dump([d.isoformat() for d in out], open(path, "w"))
    return out


def _scan(days, y, out, last):
        q = urllib.parse.urlencode({"id": ",".join(["CPIAUCSL"] * len(days)),
                                    "vintage_date": ",".join(d.isoformat() for d in days),
                                    "cosd": f"{y - 1}-01-01"})
        rows = [r.split(",") for r in R23.get("https://alfred.stlouisfed.org/graph/alfredgraph.csv?" + q).splitlines()[1:]]
        for k, d in enumerate(days):
            have = [r[0] for r in rows if len(r) > k + 1 and r[k + 1] not in ("", ".")]
            newest = max(have) if have else None
            if last is not None and newest and newest > last:
                out.append(d)
            if newest:
                last = newest if last is None else max(last, newest)
        return last


def _ok(y, m, d):
    try:
        date(y, m, d); return True
    except ValueError:
        return False


class Daily:
    def __init__(self, sid):
        self.days, self.vals = fred(sid)

    def k(self, t):                      # index of the last value dated before t's UTC date
        return bisect_right(self.days, t.date() - timedelta(days=1)) - 1

    def level(self, t):
        k = self.k(t)
        return self.vals[k] if k >= 0 else None

    def chg(self, t, n, pct=False):
        k = self.k(t)
        if k < n:
            return None
        a, b = self.vals[k], self.vals[k - n]
        return (a / b - 1) * 100 if pct else a - b


class Hourly:
    """Closes by candle close time, as-of lookups that refuse stale prices."""
    def __init__(self, bars):
        self.t = [b["t"] + HOUR for b in bars]; self.c = [b["c"] for b in bars]

    def at(self, T):
        i = bisect_right(self.t, T) - 1
        return self.c[i] if i >= 0 and self.t[i] >= T - 2 * HOUR else None

    def ret(self, T, hours):
        a, b = self.at(T), self.at(T - timedelta(hours=hours))
        return None if a is None or b is None else a / b - 1


def gold_bars():
    return R28.load_all()


def hourly_markets():
    p = lambda f: os.path.join(ROOT, "data", f)
    g = [b for b in gold_bars() if b["t"].year >= 2008]
    return {"gold": g, "eurusd": R10.load(p("eurusd_h1.csv")), "gbpusd": R10.load(p("gbpusd_h1.csv")),
            "usdjpy": R10.load(p("usdjpy_h1.csv")), "silver": R10.load(p("xagusd_h1.csv")),
            "spx": R10.load(p("markets/usa500idxusd_h1.csv.gz")), "wti": R10.load(p("markets/lightcmdusd_h1.csv.gz"))}


def events():
    fomc = [date.fromisoformat(d) for f in ("fomc_dates_2003_2007.json", "fomc_dates.json")
            for d in json.load(open(os.path.join(MACRO, f)))]
    cpi = [datetime.combine(d, time(8, 30), NY).astimezone(UTC) for d in cpi_dates()]
    ev = R23.statement_times(sorted(set(fomc))) + R23.jobs_times(datetime(2003, 6, 1), datetime(2027, 12, 1)) + cpi
    return sorted(ev)


# ---------------------------------------------------------------- tests
def welch(name, tr, fn, split):
    tr = [dict(t, f=fn(t)) for t in tr]
    a = [t for t in tr if t["f"] is True]; b = [t for t in tr if t["f"] is False]
    ra, rb = [t["r"] for t in a], [t["r"] for t in b]
    if len(ra) < 2 or len(rb) < 2:
        print(f"  {name:52s} too few | fail"); return {"test": name, "verdict": "fail"}
    tt = (st.mean(ra) - st.mean(rb)) / math.sqrt(st.variance(ra) / len(ra) + st.variance(rb) / len(rb))
    p = 0.5 * math.erfc(tt / math.sqrt(2))
    half = lambda xs, lo: [t["r"] for t in xs if (t["t"] < split) == lo]
    hs = [(st.mean(half(a, lo)) if half(a, lo) else float("nan"), st.mean(half(b, lo)) if half(b, lo) else float("nan"))
          for lo in (True, False)]
    ok = len(ra) >= 30 and st.mean(ra) > 0 and st.mean(ra) > st.mean(rb) and p < ALPHA and all(x > y for x, y in hs)
    print(f"  {name:52s} favoured {st.mean(ra):+.3f}R ({len(ra)}) rest {st.mean(rb):+.3f}R ({len(rb)}) p={p:.2g} | "
          f"before {split:%Y} {hs[0][0]:+.3f}/{hs[0][1]:+.3f}, from {hs[1][0]:+.3f}/{hs[1][1]:+.3f} | {'PASS' if ok else 'fail'}")
    return {"test": name, "fav": round(st.mean(ra), 3), "n_fav": len(ra), "rest": round(st.mean(rb), 3), "n_rest": len(rb),
            "p": f"{p:.2g}", "halves": [[round(x, 3), round(y, 3)] for x, y in hs], "verdict": "PASS" if ok else "fail"}


def features(name, bars, mk, macro, ev):
    import numpy as np
    F = S.Features(bars, S.CONFIG)
    c = [b["c"] for b in bars]; h = [b["h"] for b in bars]; l = [b["l"] for b in bars]
    rng = [h[i] - l[i] for i in range(len(bars))]
    cum = [0.0]; crng = [0.0]
    for i in range(len(bars)):
        cum.append(cum[-1] + c[i]); crng.append(crng[-1] + rng[i])
    cross = {k: Hourly(v) for k, v in mk.items() if k != name}
    rows, T = [], []
    for i in range(len(bars)):
        Ti = bars[i]["t"] + HOUR
        T.append(Ti)
        if i < 1200:
            rows.append(None); continue
        r = [c[i] / c[i - k] - 1 for k in (1, 3, 6, 12, 24, 72, 120)]
        for n in (24, 120, 480):
            lo, hi = min(l[i - n + 1:i + 1]), max(h[i - n + 1:i + 1])
            r.append((c[i] - lo) / (hi - lo) if hi > lo else 0.5)
        r.append(((crng[i + 1] - crng[i - 23]) / 24) / ((crng[i + 1] - crng[i - 479]) / 480 or 1))
        hk = F.h4_idx[i]
        ha = F.h4_ha[hk] if hk >= 0 else None
        r.append(0 if not ha else (1 if ha["c"] > ha["o"] else -1))
        r += [c[i] / ((cum[i + 1] - cum[i + 1 - n]) / n) - 1 for n in (480, 1200)]
        r += [Ti.hour, Ti.weekday()]
        m = macro
        v = [m["DGS10"].level(Ti), m["DGS10"].chg(Ti, 1), m["DGS10"].chg(Ti, 5), m["DGS2"].chg(Ti, 5),
             None if m["DGS10"].level(Ti) is None or m["DGS2"].level(Ti) is None else m["DGS10"].level(Ti) - m["DGS2"].level(Ti),
             m["T10YIE"].chg(Ti, 5), m["DFII10"].chg(Ti, 5), m["DTWEXBGS"].chg(Ti, 5, pct=True),
             m["VIXCLS"].level(Ti), m["VIXCLS"].chg(Ti, 5), m["GVZCLS"].level(Ti)]
        for k in sorted(cross):
            v += [cross[k].ret(Ti, 6), cross[k].ret(Ti, 24)]
        j = bisect_right(ev, Ti)
        v += [min(168, (Ti - ev[j - 1]).total_seconds() / 3600) if j else 168,
              min(168, (ev[j] - Ti).total_seconds() / 3600) if j < len(ev) else 168]
        rows.append(r + [np.nan if x is None else x for x in v])
    return rows, T


def horizon(name, bars, rows, T, H, cost_bp):
    """Walk-forward forecasts; returns scored grid forecasts and all-hour probabilities."""
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    hz = Hourly(bars)
    fut, mae = [None] * len(bars), [None] * len(bars)
    for i in range(len(bars)):
        p0 = bars[i]["c"]; pH = hz.at(T[i] + timedelta(hours=H))
        if pH is None or hz.t[bisect_right(hz.t, T[i] + timedelta(hours=H)) - 1] < T[i] + timedelta(hours=H - 1):
            continue
        fut[i] = pH / p0 - 1
        j = bisect_right(hz.t, T[i] + timedelta(hours=H))
        seg = bars[i + 1:j]
        mae[i] = (min(b["l"] for b in seg) / p0 - 1, max(b["h"] for b in seg) / p0 - 1) if seg else (0.0, 0.0)
    prob, out = {}, []
    for Y in range(2012, 2027):
        y0 = datetime(Y, 1, 1, tzinfo=UTC)
        tr = [i for i in range(len(bars)) if rows[i] is not None and fut[i] not in (None, 0.0)
              and T[i] + timedelta(hours=H) < y0]
        te = [i for i in range(len(bars)) if rows[i] is not None and y0 <= T[i] < datetime(Y + 1, 1, 1, tzinfo=UTC)]
        if not tr or not te:
            continue
        mdl = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, min_samples_leaf=500,
                                             l2_regularization=1.0, early_stopping=False, random_state=0)
        Xtr = np.array([rows[i] for i in tr], float)
        # a column with no data yet in the training years (S&P 500 and oil start in 2012) is dropped for that year
        keep = [j for j in range(Xtr.shape[1]) if len(np.unique(Xtr[~np.isnan(Xtr[:, j]), j])) > 1]
        mdl.fit(Xtr[:, keep], np.array([fut[i] > 0 for i in tr]))
        pr = mdl.predict_proba(np.array([rows[i] for i in te], float)[:, keep])[:, 1]
        for i, p in zip(te, pr):
            prob[T[i]] = p
            if fut[i] is None or T[i].hour % H:
                continue
            d = 1 if p > 0.5 else -1
            cb = cost_bp(bars[i]["c"])
            adverse = -mae[i][0] if d == 1 else mae[i][1]
            out.append({"t": T[i], "d": d, "move": fut[i] * 1e4, "cost": cb, "against": max(0.0, adverse) * 1e4})
        print(f"    {name} {H}H {Y}: trained on {len(tr):,}, forecast {len(te):,}", flush=True)
    mu = st.mean(o["move"] for o in out)
    for o in out:
        o["raw"] = o["d"] * o["move"] - o["cost"]; o["s"] = o["raw"] - o["d"] * mu
    return out, prob


def judge_h(name, out):
    s = [o["s"] for o in out]
    m, sd = st.mean(s), st.stdev(s)
    t = m / (sd / math.sqrt(len(s))); p = 0.5 * math.erfc(t / math.sqrt(2))
    cut = datetime(2019, 1, 1, tzinfo=UTC)
    a = [o["s"] for o in out if o["t"] < cut]; b = [o["s"] for o in out if o["t"] >= cut]
    hit = 100 * sum(o["d"] * o["move"] > 0 for o in out) / len(out)
    ok = m > 0 and p < ALPHA and st.mean(a) > 0 and st.mean(b) > 0
    yrs = {}
    for o in out:
        yrs.setdefault(o["t"].year, []).append(o["s"])
    print(f"  {name:22s} n={len(s):,} hit {hit:.1f}% raw {st.mean(o['raw'] for o in out):+.2f} bp, drift-adj {m:+.2f} bp "
          f"t={t:+.2f} p={p:.2g} | 2012-18 {st.mean(a):+.2f}, 2019-26 {st.mean(b):+.2f} | "
          f"median move against first {st.median(o['against'] for o in out):.1f} bp | "
          f"years + {sum(st.mean(v) > 0 for v in yrs.values())}/{len(yrs)} | {'PASS' if ok else 'fail'}")
    return {"test": name, "n": len(s), "hit": round(hit, 1), "raw_bp": round(st.mean(o["raw"] for o in out), 2),
            "adj_bp": round(m, 2), "p": f"{p:.2g}", "h1": round(st.mean(a), 2), "h2": round(st.mean(b), 2),
            "median_against_bp": round(st.median(o["against"] for o in out), 1),
            "years": {y: round(st.mean(v), 2) for y, v in sorted(yrs.items())}, "verdict": "PASS" if ok else "fail"}


def main():
    rows = []
    macro = {s: Daily(s) for s in FRED}
    ev = events()
    gold = gold_bars()
    mk = hourly_markets()
    silver, spx = Hourly(mk["silver"]), Hourly(mk["spx"])
    jr = SS.replay(S.CONFIG, gold)
    tr = [{"t": datetime.fromisoformat(j["sig_time"]), "d": j["dir"], "r": j["r"]} for j in jr
          if j.get("strategy", "trend") == "trend" and datetime.fromisoformat(j["sig_time"]) >= datetime(2004, 1, 1, tzinfo=UTC)]
    print(f"A. {len(tr)} gold trend trades 2004-26, average {st.mean(t['r'] for t in tr):+.3f}R")
    sp = datetime(2015, 1, 1, tzinfo=UTC)

    def agree(series, n, falling_for_buys):
        def f(t):
            c = macro[series].chg(t["t"], n)
            if c is None or c == 0:
                return None
            return ((c < 0) if falling_for_buys else (c > 0)) == (t["d"] == 1)
        return f

    def hr(h, opposite):
        def f(t):
            r = h.ret(t["t"], 24)
            if r is None or r == 0:
                return None
            return ((r < 0) if opposite else (r > 0)) == (t["d"] == 1)
        return f

    rows.append(welch("A1 10-year yield 5-day change agrees", tr, agree("DGS10", 5, True), sp))
    rows.append(welch("A2 2-year yield 5-day change agrees", tr, agree("DGS2", 5, True), sp))
    rows.append(welch("A3 10-year breakeven inflation agrees", tr, agree("T10YIE", 5, False), sp))
    rows.append(welch("A4 VIX 5-day change agrees", tr, agree("VIXCLS", 5, False), sp))
    rows.append(welch("A5 silver's last 24h agrees", tr, hr(silver, False), sp))
    rows.append(welch("A6 S&P 500 last 24h risk-off", tr, hr(spx, True), sp))
    rows.append(welch("A7 FOMC/jobs/CPI in the 24h before", tr,
                      lambda t: R23.near(ev, t["t"], timedelta(hours=24), timedelta(0)), sp))

    print("\nB. Horizon forecasts, walk-forward 2012-26")
    gold_cost = lambda p: 0.35 / p * 1e4
    probs = {}
    for test, name, H, cost in [("B1 gold 3H", "gold", 3, gold_cost), ("B2 gold 6H", "gold", 6, gold_cost),
                                ("B3 gold 12H", "gold", 12, gold_cost), ("B4 EURUSD 3H", "eurusd", 3, lambda p: 1.0),
                                ("B5 EURUSD 6H", "eurusd", 6, lambda p: 1.0), ("B6 GBPUSD 12H", "gbpusd", 12, lambda p: 1.2)]:
        if name not in probs:
            probs[name] = features(name, mk[name], mk, macro, ev)
        X, T = probs[name]
        out, prob = horizon(name, mk[name], X, T, H, cost)
        rows.append(judge_h(test, out))
        if test.startswith("B3"):
            g12 = prob
    tr12 = [t for t in tr if t["t"] >= datetime(2012, 1, 1, tzinfo=UTC)]
    rows.append(welch("B7 gold trend, 12H forecast agrees", tr12,
                      lambda t: None if t["t"] not in g12 else (g12[t["t"]] > 0.5) == (t["d"] == 1),
                      datetime(2019, 1, 1, tzinfo=UTC)))
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round31_results.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
