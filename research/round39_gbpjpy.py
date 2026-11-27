"""Round 39: three GBPJPY edges with a named payer (pre-registered 27 Nov 2026,
before the UK and Japanese interest-rate series were downloaded and before any
of these rules was run on GBPJPY).

Bradley asked for an edge on GBPJPY. Rounds 3, 10, 17, 29 and 35 found none in
FX chart rules: the gold trend rules made +0.043R a trade on GBPJPY (p 0.13),
and eight strategy families have failed across 31 pairs. This round tests what
is specific to a yen carry cross instead, each idea with someone on the other
side who is forced or slow:
  - equity markets reprice risk first and the yen crosses catch up (the
    "information hits one market before another" idea from the 27 Nov
    r/algotrading scrape; round 37's dollar-lead test on gold failed, this is
    the yen-cross version, which is a different mechanism);
  - carry-trade unwinds are forced deleveraging and continue for days
    (Brunnermeier, Nagel and Pedersen 2008, "Carry trades and currency crashes");
  - the carry premium is pay for crash risk that arrives when volatility is high
    (Menkhoff, Sarno, Schmeling and Schrimpf 2012), so carry earned only in calm
    markets should beat carry earned in stressed ones.
  - on gotobi days (the 5th, 10th, 15th, 20th, 25th and last day of the month)
    Japanese importers settle dollar bills at the 9:55 Tokyo fix and buy
    dollars with yen beforehand, so the yen weakens overnight into the fix
    (Bessho, Sugimoto and Suzuki, arXiv 2301.13204, USDJPY 2018-20). Round 11's
    M9 traded USDJPY into the fix on every day and failed; the gotobi-day
    version on GBPJPY has not been tested.
The four came from Bradley's request (27 Nov 2026) to research ideas specific
to the market instead of reusing gold's rules. Four tests; hypotheses_tested
rises from 1,411 to 1,415 and the bar is p < 0.05 / 4.

Data: Dukascopy GBPJPY and S&P 500 CFD hourly candles (data/markets/), FRED
VIXCLS (data/macro/), and the OECD 3-month interbank rates for the UK
(IR3TIB01GBM156N) and Japan (IR3TIB01JPM156N) from FRED, downloaded at run
time; a month's rate applies to every day of that month and the last published
month is carried forward. Costs: 2.5 basis points a round trip (round 10's
GBPJPY cost). Positions held past a day boundary pay or earn financing per
calendar day: long earns (UK rate - Japan rate - 1.0%) a year, short pays
(UK rate - Japan rate + 1.0%) a year, the 1.0% standing for a retail broker's
markup. A trading day runs from 17:00 to 17:00 New York time.

  G1 Equities move first. On each closed GBPJPY hour from 2012, with the
     previous 500 hours' standard deviation of the S&P 500's hourly return and
     GBPJPY's beta to it: if the S&P 500 moved more than 2 standard deviations
     this hour and GBPJPY moved less than half the move its beta implies (in the
     implied direction), buy or sell GBPJPY at the close in the implied
     direction and close 3 hours later. One trade at a time. Pass: at least 100
     trades, average after costs above zero with one-sided p < 0.0125 on
     daily-summed returns, and positive in 2012-15, 2016-24 and 2025-26.
  G2 Carry unwinds continue. When a trading day's GBPJPY close-to-close return
     is below -2 times the standard deviation of the previous 60 days' returns,
     sell at that close and buy back 5 trading days later, with financing. One
     trade at a time, 2008-26. Pass: at least 50 trades, average after costs
     above zero with one-sided p < 0.0125 (trade-level t-test), and positive in
     every period with at least 5 trades (2008-15, 2016-24, 2025-26).
  G3 Carry only when calm. Every trading day from 2009 is "calm" when the last
     VIX close known before the day starts is below the median of the 252 VIX
     closes before it. The return of holding GBPJPY long that day (close to
     close plus a day's long financing, three days' on the day that spans a
     weekend) is compared between calm days and the rest; switching between
     long and flat costs 1.25 basis points each way on calm days. Pass: calm
     days beat the rest with a one-sided Welch p < 0.0125, and in each of
     2009-15, 2016-24 and 2025-26 calm days average above zero and above the
     rest.
  G4 Gotobi. A gotobi day is the 5th, 10th, 15th, 20th, 25th or last calendar
     day of the month, moved to the previous weekday when it falls on a weekend
     (Japanese holidays are ignored, an approximation stated now). On each
     gotobi day from 2008, buy GBPJPY at 18:00 UTC the evening before (03:00
     Tokyo) and sell at 01:00 UTC (10:00 Tokyo, five minutes after the fix).
     The same hold on other weekdays is the comparison. Pass: gotobi trades
     average above zero after costs with one-sided p < 0.0125, beat the other
     days with one-sided Welch p < 0.0125, and are positive and ahead of the
     other days in each of 2008-15, 2016-24 and 2025-26.

A pass goes to Bradley as a proposal; nothing is alerted without his decision
and a separate end-to-end-checked change. Research only: the hypotheses_tested
counter in signals.py is not touched.
"""
import bisect
import csv
import json
import math
import os
import statistics as st
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
import round37_new_inputs as R37  # noqa: E402

UTC, NY = timezone.utc, ZoneInfo("America/New_York")
ALPHA = 0.05 / 4
COST = 2.5 / 1e4
MARKUP = 1.0
DATA = os.path.join(ROOT, "data")
MACRO = os.path.join(DATA, "macro")
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="


# ----------------------------------------------------------------- data
def bars(name):
    return R37.load_csv_bars(os.path.join(DATA, "markets", f"{name}_h1.csv.gz"))


def fred(series):
    path = os.path.join(MACRO, f"{series}.csv")
    if not os.path.exists(path):
        req = urllib.request.Request(FRED + series, headers={"User-Agent": "Mozilla/5.0"})
        with open(path, "wb") as f:
            f.write(urllib.request.urlopen(req, timeout=60).read())
    out = []
    with open(path) as f:
        for r in csv.reader(list(f)[1:]):
            if r[1] not in ("", "."):
                out.append((date.fromisoformat(r[0]), float(r[1])))
    return out


def rate_diff():
    """{(year, month): UK minus Japan 3-month rate, %}, carried forward."""
    uk, jp = dict(((d.year, d.month), v) for d, v in fred("IR3TIB01GBM156N")), \
        dict(((d.year, d.month), v) for d, v in fred("IR3TIB01JPM156N"))
    months = sorted(set(uk) & set(jp))
    return {m: uk[m] - jp[m] for m in months}, months


def diff_on(d, diffs, months):
    i = bisect.bisect_right(months, (d.year, d.month)) - 1
    return diffs[months[max(i, 0)]]


def trading_days(bs):
    """[(trading-day date, close)] with the day ending 17:00 New York."""
    out = {}
    for b in bs:
        end = (b["t"] + timedelta(hours=1)).astimezone(NY)
        day = (end - timedelta(hours=17)).date() + timedelta(days=1)
        out[day] = b["c"]
    return sorted(out.items())


def period(d, cuts):
    for name, lo, hi in cuts:
        if lo <= d < hi:
            return name
    return None


def t_one_sided(x):
    m, sd = st.mean(x), st.stdev(x)
    t = m / (sd / math.sqrt(len(x))) if sd else 0.0
    return m, t, 0.5 * math.erfc(t / math.sqrt(2))


# ----------------------------------------------------------------- tests
def g1(gj, spx):
    s_at = {b["t"]: b["c"] for b in spx}
    rows, prev = [], None
    for i, b in enumerate(gj):
        if i == 0:
            continue
        t, p = b["t"], gj[i - 1]
        if t - p["t"] != timedelta(hours=1) or t not in s_at or p["t"] not in s_at:
            continue
        rows.append((i, math.log(s_at[t] / s_at[p["t"]]), math.log(b["c"] / p["c"])))
    trades, busy = [], -1
    for k in range(500, len(rows)):
        i, sr, gr = rows[k]
        if i <= busy or gj[i]["t"].year < 2012:
            continue
        win = rows[k - 500:k]
        xs, ys = [r[1] for r in win], [r[2] for r in win]
        sd = st.pstdev(xs)
        mx, my = st.mean(xs), st.mean(ys)
        var = sum((x - mx) ** 2 for x in xs)
        beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var if var else 0
        if sd == 0 or abs(sr) <= 2 * sd or beta <= 0:
            continue
        d = 1 if sr > 0 else -1
        implied = beta * sr
        if gr * d >= 0.5 * abs(implied):
            continue
        j = i + 3
        if j >= len(gj) or gj[j]["t"] - gj[i]["t"] != timedelta(hours=3):
            continue
        ret = d * math.log(gj[j]["c"] / gj[i]["c"]) - COST
        trades.append((gj[i]["t"], ret * 1e4))
        busy = j
    daily = {}
    for t, r in trades:
        daily[t.date()] = daily.get(t.date(), 0) + r
    m, t, p = t_one_sided(list(daily.values()))
    cuts = [("2012-15", date(2012, 1, 1), date(2016, 1, 1)), ("2016-24", date(2016, 1, 1), date(2025, 1, 1)),
            ("2025-26", date(2025, 1, 1), date(2030, 1, 1))]
    parts, pos = [], True
    for name, lo, hi in cuts:
        x = [r for tt, r in trades if lo <= tt.date() < hi]
        pos &= bool(x) and st.mean(x) > 0
        parts.append(f"{name} {st.mean(x):+.2f}bp ({len(x)})" if x else f"{name} n/a")
    avg = st.mean(r for _, r in trades)
    ok = len(trades) >= 100 and avg > 0 and p < ALPHA and pos
    print(f"  G1 equities move first\n     {len(trades)} trades, {avg:+.2f}bp a trade after costs, "
          f"{100 * sum(r > 0 for _, r in trades) / len(trades):.0f}% win, p={p:.2g} (daily) | "
          + " | ".join(parts) + f" | {'PASS' if ok else 'fail'}")
    return {"test": "G1 equities move first", "n": len(trades), "avg_bp": round(avg, 2), "p": f"{p:.2g}",
            "periods": parts, "verdict": "PASS" if ok else "fail"}


def g2(days, diffs, months):
    rets = [(days[i][0], math.log(days[i][1] / days[i - 1][1])) for i in range(1, len(days))]
    trades, busy = [], -1
    for k in range(60, len(rets)):
        d, r = rets[k]
        if k <= busy or d.year < 2008:
            continue
        sd = st.stdev(x for _, x in rets[k - 60:k])
        if r >= -2 * sd:
            continue
        j = k + 5
        if j >= len(rets):
            break
        entry, exit_ = days[k + 1][1], days[j + 1][1]
        held = (rets[j][0] - d).days
        fin = (diff_on(d, diffs, months) + MARKUP) / 100 / 365 * held
        trades.append((d, -math.log(exit_ / entry) - COST - fin))
        busy = j
    cuts = [("2008-15", date(2008, 1, 1), date(2016, 1, 1)), ("2016-24", date(2016, 1, 1), date(2025, 1, 1)),
            ("2025-26", date(2025, 1, 1), date(2030, 1, 1))]
    x = [r * 1e4 for _, r in trades]
    m, t, p = t_one_sided(x)
    parts, pos = [], True
    for name, lo, hi in cuts:
        y = [r * 1e4 for dd, r in trades if lo <= dd < hi]
        if len(y) >= 5:
            pos &= st.mean(y) > 0
        parts.append(f"{name} {st.mean(y):+.1f}bp ({len(y)})" if y else f"{name} n/a")
    ok = len(x) >= 50 and m > 0 and p < ALPHA and pos
    print(f"  G2 carry unwinds continue (sell after a 2-sd down day, hold 5 days)\n     {len(x)} trades, "
          f"{m:+.1f}bp a trade after costs and financing, {100 * sum(v > 0 for v in x) / len(x):.0f}% win, "
          f"p={p:.2g} | " + " | ".join(parts) + f" | {'PASS' if ok else 'fail'}")
    return {"test": "G2 carry unwinds continue", "n": len(x), "avg_bp": round(m, 1), "p": f"{p:.2g}",
            "periods": parts, "verdict": "PASS" if ok else "fail"}


def g3(days, diffs, months):
    vix = fred("VIXCLS")
    vd = [d for d, _ in vix]
    rows, was_calm = [], False
    for i in range(1, len(days)):
        d, c = days[i]
        if d.year < 2009:
            continue
        k = bisect.bisect_left(vd, d) - 1          # last VIX close dated before this trading day
        if k < 252:
            continue
        calm = vix[k][1] < st.median(v for _, v in vix[k - 252:k])
        held = (d - days[i - 1][0]).days
        r = math.log(c / days[i - 1][1]) + (diff_on(d, diffs, months) - MARKUP) / 100 / 365 * held
        if calm:
            r -= (COST / 2) if not was_calm else 0
        elif was_calm:
            rows[-1] = (rows[-1][0], rows[-1][1], rows[-1][2] - COST / 2)
        rows.append((d, calm, r))
        was_calm = calm
    a = [r * 1e4 for _, c, r in rows if c]
    b = [r * 1e4 for _, c, r in rows if not c]
    diff, t, p2 = R37.welch(a, b)
    p = p2 / 2 if diff > 0 else 1 - p2 / 2
    cuts = [("2009-15", date(2009, 1, 1), date(2016, 1, 1)), ("2016-24", date(2016, 1, 1), date(2025, 1, 1)),
            ("2025-26", date(2025, 1, 1), date(2030, 1, 1))]
    parts, ok_p = [], True
    for name, lo, hi in cuts:
        x = [r * 1e4 for d, c, r in rows if c and lo <= d < hi]
        y = [r * 1e4 for d, c, r in rows if not c and lo <= d < hi]
        ok_p &= bool(x) and bool(y) and st.mean(x) > 0 and st.mean(x) > st.mean(y)
        parts.append(f"{name} calm {st.mean(x):+.2f}bp ({len(x)}) vs {st.mean(y):+.2f}bp ({len(y)})")
    ok = p < ALPHA and ok_p
    yr = lambda v: v * 252 / 1e4 * 100
    print(f"  G3 carry only when calm\n     calm days {st.mean(a):+.2f}bp ({len(a)}, about {yr(st.mean(a)) * len(a) / (len(a) + len(b)):+.1f}% a year "
          f"held) vs rest {st.mean(b):+.2f}bp ({len(b)}), p={p:.2g} | " + " | ".join(parts)
          + f" | {'PASS' if ok else 'fail'}")
    return {"test": "G3 carry only when calm", "n_calm": len(a), "n_rest": len(b), "calm_bp": round(st.mean(a), 2),
            "rest_bp": round(st.mean(b), 2), "p": f"{p:.2g}", "periods": parts, "verdict": "PASS" if ok else "fail"}


def gotobi_days(y0, y1):
    out = set()
    for y in range(y0, y1 + 1):
        for m in range(1, 13):
            last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
            for dd in (5, 10, 15, 20, 25, last):
                d = date(y, m, dd)
                while d.weekday() >= 5:
                    d -= timedelta(days=1)
                out.add(d)
    return out


def g4(gj):
    at = {b["t"]: b for b in gj}
    got = gotobi_days(2008, 2026)
    a, b, rows = [], [], []
    d = date(2008, 1, 2)
    while d <= gj[-1]["t"].date():
        if d.weekday() < 5:
            t_in = datetime(d.year, d.month, d.day, tzinfo=UTC) - timedelta(hours=7)   # bar 17:00 closes 18:00
            t_out = datetime(d.year, d.month, d.day, tzinfo=UTC)                     # bar 00:00 closes 01:00
            if t_in in at and t_out in at:
                r = (math.log(at[t_out]["c"] / at[t_in]["c"]) - COST) * 1e4
                rows.append((d, d in got, r))
        d += timedelta(days=1)
    a = [r for _, g, r in rows if g]
    b = [r for _, g, r in rows if not g]
    m, t, p0 = t_one_sided(a)
    diff, _, p2 = R37.welch(a, b)
    p1 = p2 / 2 if diff > 0 else 1 - p2 / 2
    cuts = [("2008-15", date(2008, 1, 1), date(2016, 1, 1)), ("2016-24", date(2016, 1, 1), date(2025, 1, 1)),
            ("2025-26", date(2025, 1, 1), date(2030, 1, 1))]
    parts, ok_p = [], True
    for name, lo, hi in cuts:
        x = [r for dd, g, r in rows if g and lo <= dd < hi]
        y = [r for dd, g, r in rows if not g and lo <= dd < hi]
        ok_p &= bool(x) and st.mean(x) > 0 and st.mean(x) > st.mean(y)
        parts.append(f"{name} {st.mean(x):+.2f}bp ({len(x)}) vs {st.mean(y):+.2f}bp")
    ok = m > 0 and p0 < ALPHA and p1 < ALPHA and ok_p
    print(f"  G4 gotobi: long GBPJPY 18:00-01:00 UTC into the Tokyo fix\n     gotobi {m:+.2f}bp ({len(a)}, "
          f"{100 * sum(v > 0 for v in a) / len(a):.0f}% win, p={p0:.2g}) vs other days {st.mean(b):+.2f}bp ({len(b)}), "
          f"p={p1:.2g} | " + " | ".join(parts) + f" | {'PASS' if ok else 'fail'}")
    return {"test": "G4 gotobi", "n": len(a), "avg_bp": round(m, 2), "other_bp": round(st.mean(b), 2),
            "p": f"{p0:.2g}", "p_vs_other": f"{p1:.2g}", "periods": parts, "verdict": "PASS" if ok else "fail"}


def main():
    gj, spx = bars("gbpjpy"), bars("usa500idxusd")
    days = trading_days(gj)
    diffs, months = rate_diff()
    print(f"GBPJPY {gj[0]['t']:%Y-%m-%d} to {gj[-1]['t']:%Y-%m-%d}, {len(days)} trading days; "
          f"rate gap {months[0]} to {months[-1]}, last {diffs[months[-1]]:+.2f}%")
    rows = [g1(gj, spx), g2(days, diffs, months), g3(days, diffs, months), g4(gj)]
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round39_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
