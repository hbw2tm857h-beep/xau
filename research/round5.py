"""Round 5: everything else open-source that could add edge to the live rules.

The live rules now include the 4H Ichimoku cloud check (round 4), so that is
the baseline every idea has to beat. Everything below was fixed BEFORE any
result was seen: authors' default settings, no tuning on gold.

Part A - 21 more TradingView indicators (tv_indicators2.py), each tested as
         an H1 filter, a 4H filter and a replacement trigger; plus 2
         non-directional regime filters (Choppiness, squeeze released) on H1/4H.
Part B - calendar filters:
         skip Mondays | skip Fridays | skip the 28th onwards (month-end flows)
         | skip the first Friday of the month (US jobs report) | trade with the
         published intraday "hat" seasonality (no longs signalled 13-21 UTC,
         no shorts signalled 00-08 UTC).
Part C - other markets as filters (gold is priced in dollars):
         USD index (equal-weight EUR, GBP, AUD, JPY vs USD) below/above its
         50-day EMA | USD 20-day momentum against the trade | USD 4H Heikin Ashi
         candle against the trade | silver daily trend agrees | silver 4H Heikin
         Ashi candle agrees.

Adoption (stricter than round 4 because far more ideas are tried here):
  1. Stage 1: average R better than the live rules by > 0.02 in BOTH 2016-22
     and 2023-24, keeping at least 60% of the 2016-22 trades.
  2. Stage 2: also better than the live rules in 2008-15 AND 2025-26.
  3. Stage 3, over 2008-26: total R must not fall, and dropping the same number
     of the live trades at random must match the gain in < 0.1% of 10,000 tries.
Anything that passes all three is a candidate. Only one change is adopted per
round, and only if it is not a near-copy of what's already in the rules.
"""
import bisect
import csv
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import signals as S  # noqa: E402
import tv_indicators as T1  # noqa: E402
import tv_indicators2 as T2  # noqa: E402

UTC = timezone.utc
DATA = os.path.join(HERE, "..", "data")
BASE_P = {"session": False, "h4": True, "breakout": False, "swing": 5}
M = {"part_r": 1.0, "part_frac": 0.5, "target_r": 2.0}
D = lambda y: datetime(y, 1, 1, tzinfo=UTC)
PERIODS = {"tune": ("new", D(2016), D(2023)), "val": ("new", D(2023), D(2025)),
           "2008-15": ("old", D(2008), D(2016)), "2025-26": ("new", D(2025), D(2030))}


# --------------------------------------------------------------------------
# Generators
# --------------------------------------------------------------------------
def gen_pred(lab, p):
    """Live-rule signals that also satisfy pred(i, d)."""
    pred = p["pred"]
    for sig in lab.base_sigs:
        if pred(sig[0], sig[1]):
            yield sig


def gen_trig(lab, p):
    """Fresh H1 flip of `ind` (None = Heikin Ashi colour flip) with the live
    daily trend, 4H Heikin Ashi and 4H cloud agreement; live stop/entry/exits."""
    F, b, arr = lab.F, lab.b, p.get("ind")
    for i in range(2, len(b)):
        if not F.warm(i):
            continue
        for d in (1, -1):
            if arr is None:
                x, px = F.ha[i], F.ha[i - 1]
                flip = (S.bull(x) and S.bear(px)) if d == 1 else (S.bear(x) and S.bull(px))
            else:
                flip = arr[i] == d and arr[i - 1] != d
            if not flip or lab.trend(i) != d:
                continue
            k = F.h4_idx[i]
            c4 = F.h4_ha[k]
            if not (S.bull(c4) if d == 1 else S.bear(c4)) or F.h4_cloud[k] != d:
                continue
            sw = b[max(0, i - 4):i + 1]; hatr = F.hatr[i] or 0
            if d == 1:
                entry, stop = b[i]["h"] + 0.3, min(z["l"] for z in sw) - 0.2 * hatr
            else:
                entry, stop = b[i]["l"] - 0.3, max(z["h"] for z in sw) + 0.2 * hatr
            yield i, d, entry, stop, 12, False
            break


L.FAMILIES["pred"] = gen_pred
L.FAMILIES["trig"] = gen_trig


# --------------------------------------------------------------------------
# Other markets
# --------------------------------------------------------------------------
def load_closes(name):
    out = {}
    with open(os.path.join(DATA, name)) as f:
        for r in csv.DictReader(f):
            out[datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)] = float(r["close"])
    return out


def usd_index():
    """Equal-weight USD index from H1 closes: log-returns of USDJPY, minus those
    of EURUSD, GBPUSD and AUDUSD, averaged and cumulated."""
    pairs = {"eurusd_h1.csv": -1, "gbpusd_h1.csv": -1, "audusd_h1.csv": -1, "usdjpy_h1.csv": 1}
    series = {k: load_closes(k) for k in pairs}
    times = sorted(set().union(*[set(s) for s in series.values()]))
    last = {k: None for k in pairs}
    lvl, out = 0.0, []
    for t in times:
        rets = []
        for k, sgn in pairs.items():
            v = series[k].get(t)
            if v is None:
                continue
            if last[k] is not None:
                rets.append(sgn * math.log(v / last[k]))
            last[k] = v
        if rets:
            lvl += sum(rets) / len(rets)
            out.append({"t": t, "c": lvl})
    for j, x in enumerate(out):  # synthetic OHLC so it can be grouped into 4H candles
        po = out[j - 1]["c"] if j else x["c"]
        x.update(o=po, h=max(po, x["c"]), l=min(po, x["c"]))
    return out


def silver_bars():
    bars = []
    with open(os.path.join(DATA, "xagusd_h1.csv")) as f:
        for r in csv.DictReader(f):
            t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            o, h, l, c = (float(r[k]) for k in ("open", "high", "low", "close"))
            if h - l <= 0 and o == c:
                continue
            bars.append({"t": t, "o": o, "h": h, "l": l, "c": c})
    return bars


class Market:
    """An H1 series looked up by time, with only closed data visible."""

    def __init__(self, bars):
        self.b = bars
        self.t = [x["t"] for x in bars]
        c = [x["c"] for x in bars]
        self.ema1200 = L.ema_series(c, 1200)          # ~50 trading days of H1 candles
        self.c = c
        self.h4 = S.aggregate(bars, S.h4_key, S.h4_end)
        self.h4_ha = S.heikin_ashi(self.h4)
        self.h4_end = [x["end"] for x in self.h4]
        self.daily = S.aggregate(bars, S.trading_day, S.day_end)
        self.d_end = [x["end"] for x in self.daily]
        cfg = dict(S.CONFIG)
        self.d_trend = [S.daily_trend(self.daily[max(0, k - 150):k + 1], cfg) for k in range(len(self.daily))]

    def idx(self, close_time):
        """Last H1 candle that has closed by close_time."""
        return bisect.bisect_right(self.t, close_time - S.H1) - 1

    def h4_dir(self, close_time):
        k = bisect.bisect_right(self.h4_end, close_time) - 1
        if k < 0:
            return 0
        x = self.h4_ha[k]
        return 1 if S.bull(x) else -1 if S.bear(x) else 0

    def day_trend(self, close_time):
        k = bisect.bisect_right(self.d_end, close_time) - 1
        return self.d_trend[k] if k >= 0 else 0


# --------------------------------------------------------------------------
class Dataset:
    def __init__(self, path):
        self.lab = L.Lab(L.load(path))
        self.lab.base_sigs = list(L.gen_ha(self.lab, BASE_P))
        self.cache = {}

    def ind(self, key, fn, tf):
        if key not in self.cache:
            bars = self.lab.b if tf == "h1" else self.lab.F.h4
            self.cache[key] = np.asarray(T1.compute(bars, fn))
        return self.cache[key]

    def close_time(self, i):
        return self.lab.b[i]["t"] + S.H1


def make_tests(ds, usd, ag):
    lab, F = ds.lab, ds.lab.F
    h4i = F.h4_idx
    tests = []

    def ind_pred(arr, tf, nondir=False):
        if nondir:
            return (lambda i, d: arr[i] == 1) if tf == "h1" else (lambda i, d: arr[h4i[i]] == 1)
        return (lambda i, d: arr[i] == d) if tf == "h1" else (lambda i, d: arr[h4i[i]] == d)

    # Part A
    for name, fn in T2.INDICATORS.items():
        for tf in ("h1", "h4"):
            tests.append(("A", f"{name} | filter {tf.upper()}", "pred", {"pred": ind_pred(ds.ind((name, tf), fn, tf), tf)}))
        tests.append(("A", f"{name} | trigger", "trig", {"ind": ds.ind((name, "h1"), fn, "h1")}))
    for name, fn in T2.NONDIR.items():
        for tf in ("h1", "h4"):
            tests.append(("A", f"{name} | filter {tf.upper()}", "pred", {"pred": ind_pred(ds.ind((name, tf), fn, tf), tf, True)}))

    # Part B
    def utc(i):
        return lab.b[i]["t"]  # candle open time; the signal is at its close
    ct = lambda i: utc(i) + S.H1
    tests += [
        ("B", "Skip Mondays", "pred", {"pred": lambda i, d: ct(i).astimezone(S.NY).weekday() != 0}),
        ("B", "Skip Fridays", "pred", {"pred": lambda i, d: ct(i).astimezone(S.NY).weekday() != 4}),
        ("B", "Skip the 28th onwards", "pred", {"pred": lambda i, d: ct(i).astimezone(S.NY).day < 28}),
        ("B", "Skip first Friday (US jobs report)", "pred",
         {"pred": lambda i, d: not (ct(i).astimezone(S.NY).weekday() == 4 and ct(i).astimezone(S.NY).day <= 7)}),
        ("B", "Intraday seasonality (no longs 13-21 UTC, no shorts 00-08 UTC)", "pred",
         {"pred": lambda i, d: not ((d == 1 and 13 <= utc(i).hour < 21) or (d == -1 and utc(i).hour < 8))}),
    ]

    # Part C
    def usd_trend(i):
        j = usd.idx(ct(i))
        if j < 0 or usd.ema1200[j] is None:
            return 0
        return 1 if usd.c[j] > usd.ema1200[j] else -1

    def usd_mom(i):
        j = usd.idx(ct(i))
        if j < 480:
            return 0
        return 1 if usd.c[j] > usd.c[j - 480] else -1

    tests += [
        ("C", "USD index vs 50-day EMA against the trade", "pred", {"pred": lambda i, d: usd_trend(i) == -d}),
        ("C", "USD 20-day momentum against the trade", "pred", {"pred": lambda i, d: usd_mom(i) == -d}),
        ("C", "USD 4H Heikin Ashi against the trade", "pred", {"pred": lambda i, d: usd.h4_dir(ct(i)) == -d}),
        ("C", "Silver daily trend agrees", "pred", {"pred": lambda i, d: ag.day_trend(ct(i)) == d}),
        ("C", "Silver 4H Heikin Ashi agrees", "pred", {"pred": lambda i, d: ag.h4_dir(ct(i)) == d}),
    ]
    return tests


def period_stats(trades, a, b):
    return S.stats([t["r"] for t in trades if a <= t["t"] < b])


def perm_p(base_rs, n_keep, gain, tries=10000, seed=7):
    """Share of random same-size subsets of the live trades whose average R
    beats the live average by at least `gain`."""
    rnd = random.Random(seed); base_avg = sum(base_rs) / len(base_rs); hit = 0
    for _ in range(tries):
        sub = rnd.sample(base_rs, n_keep)
        if sum(sub) / n_keep - base_avg >= gain:
            hit += 1
    return hit / tries


def main():
    new = Dataset(os.path.join(DATA, "xauusd_h1.csv"))
    old = Dataset(os.path.join(DATA, "xauusd_h1_2008_2015.csv"))
    usd, ag = Market(usd_index()), Market(silver_bars())
    sets = {"new": new, "old": old}
    tests_by = {k: make_tests(ds, usd, ag) for k, ds in sets.items()}

    def run(k, fam, p):
        if fam == "live":
            return L.backtest(sets[k].lab, "ha", BASE_P, M)
        return L.backtest(sets[k].lab, fam, p, M)

    base = {k: run(k, "live", None) for k in sets}
    bstat = {pk: period_stats(base[src], a, b) for pk, (src, a, b) in PERIODS.items()}
    base_all = [t["r"] for t in base["old"] if t["t"] < D(2016)] + [t["r"] for t in base["new"]]
    print(f"Live rules: " + " | ".join(f"{pk} n={s['n']} {s['avg']:+.3f}" for pk, s in bstat.items())
          + f" | 2008-26 n={len(base_all)} total {sum(base_all):+.1f}R avg {sum(base_all)/len(base_all):+.3f}")

    rows = [{"part": "-", "test": "Live rules (baseline, includes 4H cloud)",
             **{f"{pk}_n": s["n"] for pk, s in bstat.items()},
             **{f"{pk}_R": round(s["avg"], 3) for pk, s in bstat.items()},
             "all_n": len(base_all), "all_total": round(sum(base_all), 1)}]
    for idx, (part, label, fam, p_new) in enumerate(tests_by["new"]):
        tr_new = run("new", fam, p_new)
        st = {pk: period_stats(tr_new, a, b) for pk, (src, a, b) in PERIODS.items() if src == "new"}
        dt = st["tune"].get("avg", -9) - bstat["tune"]["avg"]
        dv = st["val"].get("avg", -9) - bstat["val"]["avg"]
        s1 = dt > 0.02 and dv > 0.02 and st["tune"].get("n", 0) >= 0.6 * bstat["tune"]["n"]
        row = {"part": part, "test": label,
               **{f"{pk}_n": s.get("n", 0) for pk, s in st.items()},
               **{f"{pk}_R": round(s.get("avg", 0), 3) for pk, s in st.items()},
               "d_tune": round(dt, 3), "d_val": round(dv, 3), "stage1": "PASS" if s1 else ""}
        verdict = ""
        if s1:
            tr_old = run("old", fam, tests_by["old"][idx][3])
            so = period_stats(tr_old, D(2008), D(2016))
            row["2008-15_n"], row["2008-15_R"] = so.get("n", 0), round(so.get("avg", 0), 3)
            s2 = so.get("avg", -9) > bstat["2008-15"]["avg"] and st["2025-26"].get("avg", -9) > bstat["2025-26"]["avg"]
            row["stage2"] = "PASS" if s2 else "fail"
            allr = [t["r"] for t in tr_old if t["t"] < D(2016)] + [t["r"] for t in tr_new]
            row["all_n"], row["all_total"] = len(allr), round(sum(allr), 1)
            if s2:
                gain = sum(allr) / len(allr) - sum(base_all) / len(base_all)
                p = perm_p(base_all, min(len(allr), len(base_all)), gain)
                row["perm_p"] = p
                s3 = sum(allr) >= sum(base_all) and p < 0.001
                row["stage3"] = "PASS" if s3 else "fail"
            verdict = f" | 08-15 {row['2008-15_R']:+.3f} -> {row.get('stage2')}" + \
                      (f" | all n={row['all_n']} total {row['all_total']:+.1f}R p={row.get('perm_p')} -> {row.get('stage3')}" if "perm_p" in row else "")
        rows.append(row)
        print(f"[{part}] {label:58s} T n={row['tune_n']:3d} {row['tune_R']:+.3f} | V n={row['val_n']:3d} {row['val_R']:+.3f} | "
              f"dT={dt:+.3f} dV={dv:+.3f} {row['stage1']}{verdict}", flush=True)

    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(HERE, "results_round5.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, lineterminator="\n"); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
