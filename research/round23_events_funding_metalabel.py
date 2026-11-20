"""Round 23: news timing, funding rates, cross-market confirmation, a session
split and a walk-forward trade filter (pre-registered 20 Nov 2026, before the
FOMC calendar and the Binance funding history were downloaded and before any of
these splits was looked at; the only contact with either source before this
commit was a three-row request to confirm the endpoints answer).

Bradley asked for a deeper, more creative search for ways to improve the system.
The ideas come from that search: the New York Fed's pre-FOMC drift (Lucca and
Moench 2015; Liberty Street Economics 2018), studies of gold around FOMC and
jobs releases (Christie-David, Chaudhry and Koch 2000; the MMU FOMC-shock
study), perpetual-futures funding (He, Manela, Ross and von Wachter, arXiv
2212.06888), the Bitcoin-Ether lead-lag literature (Mohamad, Sifat and Shariff
2019), the "Asia buys the dip, US sells the rip" description of gold's sessions
(StoneX, 16 Nov 2026) and Lopez de Prado's meta-labelling. Seven tests;
hypotheses_tested rises by 7 and the bar is p < 0.05 / 7 = 0.00714.

Event dates
  FOMC: scheduled meetings only, from the Federal Reserve's calendar pages
  (fomchistoricalYYYY.htm for 2008-2020, fomccalendars.htm after), statement at
  14:00 New York time on the meeting's last day (14:15 before 2013; the hour is
  the same for these tests). Unscheduled calls and notation votes are excluded.
  Jobs report: the first Friday of each month at 08:30 New York time. The Bureau
  of Labor Statistics sometimes moves it (shutdowns, early first Fridays); that
  approximation was fixed here before testing.

Filter tests (split an existing strategy's trades into a favoured group and the
rest; pass as rounds 20 and 21: the favoured group has 100+ trades and a positive
average in every period with 10+ trades; it beats the rest in at least three of
the periods where both have 10+ trades, at least two if only two qualify; and a
one-sided Welch t-test gives p < 0.00714):
  E1 Gold trend, no news ahead: favoured = no FOMC statement or jobs report in the
     24 hours after the signal candle closes.
  E2 Gold trend, after the news: favoured = the signal candle closes within the
     24 hours after an FOMC statement or jobs report (news-driven moves continue).
  E4 BTC/USD trend, against the funding crowd (Binance BTCUSDT perpetual funding,
     from September 2019): f = mean of the last 9 funding prints (3 days) known at
     the signal; favoured = buys when f is below the median of f over the previous
     180 days, sells when above.
  E5 ETH/USD inside-day, Bitcoin agrees: favoured = buys when BTC/USD's last close
     at the signal is above its average of the previous 480 hourly closes (20
     days), sells when below.
  E7 Gold trend, walk-forward meta-label: a logistic regression predicts whether a
     trend trade wins from five features known at the signal (24-hour and 120-hour
     moves in the trade's direction in ATR units, 24h/240h ATR ratio, distance from
     the 480-hour average in the trade's direction in ATR units, and whether the
     signal closes 07:00-16:00 UTC). For each year from 2012 it is trained only on
     trades signalled more than 30 days before that year starts; favoured = the
     predicted probability is above the median prediction on its own training set.

Standalone tests (pass: enough observations, average after costs above zero,
one-sided t-test p < 0.00714, positive in every period with 10+ observations):
  E3 Pre-FOMC drift, US indices: long the S&P 500, Nasdaq 100 and Dow from the
     close of the hourly bar starting 13:00 New York time on the trading day before
     the statement to the close of the bar starting 13:00 on statement day (shut
     before the announcement). 1 bp round-trip cost per index; one observation per
     meeting = the average over the indices with data. Needs 80+ meetings.
  E6 Gold Asia minus US: each weekday, the return from the open of the 00:00 UTC
     bar to the close of the 06:00 UTC bar, minus the return from the open of the
     13:00 UTC bar to the close of the 19:00 UTC bar, less 3.5 bp (two round trips
     at 1.75 bp). Drift-neutral: it pays only if Asia really is the stronger session.
     Needs 150+ days.

Anything that passes goes into nursery.json as a candidate. Nothing changes the
live alerts without Bradley's decision and a separate end-to-end-checked change.
"""
import json
import math
import os
import re
import statistics as st
import sys
import urllib.request
from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import round10_btc_checks as B  # noqa: E402
import round12_beyond_gold as M  # noqa: E402
import round21_positioning_and_market_filters as R21  # noqa: E402
import similar_setups as SS  # noqa: E402

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
ALPHA = 0.05 / 7
MACRO = os.path.join(ROOT, "data", "macro")
UA = {"User-Agent": "Mozilla/5.0 research"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
SHORT = {k[:3]: v for k, v in MONTHS.items()}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf8", "ignore")


# ---------------------------------------------------------------- event dates
def fomc_dates():
    """Scheduled FOMC statement dates, 2008 onward."""
    path = os.path.join(MACRO, "fomc_dates.json")
    if os.path.exists(path):
        return [date.fromisoformat(d) for d in json.load(open(path))]
    out = set()
    for y in range(2008, 2021):
        for h in re.findall(r"<h5[^>]*>([^<]*)</h5>", get(f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm")):
            h = " ".join(h.split())
            if "Meeting" not in h or "(" in h:          # unscheduled, cancelled, notation votes
                continue
            m = re.match(r"(.+?) Meeting", h).group(1)          # "July 31-August 1", "April/May 29-1"
            mon = re.findall(r"[A-Za-z]+", m)[-1].lower()       # the meeting's last month
            out.add(date(y, SHORT[mon[:3]], int(re.findall(r"\d+", m)[-1])))
    cal = get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
    parts = re.split(r'<h4[^>]*><a[^>]*>(\d{4}) FOMC Meetings', cal)
    for y, block in zip(parts[1::2], parts[2::2]):
        for mon, day in re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]*)</strong>.*?fomc-meeting__date[^>]*>([^<]*)<',
                                   block, re.S):
            if "notation" in day or "nscheduled" in day or "call" in day.lower():
                continue
            mon = mon.split("/")[-1].strip().lower()[:3]
            d = int(re.findall(r"\d+", day)[-1])
            out.add(date(int(y), SHORT[mon], d))
    dates = sorted(out)
    os.makedirs(MACRO, exist_ok=True)
    json.dump([d.isoformat() for d in dates], open(path, "w"))
    return dates


def statement_times(dates):
    return [datetime.combine(d, time(14), NY).astimezone(UTC) for d in dates]


def jobs_times(start, end):
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        d = date(y, m, 1)
        d += timedelta(days=(4 - d.weekday()) % 7)
        out.append(datetime.combine(d, time(8, 30), NY).astimezone(UTC))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def funding():
    """Binance BTCUSDT perpetual funding prints: sorted [(time, rate)]."""
    path = os.path.join(MACRO, "funding_btcusdt.json")
    if not os.path.exists(path):
        rows, t0 = [], 1567296000000
        while True:
            batch = json.loads(get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&startTime={t0}&limit=1000"))
            if not batch:
                break
            rows += [(r["fundingTime"], float(r["fundingRate"])) for r in batch]
            t0 = batch[-1]["fundingTime"] + 1
            if len(batch) < 1000:
                break
        json.dump(rows, open(path, "w"))
    return [(datetime.fromtimestamp(t / 1000, UTC), r) for t, r in json.load(open(path))]


# ---------------------------------------------------------------- judges
def split(name, trades, fn, periods):
    tr = [dict(t, flag=fn(t)) for t in trades]
    tr = [t for t in tr if t["flag"] is not None]
    a = [t for t in tr if t["flag"]]; b = [t for t in tr if not t["flag"]]
    if len(a) < 2 or len(b) < 2:
        print(f"  {name:46s} too few trades (favoured {len(a)}, rest {len(b)}) | fail")
        return {"test": name, "n_fav": len(a), "n_rest": len(b), "verdict": "fail"}
    ra, rb = [t["r"] for t in a], [t["r"] for t in b]
    tstat = (st.mean(ra) - st.mean(rb)) / math.sqrt(st.variance(ra) / len(ra) + st.variance(rb) / len(rb))
    p = 0.5 * math.erfc(tstat / math.sqrt(2))
    wins, both, pos = 0, 0, True
    for _pn, lo, hi in periods:
        xa = [t["r"] for t in a if lo <= t["t"] < hi]; xb = [t["r"] for t in b if lo <= t["t"] < hi]
        if len(xa) >= 10:
            pos = pos and st.mean(xa) > 0
        if len(xa) >= 10 and len(xb) >= 10:
            both += 1; wins += st.mean(xa) > st.mean(xb)
    need = 3 if both >= 3 else 2
    ok = len(a) >= 100 and pos and both >= 2 and wins >= need and p < ALPHA
    print(f"  {name:46s} favoured n={len(a):3d} avg={st.mean(ra):+.3f}R | rest n={len(b):3d} avg={st.mean(rb):+.3f}R | "
          f"t={tstat:+.2f} p={p:.2g} | ahead in {wins}/{both} periods | {'PASS' if ok else 'fail'}")
    return {"test": name, "n_fav": len(a), "avg_fav": round(st.mean(ra), 3), "n_rest": len(b),
            "avg_rest": round(st.mean(rb), 3), "t": round(tstat, 2), "p": f"{p:.2g}",
            "periods": f"{wins}/{both}", "verdict": "PASS" if ok else "fail"}


def alone(name, obs, need):
    x = [o["bps"] for o in obs]
    if len(x) < 3:
        print(f"  {name:46s} {len(x)} observations | fail")
        return {"test": name, "n": len(x), "verdict": "fail"}
    m, sd = st.mean(x), st.stdev(x)
    tstat = m / (sd / math.sqrt(len(x)))
    p = 0.5 * math.erfc(tstat / math.sqrt(2))
    per, pos = [], True
    for pn, lo, hi in M.PERIODS:
        y = [o["bps"] for o in obs if lo <= o["t"] < hi]
        per.append(f"{pn} {st.mean(y):+.1f} ({len(y)})" if y else f"{pn} -")
        if len(y) >= 10:
            pos = pos and st.mean(y) > 0
    ok = len(x) >= need and m > 0 and p < ALPHA and pos
    print(f"  {name:46s} n={len(x)} avg={m:+.2f}bp win={100 * sum(v > 0 for v in x) / len(x):.0f}% t={tstat:+.2f} "
          f"p={p:.2g} | " + " | ".join(per) + f" | {'PASS' if ok else 'fail'}")
    return {"test": name, "n": len(x), "avg_bp": round(m, 2), "t": round(tstat, 2), "p": f"{p:.2g}",
            "periods": per, "verdict": "PASS" if ok else "fail"}


# ---------------------------------------------------------------- helpers
def near(events, t, before, after):
    """True if any event lies in (t - before, t + after]."""
    i = bisect_right(events, t - before)
    return i < len(events) and events[i] <= t + after


def gold_features(bars):
    closes = [b["c"] for b in bars]
    tr = [bars[0]["h"] - bars[0]["l"]] + [max(b["h"], p["c"]) - min(b["l"], p["c"]) for p, b in zip(bars, bars[1:])]
    cum = np.concatenate([[0.0], np.cumsum(tr)])
    ccum = np.concatenate([[0.0], np.cumsum(closes)])
    idx = {b["t"] + timedelta(hours=1): i for i, b in enumerate(bars)}

    def feat(t, d):
        i = idx.get(t)
        if i is None or i < 480:
            return None
        a24 = (cum[i + 1] - cum[i - 23]) / 24
        a240 = (cum[i + 1] - cum[i - 239]) / 240
        avg480 = (ccum[i] - ccum[i - 480]) / 480
        c = closes[i]
        return [d * (c - closes[i - 24]) / a24, d * (c - closes[i - 120]) / a24, a24 / a240,
                d * (c - avg480) / a24, 1.0 if 7 <= t.hour <= 16 else 0.0]
    return feat


def logit_fit(X, y, l2=1.0, steps=3000, lr=0.1):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = np.hstack([np.ones((len(X), 1)), (X - mu) / sd])
    w = np.zeros(Z.shape[1])
    for _ in range(steps):
        p = 1 / (1 + np.exp(-Z @ w))
        g = Z.T @ (p - y) / len(y) + l2 * np.r_[0, w[1:]] / len(y)
        w -= lr * g
    return lambda Xn: 1 / (1 + np.exp(-np.hstack([np.ones((len(Xn), 1)), (Xn - mu) / sd]) @ w))


# ---------------------------------------------------------------- main
def main():
    rows = []
    now = datetime.now(UTC)
    gbars = S.closed_h1(S.load_history(S.CONFIG), now)
    jg = SS.replay(S.CONFIG, gbars)
    gold = [{"t": datetime.fromisoformat(j["sig_time"]), "d": j["dir"], "r": j["r"]}
            for j in jg if j.get("strategy", "trend") == "trend"]
    fomc = fomc_dates()
    print(f"FOMC statements: {len(fomc)} ({fomc[0]} to {fomc[-1]}); gold trend trades: {len(gold)}")
    news = sorted(statement_times(fomc) + jobs_times(date(2008, 1, 1), date(2026, 12, 31)))
    day = timedelta(hours=24)

    print("Gold trend: news timing")
    rows.append(split("E1 gold trend, no news in the next 24h", gold,
                      lambda t: not near(news, t["t"], timedelta(0), day), M.PERIODS))
    rows.append(split("E2 gold trend, signal within 24h after news", gold,
                      lambda t: near(news, t["t"], day, timedelta(0)), M.PERIODS))

    print("US indices: pre-FOMC drift")
    obs = []
    for d in fomc:
        prev = d - timedelta(days=1)
        while prev.weekday() >= 5:
            prev -= timedelta(days=1)
        rets = []
        for name in M.US3:
            a, b = M.at(name, NY, prev, 13), M.at(name, NY, d, 13)
            if a and b:
                rets.append(1e4 * (b["c"] / a["c"] - 1) - M.cost(name))
        if rets:
            obs.append({"t": datetime.combine(d, time(14), NY).astimezone(UTC), "bps": st.mean(rets)})
    rows.append(alone("E3 pre-FOMC drift, S&P/Nasdaq/Dow", obs, 80))

    print("Crypto: funding and cross-market confirmation")
    jb = SS.replay(S.market_cfg("btc"), B.load_247("data/markets/btcusd_h1.csv.gz"), scale=True)
    je = SS.replay(S.market_cfg("eth"), B.load_247("data/markets/ethusd_h1.csv.gz"), scale=True)
    btc = [{"t": datetime.fromisoformat(j["sig_time"]), "d": j["dir"], "r": j["r"]}
           for j in jb if j.get("strategy") == "btc_trend"]
    eth = [{"t": datetime.fromisoformat(j["sig_time"]), "d": j["dir"], "r": j["r"]}
           for j in je if j.get("strategy") == "eth_inside_day"]
    fr = funding()
    ft = [t for t, _ in fr]
    f3 = [st.mean(r for _, r in fr[max(0, i - 8):i + 1]) for i in range(len(fr))]

    def against_crowd(t):
        i = bisect_right(ft, t["t"]) - 1
        if i < 9:
            return None
        j = bisect_right(ft, t["t"] - timedelta(days=180))
        if (t["t"] - ft[0]).days < 180:
            return None
        med = st.median(f3[j:i])
        if f3[i] == med:
            return None
        return (f3[i] < med) == (t["d"] == 1)

    rows.append(split("E4 BTC/USD trend against the funding crowd", btc, against_crowd, R21.PERIODS))
    bb = B.load_247("data/markets/btcusd_h1.csv.gz")
    bt = [b["t"] + timedelta(hours=1) for b in bb]
    bc = np.concatenate([[0.0], np.cumsum([b["c"] for b in bb])])

    def btc_agrees(t):
        i = bisect_right(bt, t["t"]) - 1
        if i < 480:
            return None
        avg = (bc[i] - bc[i - 480]) / 480
        c = bb[i]["c"]
        return None if c == avg else (c > avg) == (t["d"] == 1)

    rows.append(split("E5 ETH/USD inside-day, Bitcoin agrees", eth, btc_agrees, R21.PERIODS))

    print("Gold sessions")
    by = {b["t"]: b for b in gbars}
    obs = []
    d = gbars[0]["t"].date()
    while d <= gbars[-1]["t"].date():
        if d.weekday() < 5:
            h = lambda hr: by.get(datetime.combine(d, time(hr), UTC))
            a0, a6, u13, u19 = h(0), h(6), h(13), h(19)
            if a0 and a6 and u13 and u19:
                asia = a6["c"] / a0["o"] - 1
                us = u19["c"] / u13["o"] - 1
                obs.append({"t": datetime.combine(d, time(20), UTC), "bps": 1e4 * (asia - us) - 3.5})
        d += timedelta(days=1)
    rows.append(alone("E6 gold Asia minus US session", obs, 150))

    print("Gold trend: walk-forward meta-label")
    feat = gold_features(gbars)
    data = [dict(t, x=feat(t["t"], t["d"])) for t in gold]
    data = [t for t in data if t["x"] is not None]
    for t in data:
        t["flag"] = None
    for y in range(2012, now.year + 1):
        start = datetime(y, 1, 1, tzinfo=UTC)
        train = [t for t in data if t["t"] < start - timedelta(days=30)]
        test = [t for t in data if start <= t["t"] < datetime(y + 1, 1, 1, tzinfo=UTC)]
        if len(train) < 100 or not test:
            continue
        model = logit_fit(np.array([t["x"] for t in train]), np.array([1.0 if t["r"] > 0 else 0.0 for t in train]))
        cut = float(np.median(model(np.array([t["x"] for t in train]))))
        pred = model(np.array([t["x"] for t in test]))
        for t, p in zip(test, pred):
            t["flag"] = bool(p > cut)
    rows.append(split("E7 gold trend, walk-forward meta-label", data, lambda t: t["flag"], M.PERIODS))

    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round23_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
