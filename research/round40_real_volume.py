"""Round 40: real COMEX gold futures volume (pre-registered 27 Nov 2026, before
the volume series was saved or joined to any trade; the only contact with it
was a row count to confirm Yahoo serves daily GC=F volume from 2000).

Round 18 tested volume with Dukascopy's proxy volume, which is the broker's own
flow, not the exchange's, and found nothing. Bradley asked what data would
improve the edge; real gold futures volume is the one input the research could
not get. Yahoo Finance serves the continuous front-month COMEX gold future
(GC=F) with real exchange volume on daily candles from 2000, free. This round
re-runs round 18's two gold volume tests on it and adds one new idea. Three
tests; hypotheses_tested rises from 1,415 to 1,418 and the bar is p < 0.05 / 3.

Volume. Daily GC=F candles from Yahoo's chart API (2000-01-01 to now), saved
to data/volume/gc_daily_yahoo.csv. A day's volume is known from 17:00 New York
time on its date (the COMEX session close). GC=F is a rolling front-month
series, so its volume jumps around contract rolls; to keep those artefacts out,
a day whose volume is below 0.3 or above 4 times the median of the previous 20
valid days is marked invalid, as is any zero-volume day. A measure that needs
an invalid day is missing, and trades without the measure are left out.

Trades: every gold trend trade and every gold inside-day trade the live state
machine takes (research/similar_setups.replay with signals.CONFIG), 2008-26
from the live history files and 2004-07 from round 27's sealed file. A trade
uses the last valid volume day whose 17:00 New York close is at or before its
sig_time.

  Q1 Volume confirms the trend (round 18's V2 on real volume). RVOL is that
     day's volume divided by the mean of the previous 20 valid days. Group:
     trend trades with RVOL >= 1.0. Expected: the group does better.
  Q2 Quiet inside days (round 18's V4 on real volume). Group: inside-day
     trades whose inside day (the last volume day before the signal) has
     RVOL < 1.0. Expected: the group does better.
  Q3 Volume dries up before the trend resumes (new). Dry-up = the mean volume
     of the last 5 valid days divided by the mean of the 60 valid days before
     those 5. Group: trend trades with dry-up < 0.8. Expected: the group does
     better.

Pass (each test): the difference in average R (group minus the rest) has the
expected sign, a two-sided Welch p < 0.05 / 3 on 2008-26, and the same sign in
every period where the group has at least 20 trades, among 2008-15, 2016-24,
2025-26 and 2004-07. The 20-trade minimum replaces the 5 used in rounds 37-39,
decided on 27 Nov 2026 before this round (five trades let noise veto a result)
and applied from this round on.

A pass goes to Bradley as a proposal; nothing changes the live alerts without
his decision and a separate end-to-end-checked change. Research only: the
hypotheses_tested counter in signals.py is not touched.
"""
import bisect
import csv
import json
import os
import statistics as st
import sys
import urllib.request
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import similar_setups as SS  # noqa: E402
import round37_new_inputs as R37  # noqa: E402

UTC, NY = timezone.utc, ZoneInfo("America/New_York")
ALPHA = 0.05 / 3
MIN_N = 20
D = lambda y: datetime(y, 1, 1, tzinfo=UTC)
PERIODS = R37.PERIODS + [R37.OLD]
VOL_CSV = os.path.join(ROOT, "data", "volume", "gc_daily_yahoo.csv")
URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?period1=946684800&period2={}&interval=1d"


# ----------------------------------------------------------------- data
def volume_days():
    """[(known-from UTC time, volume or None if invalid)] in date order."""
    if not os.path.exists(VOL_CSV):
        req = urllib.request.Request(URL.format(int(datetime.now(UTC).timestamp())), headers={"User-Agent": "Mozilla/5.0"})
        d = json.load(urllib.request.urlopen(req, timeout=60))["chart"]["result"][0]
        os.makedirs(os.path.dirname(VOL_CSV), exist_ok=True)
        with open(VOL_CSV, "w") as f:
            f.write("date,volume\n")
            for ts, v in zip(d["timestamp"], d["indicators"]["quote"][0]["volume"]):
                day = datetime.fromtimestamp(ts, NY).date()
                f.write(f"{day},{v or 0}\n")
    rows = []
    with open(VOL_CSV) as f:
        for r in csv.DictReader(f):
            day = datetime.fromisoformat(r["date"]).date()
            rows.append((datetime.combine(day, time(17), NY).astimezone(UTC), float(r["volume"])))
    out, valid = [], []
    for t, v in rows:
        ok = v > 0
        if ok and len(valid) >= 20:
            med = st.median(valid[-20:])
            ok = 0.3 * med <= v <= 4 * med
        out.append((t, v if ok else None))
        if ok:
            valid.append(v)
    return out


def measures(days):
    """{known-from time: (rvol or None, dry-up or None)} for each day."""
    out, hist = {}, []          # hist: previous valid volumes
    for t, v in days:
        rvol = dry = None
        if v is not None:
            if len(hist) >= 20:
                rvol = v / st.mean(hist[-20:])
            last5 = (hist + [v])[-5:]
            prior = (hist + [v])[-65:-5]
            if len(prior) == 60:
                dry = st.mean(last5) / st.mean(prior)
            hist.append(v)
        out[t] = (rvol, dry)
    return out


# ----------------------------------------------------------------- trades
def trades(cfg, bars, lo, hi, strategy):
    out = []
    for j in SS.replay(cfg, bars):
        if j.get("strategy", "trend") != strategy or not j.get("entry_time"):
            continue
        t0 = datetime.fromisoformat(j["sig_time"])
        if lo <= t0 < hi:
            out.append({"t": t0, "r": j["r"]})
    return out


def judge(name, trs, pred):
    g = {}
    for tr in trs:
        flag = pred(tr)
        if flag is None:
            continue
        pn = next((p for p, lo, hi in PERIODS if lo <= tr["t"] < hi), None)
        a, b = g.setdefault(pn, ([], []))
        (a if flag else b).append(tr["r"])
    a = [r for p, _, _ in R37.PERIODS for r in g.get(p, ([], []))[0]]
    b = [r for p, _, _ in R37.PERIODS for r in g.get(p, ([], []))[1]]
    diff, t, p = R37.welch(a, b)
    same, parts = diff > 0, []
    for pn, _, _ in PERIODS:
        ga, gb = g.get(pn, ([], []))
        if len(ga) >= MIN_N and len(gb) >= 2:
            same &= st.mean(ga) > st.mean(gb)
            parts.append(f"{pn} {st.mean(ga):+.3f} ({len(ga)}) vs {st.mean(gb):+.3f} ({len(gb)})")
        else:
            parts.append(f"{pn} n/a ({len(ga)})")
    ok = p < ALPHA and same
    left_out = len(trs) - sum(len(x) + len(y) for x, y in g.values())
    print(f"  {name}\n     2008-26: {st.mean(a):+.3f}R ({len(a)}) vs {st.mean(b):+.3f}R ({len(b)}), diff {diff:+.3f}R, "
          f"p={p:.2g} | " + " | ".join(parts) + f" | {left_out} without volume | {'PASS' if ok else 'fail'}")
    return {"test": name, "n_group": len(a), "n_rest": len(b), "group": round(st.mean(a), 3),
            "rest": round(st.mean(b), 3), "diff": round(diff, 3), "p": f"{p:.2g}", "periods": parts,
            "left_out": left_out, "verdict": "PASS" if ok else "fail"}


def main():
    cfg = S.CONFIG
    bars = S.closed_h1(S.load_history(cfg), datetime.now(UTC))
    old_bars = R37.load_csv_bars(os.path.join(ROOT, "data", "xauusd_h1_2003_2007.csv.gz"))
    days = volume_days()
    m = measures(days)
    known = [t for t, _ in days]
    bad = sum(1 for _, v in days if v is None)
    print(f"GC=F volume {known[0]:%Y-%m-%d} to {known[-1]:%Y-%m-%d}, {len(days)} days, {bad} marked invalid")

    def at(tr, k):
        i = bisect.bisect_right(known, tr["t"]) - 1
        return m[known[i]][k] if i >= 0 else None

    trend = trades(cfg, bars, D(2008), D(2030), "trend") + trades(cfg, old_bars, *R37.OLD[1:], "trend")
    inside = trades(cfg, bars, D(2008), D(2030), "inside_day") + trades(cfg, old_bars, *R37.OLD[1:], "inside_day")
    print(f"{len(trend)} trend trades, {len(inside)} inside-day trades")
    flag = lambda x, f: None if x is None else f(x)
    rows = [judge("Q1 trend trade, RVOL >= 1.0 (volume confirms)", trend, lambda tr: flag(at(tr, 0), lambda x: x >= 1.0)),
            judge("Q2 inside-day trade, RVOL < 1.0 (quiet inside day)", inside, lambda tr: flag(at(tr, 0), lambda x: x < 1.0)),
            judge("Q3 trend trade, 5-day volume < 0.8x the prior 60 (dry-up)", trend, lambda tr: flag(at(tr, 1), lambda x: x < 0.8))]
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round40_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
