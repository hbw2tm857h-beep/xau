"""Round 10: stress tests on the two Bitcoin passes (trend, inside-day).

None of these change the rules. They ask whether the Bitcoin result is an
artefact of how the test was set up:
  1. costs at 2x and 4x the assumed 5 basis points
  2. 24/7 data: the main test dropped weekend candles to match gold's hours,
     but Bitcoin trades through the weekend, and a live bot would see it
  3. longs vs shorts and year by year (2017-2026 was a huge bull market)
  4. the round 7 shuffle test: same candles in random order (20 shuffles)
"""
import collections
import csv
import gzip
import os
import random
import statistics as st
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import round7_synthetic as R7  # noqa: E402
import round10_markets as R10  # noqa: E402
import signals as S  # noqa: E402

UTC = timezone.utc
PATH = os.path.join(R10.DATA, "markets", "btcusd_h1.csv.gz")


def load_247(path):
    bars = []
    with gzip.open(path, "rt") as f:
        for r in csv.DictReader(f):
            t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            if h - l <= 0 and o == c:
                continue
            bars.append({"t": t, "o": o, "h": h, "l": l, "c": c})
    return bars


def make_lab(bars, gold_atr):
    lab = L.Lab(bars)
    k = R10.median_atr(lab) / gold_atr
    for key in ("entry_buffer", "h4_entry_buffer", "h4_stop_buffer"):
        lab.cfg[key] = S.CONFIG[key] * k
    return lab


def both(lab, bps):
    return {"trend": R10.run_orders(lab, L.gen_ha(lab, R10.BASE_P), bps),
            "insideday": R10.run_insideday(lab, bps)}


def line(label, tr):
    s, per, p, ok = R10.judge(tr)
    return (f"{label:44s} n={s.get('n', 0):4d} avg={s.get('avg', 0):+.3f} PF={s.get('pf', 0):.2f} | "
            + " ".join(f"{pn} {('%+.3f' % v) if v is not None else '  -   '}" for pn, (n, v) in per.items() if n)
            + f" | p={p:.2g}")


def main():
    gold_atr = R10.gold_median_atr()
    hours = sorted(R10.load(PATH), key=lambda b: b["t"])
    full = load_247(PATH)
    lab_h, lab_f = make_lab(hours, gold_atr), make_lab(full, gold_atr)

    print("1-2. Costs and weekends")
    for label, lab in (("gold's hours (as tested)", lab_h), ("24/7 incl. weekends", lab_f)):
        for bps in (5, 10, 20):
            for strat, tr in both(lab, bps).items():
                print(line(f"  {strat:9s} {label}, {bps} bp", tr))

    print("\n3. Direction and years (gold's hours, 5 bp)")
    res = both(lab_h, 5)
    for strat, tr in res.items():
        lo = [t["r"] for t in tr if t.get("d") == 1]; sh = [t["r"] for t in tr if t.get("d") == -1]
        yrs = collections.defaultdict(float)
        for t in tr:
            yrs[t["t"].year] += t["r"]
        print(f"  {strat:9s} longs n={len(lo)} avg={st.mean(lo):+.3f} | shorts n={len(sh)} avg={st.mean(sh):+.3f} | "
              + " ".join(f"{y % 100:02d}:{v:+.1f}" for y, v in sorted(yrs.items()))
              + f" | positive years {sum(v > 0 for v in yrs.values())}/{len(yrs)}")

    print("\n4. Shuffle test (gold's hours, 5 bp, 20 shuffles)")
    real = {k: st.mean(t["r"] for t in v) for k, v in res.items()}
    rnd = random.Random(11)
    sh = collections.defaultdict(list)
    for _ in range(20):
        lab_s = make_lab(R7.shuffled_bars(hours, rnd), gold_atr)
        for k, tr in both(lab_s, 5).items():
            sh[k].append(st.mean(t["r"] for t in tr) if tr else 0.0)
    for k, vals in sh.items():
        m, sd = st.mean(vals), st.stdev(vals)
        print(f"  {k:9s} real {real[k]:+.3f} | shuffled mean {m:+.3f} sd {sd:.3f} best {max(vals):+.3f} | "
              f"{sum(v >= real[k] for v in vals)}/20 reached real, {(real[k] - m) / sd:.1f} sd above")


if __name__ == "__main__":
    main()
