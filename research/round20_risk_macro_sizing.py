"""Round 20: tail protection, gold macro filters, and sizing (pre-registered
19 Nov 2026, before any of the macro data was downloaded).

Nine tests in three groups. Every rule and pass mark below was committed before
running. hypotheses_tested rises by 9.

A. US index rebounds: protecting the tail (S&P 500, Nasdaq 100, Dow, Russell 2000,
   616 trades, R = 25-day average range, 1 bp cost). The strategy has no stop and
   its worst run was 42R. Each variant changes one thing:
     A1 time stop: exit at the close of the 10th session if not already out.
     A2 catastrophe stop: exit at the first close more than 3R below the entry.
     A3 trend filter: skip signals when the index closes below its 200-day average.
   Pass (a risk test, not an edge test): the worst run of losses (maximum
   drawdown in R) and the worst single trade both shrink by at least 25%, while the
   average R per trade falls by no more than 10%; and the drawdown improvement holds
   in both halves (2012-2018 and 2019-2026).

B. Gold trend setups (720 trades, 2008-2026): macro filters. Each splits the trades
   into a favoured group and the rest, judged like round 18: the favoured group has
   100+ trades and a positive average in every period with 10+ trades, beats the rest
   in at least three of four periods, and a Welch t-test gives p < 0.05 / 9 = 0.0056
   (one-sided, except B4 two-sided). Data as known at the signal's close.
     B1 real yields (FRED DFII10, 10-year TIPS yield): favoured = buys when the yield
        fell over the previous 20 trading days, sells when it rose.
     B2 the dollar (FRED DTWEXBGS, broad trade-weighted dollar): favoured = buys
        when the dollar fell over the previous 20 trading days, sells when it rose.
     B3 positioning (CFTC disaggregated COT, gold 088691, managed money net = long
        - short, latest report released before the signal): favoured = every trade
        except buys when the net is in its top 10% of the previous 156 weeks and
        sells when it is in its bottom 10% (not following an extreme crowd).
     B4 gold volatility (FRED GVZCLS): favoured = GVZ above its previous 252-day
        median. Two-sided: there was no strong prior for the direction.

C. Sizing, on the five-strategy portfolio from round 19 (monthly R, March 2018 -
   October 2026, base weights = risk parity fitted on the first half, as round 19).
     C1 volatility targeting: each strategy's weight in a month is multiplied by its
        previous-36-month volatility / previous-6-month volatility, capped to 0.5-2.
     C2 drawdown brake: a strategy's weight halves while its own weighted equity is
        more than 10R below its peak, and returns to full on a new peak.
   Pass: Sharpe ratio higher and the worst drawdown no larger than the base, in
   both halves of the period.

Anything that passes is reported for a decision; none of it changes the live bot
without a separate, end-to-end-checked change.
"""
import csv
import gzip
import io
import json
import math
import os
import statistics as st
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import round12_beyond_gold as M  # noqa: E402
import round19_portfolio as P  # noqa: E402
import similar_setups as SS  # noqa: E402

UTC = timezone.utc
MACRO = os.path.join(ROOT, "data", "macro")
ALPHA = 0.05 / 9
M.R10.MARKETS["Russell 2000"] = (["markets/ussc2000idxusd_h1.csv.gz"], 2.0)
M.SESSION["Russell 2000"] = (ZoneInfo("America/New_York"), 9, 15)
US4 = ["S&P 500", "Nasdaq 100", "Dow", "Russell 2000"]


# ---------------------------------------------------------------- data
def fred(series):
    path = os.path.join(MACRO, f"{series}.csv")
    if not os.path.exists(path):
        os.makedirs(MACRO, exist_ok=True)
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
        req = urllib.request.Request(url, headers={"User-Agent": "xau-research/1.0"})
        open(path, "wb").write(urllib.request.urlopen(req, timeout=60).read())
    out = {}
    with open(path) as f:
        r = csv.reader(f); next(r)
        for row in r:
            try:
                out[date.fromisoformat(row[0])] = float(row[1])
            except (ValueError, IndexError):
                pass
    return out


def cot_gold():
    """Managed-money net position in COMEX gold, by report date (Tuesday); the
    report is released the following Friday, which is the date returned."""
    path = os.path.join(MACRO, "cot_gold_managed_money.csv")
    if not os.path.exists(path):
        os.makedirs(MACRO, exist_ok=True)
        files = ["fut_disagg_txt_hist_2006_2016.zip"] + [f"fut_disagg_txt_{y}.zip" for y in range(2017, 2027)]
        rows = {}
        for fn in files:
            local = os.path.join(MACRO, "cot", fn)       # the CFTC site drops scripted downloads; fetch by browser
            if os.path.exists(local):
                z = zipfile.ZipFile(local)
            else:
                req = urllib.request.Request("https://www.cftc.gov/files/dea/history/" + fn,
                                             headers={"User-Agent": "xau-research/1.0"})
                z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(req, timeout=120).read()))
            for name in z.namelist():
                rd = csv.DictReader(io.TextIOWrapper(z.open(name), encoding="latin-1"))
                for r in rd:
                    if (r.get("CFTC_Contract_Market_Code") or "").strip() != "088691":
                        continue
                    d = (r.get("Report_Date_as_YYYY-MM-DD") or "").strip()
                    try:
                        net = float(r["M_Money_Positions_Long_All"]) - float(r["M_Money_Positions_Short_All"])
                    except (KeyError, ValueError):
                        continue
                    rows[d] = net
        with open(path, "w") as f:
            f.write("report_date,mm_net\n")
            for d in sorted(rows):
                f.write(f"{d},{rows[d]:.0f}\n")
    out = {}
    with open(path) as f:
        next(f)
        for line in f:
            d, v = line.strip().split(",")
            out[date.fromisoformat(d) + timedelta(days=3)] = float(v)   # released on the Friday
    return out


def asof(series, d):
    """Latest value on or before d, with its index in the sorted key list."""
    keys = series["_keys"] if "_keys" in series else None
    import bisect
    i = bisect.bisect_right(keys, d) - 1
    return (i, keys[i]) if i >= 0 else (None, None)


def prep(series):
    s = dict(series); s["_keys"] = sorted(k for k in series)
    return s


# ---------------------------------------------------------------- A
def ibs_variant(days, mode):
    out, i = [], 25
    closes = [d["c"] for d in days]
    while i < len(days) - 1:
        hi10 = max(d["h"] for d in days[i - 9:i + 1])
        ar = sum(d["h"] - d["l"] for d in days[i - 24:i + 1]) / 25
        c = days[i]
        rng = c["h"] - c["l"]
        ok = rng > 0 and ar > 0 and c["c"] < hi10 - 2.5 * ar and (c["c"] - c["l"]) / rng < 0.3
        if ok and mode == "A3":
            ok = i >= 200 and c["c"] >= sum(closes[i - 199:i + 1]) / 200
        if ok:
            j = i + 1
            while j < len(days):
                if days[j]["c"] > days[j - 1]["h"]:
                    break
                if mode == "A1" and j - i >= 10:
                    break
                if mode == "A2" and days[j]["c"] < c["c"] - 3 * ar:
                    break
                j += 1
            if j >= len(days):
                break
            x = days[j]
            out.append({"t": x["t_close"], "r": (x["c"] - c["c"] - 1e-4 * c["c"]) / ar})
            i = j + 1
            continue
        i += 1
    return out


def risk_stats(tr):
    tr = sorted(tr, key=lambda t: t["t"])
    eq, peak, dd = 0.0, 0.0, 0.0
    for t in tr:
        eq += t["r"]; peak = max(peak, eq); dd = max(dd, peak - eq)
    rs = [t["r"] for t in tr]
    return {"n": len(rs), "avg": st.mean(rs), "worst": min(rs), "dd": dd}


def group_a():
    print("A. US index rebounds: tail protection")
    days_by = {}
    for n in US4:
        s = M.sessions(n)
        days_by[n] = [dict(s[d], t_close=s[d]["t"]) for d in sorted(s)]
    split = datetime(2019, 1, 1, tzinfo=UTC)
    res = {}
    for mode in ("base", "A1", "A2", "A3"):
        tr = [t for n in US4 for t in ibs_variant(days_by[n], mode)]
        res[mode] = (risk_stats(tr), risk_stats([t for t in tr if t["t"] < split]),
                     risk_stats([t for t in tr if t["t"] >= split]))
    b = res["base"]
    rows = []
    for mode in ("base", "A1", "A2", "A3"):
        a, h1, h2 = res[mode]
        ok = ""
        if mode != "base":
            ok = ("PASS" if a["dd"] <= 0.75 * b[0]["dd"] and a["worst"] >= 0.75 * b[0]["worst"]
                  and a["avg"] >= 0.9 * b[0]["avg"] and h1["dd"] < b[1]["dd"] and h2["dd"] < b[2]["dd"] else "fail")
        print(f"  {mode:5s} n={a['n']:4d} avg={a['avg']:+.3f}R worst={a['worst']:+.2f}R maxDD={a['dd']:.1f}R | "
              f"2012-18 DD {h1['dd']:.1f}R | 2019-26 DD {h2['dd']:.1f}R {ok}")
        rows.append({"test": mode, **{k: round(v, 3) for k, v in a.items()}, "dd_h1": round(h1["dd"], 1),
                     "dd_h2": round(h2["dd"], 1), "verdict": ok})
    return rows


# ---------------------------------------------------------------- B
def group_b():
    print("\nB. Gold trend: macro filters")
    now = datetime.now(UTC)
    jg = SS.replay(S.CONFIG, S.closed_h1(S.load_history(S.CONFIG), now))
    trades = [{"t": datetime.fromisoformat(j["sig_time"]), "d": j["dir"], "r": j["r"]}
              for j in jg if j.get("strategy", "trend") == "trend"]
    ry, usd, gvz, cot = prep(fred("DFII10")), prep(fred("DTWEXBGS")), prep(fred("GVZCLS")), prep(cot_gold())

    def change20(s, d):
        i, k = asof(s, d - timedelta(days=1))           # the last full day before the signal
        if i is None or i < 20:
            return None
        return s[k] - s[s["_keys"][i - 20]]

    rows = []
    defs = {
        "B1 real yields agree": lambda t: (lambda c: None if c is None else (c < 0) == (t["d"] == 1))(change20(ry, t["t"].date())),
        "B2 dollar agrees": lambda t: (lambda c: None if c is None else (c < 0) == (t["d"] == 1))(change20(usd, t["t"].date())),
    }

    def cot_ok(t):
        i, k = asof(cot, t["t"].date())
        if i is None or i < 156:
            return None
        hist = [cot[cot["_keys"][j]] for j in range(i - 156, i)]
        lo, hi = np.percentile(hist, 10), np.percentile(hist, 90)
        v = cot[k]
        return not ((t["d"] == 1 and v >= hi) or (t["d"] == -1 and v <= lo))

    def gvz_hi(t):
        i, k = asof(gvz, t["t"].date() - timedelta(days=1))
        if i is None or i < 252:
            return None
        return gvz[k] > st.median(gvz[gvz["_keys"][j]] for j in range(i - 252, i))

    defs["B3 not with an extreme crowd"] = cot_ok
    defs["B4 gold volatility high"] = gvz_hi
    for name, fn in defs.items():
        tr = [dict(t, flag=fn(t)) for t in trades]
        tr = [t for t in tr if t["flag"] is not None]
        a = [t for t in tr if t["flag"]]; b = [t for t in tr if not t["flag"]]
        ra, rb = [t["r"] for t in a], [t["r"] for t in b]
        va, vb = st.variance(ra) / len(ra), st.variance(rb) / len(rb)
        tstat = (st.mean(ra) - st.mean(rb)) / math.sqrt(va + vb)
        p = 0.5 * math.erfc(tstat / math.sqrt(2))
        if name.startswith("B4"):
            p = math.erfc(abs(tstat) / math.sqrt(2))
        per, wins = [], 0
        for pn, lo, hi in M.PERIODS:
            xa = [t["r"] for t in a if lo <= t["t"] < hi]; xb = [t["r"] for t in b if lo <= t["t"] < hi]
            if len(xa) >= 10 and len(xb) >= 10:
                wins += (st.mean(xa) > st.mean(xb)) if not name.startswith("B4") or tstat > 0 else (st.mean(xa) < st.mean(xb))
            per.append((pn, len(xa), st.mean(xa) if xa else None))
        fav = a if (not name.startswith("B4") or tstat >= 0) else b
        counted = [m for _pn, n, m in per if n >= 10]
        ok = len(fav) >= 100 and wins >= 3 and p < ALPHA and all(
            st.mean([t["r"] for t in fav if lo <= t["t"] < hi]) > 0 for pn, lo, hi in M.PERIODS
            if len([t for t in fav if lo <= t["t"] < hi]) >= 10)
        print(f"  {name:30s} favoured n={len(a):3d} avg={st.mean(ra):+.3f}R | rest n={len(b):3d} avg={st.mean(rb):+.3f}R | "
              f"t={tstat:+.2f} p={p:.2g} | periods favoured ahead {wins}/4 | {'PASS' if ok else 'fail'}")
        rows.append({"test": name, "n_fav": len(a), "avg_fav": round(st.mean(ra), 3), "n_rest": len(b),
                     "avg_rest": round(st.mean(rb), 3), "t": round(tstat, 2), "p": f"{p:.2g}",
                     "verdict": "PASS" if ok else "fail"})
    return rows


# ---------------------------------------------------------------- C
def group_c():
    print("\nC. Sizing on the five-strategy portfolio")
    raw = {k: P.monthly(v) for k, v in P.streams().items()}
    names = list(raw)
    first = max(min(v) for v in raw.values()); last = min(max(v) for v in raw.values())
    months, (y, m) = [], first
    while (y, m) <= last:
        months.append((y, m)); y, m = (y + (m == 12), m % 12 + 1)
    X = np.array([[raw[k].get(mm, 0.0) for k in names] for mm in months])
    # full history per stream, for trailing volatility before the window starts
    allm = sorted(set().union(*raw.values()))
    full = {k: [raw[k].get(mm, 0.0) for mm in allm] for k in names}
    pos = {mm: i for i, mm in enumerate(allm)}
    h = len(months) // 2
    inv = 1 / X[:h].std(axis=0, ddof=1); base_w = inv / inv.sum() * len(names)

    def sharpe(x):
        return float(np.mean(x) / np.std(x, ddof=1) * np.sqrt(12))

    def maxdd(x):
        eq = np.concatenate([[0], np.cumsum(x)]); return float(np.max(np.maximum.accumulate(eq) - eq))

    base = X @ base_w
    c1 = np.zeros(len(months))
    for t, mm in enumerate(months):
        i = pos[mm]
        for j, k in enumerate(names):
            s = full[k]
            v36 = np.std(s[max(0, i - 36):i], ddof=1) if i >= 12 else 0
            v6 = np.std(s[max(0, i - 6):i], ddof=1) if i >= 6 else 0
            mult = min(2.0, max(0.5, v36 / v6)) if v6 > 0 and v36 > 0 else 1.0
            c1[t] += X[t, j] * base_w[j] * mult
    c2 = np.zeros(len(months))
    eq = np.zeros(len(names)); peak = np.zeros(len(names))
    for t in range(len(months)):
        for j in range(len(names)):
            w = base_w[j] * (0.5 if peak[j] - eq[j] > 10 else 1.0)
            c2[t] += X[t, j] * w
            eq[j] += X[t, j] * w; peak[j] = max(peak[j], eq[j])
    rows = []
    for label, x in (("base (risk parity)", base), ("C1 volatility targeting", c1), ("C2 drawdown brake", c2)):
        s1, s2, d1, d2 = sharpe(x[:h]), sharpe(x[h:]), maxdd(x[:h]), maxdd(x[h:])
        ok = ""
        if label != "base (risk parity)":
            ok = "PASS" if s1 > sharpe(base[:h]) and s2 > sharpe(base[h:]) and d1 <= maxdd(base[:h]) and d2 <= maxdd(base[h:]) else "fail"
        print(f"  {label:26s} Sharpe {sharpe(x):.2f} (halves {s1:.2f} / {s2:.2f}) | worst drop {maxdd(x):.1f}R "
              f"(halves {d1:.1f} / {d2:.1f}) | {np.mean(x):+.2f}R a month {ok}")
        rows.append({"test": label, "sharpe": round(sharpe(x), 2), "sharpe_h1": round(s1, 2), "sharpe_h2": round(s2, 2),
                     "maxdd": round(maxdd(x), 1), "dd_h1": round(d1, 1), "dd_h2": round(d2, 1), "verdict": ok})
    return rows


def main():
    out = {"A": group_a(), "B": group_b(), "C": group_c()}
    with open(os.path.join(HERE, "results_round20_risk_macro_sizing.json"), "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
