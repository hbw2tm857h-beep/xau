"""Round 7: does the edge come from real structure, or from the return distribution?

Prompted by a question about running these rules on Deriv's synthetic indices.
Deriv generates those series itself, so their increments are independent by
construction. If that is true, a trend-following rule cannot have an edge on
them beyond noise. Rather than assert it, test it - and the same machinery
answers a sharper question about the gold strategy that rounds 1-6 never asked.

TWO TESTS

A. SHUFFLE TEST (real gold). Take the real H1 bars, keep each bar's shape and
   its return, but replay them in random order. That destroys all serial
   structure - trends, daily levels, session effects, everything the rules are
   supposed to read - while keeping the return distribution, the volatility
   clustering of individual bars and the cost model identical. Run the live
   rules on each shuffle. If the real +0.18R sits inside the shuffled
   distribution, the "edge" is an artifact of gold's return distribution and
   the rules are reading nothing. If it sits outside, the edge comes from real
   serial structure. This is the single most direct test of whether the
   strategy reads anything at all, and it has never been run on this project.

B. RANDOM-WALK CONTROL - KEPT, BUT INCONCLUSIVE. Generate geometric Brownian
   motion at 75% annualised volatility, 24/7, intrabar highs and lows from
   sub-steps. The intent was a series with no structure to read.

   It does not work as a null, and the reason is worth recording. A GBM cannot
   be driftless in both measures at once:
     - a martingale in PRICE (px *= 1 + e) has log drift -sigma^2/2, which over
       113k hours is a ~97% decline: a real downtrend, shorted for +0.091R
     - a martingale in LOG price (px *= exp(e), what this file now does) has
       arithmetic drift +sigma^2/2 by Jensen, an uptrend over the same span,
       which measures +0.034R at zero cost and +0.026R with cost
   One artifact for its mirror image. A trend follower reads price levels, so
   whichever measure is pinned, the other one drifts and the rules pick it up.

   Test A has no such problem: it uses gold's own returns and destroys only
   their order, assuming nothing about drift. A is the null that counts; B is
   kept only to show what a parametric control does and why it is not usable.

Run: python3 research/round7_synthetic.py [n_shuffles] [n_walks]
"""
import os
import random
import statistics
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import round6 as R6  # noqa: E402

UTC = timezone.utc


def real_bars():
    merged = {}
    for p in ("xauusd_h1_2008_2015.csv", "xauusd_h1.csv"):
        fp = os.path.join(HERE, "..", "data", p)
        if os.path.exists(fp):
            for b in L.load(fp):
                merged[b["t"]] = b
    return [merged[k] for k in sorted(merged)]


def shuffled_bars(bars, rnd):
    """Same bars, same shapes, same returns - replayed in random order.

    Each bar is stored as multiplicative moves from the previous close, then
    chained back together in a shuffled order from the original start price.
    """
    shapes = []
    prev = bars[0]["o"]
    for b in bars:
        if prev <= 0:
            prev = b["o"]
        shapes.append((b["o"] / prev, b["h"] / prev, b["l"] / prev, b["c"] / prev))
        prev = b["c"]
    order = list(range(len(shapes)))
    rnd.shuffle(order)
    out, px = [], bars[0]["o"]
    for i, k in enumerate(order):
        o, h, l, c = shapes[k]
        bar = {"t": bars[i]["t"], "o": px * o, "h": px * h, "l": px * l, "c": px * c}
        # keep the candle coherent after rescaling
        bar["h"] = max(bar["h"], bar["o"], bar["c"])
        bar["l"] = min(bar["l"], bar["o"], bar["c"])
        out.append(bar)
        px = bar["c"]
    return out


def gbm_bars(n, rnd, start=2000.0, annual_vol=0.75, substeps=30):
    """Driftless random walk in LOG price at `annual_vol`, hourly, 24/7.

    The log price is the martingale, so there is no direction to predict. Doing
    this multiplicatively as px *= (1 + e) instead would put a -sigma^2/2 log
    drift into the series: over 113k hours that is a ~97% decline, a thumping
    downtrend that a trend follower really can profit from. That would be an
    artifact of the generator, not a finding, so the drift is removed here.

    Highs and lows come from sub-steps inside each hour, so the candles have a
    believable shape instead of being pure open/close lines.
    """
    import math
    sigma_h = annual_vol / (8760 ** 0.5)
    sigma_s = sigma_h / (substeps ** 0.5)
    t0 = datetime(2010, 1, 1, tzinfo=UTC)
    logpx, out = math.log(start), []
    for i in range(n):
        o = math.exp(logpx)
        hi = lo = o
        for _ in range(substeps):
            logpx += rnd.gauss(0.0, sigma_s)
            p = math.exp(logpx)
            hi = max(hi, p)
            lo = min(lo, p)
        out.append({"t": t0 + timedelta(hours=i), "o": o, "h": hi, "l": lo, "c": math.exp(logpx)})
    return out


def avg_r(bars, cost):
    old = L.COST
    L.COST = cost
    try:
        lab = L.Lab(bars)
        tr = R6.run(lab)
        rs = [t["r"] for t in tr]
        return (sum(rs) / len(rs) if rs else 0.0), len(rs)
    finally:
        L.COST = old


def summarise(name, vals, real=None):
    if not vals:
        print(f"{name}: no runs")
        return
    m = statistics.mean(vals)
    sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    line = (f"{name}: {len(vals)} runs, avg R per run {m:+.4f} "
            f"(sd {sd:.4f}, min {min(vals):+.4f}, max {max(vals):+.4f})")
    if real is not None:
        beat = sum(1 for v in vals if v >= real)
        line += f"\n   runs matching or beating the real {real:+.3f}R: {beat}/{len(vals)}"
        line += f"  ->  p = {(beat + 1) / (len(vals) + 1):.4f}"
        if sd > 0:
            line += f"\n   the real result is {(real - m) / sd:+.1f} standard deviations above the shuffles"
    print(line)


def main():
    n_shuf = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    n_walk = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    bars = real_bars()
    print(f"real bars {len(bars):,}  {bars[0]['t']:%Y-%m-%d} -> {bars[-1]['t']:%Y-%m-%d}")

    real, n_real = avg_r(bars, 0.35)
    print(f"\nREAL GOLD, live rules: {n_real} trades, avg {real:+.4f}R\n")

    print(f"A. SHUFFLE TEST - {n_shuf} shuffles of the same bars, same cost")
    rnd = random.Random(20261118)
    vals, counts = [], []
    for i in range(n_shuf):
        a, n = avg_r(shuffled_bars(bars, rnd), 0.35)
        vals.append(a)
        counts.append(n)
        print(f"   shuffle {i+1:2d}: {n:4d} trades, avg {a:+.4f}R")
    summarise("   shuffled", vals, real)
    print(f"   trades per shuffle: median {statistics.median(counts):.0f} "
          f"(real {n_real})")

    print(f"\nB. RANDOM-WALK TEST - {n_walk} driftless GBM series at 75% annual vol, "
          f"{len(bars):,} hourly bars each")
    for cost in (0.0, 0.35):
        rnd2 = random.Random(7771 + int(cost * 100))
        vals2, counts2 = [], []
        for i in range(n_walk):
            series = gbm_bars(len(bars), rnd2)
            a, n = avg_r(series, cost)
            vals2.append(a)
            counts2.append(n)
        label = "zero cost" if cost == 0 else f"cost ${cost:.2f}"
        summarise(f"   random walk, {label}", vals2)
        print(f"   trades per run: median {statistics.median(counts2):.0f}")

    print("\nTest A is the null that counts: gold's own returns, order destroyed.")
    print("Test B is a parametric control and is inconclusive by construction - a GBM")
    print("pinned as a martingale in one measure drifts in the other, and a trend")
    print("follower reads that drift. See this file's docstring.")


if __name__ == "__main__":
    main()
