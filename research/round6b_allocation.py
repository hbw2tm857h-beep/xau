"""Round 6b: how much risk should the inside-day setup get?

Rounds 4-6 say the entry rules are close to picked over: 41 indicators and 6
fresh ideas produced one adoption between them. But there is a lever that is
not another pattern search at all. The bot runs two strategies whose trades
are almost uncorrelated, and the split between them - trend at 1.0x risk,
inside-day at 0.5x - was chosen in round 5 on return-per-drawdown. That is a
ONE-parameter question over two return streams that have each already been
validated, so the overfitting surface is tiny compared with a filter sweep.

This sweeps the inside-day weight and reports what each choice does to the
combined account curve.

Assumptions, stated because they matter:
  - risk per trade is a fixed fraction of a constant account (additive R, no
    compounding). The real bot sizes off the live balance, so a real curve
    would compound; the ranking of weights is unaffected.
  - trades are placed on the calendar by exit time. The two strategies can
    hold at once, which is the point of running both.
  - Sharpe is computed on monthly totals and annualised by sqrt(12). With
    ~18 years that is ~220 months, enough to rank but not to split hairs.
  - costs are already inside each trade's R (lab.COST / signals cost_per_trade).

Run: python3 research/round6b_allocation.py
"""
import collections
import csv
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import round6 as R6  # noqa: E402
import signals as S  # noqa: E402

UTC = timezone.utc
TREND_RISK = 1.0


def load_bars():
    merged = {}
    for p in [os.path.join(HERE, "..", "data", "xauusd_h1_2008_2015.csv"),
              os.path.join(HERE, "..", "data", "xauusd_h1.csv")]:
        if os.path.exists(p):
            for b in L.load(p):
                merged[b["t"]] = b
    return [merged[k] for k in sorted(merged)]


def curve(series, weights):
    """series: {name: [(time, r)]}. Returns (monthly totals, equity path) in
    units of 'percent of account' given each strategy's risk weight."""
    pts = []
    for name, trades in series.items():
        w = weights[name]
        for t, r in trades:
            pts.append((t, r * w))
    pts.sort(key=lambda x: x[0])
    monthly = collections.OrderedDict()
    eq, path = 0.0, []
    for t, x in pts:
        eq += x
        path.append(eq)
        key = f"{t:%Y-%m}"
        monthly[key] = monthly.get(key, 0.0) + x
    return monthly, path, pts


def max_dd(path):
    peak, dd = 0.0, 0.0
    for v in path:
        peak = max(peak, v)
        dd = max(dd, peak - v)
    return dd


def sharpe(monthly):
    xs = list(monthly.values())
    if len(xs) < 24:
        return 0.0
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    sd = var ** 0.5
    return 0.0 if sd == 0 else (m / sd) * (12 ** 0.5)


def main():
    bars = load_bars()
    print(f"bars {len(bars):,}  {bars[0]['t']:%Y-%m-%d} -> {bars[-1]['t']:%Y-%m-%d}")
    lab = L.Lab(bars)

    trend = [(t["t"], t["r"]) for t in R6.run(lab)]
    F = lab.F
    ib = [(t["t"], t["r"]) for t in S.simulate_ib(F, dict(lab.cfg, inside_day=True))]
    print(f"trend trades      {len(trend):4d}  avgR {sum(r for _, r in trend)/len(trend):+.3f}")
    print(f"inside-day trades {len(ib):4d}  avgR {sum(r for _, r in ib)/len(ib):+.3f}")

    # how much do they actually overlap? monthly correlation
    mt = collections.defaultdict(float)
    mi = collections.defaultdict(float)
    for t, r in trend:
        mt[f"{t:%Y-%m}"] += r
    for t, r in ib:
        mi[f"{t:%Y-%m}"] += r
    keys = sorted(set(mt) | set(mi))
    a = [mt.get(k, 0.0) for k in keys]
    b = [mi.get(k, 0.0) for k in keys]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)
    sa = (sum((x - ma) ** 2 for x in a) / (len(a) - 1)) ** 0.5
    sb = (sum((y - mb) ** 2 for y in b) / (len(b) - 1)) ** 0.5
    print(f"monthly correlation between the two: {cov / (sa * sb):+.3f}  ({len(keys)} months)")

    series = {"trend": trend, "inside_day": ib}
    rows = []
    print(f"\n{'ib weight':>10} {'total %':>9} {'maxDD %':>8} {'ret/DD':>7} {'Sharpe':>7} {'worst mo':>9}")
    for w in [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5]:
        monthly, path, _ = curve(series, {"trend": TREND_RISK, "inside_day": w})
        tot, dd, sh = path[-1], max_dd(path), sharpe(monthly)
        worst = min(monthly.values())
        rows.append({"ib_weight": w, "total_pct": round(tot, 1), "max_dd_pct": round(dd, 1),
                     "ret_over_dd": round(tot / dd, 2) if dd else None,
                     "sharpe": round(sh, 3), "worst_month_pct": round(worst, 1),
                     "months": len(monthly)})
        star = "  <- live setting" if w == 0.5 else ""
        print(f"{w:>10.2f} {tot:>9.1f} {dd:>8.1f} {tot/dd if dd else 0:>7.2f} {sh:>7.3f} {worst:>9.1f}{star}")

    out = os.path.join(HERE, "results_round6b_allocation.csv")
    with open(out, "w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        wtr.writeheader()
        wtr.writerows(rows)
    print(f"\nwrote {out}")

    best_sh = max(rows, key=lambda r: r["sharpe"])
    best_rd = max(rows, key=lambda r: r["ret_over_dd"] or 0)
    print(f"best Sharpe at ib weight {best_sh['ib_weight']}, best return/drawdown at {best_rd['ib_weight']}")
    print("Both are one number read off the same 18 years the weight was chosen on, so treat a")
    print("different winner as weak evidence: it is a re-read of seen data, not a new test.")


if __name__ == "__main__":
    main()
