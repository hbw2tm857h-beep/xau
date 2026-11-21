"""Round 27: a second sealed test on 2004-2007 gold, a period no round has used
(pre-registered 21 Nov 2026, committed before any trade in it was simulated).

Bradley asked how the bot can be pushed further. Every round so far has used
2008-2026, so six near misses (rounds 23-25) can only be settled on data none
of them has seen. Dukascopy serves XAUUSD hourly candles from May 2003; 2003-07
were downloaded (data/xauusd_h1_2003_2007.csv.gz) and only row counts per year
were checked before this file was committed. May-Dec 2003 is warm-up only: no
trade signalled before 1 Jan 2004 counts.

Rules and costs are the live ones, unchanged: signals.CONFIG through the live
state machine (research/similar_setups.replay). Gold was $375-$840 in 2004-07,
against $800-$4,000 since 2008, so the fixed $0.35 cost and $0.30 buffers are a
larger share of price than in any period tested so far. That is deliberately
not adjusted: it makes the test harder, not easier.

Six tests; hypotheses_tested rises by 6 and the bar is p < 0.05 / 6 = 0.0083.

  L1 Gold trend rules hold: the average R of the live trend trades is above
     zero, one-sided t-test, and positive in at least 3 of the 4 years.
  L2 Gold inside-day breakout holds: as L1, for the inside-day trades.
  L3 Round 25 Q1, trade with the 12-month trend: favoured = the trade's direction
     matches the sign of gold's return over the previous 252 daily closes (as
     round 25: last hourly close of each UTC date). Pass: favoured average above
     the rest, one-sided Welch t-test, and favoured average above zero. Trades
     with fewer than 253 prior daily closes are left out.
  L4 Round 24 X1, first partial at 1.5R instead of 1R: paired per-trade gain
     above zero (round24_exits.simulate, whose base must reproduce the live R
     on every trade, or the test is void).
  L5 Round 24 X2, chandelier trail (3x hourly ATR) on the second half instead
     of the 2R target: as L4.
  L6 Round 23 E2, trends that start after big US news: favoured = an event in
     the 24 hours up to the signal time (round 23's own near()): a scheduled FOMC statement (14:00 New
     York; dates from the Federal Reserve's historical pages, fetched by the
     same parser as round 23) or a jobs report (first Friday, 08:30 New York, as
     round 23). Pass as L3.

What a pass means: L1/L2 confirm the live rules on a third independent period.
L3-L6 passing here, after their near miss on 2008-26, makes them proposals to
Bradley; nothing changes in the alerts without his decision and a separate,
end-to-end-checked change. A fail is reported as a fail.
"""
import gzip
import json
import math
import os
import re
import statistics as st
import sys
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import similar_setups as SS  # noqa: E402
import round23_events_funding_metalabel as R23  # noqa: E402
import round24_exits as R24  # noqa: E402

UTC = timezone.utc
ALPHA = 0.05 / 6
DATA = os.path.join(ROOT, "data", "xauusd_h1_2003_2007.csv.gz")
START, END = datetime(2004, 1, 1, tzinfo=UTC), datetime(2008, 1, 1, tzinfo=UTC)
YEARS = [(str(y), datetime(y, 1, 1, tzinfo=UTC), datetime(y + 1, 1, 1, tzinfo=UTC)) for y in range(2004, 2008)]


def load():
    import csv
    bars = []
    with gzip.open(DATA, "rt") as f:
        for r in csv.DictReader(f):
            t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            if h - l <= 0 and o == c:
                continue
            bars.append({"t": t, "o": o, "h": h, "l": l, "c": c})
    return bars


def fomc_2003_07():
    path = os.path.join(R23.MACRO, "fomc_dates_2003_2007.json")
    if os.path.exists(path):
        return [date.fromisoformat(d) for d in json.load(open(path))]
    out = set()
    for y in range(2003, 2008):
        for h in re.findall(r"<h5[^>]*>([^<]*)</h5>", R23.get(f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm")):
            h = " ".join(h.split())
            if "Meeting" not in h or "(" in h:
                continue
            m = re.match(r"(.+?) Meeting", h).group(1)
            mon = re.findall(r"[A-Za-z]+", m)[-1].lower()
            out.add(date(y, R23.SHORT[mon[:3]], int(re.findall(r"\d+", m)[-1])))
    dates = sorted(out)
    json.dump([d.isoformat() for d in dates], open(path, "w"))
    return dates


def one_sample(name, xs):
    m, sd = st.mean(xs), st.stdev(xs)
    t = m / (sd / math.sqrt(len(xs)))
    return m, t, 0.5 * math.erfc(t / math.sqrt(2))


def holds(name, tr):
    rs = [t["r"] for t in tr]
    m, t, p = one_sample(name, rs)
    yrs = [(pn, [t["r"] for t in tr if lo <= t["t"] < hi]) for pn, lo, hi in YEARS]
    pos = sum(st.mean(x) > 0 for _, x in yrs if x)
    win = 100 * sum(r > 0 for r in rs) / len(rs)
    ok = m > 0 and p < ALPHA and pos >= 3
    print(f"  {name:44s} n={len(rs)} avg={m:+.3f}R win={win:.0f}% total={sum(rs):+.1f}R t={t:+.2f} p={p:.2g} | "
          + " ".join(f"{pn} {st.mean(x):+.3f}({len(x)})" if x else f"{pn} -" for pn, x in yrs)
          + f" | {'PASS' if ok else 'fail'}")
    return {"test": name, "n": len(rs), "avg": round(m, 3), "win": round(win), "t": round(t, 2), "p": f"{p:.2g}",
            "years_pos": f"{pos}/4", **{pn: round(st.mean(x), 3) if x else None for pn, x in yrs},
            "verdict": "PASS" if ok else "fail"}


def split(name, tr, fn):
    tr = [dict(t, flag=fn(t)) for t in tr]
    a = [t["r"] for t in tr if t["flag"] is True]; b = [t["r"] for t in tr if t["flag"] is False]
    if len(a) < 2 or len(b) < 2:
        print(f"  {name:44s} too few (favoured {len(a)}, rest {len(b)}) | fail")
        return {"test": name, "n_fav": len(a), "n_rest": len(b), "verdict": "fail"}
    t = (st.mean(a) - st.mean(b)) / math.sqrt(st.variance(a) / len(a) + st.variance(b) / len(b))
    p = 0.5 * math.erfc(t / math.sqrt(2))
    ok = st.mean(a) > st.mean(b) and st.mean(a) > 0 and p < ALPHA
    print(f"  {name:44s} favoured n={len(a)} avg={st.mean(a):+.3f}R | rest n={len(b)} avg={st.mean(b):+.3f}R | "
          f"t={t:+.2f} p={p:.2g} | {'PASS' if ok else 'fail'}")
    return {"test": name, "n_fav": len(a), "avg_fav": round(st.mean(a), 3), "n_rest": len(b),
            "avg_rest": round(st.mean(b), 3), "t": round(t, 2), "p": f"{p:.2g}", "verdict": "PASS" if ok else "fail"}


def paired(name, gains):
    g = [x for x in gains if x is not None]
    m, t, p = one_sample(name, g)
    ok = m > 0 and p < ALPHA
    print(f"  {name:44s} n={len(g)} gain {m:+.3f}R/trade t={t:+.2f} p={p:.2g} | {'PASS' if ok else 'fail'}")
    return {"test": name, "n": len(g), "gain": round(m, 3), "t": round(t, 2), "p": f"{p:.2g}",
            "verdict": "PASS" if ok else "fail"}


def main():
    cfg = S.CONFIG
    bars = load()
    print(f"{len(bars):,} hourly candles {bars[0]['t']:%Y-%m-%d} -> {bars[-1]['t']:%Y-%m-%d}; "
          f"gold ${min(b['c'] for b in bars):.0f}-${max(b['c'] for b in bars):.0f}")
    jg = [j for j in SS.replay(cfg, bars) if START <= datetime.fromisoformat(j["sig_time"]) < END]
    trend = [j for j in jg if j.get("strategy", "trend") == "trend"]
    ib = [j for j in jg if j.get("strategy") == "inside_day"]
    T = lambda js: [{"t": datetime.fromisoformat(j["sig_time"]), "d": j["dir"], "r": j["r"]} for j in js]
    rows = [holds("L1 gold trend rules hold", T(trend)),
            holds("L2 gold inside-day holds", T(ib))]

    daily = {}
    for b in bars:
        daily[b["t"].date()] = b["c"]
    days = sorted(daily); closes = [daily[d] for d in days]
    from bisect import bisect_left

    def year_agrees(t):
        n = bisect_left(days, t["t"].date())
        if n < 253:
            return None
        r = closes[n - 1] / closes[n - 253] - 1
        return None if r == 0 else (r > 0) == (t["d"] == 1)

    rows.append(split("L3 12-month trend agrees (round 25 Q1)", T(trend), year_agrees))

    F = S.Features(bars, cfg)
    idx = {b["t"] + timedelta(hours=1): i for i, b in enumerate(bars)}
    tr, bad = [], 0
    for j in trend:
        if not j.get("entry_time"):
            continue
        idea = j["idea"]
        t = {"t": datetime.fromisoformat(j["sig_time"]), "dir": idea["dir"], "entry": idea["entry"], "stop": idea["stop"],
             "risk": idea["risk"], "r": j["r"], "k": idx[datetime.fromisoformat(j["entry_time"])],
             "sig_i": idx[datetime.fromisoformat(j["sig_time"])]}
        t["base"] = R24.simulate(bars, F.hatr, t["k"], t, cfg, "base")
        bad += t["base"] is None or abs(t["base"] - t["r"]) > 0.002
        tr.append(t)
    print(f"  (exit re-run: base differs from the live state machine on {bad} of {len(tr)} trades)")
    for name, mode in [("L4 first partial at 1.5R (round 24 X1)", "x1"), ("L5 chandelier trail (round 24 X2)", "x2")]:
        if bad:
            print(f"  {name:44s} void: base re-run does not reproduce the live rules")
            rows.append({"test": name, "verdict": "void"}); continue
        gains = []
        for t in tr:
            v = R24.simulate(bars, F.hatr, t["k"], t, cfg, mode)
            gains.append(None if v is None else v - t["base"])
        rows.append(paired(name, gains))

    events = R23.statement_times(fomc_2003_07()) + R23.jobs_times(datetime(2003, 6, 1), datetime(2008, 1, 1))
    events.sort()

    def after_news(t):
        return R23.near(events, t["t"], timedelta(hours=24), timedelta(0))   # round 23's own test

    rows.append(split("L6 signal within 24h after FOMC/jobs (round 23 E2)", T(trend), after_news))
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round27_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
