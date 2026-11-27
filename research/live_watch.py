"""Live watch: do the research near misses hold up on live gold trend trades?
(rules fixed 27 Nov 2026, before any trade they will judge was signalled)

Four leads looked good on history but ran out of untouched data to prove
themselves. History can't settle them any more; live trades can. This script
tags every live gold trend trade with each lead, using only information that
was public before the trade's signal, and compares tagged with untagged trades.
It reads the live record and never touches the alerts. Nothing here is posted
to Discord: the research side stays private.

Trades: rows of data/outcomes.csv with strategy "trend" and sig_time on or
after 28 Nov 2026 00:00 UTC. Earlier live trades fall inside the data the
research used and are left out.

  W1 GLD flows (round 37 T1, +0.26R vs +0.01R on 2008-26): the trade agrees
     with the sign of the change in GLD's tonnes over the last 5 published
     days; a day's figure counts from 12:00 UTC the next calendar day. Zero
     flow is left out.
  W2 After the news (round 23 E2, +0.60R vs +0.16R): the signal closes within
     24 hours after an FOMC statement (14:00 New York, data/macro/fomc_dates.json)
     or a jobs report (first Friday, 08:30 New York).
  W3 The year agrees (round 25 Q1, +0.24R vs +0.09R): the trade's direction
     matches the sign of gold's return over the previous 252 daily closes
     (the last hourly close of each UTC date, days finished before the signal).
     Left empty when the history file ends more than 4 days before the signal.
  W4 Volume dried up (round 41 Q3, +0.43R vs +0.19R): the mean COMEX volume
     (Yahoo GC=F daily, from 1 June 2020) of the last 5 valid days is under 0.8
     times the mean of the 60 valid days before them. A day is valid when its
     volume is above zero and between 0.3 and 4 times the median of the
     previous 20 valid days; a day's volume counts from 17:00 New York.

Review, fixed now: when 40 live trend trades have closed (roughly a year at the
current rate), each lead is read once. It holds if both groups have at least 8
trades and the tagged trades average more than the rest; otherwise it is
dropped. Forty trades cannot prove an edge, so a lead that holds is not added
to the alerts by this check: it goes to Bradley as the case for a decision,
with the historical and live results side by side. Until then the report is
for watching only, and no lead is judged early.

Usage: python3 research/live_watch.py  (writes research/live_watch.md)
GLD and Yahoo files are cached in gitignored paths because their terms bar
redistribution and the repo is public.
"""
import bisect
import csv
import io
import json
import os
import re
import statistics as st
import sys
import urllib.request
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
import signals as S  # noqa: E402

UTC, NY = timezone.utc, ZoneInfo("America/New_York")
START = datetime(2026, 11, 28, tzinfo=UTC)
REVIEW_AT, MIN_GROUP = 40, 8
DATA = os.path.join(ROOT, "data")
GLD_CSV = os.path.join(DATA, "macro", "gld_holdings.csv")
GLD_URL = "https://api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en"
VOL_CSV = os.path.join(DATA, "volume", "gc_daily_yahoo.csv")
VOL_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?period1=946684800&period2={}&interval=1d"
VOL_START = date(2020, 6, 1)
OUT = os.path.join(HERE, "live_watch.md")
LEADS = [("W1", "Trade agrees with the last 5 days of GLD flows", "+0.26R vs +0.01R (2008-26)"),
         ("W2", "Signal within 24h after FOMC or a jobs report", "+0.60R vs +0.16R (2008-26)"),
         ("W3", "Trade agrees with gold's 12-month return", "+0.24R vs +0.09R (2008-26)"),
         ("W4", "COMEX volume dried up over the last 5 days", "+0.43R vs +0.19R (Sep 2020-26)")]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=120).read()


def stale(path, newest):
    """True when the cached file is missing or ends before `newest` (a date)."""
    if not os.path.exists(path):
        return True
    with open(path) as f:
        last = f.read().strip().splitlines()[-1].split(",")[0]
    try:
        return date.fromisoformat(last) < newest
    except ValueError:
        return True


# ----------------------------------------------------------------- inputs
def gld(newest):
    """[(date, tonnes)], refreshed from SPDR's archive when the cache is behind."""
    if stale(GLD_CSV, newest):
        z = zipfile.ZipFile(io.BytesIO(fetch(GLD_URL)))
        ss = [re.sub(r"<[^>]+>", "", s) for s in
              re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)]
        rows = []
        for r in re.findall(r"<row[^>]*>(.*?)</row>", z.read("xl/worksheets/sheet2.xml").decode(), re.S):
            rows.append([ss[int(v)] if 't="s"' in a else v
                         for a, v in re.findall(r"<c ([^>]*)>(?:<f>.*?</f>)?<v>(.*?)</v>", r)])
        di, ti = rows[0].index("Date"), rows[0].index("Tonnes of Gold")
        out = []
        for c in rows[1:]:
            try:
                out.append((datetime.strptime(c[di], "%d-%b-%Y").date(), float(c[ti])))
            except (ValueError, IndexError):
                continue
        os.makedirs(os.path.dirname(GLD_CSV), exist_ok=True)
        with open(GLD_CSV, "w") as f:
            f.write("date,tonnes\n" + "".join(f"{d},{t}\n" for d, t in sorted(out)))
    with open(GLD_CSV) as f:
        return sorted((date.fromisoformat(r["date"]), float(r["tonnes"])) for r in csv.DictReader(f))


def news_times():
    fomc = [date.fromisoformat(d) for d in json.load(open(os.path.join(DATA, "macro", "fomc_dates.json")))]
    out = [datetime.combine(d, time(14), NY).astimezone(UTC) for d in fomc]
    for y in range(2026, 2030):
        for m in range(1, 13):
            d = date(y, m, 1)
            d += timedelta(days=(4 - d.weekday()) % 7)
            out.append(datetime.combine(d, time(8, 30), NY).astimezone(UTC))
    return sorted(out)


def volume(newest):
    """[(known-from time, volume or None)], refreshed from Yahoo when behind."""
    if stale(VOL_CSV, newest):
        d = json.loads(fetch(VOL_URL.format(int(datetime.now(UTC).timestamp()))))["chart"]["result"][0]
        os.makedirs(os.path.dirname(VOL_CSV), exist_ok=True)
        with open(VOL_CSV, "w") as f:
            f.write("date,volume\n")
            for ts, v in zip(d["timestamp"], d["indicators"]["quote"][0]["volume"]):
                f.write(f"{datetime.fromtimestamp(ts, NY).date()},{v or 0}\n")
    out, valid = [], []
    with open(VOL_CSV) as f:
        for r in csv.DictReader(f):
            day = date.fromisoformat(r["date"])
            if day < VOL_START:
                continue
            v = float(r["volume"])
            ok = v > 0 and (len(valid) < 20 or 0.3 * st.median(valid[-20:]) <= v <= 4 * st.median(valid[-20:]))
            out.append((datetime.combine(day, time(17), NY).astimezone(UTC), v if ok else None))
            if ok:
                valid.append(v)
    return out


# ----------------------------------------------------------------- tags
def tagger():
    trades = []
    with open(os.path.join(DATA, "outcomes.csv")) as f:
        for r in csv.DictReader(f):
            if r["strategy"] != "trend" or not r["r"]:
                continue
            t = datetime.fromisoformat(r["sig_time"])
            if t >= START:
                trades.append({"t": t, "dir": int(r["dir"]), "r": float(r["r"])})
    newest = max((tr["t"].date() for tr in trades), default=START.date()) - timedelta(days=1)

    tonnes = gld(newest) if trades else []
    g_avail = [datetime.combine(d + timedelta(days=1), time(12), UTC) for d, _ in tonnes]
    news = news_times()
    closes = {}
    for b in S.load_history(S.CONFIG):
        closes[b["t"].date()] = (b["t"] + timedelta(hours=1), b["c"])
    days = sorted(closes.items())
    vol = volume(newest) if trades else []
    v_known = [t for t, _ in vol]

    def w1(tr):
        k = bisect.bisect_right(g_avail, tr["t"]) - 1
        if k < 5:
            return None
        flow = tonnes[k][1] - tonnes[k - 5][1]
        return None if flow == 0 else (flow > 0) == (tr["dir"] == 1)

    def w2(tr):
        i = bisect.bisect_left(news, tr["t"] - timedelta(hours=24))
        return i < len(news) and news[i] <= tr["t"]

    def w3(tr):
        done = [(d, c) for d, (end, c) in days if d < tr["t"].date() and end <= tr["t"]]
        if len(done) < 253 or (tr["t"].date() - done[-1][0]).days > 4:
            return None                 # history too short or not updated up to the signal
        done = [c for _, c in done]
        return (done[-1] > done[-253]) == (tr["dir"] == 1)

    def w4(tr):
        k = bisect.bisect_right(v_known, tr["t"]) - 1
        hist = [v for _, v in vol[:k + 1] if v is not None]
        if len(hist) < 65:
            return None
        return st.mean(hist[-5:]) / st.mean(hist[-65:-5]) < 0.8

    for tr in trades:
        for name, fn in zip(("W1", "W2", "W3", "W4"), (w1, w2, w3, w4)):
            try:
                tr[name] = fn(tr)
            except Exception:           # a missing input leaves the tag empty
                tr[name] = None
    return trades


def report(trades):
    n = len(trades)
    lines = ["# Live watch: research near misses on live gold trend trades", "",
             f"Updated {datetime.now(UTC):%d %b %Y %H:%M} UTC by `research/live_watch.py`. Rules and the review point "
             f"are in the script's docstring, fixed on 27 Nov 2026. Trend trades signalled from 28 Nov 2026: "
             f"**{n} closed**, review at {REVIEW_AT}.", "",
             "Not for Discord. Nothing here changes the alerts.", "",
             "| Lead | History | Tagged | Untagged | Live difference |",
             "|---|---|---|---|---|"]
    for code, name, hist in LEADS:
        a = [tr["r"] for tr in trades if tr.get(code) is True]
        b = [tr["r"] for tr in trades if tr.get(code) is False]
        fmt = lambda x: f"{st.mean(x):+.2f}R ({len(x)})" if x else "none yet"
        diff = f"{st.mean(a) - st.mean(b):+.2f}R" if a and b else "n/a"
        lines.append(f"| {code} {name} | {hist} | {fmt(a)} | {fmt(b)} | {diff} |")
    if n >= REVIEW_AT:
        lines += ["", f"**Review point reached.** Per the fixed rule, a lead holds if both groups have at least "
                  f"{MIN_GROUP} trades and the tagged trades average more than the rest. Bradley decides what follows."]
    else:
        lines += ["", f"{REVIEW_AT - n} more trades before the review. No lead is judged early."]
    if trades:
        lines += ["", "| Signal (UTC) | Dir | R | W1 | W2 | W3 | W4 |", "|---|---|---|---|---|---|---|"]
        mark = {True: "yes", False: "no", None: "–"}
        for tr in trades:
            lines.append(f"| {tr['t']:%Y-%m-%d %H:%M} | {'buy' if tr['dir'] == 1 else 'sell'} | {tr['r']:+.2f} | "
                         + " | ".join(mark[tr.get(c)] for c in ("W1", "W2", "W3", "W4")) + " |")
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:14]))


if __name__ == "__main__":
    report(tagger())
