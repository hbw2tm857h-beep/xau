"""Round 12: documented edges on markets other than gold (pre-registered 19 Nov 2026).

Bradley asked for the Slack system to cover more than gold. Rounds 3 and 10 showed
the gold rules do not travel (FX, oil, silver and the indices all failed; only the
Bitcoin trend rules passed). So this round goes the other way: start from edges
documented on each market in the literature, or proposed on Reddit (research/
reddit_catalogue.md), and test them on the hourly data already in data/.

Every rule below was written down and committed before any result was seen.
Nothing was tuned. Results are in basis points per observation after costs.

  M1 Time-series momentum         Moskowitz, Ooi & Pedersen (JFE 2012); Hurst, Ooi &
                                  Pedersen (2017). All 22 markets. At each month end,
                                  go long if the last 12 months' return is positive,
                                  short if negative, for the next month. Each market is
                                  sized to 10% annualised volatility (60-day daily
                                  stdev, weight capped at 5x). One observation = one
                                  month of the equal-weighted portfolio. Every
                                  position pays its full round-trip cost every month.
  M2 FX: home currency weakens    Breedon & Ranaldo (JMCB 2013). Six USD pairs (EUR,
     in its own morning           GBP, CHF, JPY, AUD, NZD). Each foreign currency is
                                  sold against the dollar from 08:00 to 12:00 in its
                                  home time (London for EUR, GBP and CHF; Tokyo,
                                  Sydney, Auckland). One observation = one day, the
                                  average of the six trades.
  M3 FX: dollar weakens in the    Same paper, the dollar side. The six pairs, buying
     US morning                   each foreign currency from 08:00 to 12:00 New York.
  M4 FX month-end hedge flows     Melvin & Prins (JFM 2015). On the last weekday of each
                                  month, compare the month-to-date S&P 500 return with
                                  the DAX, FTSE and Nikkei in dollars (to 07:00
                                  London). If US stocks did better, buy that foreign
                                  currency against the dollar from 08:00 to the 16:00
                                  London fix; otherwise sell it. One observation = one
                                  month, the average of EURUSD, GBPUSD and USDJPY.
  M5 Turn of the month, indices   Lakonishok & Smidt (1988), McConnell & Xu (2008).
                                  Six indices. Long from the cash close of the
                                  second-to-last trading day to the close of the third
                                  trading day of the new month. One observation = one
                                  month, the average across indices.
  M6 US overnight drift           Cliff, Cooper & Gulen (2008), Kelly & Clark (2011);
                                  Reddit catalogue #6. S&P 500, Nasdaq 100 and Dow.
                                  Long from the 16:00 New York close to the 09:00 New
                                  York open the next trading day. One observation = one
                                  night, the average of the three.
  M7 European-open drift in       Boyarchenko, Larsen & Whelan (RFS 2023). Long the
     US index futures             three US indices from 02:00 to 04:00 New York. One
                                  observation = one day, the average of the three.
  M8 IBS band reversion, indices  Reddit catalogue #1 (rules as posted); IBS effect,
                                  Pagonidis (2013). Six indices, daily cash-session
                                  candles. Buy the close when close < (10-day highest
                                  high - 2.5 x 25-day average range) and
                                  IBS = (close - low) / (high - low) < 0.3. Exit at the
                                  first close above the previous day's high. One
                                  observation = one trade.
  M9 USDJPY into the Tokyo fix    Ito & Yamada (2017), "gotoday" demand. On the 5th,
                                  10th, 15th, 20th and 25th and the last weekday of the
                                  month (moved to the previous Friday if it falls at a
                                  weekend), buy USDJPY from 08:00 to 10:00 Tokyo.

Costs: each market's round-trip cost from round 10 (FX 1.0-2.0 bp, indices 1.0-2.0 bp,
oil 5, silver 10, Bitcoin 5, gold 1.75). Trades held overnight on an index (M5, M6,
M8) also pay CFD financing for a long position: (US policy rate + 2.5%) / 365 for
every calendar night, using the yearly average rates in FED below. That is how an
MT5 broker would charge it, and the pass is judged after it.

Pass, fixed in advance: at least 150 observations; a positive average in every
period with 10+ observations (2008-15, 2016-22, 2023-24, 2025-26); and one-sided
p < 0.05 / 9 = 0.0056. Anything that passes becomes a nursery candidate only, after
a correlation check against the live strategies.
"""
import csv
import math
import os
import statistics as st
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import round10_btc_checks as B  # noqa: E402
import round10_markets as R10  # noqa: E402

UTC = timezone.utc
NY, LDN, BER, TKY = ZoneInfo("America/New_York"), ZoneInfo("Europe/London"), ZoneInfo("Europe/Berlin"), ZoneInfo("Asia/Tokyo")
SYD, AKL = ZoneInfo("Australia/Sydney"), ZoneInfo("Pacific/Auckland")
D = lambda y: datetime(y, 1, 1, tzinfo=UTC)
PERIODS = [("2008-15", D(2008), D(2016)), ("2016-22", D(2016), D(2023)),
           ("2023-24", D(2023), D(2025)), ("2025-26", D(2025), D(2030))]
N_TESTS = 9
ALPHA = 0.05 / N_TESTS

# Yearly average US policy rate, %, for CFD financing (2025-26 approximate).
FED = {2008: 1.9, 2009: 0.16, 2010: 0.18, 2011: 0.10, 2012: 0.14, 2013: 0.11, 2014: 0.09, 2015: 0.13,
       2016: 0.40, 2017: 1.00, 2018: 1.83, 2019: 2.16, 2020: 0.38, 2021: 0.08, 2022: 1.68, 2023: 5.02,
       2024: 5.14, 2025: 4.20, 2026: 3.70}

# Cash sessions for the indices: (zone, first hourly bar, last hourly bar), local time.
SESSION = {"S&P 500": (NY, 9, 15), "Nasdaq 100": (NY, 9, 15), "Dow": (NY, 9, 15),
           "DAX": (BER, 9, 16), "FTSE 100": (LDN, 8, 15), "Nikkei 225": (TKY, 9, 14)}
US3 = ["S&P 500", "Nasdaq 100", "Dow"]
# USD pairs: name -> (home zone of the foreign currency, +1 if quoted XXXUSD, -1 if USDXXX)
FX6 = {"EURUSD": (LDN, 1), "GBPUSD": (LDN, 1), "USDCHF": (LDN, -1),
       "USDJPY": (TKY, -1), "AUDUSD": (SYD, 1), "NZDUSD": (AKL, 1)}

_cache = {}


def bars(name):
    if name not in _cache:
        files, cost = R10.MARKETS[name if name != "XAUUSD" else "XAUUSD (reference)"]
        if name == "BTCUSD":
            b = B.load_247(os.path.join(R10.DATA, files[0]))
        else:
            b = sorted((x for f in files for x in R10.load(os.path.join(R10.DATA, f))), key=lambda x: x["t"])
        _cache[name] = ({x["t"]: x for x in b}, b, cost)
    return _cache[name]


def cost(name):
    return bars(name)[2]


def at(name, zone, d, hour):
    """The hourly bar that starts at local `hour` on date d, or None."""
    t = datetime.combine(d, time(hour), zone).astimezone(UTC)
    return bars(name)[0].get(t)


def finance_bps(t0, t1):
    nights = (t1.date() - t0.date()).days
    return sum((FED[(t0 + timedelta(days=i)).year] + 2.5) / 365 * 100 for i in range(nights))


def weekdays(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def span(names):
    ts = [bars(n)[1] for n in names]
    return max(b[0]["t"] for b in ts).date(), min(b[-1]["t"] for b in ts).date()


def obs(t, v):
    return {"t": t, "bps": v}


# --------------------------------------------------------------------------
def daily_closes(name):
    """Last close of each UTC date."""
    out = {}
    for b in bars(name)[1]:
        out[b["t"].date()] = b["c"]
    return out


def m1_tsmom():
    names = [n if n != "XAUUSD (reference)" else "XAUUSD" for n in R10.MARKETS]
    per_mkt = {}
    for n in names:
        dc = daily_closes(n)
        days = sorted(dc)
        month_end = {}
        for d in days:
            month_end[(d.year, d.month)] = d
        per_mkt[n] = (dc, days, month_end)
    months = sorted({m for n in names for m in per_mkt[n][2]})
    out = []
    for i in range(12, len(months) - 1):
        m, nxt, base = months[i], months[i + 1], months[i - 12]
        legs = []
        for n in names:
            dc, days, me = per_mkt[n]
            if m not in me or nxt not in me or base not in me:
                continue
            d0 = me[m]
            if (date(*m, 1) - date(*base, 1)).days < 330:
                continue
            k = days.index(d0)
            if k < 61:
                continue
            rets = [dc[days[j]] / dc[days[j - 1]] - 1 for j in range(k - 59, k + 1)]
            vol = st.stdev(rets) * math.sqrt(365 if n == "BTCUSD" else 261)
            if vol <= 0:
                continue
            w = min(0.10 / vol, 5.0)
            side = 1 if dc[d0] > dc[me[base]] else -1
            r = dc[me[nxt]] / dc[d0] - 1
            legs.append(w * (side * r * 1e4 - cost(n)))
        if len(legs) >= 5:
            out.append(obs(datetime(*nxt, 1, tzinfo=UTC), st.mean(legs)))
    return out


def fx_morning(home):
    """M2 (home=True): each foreign currency weakens 08-12 in its own time.
    M3 (home=False): the dollar weakens 08-12 New York."""
    a, b = span(list(FX6))
    out = []
    for d in weekdays(a, b):
        legs = []
        for n, (zone, q) in FX6.items():
            z = zone if home else NY
            e, x = at(n, z, d, 8), at(n, z, d, 11)
            if not e or not x:
                continue
            side = -q if home else q          # sell the foreign currency, or buy it
            legs.append(side * (x["c"] / e["o"] - 1) * 1e4 - cost(n))
        if len(legs) >= 4:
            out.append(obs(datetime.combine(d, time(12), UTC), st.mean(legs)))
    return out


def last_weekday(y, m):
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def close_before(name, t):
    """Close of the last bar that ends at or before t."""
    idx, lst, _ = bars(name)
    lo, hi = 0, len(lst)
    while lo < hi:
        mid = (lo + hi) // 2
        if lst[mid]["t"] + timedelta(hours=1) <= t:
            lo = mid + 1
        else:
            hi = mid
    return lst[lo - 1]["c"] if lo else None


def m4_month_end():
    pairs = {"EURUSD": ("DAX", 1), "GBPUSD": ("FTSE 100", 1), "USDJPY": ("Nikkei 225", -1)}
    a, b = span(list(pairs) + [v[0] for v in pairs.values()] + ["S&P 500"])
    out = []
    y, m = a.year, a.month
    while date(y, m, 1) <= b:
        d = last_weekday(y, m)
        prev_end = datetime.combine(date(y, m, 1), time(0), UTC)
        cut = datetime.combine(d, time(7), LDN).astimezone(UTC)
        legs = []
        spx0, spx1 = close_before("S&P 500", prev_end), close_before("S&P 500", cut)
        for n, (idx, q) in pairs.items():
            e, x = at(n, LDN, d, 8), at(n, LDN, d, 15)
            i0, i1 = close_before(idx, prev_end), close_before(idx, cut)
            f0, f1 = close_before(n, prev_end), close_before(n, cut)
            if not (e and x and spx0 and spx1 and i0 and i1 and f0 and f1):
                continue
            fx_ret = (f1 / f0) if q == 1 else (f0 / f1)   # foreign currency in dollars
            foreign_usd = i1 / i0 * fx_ret - 1
            us = spx1 / spx0 - 1
            side = (1 if us > foreign_usd else -1) * q    # buy the foreign currency if US did better
            legs.append(side * (x["c"] / e["o"] - 1) * 1e4 - cost(n))
        if len(legs) >= 2:
            out.append(obs(datetime.combine(d, time(12), UTC), st.mean(legs)))
        y, m = (y + (m == 12), m % 12 + 1)
    return out


def sessions(name):
    """Daily cash-session candles: date -> dict(o, h, l, c, t_close)."""
    zone, h0, h1 = SESSION[name]
    days = {}
    for b in bars(name)[1]:
        lt = b["t"].astimezone(zone)
        if lt.weekday() < 5 and h0 <= lt.hour <= h1:
            days.setdefault(lt.date(), []).append(b)
    out = {}
    for d, bs in days.items():
        bs.sort(key=lambda x: x["t"])
        if bs[0]["t"].astimezone(zone).hour != h0 or bs[-1]["t"].astimezone(zone).hour != h1:
            continue
        out[d] = {"o": bs[0]["o"], "h": max(x["h"] for x in bs), "l": min(x["l"] for x in bs),
                  "c": bs[-1]["c"], "t": bs[-1]["t"] + timedelta(hours=1)}
    return out


def m5_turn_of_month():
    names = list(SESSION)
    by = {n: sessions(n) for n in names}
    months = sorted({(d.year, d.month) for n in names for d in by[n]})
    out = []
    for i in range(1, len(months) - 1):
        legs = []
        for n in names:
            prev = sorted(d for d in by[n] if (d.year, d.month) == months[i - 1])
            cur = sorted(d for d in by[n] if (d.year, d.month) == months[i])
            if len(prev) < 15 or len(cur) < 15:
                continue
            e, x = by[n][prev[-2]], by[n][cur[2]]
            legs.append((x["c"] / e["c"] - 1) * 1e4 - cost(n) - finance_bps(e["t"], x["t"]))
        if len(legs) >= 3:
            out.append(obs(datetime(*months[i], 1, tzinfo=UTC), st.mean(legs)))
    return out


def m6_overnight():
    by = {n: sessions(n) for n in US3}
    days = sorted(set.intersection(*(set(v) for v in by.values())))
    out = []
    for d0, d1 in zip(days, days[1:]):
        if (d1 - d0).days > 4:
            continue
        legs = []
        for n in US3:
            e, x = by[n][d0], by[n][d1]
            legs.append((x["o"] / e["c"] - 1) * 1e4 - cost(n) - finance_bps(e["t"], x["t"] - timedelta(hours=7)))
        out.append(obs(by[US3[0]][d0]["t"], st.mean(legs)))
    return out


def m7_europe_open():
    a, b = span(US3)
    out = []
    for d in weekdays(a, b):
        legs = []
        for n in US3:
            e, x = at(n, NY, d, 2), at(n, NY, d, 3)
            if e and x:
                legs.append((x["c"] / e["o"] - 1) * 1e4 - cost(n))
        if len(legs) == 3:
            out.append(obs(datetime.combine(d, time(8), UTC), st.mean(legs)))
    return out


def m8_ibs():
    out = []
    for n in SESSION:
        s = sessions(n)
        days = sorted(s)
        i = 25
        while i < len(days) - 1:
            win10, win25 = days[i - 9:i + 1], days[i - 24:i + 1]
            band = max(s[d]["h"] for d in win10) - 2.5 * st.mean(s[d]["h"] - s[d]["l"] for d in win25)
            c = s[days[i]]
            rng = c["h"] - c["l"]
            if rng > 0 and c["c"] < band and (c["c"] - c["l"]) / rng < 0.3:
                j = i + 1
                while j < len(days) and s[days[j]]["c"] <= s[days[j - 1]]["h"]:
                    j += 1
                if j >= len(days):
                    break
                x = s[days[j]]
                out.append(obs(c["t"], (x["c"] / c["c"] - 1) * 1e4 - cost(n) - finance_bps(c["t"], x["t"])))
                i = j + 1
                continue
            i += 1
    return out


def gotoday(y, m):
    ds = [date(y, m, k) for k in (5, 10, 15, 20, 25)] + [last_weekday(y, m)]
    out = set()
    for d in ds:
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        out.add(d)
    return sorted(out)


def m9_gotoday():
    a, b = span(["USDJPY"])
    out = []
    y, m = a.year, a.month
    while date(y, m, 1) <= b:
        for d in gotoday(y, m):
            e, x = at("USDJPY", TKY, d, 8), at("USDJPY", TKY, d, 9)
            if e and x:
                out.append(obs(e["t"], (x["c"] / e["o"] - 1) * 1e4 - cost("USDJPY")))
        y, m = (y + (m == 12), m % 12 + 1)
    return out


# --------------------------------------------------------------------------
def judge(o):
    x = [t["bps"] for t in o]
    n = len(x)
    if n < 3:
        return {"n": n}
    m, sd = st.mean(x), st.stdev(x)
    tstat = m / (sd / math.sqrt(n)) if sd else 0
    p = 0.5 * math.erfc(tstat / math.sqrt(2))
    per = {}
    for pn, a, b in PERIODS:
        y = [t["bps"] for t in o if a <= t["t"] < b]
        per[pn] = (len(y), st.mean(y) if y else None)
    counted = [v for k, v in per.values() if k >= 10]
    ok = n >= 150 and m > 0 and all(v > 0 for v in counted) and p < ALPHA
    years = {}
    for t in o:
        years[t["t"].year] = years.get(t["t"].year, 0) + t["bps"]
    return {"n": n, "avg": m, "win": 100 * sum(v > 0 for v in x) / n, "p": p, "t": tstat, "per": per, "ok": ok,
            "pos_years": sum(v > 0 for v in years.values()), "years": len(years)}


TESTS = [
    ("M1 Time-series momentum, 22 markets", m1_tsmom),
    ("M2 FX: home currency weakens 08-12 local", lambda: fx_morning(True)),
    ("M3 FX: dollar weakens 08-12 New York", lambda: fx_morning(False)),
    ("M4 FX month-end hedge flows", m4_month_end),
    ("M5 Turn of the month, 6 indices", m5_turn_of_month),
    ("M6 US overnight drift", m6_overnight),
    ("M7 European-open drift, US indices", m7_europe_open),
    ("M8 IBS band reversion, 6 indices", m8_ibs),
    ("M9 USDJPY into the Tokyo fix", m9_gotoday),
]


def main():
    rows = []
    for name, fn in TESTS:
        o = sorted(fn(), key=lambda t: t["t"])
        s = judge(o)
        if s["n"] < 3:
            print(f"{name}: too few observations ({s['n']})"); continue
        row = {"test": name, "n": s["n"], "win": round(s["win"], 1), "avg_bps_net": round(s["avg"], 2),
               "t": round(s["t"], 2), "p": f"{s['p']:.2g}",
               **{f"{pn}_bps": (round(v, 2) if v is not None else "") for pn, (k, v) in s["per"].items()},
               **{f"{pn}_n": k for pn, (k, v) in s["per"].items()},
               "pos_years": f"{s['pos_years']}/{s['years']}", "verdict": "PASS" if s["ok"] else ""}
        rows.append(row)
        print(f"{name:42s} n={s['n']:5d} win={s['win']:4.1f}% net={s['avg']:+7.2f}bp t={s['t']:+5.2f} | "
              + " ".join(f"{pn} {('%+.2f' % v) if v is not None else '  -  '}({k})" for pn, (k, v) in s["per"].items())
              + f" | yrs+ {s['pos_years']}/{s['years']} | p={s['p']:.2g} {row['verdict']}", flush=True)
    with open(os.path.join(HERE, "results_round12_beyond_gold.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
