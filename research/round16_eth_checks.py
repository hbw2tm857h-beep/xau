"""Round 16 stress tests on the one pass: the inside-day breakout on Ether.

Same checks as round10_btc_checks.py. Bitcoin's inside-day setup also passed on
gold-hours data in round 10 and then lost its 2025-26 edge once weekends were
included, so the realistic version decides. Fixed before running: Ether becomes
a nursery candidate only if the realistic version (24/7 data, signals only from
weekday inside days, trades tracked through weekends) stays positive in every
period with 10+ trades and has one-sided p < 0.05.

  1. costs at 1x, 2x and 4x the assumed 8 basis points
  2. 24/7 data, all signals; and 24/7 with weekday signals only (realistic)
  3. longs vs shorts and year by year
  4. the round 7 shuffle test (20 shuffles)
  5. monthly correlation with Bitcoin's inside-day and trend setups, and gold's
"""
import collections
import math
import os
import random
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import round7_synthetic as R7  # noqa: E402
import round10_btc_checks as B  # noqa: E402
import round10_markets as R10  # noqa: E402

ETH = os.path.join(R10.DATA, "markets", "ethusd_h1.csv.gz")
BPS = 8


def line(label, tr):
    s, per, p, ok = R10.judge(tr)
    return (f"{label:46s} n={s.get('n', 0):4d} avg={s.get('avg', 0):+.3f} PF={s.get('pf', 0):.2f} | "
            + " ".join(f"{pn} {('%+.3f' % v) if v is not None else '  -   '}({n})" for pn, (n, v) in per.items() if n)
            + f" | p={p:.2g}"), s, per, p


def monthly(tr):
    m = collections.defaultdict(float)
    for t in tr:
        m[(t["t"].year, t["t"].month)] += t["r"]
    return m


def corr(a, b):
    ks = sorted(set(a) | set(b))
    x, y = [a.get(k, 0) for k in ks], [b.get(k, 0) for k in ks]
    mx, my = st.mean(x), st.mean(y)
    num = sum((p - mx) * (q - my) for p, q in zip(x, y))
    return num / math.sqrt(sum((p - mx) ** 2 for p in x) * sum((q - my) ** 2 for q in y))


def main():
    gold_atr = R10.gold_median_atr()
    hours = sorted(R10.load(ETH), key=lambda b: b["t"])
    full = B.load_247(ETH)
    lab_h, lab_f = B.make_lab(hours, gold_atr), B.make_lab(full, gold_atr)

    print("1. Costs (gold's hours, as tested)")
    for bps in (BPS, 2 * BPS, 4 * BPS):
        print(line(f"  inside-day, {bps} bp", R10.run_insideday(lab_h, bps))[0])

    print("\n2. Weekends")
    allsig = R10.run_insideday(lab_f, BPS)
    print(line("  24/7, all signals", allsig)[0])
    wk = [t for t in allsig if t["t"].weekday() < 5]
    txt, s, per, p = line("  24/7, weekday signals (REALISTIC)", wk)
    print(txt)
    counted = [v for n, v in per.values() if n >= 10]
    ok = s.get("avg", 0) > 0 and all(v > 0 for v in counted) and p < 0.05
    print("  realistic verdict:", "CANDIDATE" if ok else "fail")

    print("\n3. Direction and years (gold's hours)")
    tr = R10.run_insideday(lab_h, BPS)
    lo = [t["r"] for t in tr if t["d"] == 1]; sh = [t["r"] for t in tr if t["d"] == -1]
    yrs = collections.defaultdict(float)
    for t in tr:
        yrs[t["t"].year] += t["r"]
    print(f"  longs n={len(lo)} avg={st.mean(lo):+.3f} | shorts n={len(sh)} avg={st.mean(sh):+.3f} | "
          + " ".join(f"{y % 100:02d}:{v:+.1f}" for y, v in sorted(yrs.items())))

    print("\n4. Shuffle test (20)")
    real = st.mean(t["r"] for t in tr)
    rnd = random.Random(11)
    vals = []
    for _ in range(20):
        x = R10.run_insideday(B.make_lab(R7.shuffled_bars(hours, rnd), gold_atr), BPS)
        vals.append(st.mean(t["r"] for t in x) if x else 0.0)
    print(f"  real {real:+.3f} | shuffled mean {st.mean(vals):+.3f} sd {st.stdev(vals):.3f} | "
          f"{sum(v >= real for v in vals)}/20 reached real")

    print("\n5. Monthly correlation (realistic Ether stream)")
    btc_h = sorted(R10.load(B.PATH), key=lambda b: b["t"])
    lab_b = B.make_lab(btc_h, gold_atr)
    gold_bars = sorted((b for f in R10.MARKETS["XAUUSD (reference)"][0] for b in R10.load(os.path.join(R10.DATA, f))), key=lambda b: b["t"])
    lab_g = L.Lab(gold_bars)
    others = {
        "Bitcoin inside-day": R10.run_insideday(lab_b, 5),
        "Bitcoin trend": R10.run_orders(lab_b, L.gen_ha(lab_b, R10.BASE_P), 5),
        "gold trend": R10.run_orders(lab_g, L.gen_ha(lab_g, R10.BASE_P), 1.75),
        "gold inside-day": R10.run_insideday(lab_g, 1.75),
    }
    e = monthly(wk)
    for k, v in others.items():
        print(f"  vs {k}: {corr(e, monthly(v)):+.2f}")


if __name__ == "__main__":
    main()
