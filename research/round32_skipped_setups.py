"""Round 32: the setups the live rules find and then skip (pre-registered
23 Nov 2026; committed before it was run).

The trend rules take one trade at a time. A setup that passes every check
while a trend trade is already open (or on the candle a trade closes) is
thrown away: step() only looks for a new signal when flat. Bradley asked for a
new edge; these are trades from rules that already have one, so the question is
whether the skipped setups carry it too. If they do, they add trades without
any new rule.

Each skipped setup is simulated on its own, exactly as the live state machine
would have handled it had it been flat: the same order, buffer, expiry,
cancel-on-flip, stop, half off at 1R with the stop to entry, the rest at 2R,
and the same cost (signals.step on a separate state). Signals use
signals.evaluate with the live CONFIG; no news filter, as in every replay.

  S1 Gold (signals.CONFIG), signals from 2004 on gold's 2003-26 history
     (round 27's file plus the live history).
  S2 Bitcoin (the btc market config, dollar amounts scaled to each candle's
     price as rounds 25 and 30 did).

Pass, per market: 100+ trades for gold, 50+ for Bitcoin; average R above zero
with a one-sided t-test p < 0.05 / 2; and positive in both halves (gold before
and from 2015; Bitcoin before and from 2022). Reported but not part of the pass:
the four live-backtest periods, and how often the trade already open was
stopped at a loss too (the extra risk of holding both).

hypotheses_tested rises by 2 (1,380 -> 1,382), recorded here and in README.
A pass is a proposal to Bradley: the skipped setups would go in as a candidate
(tracked, staff channel only) first, with the size of a second position decided
separately.
"""
import json
import math
import os
import statistics as st
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import round10_btc_checks as B  # noqa: E402
import round28_new_edge as R28  # noqa: E402

UTC = timezone.utc
ALPHA = 0.05 / 2
CLOSE = ("exit", "stop", "target")


def skipped(bars, cfg, scale, since):
    F = S.Features(bars, cfg)
    ref = bars[-1]["c"]
    st_, out, live = {}, [], []

    def c_at(i):
        if not scale:
            return cfg
        k = bars[i]["c"] / ref
        return dict(cfg, entry_buffer=cfg["entry_buffer"] * k, cost_per_trade=cfg["cost_per_trade"] * k)

    for i in range(len(bars)):
        if not F.warm(i):
            continue
        c = c_at(i)
        open_before = dict(st_["idea"]) if st_.get("idea") and st_["idea"]["triggered"] else None
        evs = S.step(F, i, st_, c)
        for e in evs:
            if e["type"] in CLOSE:
                live.append({"sig": e["idea"]["sig_time"], "r": e["r"]})
        if any(e["type"] == "signal" for e in evs):
            continue
        closed = any(e["type"] in CLOSE for e in evs)
        holding = st_.get("idea") and st_["idea"]["triggered"]
        if not (closed or holding):
            continue                                    # step() looked for a signal here itself
        for d in (1, -1):                               # the same order step() uses
            s = S.evaluate(F, i, d, c, None)
            if not s:
                continue
            if s["t_close"] < since:
                break
            risk = s["risk"]
            idea = {"dir": d, "entry": round(s["entry"], 2), "stop": round(s["stop"], 2), "risk": round(risk, 4),
                    "triggered": False, "age": 0,
                    "partial": round(s["entry"] + d * c["partial_r"] * risk, 2) if c["partial_r"] else None,
                    "target": round(s["entry"] + d * c["target_r"] * risk, 2) if c["target_r"] else None,
                    "sig_time": s["t_close"].isoformat(), "session": s["checks"]["session"][0],
                    "grade": s["grade"], "strategy": c.get("trend_strategy", "trend")}
            r = alone(F, i, idea, c_at)
            if r is not None:
                held = (open_before or (st_.get("idea") if holding else None) or {}).get("sig_time")
                out.append({"t": s["t_close"], "d": d, "r": r, "held": held})
            break
    lr = {x["sig"]: x["r"] for x in live}
    for t in out:
        t["held_r"] = lr.get(t["held"])
    return out


def alone(F, i, idea, c_at):
    """The setup on its own state, through the live state machine."""
    sst = {"idea": dict(idea)}
    for j in range(i + 1, len(F.h1)):
        if not F.warm(j):
            continue
        for e in S.step(F, j, sst, c_at(j)):
            if (e.get("idea") or {}).get("sig_time") != idea["sig_time"]:
                continue
            if e["type"] in CLOSE:
                return e["r"]
            if e["type"] == "cancel":
                return None
        cur = sst.get("idea")
        if not cur or cur.get("sig_time") != idea["sig_time"]:
            return None                                 # replaced while still pending, as live
    return None


def judge(name, tr, split, nmin, periods):
    rs = [t["r"] for t in tr]
    if len(rs) < 3:
        print(f"  {name}: {len(rs)} trades | fail"); return {"test": name, "n": len(rs), "verdict": "fail"}
    m, sd = st.mean(rs), st.stdev(rs)
    tt = m / (sd / math.sqrt(len(rs))); p = 0.5 * math.erfc(tt / math.sqrt(2))
    a = [t["r"] for t in tr if t["t"] < split]; b = [t["r"] for t in tr if t["t"] >= split]
    ok = len(rs) >= nmin and m > 0 and p < ALPHA and a and b and st.mean(a) > 0 and st.mean(b) > 0
    yrs = (tr[-1]["t"] - tr[0]["t"]).days / 365.25
    both = [t for t in tr if t["held_r"] is not None]
    both_loss = sum(t["r"] < 0 and t["held_r"] < 0 for t in both)
    per = " ".join(f"{lo}-{hi - 1} {st.mean(x):+.3f}({len(x)})" for lo, hi in periods
                   for x in [[t["r"] for t in tr if lo <= t["t"].year < hi]] if x)
    print(f"  {name}: {len(rs)} trades ({len(rs) / yrs / 52:.2f}/week), avg {m:+.3f}R, win {100 * sum(r > 0 for r in rs) / len(rs):.0f}%, "
          f"total {sum(rs):+.1f}R, t={tt:+.2f} p={p:.2g} | before {split:%Y} {st.mean(a) if a else float('nan'):+.3f} ({len(a)}), "
          f"from {st.mean(b) if b else float('nan'):+.3f} ({len(b)}) | {'PASS' if ok else 'fail'}")
    print(f"    periods: {per}")
    print(f"    both trades lost: {both_loss} of {len(both)} ({100 * both_loss / max(1, len(both)):.0f}%)")
    return {"test": name, "n": len(rs), "per_week": round(len(rs) / yrs / 52, 2), "avg": round(m, 3), "total": round(sum(rs), 1),
            "p": f"{p:.2g}", "first_half": round(st.mean(a), 3) if a else None, "second_half": round(st.mean(b), 3) if b else None,
            "both_lost_pct": round(100 * both_loss / max(1, len(both))), "verdict": "PASS" if ok else "fail"}


def main():
    rows = []
    gold = R28.load_all()
    g = skipped(gold, S.CONFIG, False, datetime(2004, 1, 1, tzinfo=UTC))
    rows.append(judge("S1 gold, setups skipped while a trend trade was open", g, datetime(2015, 1, 1, tzinfo=UTC), 100,
                      [(2004, 2008), (2008, 2016), (2016, 2023), (2023, 2025), (2025, 2027)]))
    btc = B.load_247(os.path.join(ROOT, "data", "markets", "btcusd_h1.csv.gz"))
    b = skipped(btc, S.market_cfg("btc"), True, datetime(2000, 1, 1, tzinfo=UTC))
    rows.append(judge("S2 Bitcoin, setups skipped while a trend trade was open", b, datetime(2022, 1, 1, tzinfo=UTC), 50,
                      [(2016, 2022), (2022, 2024), (2024, 2027)]))
    passed = [r["test"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} pass" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round32_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
