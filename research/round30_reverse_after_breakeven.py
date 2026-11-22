"""Round 30: reverse after a breakeven stop (pre-registered 22 Nov 2026;
committed before it was run). Research only: nothing in the bot changes.

Bradley's Bitcoin short (20 Nov 2026) sold at 58,761, took half off at 1R near
55k, and the rest was stopped at entry as price turned; Bitcoin then rose to
61.4k. He asked whether the bot could have caught that move. The live rules
only trade with the daily trend, so the turn is never traded. This tests the
one rule that would have caught it, on the full history.

Event: a live trend trade (signals.CONFIG on gold, the btc market config on
Bitcoin, through the live state machine, similar_setups.replay) whose first
half hit the 1R target and whose remainder was then stopped at its entry
price. Each such stop is a possible reversal.

  V1 Stop and reverse: on the bar the breakeven stop fills, enter the other way
     at the original entry price. Stop beyond the extreme the original trade
     reached between its fill and that bar (the low for a reversal buy), plus
     the live entry buffer. Half off at 1R with the stop moved to entry, the
     rest at 2R, the live exits. The stop and targets are checked from the
     next bar. Cost: the live cost per trade.
  V2 The same, only when the last closed 4H Heikin Ashi candle at that bar
     agrees with the new direction (the trend turning, as Bradley put it).

Markets: gold 2004-2026 (round 27's 2003-07 file plus the live history) and
Bitcoin (data/markets/btcusd_h1.csv.gz, weekends kept, dollar amounts scaled to
each candle's price as round 25 did). Four tests (2 rules x 2 markets);
hypotheses_tested would rise by 4. The counter in signals.py is left alone
(this round is research only); the count is recorded here and in README.

Pass, per rule and market: 30+ trades, average R above zero with a one-sided
t-test p < 0.05 / 4 = 0.0125, and a positive average in both halves (gold:
signals before / from 2015; Bitcoin: before / from 2022). A pass is a proposal
to Bradley; nothing is alerted without his decision and a separate change.
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
import round10_btc_checks as B  # noqa: E402
import round28_new_edge as R28  # noqa: E402

UTC = timezone.utc
ALPHA = 0.05 / 4


def reversals(bars, cfg, scale):
    F = S.Features(bars, cfg)
    idx = {b["t"] + timedelta(hours=1): i for i, b in enumerate(bars)}
    ref = bars[-1]["c"]
    out = []
    jr = SS.replay(cfg, bars, scale=scale)
    trend = [j for j in jr if j.get("strategy", "trend") == cfg.get("trend_strategy", "trend")]
    for j in trend:
        if j["how"] != "stop" or not j.get("entry_time") or abs(j["exit"] - j["entry"]) > 0.006:   # exit rounded to cents
            continue
        if j["r"] <= 0:                      # the first half was not booked: not a breakeven stop
            continue
        k0, k = idx[datetime.fromisoformat(j["entry_time"])], idx[datetime.fromisoformat(j["exit_time"])]
        d = -j["dir"]
        sc = bars[k]["c"] / ref if scale else 1.0
        buf, cost = cfg["entry_buffer"] * sc, cfg["cost_per_trade"] * sc
        seg = bars[k0:k + 1]
        stop = (min(b["l"] for b in seg) - buf) if d == 1 else (max(b["h"] for b in seg) + buf)
        entry = j["entry"]
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        h = F.h4_ha[F.h4_idx[k]] if F.h4_idx[k] >= 0 else None
        agree = bool(h) and ((h["c"] > h["o"]) if d == 1 else (h["c"] < h["o"]))
        r = walk(bars, k + 1, d, entry, stop, risk, cost)
        if r is None:
            continue
        out.append({"t": datetime.fromisoformat(j["exit_time"]), "d": d, "r": r, "ha": agree,
                    "risk_pct": 100 * risk / entry})
    return out, len(trend)


def walk(bars, k, d, entry, stop, risk, cost):
    t1, t2 = entry + d * risk, entry + d * 2 * risk
    booked = done = 0.0
    for b in bars[k:]:
        if (b["l"] <= stop) if d == 1 else (b["h"] >= stop):
            return booked + (1 - done) * (stop - entry) * d / risk - cost / risk
        if not done and ((b["h"] >= t1) if d == 1 else (b["l"] <= t1)):
            done, booked, stop = 0.5, 0.5, entry
        if (b["h"] >= t2) if d == 1 else (b["l"] <= t2):
            return booked + (1 - done) * 2 - cost / risk
    return None


def judge(name, tr, split):
    rs = [t["r"] for t in tr]
    if len(rs) < 3:
        print(f"  {name:34s} n={len(rs)} | fail (too few)")
        return {"test": name, "n": len(rs), "verdict": "fail"}
    m, sd = st.mean(rs), st.stdev(rs)
    t = m / (sd / math.sqrt(len(rs))) if sd else 0.0
    p = 0.5 * math.erfc(t / math.sqrt(2))
    a = [x["r"] for x in tr if x["t"] < split]; b = [x["r"] for x in tr if x["t"] >= split]
    ma, mb = (st.mean(a) if a else float("nan")), (st.mean(b) if b else float("nan"))
    ok = len(rs) >= 30 and m > 0 and p < ALPHA and ma > 0 and mb > 0
    win = 100 * sum(r > 0 for r in rs) / len(rs)
    print(f"  {name:34s} n={len(rs)} avg {m:+.3f}R win {win:.0f}% total {sum(rs):+.1f}R t={t:+.2f} p={p:.2g} | "
          f"before {split:%Y} {ma:+.3f}R ({len(a)}), from {mb:+.3f}R ({len(b)}) | {'PASS' if ok else 'fail'}")
    return {"test": name, "n": len(rs), "avg": round(m, 3), "win": round(win), "total": round(sum(rs), 1),
            "p": f"{p:.2g}", "first_half": round(ma, 3), "second_half": round(mb, 3), "verdict": "PASS" if ok else "fail"}


def main():
    rows = []
    gold = R28.load_all()
    gt, gn = reversals(gold, S.CONFIG, False)
    gt = [t for t in gt if t["t"] >= datetime(2004, 1, 1, tzinfo=UTC)]
    print(f"Gold: {gn} trend trades, {len(gt)} breakeven stops reversed (median stop {st.median(t['risk_pct'] for t in gt):.2f}% of price)")
    split = datetime(2015, 1, 1, tzinfo=UTC)
    rows.append(judge("V1 gold, stop and reverse", gt, split))
    rows.append(judge("V2 gold, reverse if 4H HA agrees", [t for t in gt if t["ha"]], split))
    btc = B.load_247(os.path.join(ROOT, "data", "markets", "btcusd_h1.csv.gz"))
    bt, bn = reversals(btc, S.market_cfg("btc"), True)
    print(f"Bitcoin: {bn} trend trades, {len(bt)} breakeven stops reversed (median stop {st.median(t['risk_pct'] for t in bt):.2f}% of price)")
    split = datetime(2022, 1, 1, tzinfo=UTC)
    rows.append(judge("V1 Bitcoin, stop and reverse", bt, split))
    rows.append(judge("V2 Bitcoin, reverse if 4H HA agrees", [t for t in bt if t["ha"]], split))
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round30_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
