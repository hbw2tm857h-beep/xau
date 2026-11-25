"""Round 37: five inputs the candles don't contain (pre-registered 25 Nov 2026,
before any of them was joined to a trade).

Bradley asked for more creative ways to find a concrete edge. 36 rounds and
1,403 hypotheses have searched gold's own candles; nearly every filter on the
trend rules failed because the multi-timeframe checks already carry what price
says. This round tries information the candles don't hold, or flows forced by
a known schedule. None of the five has been tested in rounds 1-36.
hypotheses_tested rises from 1,403 to 1,408.

Trades. T1-T4 use every gold trend trade the live state machine takes
(research/similar_setups.replay with signals.CONFIG): 2008-26 from the live
history files and 2004-07 from round 27's sealed file. T5 is a standalone rule
on hourly candles from 2008, when the FX files start.

  T1 Gold ETF flows. SPDR Gold Shares (GLD) publishes the tonnes it holds each
     day. The flow is the change in tonnes over the last 5 published days. A
     day's figure is used only from 12:00 UTC the next calendar day, after it
     has been published. Trades whose direction agrees with the flow's sign are
     compared with trades against it (zero flow excluded). GLD starts Nov 2004.
  T2 Round-number stops. Stop orders bunch just beyond round prices and price
     tends to run them (Osler 2003, FX). Round prices are multiples of $10 below
     $2,000 and of $25 from $2,000. A trade's stop is "exposed" when a round
     price lies between the stop and 0.2R inside it (above a buy's stop, below a
     sell's), so our stop sits just beyond it with the crowd's. Exposed trades
     move the stop a further 0.25R out; TP1 and TP2 are recomputed from the new
     risk and the trade is sized to the new risk, so R stays comparable. Each
     exposed trade is re-run from its fill with the live bar order (round 24's
     method) and compared with itself.
  T3 COMEX gold options expiry. Monthly gold options stop trading on the 4th
     last business day of the month, or the business day before if that is a
     Friday or the day before a holiday. Business days here are weekdays (US
     holidays are ignored, an approximation stated now). Trades signalled on the
     expiry day or the business day before it are compared with the rest.
  T4 Chinese demand calendar. Physical buying peaks before the two long Chinese
     closures and stops during them. The window is 10 days before to 7 days
     after Lunar New Year's day, and 21 September to 7 October (Golden Week).
     Trades signalled in the window are compared with the rest.
  T5 The dollar moves first. An equal-weight USD index is built from EURUSD,
     GBPUSD, AUDUSD and USDJPY hourly closes (round 5's method). On each closed
     gold hour, with the previous 500 hours' standard deviation of the USD
     index's hourly move and gold's beta to it: if the dollar moved more than 2
     standard deviations this hour and gold moved less than half the move its
     beta implies (in the implied direction), buy or sell gold at the close in
     the implied direction and close 3 hours later. One trade at a time; cost
     1.75 basis points a trade (round 10's gold cost).

Pass. T1, T3, T4: the difference in average R (group minus the rest) has a
two-sided Welch p < 0.05 / 5 = 0.01 on 2008-26, and the same sign in each of
2008-15, 2016-24 and 2025-26 and in 2004-07, counting only periods with at least
5 trades in the group. T2: the paired gain on exposed trades is above zero with
one-sided p < 0.01 on 2008-26 and positive in each of those periods. T5: at
least 100 trades, average return after costs above zero with one-sided p < 0.01
on daily-summed returns, and positive in 2008-15, 2016-24 and 2025-26.

A pass goes to Bradley as a proposal; nothing changes the live alerts without
his decision and a separate end-to-end-checked change. Research only: the
hypotheses_tested counter in signals.py is not touched.

The GLD file's terms bar redistribution, so it is downloaded at run time into
data/macro/gld_holdings.csv, which is gitignored and never committed.
"""
import bisect
import csv
import gzip
import io
import json
import math
import os
import re
import statistics as st
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import similar_setups as SS  # noqa: E402

UTC = timezone.utc
ALPHA = 0.05 / 5
D = lambda y: datetime(y, 1, 1, tzinfo=UTC)
PERIODS = [("2008-15", D(2008), D(2016)), ("2016-24", D(2016), D(2025)), ("2025-26", D(2025), D(2030))]
OLD = ("2004-07", D(2004), D(2008))
DATA = os.path.join(ROOT, "data")
GLD_CSV = os.path.join(DATA, "macro", "gld_holdings.csv")
GLD_URL = "https://api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en"
CNY = ["2004-01-22", "2005-02-09", "2006-01-29", "2007-02-18", "2008-02-07", "2009-01-26", "2010-02-14",
       "2011-02-03", "2012-01-23", "2013-02-10", "2014-01-31", "2015-02-19", "2016-02-08", "2017-01-28",
       "2018-02-16", "2019-02-05", "2020-01-25", "2021-02-12", "2022-02-01", "2023-01-22", "2024-02-10",
       "2025-01-29", "2026-02-17"]


# ----------------------------------------------------------------- data
def load_csv_bars(path):
    opener = gzip.open if path.endswith(".gz") else open
    bars = []
    with opener(path, "rt") as f:
        for r in csv.DictReader(f):
            t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            if h - l <= 0 and o == c:
                continue
            bars.append({"t": t, "o": o, "h": h, "l": l, "c": c})
    return bars


def gld_holdings():
    """[(date, tonnes)] from SPDR's archive, cached locally (not committed)."""
    if not os.path.exists(GLD_CSV):
        req = urllib.request.Request(GLD_URL, headers={"User-Agent": "Mozilla/5.0"})
        z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(req, timeout=60).read()))
        ss = [re.sub(r"<[^>]+>", "", s) for s in
              re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)]
        rows = []
        for r in re.findall(r"<row[^>]*>(.*?)</row>", z.read("xl/worksheets/sheet2.xml").decode(), re.S):
            cells = [ss[int(v)] if 't="s"' in a else v
                     for a, v in re.findall(r"<c ([^>]*)>(?:<f>.*?</f>)?<v>(.*?)</v>", r)]
            rows.append(cells)
        head = rows[0]
        di, ti = head.index("Date"), head.index("Tonnes of Gold")
        out = []
        for c in rows[1:]:
            try:
                out.append((datetime.strptime(c[di], "%d-%b-%Y").date(), float(c[ti])))
            except (ValueError, IndexError):
                continue
        os.makedirs(os.path.dirname(GLD_CSV), exist_ok=True)
        with open(GLD_CSV, "w") as f:
            f.write("date,tonnes\n" + "".join(f"{d},{t}\n" for d, t in out))
    with open(GLD_CSV) as f:
        return sorted((date.fromisoformat(r["date"]), float(r["tonnes"])) for r in csv.DictReader(f))


def usd_index():
    """Equal-weight USD index (round 5): {bar open time: cumulative log level}."""
    pairs = {"eurusd_h1.csv": -1, "gbpusd_h1.csv": -1, "audusd_h1.csv": -1, "usdjpy_h1.csv": 1}
    series = {}
    for k in pairs:
        with open(os.path.join(DATA, k)) as f:
            series[k] = {datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC): float(r["close"])
                         for r in csv.DictReader(f)}
    times = sorted(set().union(*[set(s) for s in series.values()]))
    last = {k: None for k in pairs}
    lvl, out = 0.0, {}
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
            out[t] = lvl
    return out


# ----------------------------------------------------------------- trades
def trend_trades(cfg, bars, lo, hi):
    F = S.Features(bars, cfg)
    idx = {b["t"] + timedelta(hours=1): i for i, b in enumerate(bars)}
    out = []
    for j in SS.replay(cfg, bars):
        if j.get("strategy", "trend") != "trend" or not j.get("entry_time"):
            continue
        t0 = datetime.fromisoformat(j["sig_time"])
        if lo <= t0 < hi:
            idea = j["idea"]
            out.append({"t": t0, "dir": idea["dir"], "entry": idea["entry"], "stop": idea["stop"],
                        "risk": idea["risk"], "r": j["r"], "k": idx[datetime.fromisoformat(j["entry_time"])]})
    return F, out


def simulate(bars, k, d, entry, stop, cfg):
    """R of one trade filled on bar k with the live exits, sized to |entry - stop|."""
    risk = abs(entry - stop)
    cost = cfg["cost_per_trade"]
    partial = entry + d * cfg["partial_r"] * risk
    target = entry + d * cfg["target_r"] * risk
    done = booked = 0.0
    for j in range(k, len(bars)):
        b = bars[j]
        if b["l"] <= stop if d == 1 else b["h"] >= stop:
            return booked + (1 - done) * (stop - entry) * d / risk - cost / risk
        if j == k:
            continue
        if not done and (b["h"] >= partial if d == 1 else b["l"] <= partial):
            done, booked, stop = cfg["partial_frac"], cfg["partial_frac"] * cfg["partial_r"], entry
        if b["h"] >= target if d == 1 else b["l"] <= target:
            return booked + (1 - done) * (target - entry) * d / risk - cost / risk
    return None


# ----------------------------------------------------------------- stats
def welch(a, b):
    ma, mb = st.mean(a), st.mean(b)
    va, vb = st.variance(a) / len(a), st.variance(b) / len(b)
    t = (ma - mb) / math.sqrt(va + vb)
    return ma - mb, t, math.erfc(abs(t) / math.sqrt(2))


def one_sided(x):
    m, sd = st.mean(x), st.stdev(x)
    t = m / (sd / math.sqrt(len(x))) if sd else 0.0
    return m, t, 0.5 * math.erfc(t / math.sqrt(2))


def split_test(name, groups):
    """groups: {period: (in_group R list, rest R list)}; 2008-26 pooled is the main test."""
    a = [r for p, _, _ in PERIODS for r in groups[p][0]]
    b = [r for p, _, _ in PERIODS for r in groups[p][1]]
    diff, t, p = welch(a, b)
    sign = 1 if diff > 0 else -1
    parts, same = [], True
    for pn in [x[0] for x in PERIODS] + [OLD[0]]:
        ga, gb = groups.get(pn, ([], []))
        if len(ga) >= 5 and len(gb) >= 5:
            dd = st.mean(ga) - st.mean(gb)
            same &= (dd > 0) == (sign > 0)
            parts.append(f"{pn} {st.mean(ga):+.3f} ({len(ga)}) vs {st.mean(gb):+.3f}")
        else:
            parts.append(f"{pn} n/a ({len(ga)})")
    ok = p < ALPHA and same
    print(f"  {name}\n     2008-26: {st.mean(a):+.3f}R ({len(a)}) vs {st.mean(b):+.3f}R ({len(b)}), "
          f"diff {diff:+.3f}R, p={p:.2g} | " + " | ".join(parts) + f" | {'PASS' if ok else 'fail'}")
    return {"test": name, "n_group": len(a), "n_rest": len(b), "group": round(st.mean(a), 3),
            "rest": round(st.mean(b), 3), "diff": round(diff, 3), "p": f"{p:.2g}", "periods": parts,
            "verdict": "PASS" if ok else "fail"}


def period_of(t):
    for pn, lo, hi in PERIODS + [OLD]:
        if lo <= t < hi:
            return pn
    return None


def grouped(trades, pred):
    g = {}
    for tr in trades:
        flag = pred(tr)
        if flag is None:
            continue
        a, b = g.setdefault(period_of(tr["t"]), ([], []))
        (a if flag else b).append(tr["r"])
    return g


# ----------------------------------------------------------------- tests
def t1_flows(trades):
    rows = gld_holdings()
    avail = [datetime.combine(d + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=12) for d, _ in rows]

    def agree(tr):
        k = bisect.bisect_right(avail, tr["t"]) - 1
        if k < 5:
            return None
        flow = rows[k][1] - rows[k - 5][1]
        return None if flow == 0 else (flow > 0) == (tr["dir"] == 1)
    return split_test("T1 trade agrees with the last 5 days of GLD flows", grouped(trades, agree))


def round_step(p):
    return 10.0 if p < 2000 else 25.0


def exposed(tr):
    d, s, r = tr["dir"], tr["stop"], tr["risk"]
    step = round_step(tr["entry"])
    lo, hi = (s, s + 0.2 * r) if d == 1 else (s - 0.2 * r, s)
    first = math.floor(lo / step) * step + step
    return first < hi if d == 1 else (math.ceil(hi / step) * step - step) > lo


def t2_round_stops(cfg, sets):
    gains = {}
    for bars, trades in sets:
        for tr in trades:
            if not exposed(tr):
                continue
            new_stop = tr["stop"] - tr["dir"] * 0.25 * tr["risk"]
            v = simulate(bars, tr["k"], tr["dir"], tr["entry"], new_stop, cfg)
            if v is not None:
                gains.setdefault(period_of(tr["t"]), []).append(v - tr["r"])
    allg = [x for p, _, _ in PERIODS for x in gains.get(p, [])]
    m, t, p = one_sided(allg)
    parts = [f"{pn} {st.mean(gains[pn]):+.3f}R ({len(gains[pn])})" if gains.get(pn) else f"{pn} n/a"
             for pn in [x[0] for x in PERIODS] + [OLD[0]]]
    ok = m > 0 and p < ALPHA and all(gains.get(pn) and st.mean(gains[pn]) > 0 for pn, _, _ in PERIODS)
    total = sum(len(v) for _, v in sets)
    print(f"  T2 move an exposed stop 0.25R beyond the round number\n     2008-26: {len(allg)} exposed, "
          f"gain {m:+.3f}R/trade, p={p:.2g} | " + " | ".join(parts) + f" | {'PASS' if ok else 'fail'}")
    return {"test": "T2 move an exposed stop 0.25R beyond the round number", "n_exposed": len(allg),
            "n_trades": total, "gain": round(m, 3), "p": f"{p:.2g}", "periods": parts,
            "verdict": "PASS" if ok else "fail"}


def expiry_days(y0, y1):
    out = set()
    for y in range(y0, y1 + 1):
        for m in range(1, 13):
            nxt = date(y + (m == 12), m % 12 + 1, 1)
            days = [nxt - timedelta(days=i) for i in range(1, 32)]
            biz = [x for x in days if x.month == m and x.weekday() < 5]
            e = biz[3]
            if e.weekday() == 4:
                e = biz[4]
            prev = e - timedelta(days=1)
            while prev.weekday() >= 5:
                prev -= timedelta(days=1)
            out |= {e, prev}
    return out


def t3_expiry(trades):
    ex = expiry_days(2003, 2026)
    return split_test("T3 signal on options expiry day or the day before",
                      grouped(trades, lambda tr: tr["t"].date() in ex))


def t4_china(trades):
    windows = [(date.fromisoformat(c) - timedelta(days=10), date.fromisoformat(c) + timedelta(days=7)) for c in CNY]
    windows += [(date(y, 9, 21), date(y, 10, 7)) for y in range(2003, 2027)]
    return split_test("T4 signal in the Chinese New Year or Golden Week window",
                      grouped(trades, lambda tr: any(a <= tr["t"].date() <= b for a, b in windows)))


def t5_dollar(gold):
    usd = usd_index()
    rows = []
    for i in range(1, len(gold)):
        a, b = gold[i - 1], gold[i]
        if b["t"] - a["t"] != timedelta(hours=1) or a["t"] not in usd or b["t"] not in usd:
            rows.append(None)
            continue
        rows.append((b, math.log(b["c"] / a["c"]), usd[b["t"]] - usd[a["t"]], i))
    trades, busy_until = [], -1
    win = []
    su = sg = suu = sug = 0.0
    for x in rows:
        if x is None:
            continue
        b, g, u, i = x
        if len(win) >= 500 and i > busy_until and i + 3 < len(gold):
            n = len(win)
            mu, mg = su / n, sg / n
            var = suu - n * mu * mu
            beta = (sug - n * mu * mg) / var if var > 0 else 0.0
            sd = math.sqrt(var / (n - 1)) if var > 0 else 0.0
            implied = beta * u
            if sd and abs(u) > 2 * sd and implied != 0 and g / implied < 0.5:
                d = 1 if implied > 0 else -1
                ex = gold[i + 3]
                if ex["t"] - b["t"] == timedelta(hours=3):
                    ret = d * (ex["c"] / b["c"] - 1) * 1e4 - 1.75
                    trades.append((b["t"] + timedelta(hours=1), ret))
                    busy_until = i + 3
        win.append((g, u))
        su += u; sg += g; suu += u * u; sug += u * g
        if len(win) > 500:
            og, ou = win.pop(0)
            su -= ou; sg -= og; suu -= ou * ou; sug -= ou * og
    daily = {}
    for t, r in trades:
        daily[t.date()] = daily.get(t.date(), 0.0) + r
    m, tstat, p = one_sided(list(daily.values()))
    per = {}
    for t, r in trades:
        per.setdefault(period_of(t), []).append(r)
    parts = [f"{pn} {st.mean(per[pn]):+.2f}bp ({len(per[pn])})" if per.get(pn) else f"{pn} n/a"
             for pn, _, _ in PERIODS]
    avg = st.mean(r for _, r in trades)
    ok = (len(trades) >= 100 and avg > 0 and p < ALPHA
          and all(per.get(pn) and st.mean(per[pn]) > 0 for pn, _, _ in PERIODS))
    print(f"  T5 gold catches up with a big dollar move\n     {len(trades)} trades, {avg:+.2f}bp a trade after "
          f"costs, p={p:.2g} (daily) | " + " | ".join(parts) + f" | {'PASS' if ok else 'fail'}")
    return {"test": "T5 gold catches up with a big dollar move", "n": len(trades), "avg_bp": round(avg, 2),
            "p": f"{p:.2g}", "periods": parts, "verdict": "PASS" if ok else "fail"}


def main():
    cfg = S.CONFIG
    bars = S.closed_h1(S.load_history(cfg), datetime.now(UTC))
    old_bars = load_csv_bars(os.path.join(DATA, "xauusd_h1_2003_2007.csv.gz"))
    F, new = trend_trades(cfg, bars, D(2008), D(2030))
    F0, old = trend_trades(cfg, old_bars, *OLD[1:])
    bad = sum(1 for bb, ts in ((bars, new), (old_bars, old)) for tr in ts
              if abs((simulate(bb, tr["k"], tr["dir"], tr["entry"], tr["stop"], cfg) or 99) - tr["r"]) > 0.002)
    print(f"{len(new)} trend trades 2008-26, {len(old)} in 2004-07; exit re-run differs from the live R on {bad}")
    trades = new + old
    rows = [t1_flows(trades), t2_round_stops(cfg, [(bars, new), (old_bars, old)]) if not bad else
            {"test": "T2", "verdict": "void"}, t3_expiry(trades), t4_china(trades), t5_dollar(bars)]
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round37_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
