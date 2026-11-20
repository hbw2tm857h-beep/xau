"""Round 22: Dr David Paul's springs and upthrusts on gold's 4-hour chart
(pre-registered 20 Nov 2026, before any of these trades was simulated).

Bradley asked for anything valuable from David Paul's teaching. In his own talk
("Wisdom From a Legend") he trades gold on a 4-hour chart with Wyckoff springs
and upthrusts, starts traders on a mechanical method for 30-40 trades before any
change, and avoids trades that "risk a mile to make half a mile". His volume
reading can't be tested here: round 18 found no free source of real exchange
volume. These two tests are the price-only part, written as fixed rules.

4-hour bars are built from the H1 history (2008-2026), in UTC blocks starting at
00:00, 04:00 and so on, keeping blocks with at least three H1 bars.

  S1 Spring (long): a bar trades below the lowest low of the previous 20 bars and
     closes back above that low, in the upper half of its own range. Buy-stop one
     tick above its high, valid for the next 3 bars. Stop at the spring bar's low.
  S2 Upthrust (short): the mirror image, above the highest high of the previous
     20 bars, closing back below it in the lower half of its range.

  Both: target 2R (never risk more than the reward), exit at the close of the 30th
  bar after entry if neither is hit, one trade at a time per test, a bar that
  touches both the stop and the target counts as a stop, $0.35 cost per trade,
  and setups with less than $3 of risk are skipped.

Pass, per test: 100+ trades; average R after costs above zero with a one-sided
t-test p < 0.05 / 2 = 0.025; positive in every period with 10+ trades (2008-15,
2016-22, 2023-24, 2025-26). hypotheses_tested rises by 2. A pass goes into
nursery.json as a candidate; nothing alerts without Bradley's decision.
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

UTC = timezone.utc
ALPHA = 0.05 / 2
COST, MIN_RISK, LOOK, VALID, HOLD, TARGET = 0.35, 3.0, 20, 3, 30, 2.0
D = lambda y: datetime(y, 1, 1, tzinfo=UTC)
PERIODS = [("2008-15", D(2008), D(2016)), ("2016-22", D(2016), D(2023)),
           ("2023-24", D(2023), D(2025)), ("2025-26", D(2025), D(2030))]


def h4_bars():
    h1 = {}
    for p in ("data/xauusd_h1_2008_2015.csv", "data/xauusd_h1.csv"):
        for b in S.load_history_csv(os.path.join(ROOT, p)):
            h1[b["t"]] = b
    blocks = {}
    for t in sorted(h1):
        k = t.replace(hour=t.hour - t.hour % 4)
        blocks.setdefault(k, []).append(h1[t])
    out = []
    for k in sorted(blocks):
        bs = blocks[k]
        if len(bs) >= 3:
            out.append({"t": k, "o": bs[0]["o"], "h": max(b["h"] for b in bs), "l": min(b["l"] for b in bs),
                        "c": bs[-1]["c"]})
    return out


def simulate(bars, d):
    trades, i = [], LOOK
    while i < len(bars) - 1:
        b = bars[i]
        prev = bars[i - LOOK:i]
        mid = (b["h"] + b["l"]) / 2
        if d == 1:
            lvl = min(x["l"] for x in prev)
            setup = b["l"] < lvl < b["c"] and b["c"] > mid
            entry, stop = b["h"] + 0.01, b["l"]
        else:
            lvl = max(x["h"] for x in prev)
            setup = b["h"] > lvl > b["c"] and b["c"] < mid
            entry, stop = b["l"] - 0.01, b["h"]
        risk = abs(entry - stop)
        if not setup or risk < MIN_RISK:
            i += 1
            continue
        filled = None
        for j in range(i + 1, min(i + 1 + VALID, len(bars))):
            if (d == 1 and bars[j]["h"] >= entry) or (d == -1 and bars[j]["l"] <= entry):
                filled = j
                break
        if filled is None:
            i += 1
            continue
        target = entry + d * TARGET * risk
        r, k = None, filled
        for k in range(filled, min(filled + HOLD + 1, len(bars))):
            x = bars[k]
            hit_stop = x["l"] <= stop if d == 1 else x["h"] >= stop
            hit_tgt = x["h"] >= target if d == 1 else x["l"] <= target
            if hit_stop:
                r = -1.0; break
            if hit_tgt:
                r = TARGET; break
        if r is None:
            r = d * (bars[k]["c"] - entry) / risk
        trades.append({"t": bars[i]["t"], "r": r - COST / risk})
        i = k + 1
    return trades


def judge(name, tr):
    rs = [t["r"] for t in tr]
    if len(rs) < 2:
        print(f"  {name}: {len(rs)} trades | fail")
        return {"test": name, "n": len(rs), "verdict": "fail"}
    m, sd = st.mean(rs), st.stdev(rs)
    tstat = m / (sd / math.sqrt(len(rs)))
    p = 0.5 * math.erfc(tstat / math.sqrt(2))
    per, pos = [], True
    for pn, lo, hi in PERIODS:
        x = [t["r"] for t in tr if lo <= t["t"] < hi]
        per.append(f"{pn} {st.mean(x):+.3f}R ({len(x)})" if x else f"{pn} -")
        if len(x) >= 10:
            pos = pos and st.mean(x) > 0
    ok = len(rs) >= 100 and m > 0 and p < ALPHA and pos
    win = 100 * sum(r > 0 for r in rs) / len(rs)
    print(f"  {name}: n={len(rs)} avg={m:+.3f}R win={win:.0f}% t={tstat:+.2f} p={p:.2g} | " + " | ".join(per)
          + f" | {'PASS' if ok else 'fail'}")
    return {"test": name, "n": len(rs), "avg": round(m, 3), "win_pct": round(win), "t": round(tstat, 2),
            "p": f"{p:.2g}", "periods": per, "verdict": "PASS" if ok else "fail"}


def main():
    bars = h4_bars()
    print(f"{len(bars)} 4-hour bars, {bars[0]['t']:%Y-%m-%d} to {bars[-1]['t']:%Y-%m-%d}")
    rows = [judge("S1 spring (long)", simulate(bars, 1)), judge("S2 upthrust (short)", simulate(bars, -1))]
    print(f"\n{sum(r['verdict'] == 'PASS' for r in rows)} of {len(rows)} pass")
    json.dump(rows, open(os.path.join(HERE, "round22_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
