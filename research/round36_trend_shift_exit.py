"""Round 36: take the second half off when the trend shifts after TP1
(pre-registered 25 Nov 2026, before either exit was simulated).

Bradley asked whether the bot could tell members to think about taking profits
early when a gold trend trade has hit TP1, has its stop at entry, and the trend
is turning against it, making TP2 less likely. A heads-up like that only helps
if members who act on it end up ahead, so the test simulates acting on it:
the second half is closed at the close of the hourly candle where the shift is
seen. Two definitions of "the trend is shifting"; hypotheses_tested rises by 2.

Neither has been tested before. Round 24 X2 trailed the second half with a
chandelier stop (a price rule, not a trend-turn rule), and the old exit_mode
"ha" closed the whole trade on any opposite hourly candle from the fill, before
any profit was booked. Here nothing changes until TP1 has been banked.

Method. As round 24: the entries, stops and costs are the live ones, every gold
trend trade the live state machine takes (research/similar_setups.replay with
signals.CONFIG), re-run from its fill with the live bar order (on the fill bar
only the stop is checked; afterwards the stop first, then TP1, then TP2). The
base re-run must reproduce the live state machine's R on every trade, or the
test is void. Entries are held fixed, so each trade is compared with itself.
The shift check runs at the close of each hourly candle after the one where TP1
was hit, and only if neither the stop nor TP2 was hit on that candle first.

  T1 4-hour turn: after TP1, close the second half at the hourly close once the
     latest completed 4-hour Heikin Ashi candle is against the trade (red for a
     buy, green for a sell). This is the same 4-hour check the entry requires
     to agree.
  T2 Hourly turn: after TP1, close the second half at the close of the first
     hourly Heikin Ashi candle against the trade.

Pass, per test: on 2008-2026 the average per-trade gain (variant R minus base
R) is above zero with a one-sided paired t-test p < 0.05 / 2 = 0.025, and the
gain is positive in each of 2008-15, 2016-24 and 2025-26. The 2004-07 sealed
period (data/xauusd_h1_2003_2007.csv.gz, round 27) is reported as a further
check and must not be negative. A pass goes to Bradley as a proposed alert;
nothing changes the live alerts without his decision and a separate
end-to-end-checked change.
"""
import csv
import gzip
import json
import math
import os
import statistics as st
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import similar_setups as SS  # noqa: E402

UTC = timezone.utc
ALPHA = 0.05 / 2
D = lambda y: datetime(y, 1, 1, tzinfo=UTC)
PERIODS = [("2008-15", D(2008), D(2016)), ("2016-24", D(2016), D(2025)), ("2025-26", D(2025), D(2030))]
LOCKBOX = ("2004-07", D(2004), D(2008))
OLD = os.path.join(ROOT, "data", "xauusd_h1_2003_2007.csv.gz")


def load_old():
    bars = []
    with gzip.open(OLD, "rt") as f:
        for r in csv.DictReader(f):
            t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            if h - l <= 0 and o == c:
                continue
            bars.append({"t": t, "o": o, "h": h, "l": l, "c": c})
    return bars


def against(candle, d):
    return S.bear(candle) if d == 1 else S.bull(candle)


def simulate(F, k, t, cfg, mode):
    """R of one trade filled on bar k. mode: base, t1, t2."""
    bars = F.h1
    d, entry, stop, risk = t["dir"], t["entry"], t["stop"], t["risk"]
    cost = cfg["cost_per_trade"]
    partial = entry + d * cfg["partial_r"] * risk
    target = entry + d * cfg["target_r"] * risk
    done = booked = 0.0
    tp1_bar = None
    for j in range(k, len(bars)):
        b = bars[j]
        hit_stop = b["l"] <= stop if d == 1 else b["h"] >= stop
        if j == k:
            if hit_stop:
                return booked + (1 - done) * (stop - entry) * d / risk - cost / risk
            continue
        if hit_stop:
            return booked + (1 - done) * (stop - entry) * d / risk - cost / risk
        if not done and (b["h"] >= partial if d == 1 else b["l"] <= partial):
            done, booked, stop = cfg["partial_frac"], cfg["partial_frac"] * cfg["partial_r"], entry
            tp1_bar = j
        if b["h"] >= target if d == 1 else b["l"] <= target:
            return booked + (1 - done) * (target - entry) * d / risk - cost / risk
        if done and tp1_bar is not None and j > tp1_bar:
            if mode == "t1":
                hk = F.h4_idx[j]
                turned = hk >= 0 and against(F.h4_ha[hk], d)
            elif mode == "t2":
                turned = against(F.ha[j], d)
            else:
                turned = False
            if turned:
                return booked + (1 - done) * (b["c"] - entry) * d / risk - cost / risk
    return None


def trades_for(cfg, bars, lo, hi):
    F = S.Features(bars, cfg)
    idx = {b["t"] + timedelta(hours=1): i for i, b in enumerate(bars)}
    out = []
    for j in SS.replay(cfg, bars):
        if j.get("strategy", "trend") != "trend" or not j.get("entry_time"):
            continue
        t0 = datetime.fromisoformat(j["sig_time"])
        if not lo <= t0 < hi:
            continue
        idea = j["idea"]
        out.append({"t": t0, "dir": idea["dir"], "entry": idea["entry"], "stop": idea["stop"],
                    "risk": idea["risk"], "r": j["r"], "k": idx[datetime.fromisoformat(j["entry_time"])]})
    return F, out


def check_base(F, trades, cfg, label):
    bad = 0
    for t in trades:
        t["base"] = simulate(F, t["k"], t, cfg, "base")
        if t["base"] is None or abs(t["base"] - t["r"]) > 0.002:
            bad += 1
    print(f"{label}: {len(trades)} gold trend trades; base re-run differs from the live state machine on {bad}")
    return bad == 0


def paired_p(g):
    m, sd = st.mean(g), st.stdev(g)
    tstat = m / (sd / math.sqrt(len(g))) if sd else 0.0
    return m, tstat, 0.5 * math.erfc(tstat / math.sqrt(2))


def main():
    cfg = S.CONFIG
    bars = S.closed_h1(S.load_history(cfg), datetime.now(UTC))
    F, trades = trades_for(cfg, bars, D(2008), D(2030))
    F0, old = trades_for(cfg, load_old(), *LOCKBOX[1:])
    if not (check_base(F, trades, cfg, "2008-26") and check_base(F0, old, cfg, "2004-07")):
        print("Base re-run does not reproduce the live rules: test void.")
        return
    rows = []
    for name, mode in [("T1 4-hour turn after TP1", "t1"), ("T2 hourly turn after TP1", "t2")]:
        for FF, ts in ((F, trades), (F0, old)):
            for t in ts:
                v = simulate(FF, t["k"], t, cfg, mode)
                t[mode] = None if v is None else v - t["base"]
        res = {"test": name}
        parts = []
        for pn, lo, hi in PERIODS:
            g = [t[mode] for t in trades if lo <= t["t"] < hi and t[mode] is not None]
            res[pn] = round(st.mean(g), 3)
            parts.append(f"{pn} {res[pn]:+.3f}R ({len(g)})")
        g0 = [t[mode] for t in old if t[mode] is not None]
        res["2004-07"] = round(st.mean(g0), 3)
        parts.append(f"2004-07 {res['2004-07']:+.3f}R ({len(g0)})")
        g = [t[mode] for t in trades if t[mode] is not None]
        m, tstat, p = paired_p(g)
        changed = sum(1 for x in g if abs(x) > 1e-9)
        ok = m > 0 and p < ALPHA and all(res[pn] > 0 for pn, _, _ in PERIODS) and res["2004-07"] >= 0
        base = st.mean(t["base"] for t in trades)
        print(f"  {name:28s} n={len(g)} changed={changed} gain {m:+.3f}R/trade (base {base:+.3f}R) "
              f"t={tstat:+.2f} p={p:.2g} | " + " | ".join(parts) + f" | {'PASS' if ok else 'fail'}")
        res.update(n=len(g), changed=changed, gain=round(m, 3), base=round(base, 3), t=round(tstat, 2),
                   p=f"{p:.2g}", verdict="PASS" if ok else "fail")
        rows.append(res)
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round36_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
