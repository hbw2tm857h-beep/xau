"""Round 24: three exit changes for gold's trend trades, on data round 2 never
tuned on (pre-registered 20 Nov 2026, before any of these exits was simulated).

Bradley asked whether the stop and take-profits are as efficient as they can be.
Round 2 tuned exits on 2016-22 and checked them on 2023-24, one change at a
time; nothing beat the live rules, but taking the first partial at 1.5R instead
of 1R was ahead in both samples without clearing the bar. Two exits were never
tested: a chandelier trail on the second half, and a second target that scales
with volatility. Three tests; hypotheses_tested rises by 3.

Method. The entries, stops and costs are the live ones: every gold trend trade
the live state machine takes over 2008-2026 (research/similar_setups.replay with
signals.CONFIG). Each trade is re-run from its fill with the base exit and with
each variant, using the live rules for bar order: on the fill bar only the stop
is checked; afterwards the stop first, then the partial, then the target. The
base re-run must reproduce the live state machine's R for every trade, or the
test is void. Entries are held fixed (if a variant would have closed a trade at a
different time, the next trade is still the one the live rules took), so each
trade is compared with itself.

  X1 First partial at 1.5R: half closed at +1.5R, stop to entry, the rest at +2R.
  X2 Chandelier trail on the second half: half closed at +1R and the stop moved
     to entry as now; then no fixed second target. After each closed bar the
     stop on the second half becomes the highest high since the fill minus 3x
     the 14-bar hourly ATR (lowest low plus 3x ATR for sells), never looser than
     the current stop, applied from the next bar.
  X3 Volatility-scaled second target: as now, but the second target is k x R
     with k = 2 x (hourly ATR at the signal / median hourly ATR of the previous
     500 bars), held between 1.5 and 3.0.

Pass, per test, on the trades signalled in the periods round 2 never used
(2008-15 and 2025-26): the average per-trade gain (variant R minus base R) is
above zero with a one-sided paired t-test p < 0.05 / 3 = 0.0167, and the gain is
positive in both of those periods. The 2016-24 result is reported too, but it
is the sample round 2 already searched. A pass goes to Bradley as a proposed
change; nothing changes the live alerts without his decision and a separate
end-to-end-checked change.
"""
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
ALPHA = 0.05 / 3
D = lambda y: datetime(y, 1, 1, tzinfo=UTC)
OOS = [("2008-15", D(2008), D(2016)), ("2025-26", D(2025), D(2030))]
SEEN = ("2016-24", D(2016), D(2025))


def simulate(bars, atr, k, t, cfg, mode):
    """R of one trade filled on bar k. mode: base, x1, x2, x3."""
    d, entry, stop, risk = t["dir"], t["entry"], t["stop"], t["risk"]
    cost = cfg["cost_per_trade"]
    part_r = 1.5 if mode == "x1" else 1.0
    tgt_r = 2.0
    if mode == "x3":
        i = t["sig_i"]
        hist = [v for v in atr[max(0, i - 500):i] if v is not None]
        if atr[i] and hist:
            tgt_r = min(3.0, max(1.5, 2.0 * atr[i] / st.median(hist)))
    partial = entry + d * part_r * risk
    target = None if mode == "x2" else entry + d * tgt_r * risk
    done = booked = 0.0
    ext = None
    for j in range(k, len(bars)):
        b = bars[j]
        ext = (b["h"] if d == 1 else b["l"]) if ext is None else (max(ext, b["h"]) if d == 1 else min(ext, b["l"]))
        against = b["l"] <= stop if d == 1 else b["h"] >= stop
        if j == k:
            if against:
                return booked + (1 - done) * (stop - entry) * d / risk - cost / risk
            continue
        if against:
            return booked + (1 - done) * (stop - entry) * d / risk - cost / risk
        if not done and (b["h"] >= partial if d == 1 else b["l"] <= partial):
            done, booked, stop = 0.5, 0.5 * part_r, entry
        if target is not None and (b["h"] >= target if d == 1 else b["l"] <= target):
            return booked + (1 - done) * (target - entry) * d / risk - cost / risk
        if mode == "x2" and done:
            if atr[j]:
                trail = ext - d * 3.0 * atr[j]
                stop = max(stop, trail) if d == 1 else min(stop, trail)
    return None


def main():
    cfg = S.CONFIG
    bars = S.closed_h1(S.load_history(cfg), datetime.now(UTC))
    F = S.Features(bars, cfg)
    atr = F.hatr
    idx = {b["t"] + timedelta(hours=1): i for i, b in enumerate(bars)}
    jg = SS.replay(cfg, bars)
    trades = []
    for j in jg:
        if j.get("strategy", "trend") != "trend" or not j.get("entry_time"):
            continue
        idea = j["idea"]
        trades.append({"t": datetime.fromisoformat(j["sig_time"]), "dir": idea["dir"], "entry": idea["entry"],
                       "stop": idea["stop"], "risk": idea["risk"], "r": j["r"],
                       "k": idx[datetime.fromisoformat(j["entry_time"])],
                       "sig_i": idx[datetime.fromisoformat(j["sig_time"])]})
    bad = 0
    for t in trades:
        t["base"] = simulate(bars, atr, t["k"], t, cfg, "base")
        if t["base"] is None or abs(t["base"] - t["r"]) > 0.002:
            bad += 1
    print(f"{len(trades)} gold trend trades; base re-run differs from the live state machine on {bad}")
    if bad:
        print("Base re-run does not reproduce the live rules: test void.")
        return
    rows = []
    for name, mode in [("X1 first partial at 1.5R", "x1"), ("X2 chandelier trail on the second half", "x2"),
                       ("X3 volatility-scaled second target", "x3")]:
        for t in trades:
            v = simulate(bars, atr, t["k"], t, cfg, mode)
            t[mode] = None if v is None else v - t["base"]
        res = {"test": name}
        out = []
        for pn, lo, hi in OOS + [SEEN]:
            g = [t[mode] for t in trades if lo <= t["t"] < hi and t[mode] is not None]
            out.append(f"{pn} {st.mean(g):+.3f}R ({len(g)})")
            res[pn] = round(st.mean(g), 3)
        g = [t[mode] for t in trades if t[mode] is not None and any(lo <= t["t"] < hi for _, lo, hi in OOS)]
        m, sd = st.mean(g), st.stdev(g)
        tstat = m / (sd / math.sqrt(len(g))) if sd else 0.0
        p = 0.5 * math.erfc(tstat / math.sqrt(2))
        ok = m > 0 and p < ALPHA and res["2008-15"] > 0 and res["2025-26"] > 0
        base_oos = st.mean(t["base"] for t in trades if any(lo <= t["t"] < hi for _, lo, hi in OOS))
        print(f"  {name:40s} unseen n={len(g)} gain {m:+.3f}R/trade (base {base_oos:+.3f}R) t={tstat:+.2f} p={p:.2g} | "
              + " | ".join(out) + f" | {'PASS' if ok else 'fail'}")
        res.update(n=len(g), gain=round(m, 3), base=round(base_oos, 3), t=round(tstat, 2), p=f"{p:.2g}",
                   verdict="PASS" if ok else "fail")
        rows.append(res)
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round24_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
