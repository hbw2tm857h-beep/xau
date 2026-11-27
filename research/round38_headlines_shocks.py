"""Round 38: headline posts, the size of the news surprise, and shock hours
(pre-registered 27 Nov 2026, before the post archives were downloaded and before
any of these splits was looked at).

Bradley asked for ideas from r/algotrading (27 Nov 2026 scrape). Two posts there
reported intraday systems losing on days a presidential post or headline moved
the market (the "TACO tracker" post and a gold scalper hurt by Iran news), and
round 23's near miss E2 (gold trend signals within 24h after an FOMC statement
or jobs report made +0.60R against +0.16R, but only 40 trades) raised the
question of whether the size of the surprise is what matters. The plan was an
economic-calendar scrape with consensus forecasts, but the only Apify source
charges $0.01 a row, so the surprise is measured from gold's own reaction in
the release hour instead, which needs no new data. Three tests;
hypotheses_tested rises from 1,408 to 1,411 and the bar is p < 0.05 / 3.

Trades: every gold trend trade the live state machine takes
(research/similar_setups.replay with signals.CONFIG), 2008-26 from the live
history files and 2004-07 from round 27's sealed file, exactly as round 37.
A trade's time is its sig_time, the close of the signal candle.

  N1 Headline posts. Posts from Donald Trump's accounts: the UNC
     Trump_Tweets_Example archive (Twitter and Truth Social, 2009 to 8 Jan
     2026) and the stiles trump-truth-social-archive (Truth Social to date),
     both downloaded at run time into data/macro/ and never committed. A post
     is market-relevant when its text matches, case-insensitive on word
     boundaries: tariff(s), trade war, trade deal, China, Chinese, Xi, Federal
     Reserve, the Fed, Powell, interest rate(s), rate cut(s), Iran, North
     Korea, war, missile(s), sanction(s), dollar, gold, oil, OPEC, Russia,
     Ukraine. Reposts are kept. Only trades signalled while he was president
     and posting are used: 20 Jan 2017 to 8 Jan 2021 (term 1) and from
     20 Jan 2025 (term 2). The group is trades with a market-relevant post in
     the 2 hours before the signal (post time in (t - 2h, t]). Expected: the
     group does worse.
  N2 Size of the news surprise. Releases are FOMC statements (14:00 New York
     time, data/macro/fomc_dates*.json), jobs reports (first Friday, 08:30 New
     York, round 23's approximation) and CPI releases (08:30 New York,
     data/macro/cpi_release_dates.json), 2004-26. The reaction is the absolute
     close-to-close move of the hourly candle containing the release, divided
     by the average absolute close-to-close move of the 100 hourly candles
     before it. A release with a reaction of 3.0 or more is a big surprise. The
     group is trades signalled within 24 hours after a big-surprise release
     (release in [t - 24h, t)). Expected: the group does better.
  N3 Shock hours. The general form of N2, whatever the cause: an hourly candle
     whose absolute close-to-close move is 3.0 or more times the average of the
     previous 100. The group is trades signalled within 24 hours after the
     close of a shock candle (close in [t - 24h, t]). Expected: the group does
     better.

Pass (each test): the difference in average R (group minus the rest) has the
expected sign, a two-sided Welch p < 0.05 / 3 on the main sample, and the same
sign in every period with at least 5 trades in the group. N1's main sample is
terms 1 and 2 pooled and its periods are the two terms. N2 and N3's main sample
is 2008-26 and their periods are 2008-15, 2016-24, 2025-26 and 2004-07.

A pass goes to Bradley as a proposal; nothing changes the live alerts without
his decision and a separate end-to-end-checked change. Research only: the
hypotheses_tested counter in signals.py is not touched.

The post archives carry no licence or their own terms, so they are downloaded
at run time into data/macro/ (gitignored) and never committed; the repo is
public.
"""
import bisect
import csv
import json
import math
import os
import re
import statistics as st
import sys
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import round37_new_inputs as R37  # noqa: E402

csv.field_size_limit(10 ** 8)
UTC, NY = timezone.utc, ZoneInfo("America/New_York")
ALPHA = 0.05 / 3
D = lambda y, m=1, d=1: datetime(y, m, d, tzinfo=UTC)
MACRO = os.path.join(ROOT, "data", "macro")
POST_SOURCES = [
    ("trump_posts_unc.csv", "https://raw.githubusercontent.com/UNC-INLS560/Trump_Tweets_Example/main/trump_tweets_dataset.csv"),
    ("trump_posts_truth.csv", "https://raw.githubusercontent.com/stiles/trump-truth-social-archive/main/data/truth_archive.csv"),
]
TERMS = [("term 1", D(2017, 1, 20), D(2021, 1, 8)), ("term 2", D(2025, 1, 20), D(2030))]
WORDS = re.compile(r"\b(tariffs?|trade war|trade deal|china|chinese|xi|federal reserve|the fed|powell|interest rates?|"
                   r"rate cuts?|iran|north korea|war|missiles?|sanctions?|dollar|gold|oil|opec|russia|ukraine)\b", re.I)
SHOCK = 3.0
LOOK = 100


# ----------------------------------------------------------------- data
def fetch(name, url):
    path = os.path.join(MACRO, name)
    if not os.path.exists(path):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=300).read()
        with open(path, "wb") as f:
            f.write(data)
    return path


def parse_time(s):
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S%z", "%m-%d-%Y %H:%M:%S"):
        try:
            t = datetime.strptime(s, fmt)
            return t.astimezone(UTC) if t.tzinfo else t.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def post_times():
    """Times of market-relevant posts, sorted, from both archives."""
    out, seen = [], {}
    for name, url in POST_SOURCES:
        with open(fetch(name, url), newline="", encoding="utf-8", errors="replace") as f:
            rows = csv.DictReader(f)
            cols = rows.fieldnames
            tcol = next(c for c in cols if c.lower() in ("created_at", "date", "datetime", "timestamp", "created"))
            xcol = next(c for c in cols if c.lower() in ("text", "content", "post", "body"))
            n = m = 0
            for r in rows:
                t = parse_time(r.get(tcol) or "")
                if t is None:
                    continue
                n += 1
                if WORDS.search(r.get(xcol) or ""):
                    m += 1
                    out.append(t)
            seen[name] = (n, m, tcol, xcol)
    for name, (n, m, tcol, xcol) in seen.items():
        print(f"  {name}: {n} posts read ({tcol}, {xcol}), {m} market-relevant")
    return sorted(out)


def releases():
    fomc = [date.fromisoformat(d) for f in ("fomc_dates_2003_2007.json", "fomc_dates.json")
            for d in json.load(open(os.path.join(MACRO, f)))]
    cpi = [date.fromisoformat(d) for d in json.load(open(os.path.join(MACRO, "cpi_release_dates.json")))]
    jobs, y, m = [], 2003, 1
    while (y, m) <= (2026, 12):
        d = date(y, m, 1)
        jobs.append(d + timedelta(days=(4 - d.weekday()) % 7))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    at = lambda d, h, mi: datetime.combine(d, time(h, mi), NY).astimezone(UTC)
    return sorted({at(d, 14, 0) for d in fomc} | {at(d, 8, 30) for d in jobs + cpi})


def reactions(bars):
    """{index of hourly candle: its move / the average of the previous LOOK}."""
    out = {}
    moves = [abs(bars[i]["c"] - bars[i - 1]["c"]) if i else 0.0 for i in range(len(bars))]
    run = sum(moves[1:LOOK + 1])
    for i in range(LOOK + 1, len(bars)):
        avg = run / LOOK
        if avg > 0:
            out[i] = moves[i] / avg
        run += moves[i] - moves[i - LOOK]
    return out


# ----------------------------------------------------------------- tests
def in_window(events, lo, hi, closed_hi):
    """True if any sorted event lies in [lo, hi) or [lo, hi]."""
    i = bisect.bisect_left(events, lo)
    return i < len(events) and (events[i] <= hi if closed_hi else events[i] < hi)


def judge(name, expect, groups, periods):
    names = [p for p, _, _ in periods]
    a = [r for p in names[:-1 if len(names) > 2 else None] for r in groups.get(p, ([], []))[0]]
    b = [r for p in names[:-1 if len(names) > 2 else None] for r in groups.get(p, ([], []))[1]]
    if len(a) < 2 or len(b) < 2:
        print(f"  {name}: too few trades (group {len(a)}, rest {len(b)}) | fail")
        return {"test": name, "n_group": len(a), "n_rest": len(b), "verdict": "fail"}
    diff, t, p = R37.welch(a, b)
    same, parts = (diff > 0) == (expect > 0), []
    for pn in names:
        ga, gb = groups.get(pn, ([], []))
        if len(ga) >= 5 and len(gb) >= 5:
            same &= (st.mean(ga) - st.mean(gb) > 0) == (expect > 0)
            parts.append(f"{pn} {st.mean(ga):+.3f} ({len(ga)}) vs {st.mean(gb):+.3f} ({len(gb)})")
        else:
            parts.append(f"{pn} n/a ({len(ga)})")
    ok = p < ALPHA and same
    print(f"  {name}\n     main: {st.mean(a):+.3f}R ({len(a)}) vs {st.mean(b):+.3f}R ({len(b)}), diff {diff:+.3f}R, "
          f"p={p:.2g} | " + " | ".join(parts) + f" | {'PASS' if ok else 'fail'}")
    return {"test": name, "n_group": len(a), "n_rest": len(b), "group": round(st.mean(a), 3),
            "rest": round(st.mean(b), 3), "diff": round(diff, 3), "p": f"{p:.2g}", "periods": parts,
            "verdict": "PASS" if ok else "fail"}


def split(trades, periods, pred):
    g = {}
    for tr in trades:
        pn = next((p for p, lo, hi in periods if lo <= tr["t"] < hi), None)
        if pn is None:
            continue
        a, b = g.setdefault(pn, ([], []))
        (a if pred(tr) else b).append(tr["r"])
    return g


def main():
    cfg = S.CONFIG
    bars = S.closed_h1(S.load_history(cfg), datetime.now(UTC))
    old_bars = R37.load_csv_bars(os.path.join(ROOT, "data", "xauusd_h1_2003_2007.csv.gz"))
    _, new = R37.trend_trades(cfg, bars, D(2008), D(2030))
    _, old = R37.trend_trades(cfg, old_bars, *R37.OLD[1:])
    trades = new + old
    print(f"{len(new)} trend trades 2008-26, {len(old)} in 2004-07")
    periods = R37.PERIODS + [R37.OLD]
    h, day = timedelta(hours=1), timedelta(hours=24)

    print("N1 posts")
    posts = post_times()
    n1 = judge("N1 market-relevant post in the 2 hours before the signal", -1,
               split(trades, TERMS, lambda tr: in_window(posts, tr["t"] - 2 * h + timedelta(seconds=1), tr["t"], True)),
               TERMS)

    big, shocks = [], []
    rel = releases()
    for bb in (old_bars, bars):
        react = reactions(bb)
        opens = [b["t"] for b in bb]
        for t in rel:
            i = bisect.bisect_right(opens, t) - 1
            if i >= 0 and opens[i] <= t < opens[i] + h and react.get(i, 0) >= SHOCK:
                big.append(t)
        shocks += [bb[i]["t"] + h for i, x in react.items() if x >= SHOCK]
    big, shocks = sorted(big), sorted(shocks)
    print(f"{len(rel)} releases, {len(big)} big surprises; {len(shocks)} shock hours")
    n2 = judge("N2 signal within 24h after a big-surprise release", 1,
               split(trades, periods, lambda tr: in_window(big, tr["t"] - day, tr["t"], False)), periods)
    n3 = judge("N3 signal within 24h after a shock hour", 1,
               split(trades, periods, lambda tr: in_window(shocks, tr["t"] - day, tr["t"], True)), periods)
    rows = [n1, n2, n3]
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round38_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
