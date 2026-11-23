"""Round 33: gold's trend rules with the trigger on 15-minute candles
(pre-registered 23 Nov 2026; committed before any 15-minute data was downloaded).

Bradley asked for setups the 10-minute watch could alert between the hourly
checks. Mid-hour the 1-hour candle is still forming, so that needs a faster
trigger with its own evidence. Round 9 E2 moved the trigger up to the 4-hour
candle (daily trend kept) and it passed; this moves it down, the same way.

Data: Dukascopy XAUUSD 15-minute candles (bid, as the hourly research files),
2008-2026, downloaded after this file was committed (data/xauusd_m15_*.csv.gz).

Rules: signals.CONFIG through the live state machine (signals.step), with every
candle-count setting unchanged but counted in 15-minute candles: the Heikin Ashi
trigger (first no-wick candle of a new colour, within 12 candles of the flip,
body at least the previous one's), the 5-candle swing stop plus 0.2 x ATR(14),
the $0.30 entry buffer, the 12-candle order expiry, half off at 1R with the stop
to entry, the rest at 2R, $0.35 cost. The higher timeframes are unchanged: the
daily trend (Heikin Ashi and the 50-day EMA), the 4-hour Heikin Ashi agreement
and the 4-hour Ichimoku cloud, the room to the next daily level. Candles group
into days and 4-hour blocks at 17:00 New York exactly as live. Only the trend
setup is tested (no inside day, no 4-hour trigger).

  F1 The rules above.
  F2 F1, and the last closed 1-hour Heikin Ashi candle also agrees (one more
     timeframe in the stack, as the 4-hour check did for the hourly trigger).

Pass, per test: 300+ trades; average R above zero with a one-sided t-test
p < 0.05 / 2; positive in each of 2008-15, 2016-22, 2023-24 and 2025-26.
Reported but not part of the pass: trades a week, and how many fall while an
hourly trend trade is open in the same direction (not new exposure).

hypotheses_tested rises by 2 (1,382 -> 1,384). A pass goes in as a candidate
(staff channel only) first; nothing reaches members without live evidence and
Bradley's decision.
"""
import csv
import gzip
import glob
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

UTC = timezone.utc
ALPHA = 0.05 / 2
M15 = timedelta(minutes=15)
PERIODS = [(2008, 2016), (2016, 2023), (2023, 2025), (2025, 2027)]


def load():
    bars = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "xauusd_m15_*.csv.gz"))):
        with gzip.open(p, "rt") as f:
            for r in csv.DictReader(f):
                t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
                o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
                if h - l <= 0 and o == c:
                    continue
                bars[t] = {"t": t, "o": o, "h": h, "l": l, "c": c}
    return [bars[t] for t in sorted(bars) if S.market_open(t)]


def run(bars, h1_agree):
    """Trend trades on 15-minute candles. signals.H1 is the candle length the
    live code uses for close times; it is set to 15 minutes for this replay."""
    saved = S.H1
    S.H1 = M15
    try:
        F = S.Features(bars, S.CONFIG)
        h1 = S.aggregate(bars, lambda t: t.replace(minute=0), lambda k: k + timedelta(hours=1))
        h1_ha = S.heikin_ashi(h1)
        h1_end = [x["end"] for x in h1]
        st_, out, k = {}, [], -1
        cfg = S.CONFIG
        for i in range(len(bars)):
            close = bars[i]["t"] + M15
            while k + 1 < len(h1) and h1_end[k + 1] <= close:
                k += 1
            if not F.warm(i):
                continue
            before = dict(st_["idea"]) if st_.get("idea") else None
            evs = S.step(F, i, st_, cfg)
            for e in evs:
                if e["type"] == "signal" and h1_agree:
                    d = e["idea"]["dir"]
                    x = h1_ha[k] if k >= 0 else None
                    if not x or not ((x["c"] > x["o"]) if d == 1 else (x["c"] < x["o"])):
                        st_["idea"] = before if before and not before.get("triggered") else None
                        continue
                if e["type"] in ("exit", "stop", "target"):
                    out.append({"t": datetime.fromisoformat(e["idea"]["sig_time"]), "r": e["r"], "d": e["idea"]["dir"],
                                "entry_t": datetime.fromisoformat(e["idea"]["entry_time"]), "exit_t": e["t"]})
        return out
    finally:
        S.H1 = saved


def judge(name, tr, hourly):
    rs = [t["r"] for t in tr]
    if len(rs) < 3:
        print(f"  {name}: {len(rs)} trades | fail"); return {"test": name, "n": len(rs), "verdict": "fail"}
    m, sd = st.mean(rs), st.stdev(rs)
    tt = m / (sd / math.sqrt(len(rs))); p = 0.5 * math.erfc(tt / math.sqrt(2))
    per = [[t["r"] for t in tr if lo <= t["t"].year < hi] for lo, hi in PERIODS]
    ok = len(rs) >= 300 and m > 0 and p < ALPHA and all(x and st.mean(x) > 0 for x in per)
    yrs = (tr[-1]["t"] - tr[0]["t"]).days / 365.25
    ov = sum(any(a <= t["entry_t"] <= b and d == t["d"] for a, b, d in hourly) for t in tr)
    print(f"  {name}: {len(rs)} trades ({len(rs) / yrs / 52:.2f}/week), avg {m:+.3f}R, win {100 * sum(r > 0 for r in rs) / len(rs):.0f}%, "
          f"total {sum(rs):+.1f}R, t={tt:+.2f} p={p:.2g} | "
          + " ".join(f"{lo}-{hi - 1} {st.mean(x):+.3f}({len(x)})" if x else f"{lo}-{hi - 1} -" for (lo, hi), x in zip(PERIODS, per))
          + f" | while an hourly trade is open: {ov} ({100 * ov / len(rs):.0f}%) | {'PASS' if ok else 'fail'}")
    return {"test": name, "n": len(rs), "per_week": round(len(rs) / yrs / 52, 2), "avg": round(m, 3), "p": f"{p:.2g}",
            "periods": [round(st.mean(x), 3) if x else None for x in per], "overlap_pct": round(100 * ov / len(rs)),
            "verdict": "PASS" if ok else "fail"}


def main():
    bars = load()
    print(f"{len(bars):,} 15-minute candles {bars[0]['t']:%Y-%m-%d} -> {bars[-1]['t']:%Y-%m-%d}")
    h1 = S.closed_h1(S.load_history(S.CONFIG), datetime.now(UTC))
    import similar_setups as SS
    hourly = [(datetime.fromisoformat(j["entry_time"]), datetime.fromisoformat(j["exit_time"]), j["dir"])
              for j in SS.replay(S.CONFIG, h1) if j.get("strategy", "trend") == "trend" and j.get("entry_time")]
    rows = [judge("F1 trigger on 15-minute candles", run(bars, False), hourly),
            judge("F2 F1 + the 1-hour Heikin Ashi agrees", run(bars, True), hourly)]
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round33_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
