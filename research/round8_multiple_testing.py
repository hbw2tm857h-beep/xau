"""Round 8: how much of the edge survives an honest multiple-testing adjustment?

Round 6 established that research/results*.csv records 1,063 tested
configurations, and that at a nominal 5% threshold about 53 of those would look
good by luck. That was an argument. This measures it.

THE METHOD (Bailey & Lopez de Prado, "The Deflated Sharpe Ratio", Journal of
Portfolio Management 40(5), 94-107; and Harvey & Liu, "Backtesting", SSRN
abstract 2345489, which derives an equivalent haircut).

The False Strategy Theorem: run N skill-free backtests and the best one still
posts a good Sharpe ratio purely from the spread of the trials. Its expected
value is

    E[max SR] ~ sqrt(V[SR]) * [ (1-g) * Z(1 - 1/N) + g * Z(1 - 1/(N*e)) ]

with g the Euler-Mascheroni constant, Z the inverse normal CDF and V[SR] the
variance of the Sharpe estimates across the trials. That is the bar a real
strategy has to clear, not zero. The Deflated Sharpe Ratio then asks how
confident we can be that the observed Sharpe beats that bar, correcting for
track-record length, skew and kurtosis:

    DSR = Phi[ (SR - E[max SR]) * sqrt(T-1)
               / sqrt(1 - g3*SR + ((g4-1)/4) * SR^2) ]

Two things are easy to get wrong and are worth stating:

  1. These are PER-PERIOD Sharpe ratios, never annualised. The period here is
     one trade, so SR = mean(R) / sd(R) over the trade series and T is the
     number of trades.
  2. N is the number of INDEPENDENT trials. Ours are not independent - a
     parameter sweep over one family is highly correlated - so the effective N
     is well below 1,063 and the honest answer is a range. Lopez de Prado
     suggests clustering the trials to estimate it; here the range runs from
     every recorded row down to the number of distinct ideas.

V[SR] is normally the hard input to get, because nobody keeps their failed
backtests. This project logged all of them, so it is measured here rather than
assumed: each trial's tune-period average R is converted to a per-trade Sharpe
using the live strategy's own per-trade standard deviation, which is fair
because every trial shares the same 1R-stop / 2R-target payoff shape.

Run: python3 research/round8_multiple_testing.py
"""
import csv
import glob
import math
import os
import statistics
import sys
from statistics import NormalDist

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import round6 as R6  # noqa: E402
import round7_synthetic as R7  # noqa: E402

EULER = 0.5772156649015329
ND = NormalDist()

# the in-sample selection statistic in each results file, by column name
SELECTION_COLS = ("tune_avgR", "tune_R", "avgR_tune", "avg", "2016-22_avg")


def moments(rs):
    n = len(rs)
    m = sum(rs) / n
    var = sum((r - m) ** 2 for r in rs) / (n - 1)
    sd = var ** 0.5
    g3 = (sum((r - m) ** 3 for r in rs) / n) / (sd ** 3)
    g4 = (sum((r - m) ** 4 for r in rs) / n) / (sd ** 4)
    return m, sd, g3, g4


# results.csv sweeps three unrelated strategy families. "asia" and "pullback"
# are different strategies, not variants of the adopted rules, so their spread
# is real quality dispersion rather than selection noise on one idea. Excluding
# them gives the fairer V[SR]; including them gives the conservative one.
OTHER_FAMILIES = ("asia", "pullback")


def harvest_trials():
    """Every recorded trial's in-sample selection statistic.

    Returns (all trials, trials that are variants of the adopted rules, counts).
    """
    vals, same, per_file = [], [], []
    for path in sorted(glob.glob(os.path.join(HERE, "results*.csv"))):
        got, got_same = [], []
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                for col in SELECTION_COLS:
                    if col in row and row[col] not in (None, ""):
                        try:
                            x = float(row[col])
                        except ValueError:
                            break
                        got.append(x)
                        if row.get("family", "") not in OTHER_FAMILIES:
                            got_same.append(x)
                        break
        vals += got
        same += got_same
        per_file.append((os.path.basename(path), len(got), len(got_same)))
    return vals, same, per_file


def expected_max_sr(v_sr, n):
    """False Strategy Theorem: the Sharpe the best of n skill-free trials gets."""
    if n < 2:
        return 0.0
    bracket = ((1 - EULER) * ND.inv_cdf(1 - 1.0 / n)
               + EULER * ND.inv_cdf(1 - 1.0 / (n * math.e)))
    return (v_sr ** 0.5) * bracket


def dsr(sr, sr0, t, g3, g4):
    denom = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr * sr
    if denom <= 0 or t < 2:
        return None
    return ND.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom))


def main():
    bars = R7.real_bars()
    lab = L.Lab(bars)
    trades = R6.run(lab)
    rs_all = [t["r"] for t in trades]
    # The trials were all scored on the TUNE period, so the candidate has to be
    # scored there too. Estimation variance scales with 1/T: comparing a
    # full-period Sharpe against the spread of tune-period trials would compare
    # a precise estimate with a noisy one and understate the strategy badly.
    rs_tune = [t["r"] for t in trades
               if R7.datetime(2016, 1, 1, tzinfo=R7.UTC) <= t["t"] < L.TUNE_END]
    m, sd, g3, g4 = moments(rs_tune)
    T = len(rs_tune)
    sr = m / sd
    ma, sda, g3a, g4a = moments(rs_all)
    years = (bars[-1]["t"] - bars[0]["t"]).days / 365.25
    per_year = len(rs_all) / years
    print(f"live trade series: {len(rs_all)} trades over {years:.1f} years ({per_year:.0f}/yr)")
    print(f"  WHOLE PERIOD : mean {ma:+.4f}R  sd {sda:.4f}  per-trade Sharpe {ma/sda:.4f}"
          f"  (annualised ~{(ma/sda) * math.sqrt(per_year):.2f})")
    print(f"  TUNE 2016-22 : {T} trades, mean {m:+.4f}R  sd {sd:.4f}  skew {g3:+.3f}"
          f"  kurtosis {g4:.3f}  per-trade Sharpe {sr:.4f}")
    print("  the tune figures are the ones compared below, to match the trials")

    vals, same, per_file = harvest_trials()
    print(f"\nrecorded trials harvested: {len(vals)} "
          f"({len(same)} of them variants of the adopted rules)")
    for name, k, ks in per_file:
        print(f"   {k:5d}  ({ks:4d} same-family)  {name}")

    rows = []
    for scen, pool in (("all trials", vals), ("same-family only", same)):
        tv_sd = statistics.pstdev(pool)
        v_sr = (tv_sd / sd) ** 2
        print(f"\n[{scen}] n={len(pool)}  selection stat sd {tv_sd:.4f}R"
              f"  ->  V[SR] {v_sr:.5f} (sd of trial Sharpes {v_sr**0.5:.4f})")
        print(f"  {'N trials':>10} {'E[max SR]':>11} {'luck share':>11} {'DSR':>8}  verdict")
        for n in (1, 10, 50, 100, 250, len(pool)):
            sr0 = 0.0 if n < 2 else expected_max_sr(v_sr, n)
            p = dsr(sr, sr0, T, g3, g4)
            share = sr0 / sr if sr else 0.0
            verdict = "survives" if (p is not None and p >= 0.95) else (
                "marginal" if (p is not None and p >= 0.90) else "not significant")
            label = "no selection" if n < 2 else str(n)
            print(f"  {label:>10} {sr0:>11.4f} {share:>10.0%}"
                  f" {('n/a' if p is None else f'{p:.4f}'):>8}  {verdict}")
            rows.append({"scenario": scen, "n_trials": n,
                         "trial_sd_r": round(tv_sd, 5), "v_sr": round(v_sr, 6),
                         "expected_max_sr": round(sr0, 5),
                         "luck_share_of_observed": round(share, 4),
                         "dsr": None if p is None else round(p, 5), "verdict": verdict})

    out = os.path.join(HERE, "results_round8.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["scenario", "n_trials", "trial_sd_r", "v_sr",
                                          "expected_max_sr", "luck_share_of_observed",
                                          "dsr", "verdict"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {out}")
    print("\nWhat this does and does not account for:")
    print(f"  - compared on a like basis: tune-period Sharpe {sr:.4f} on {T} trades")
    print("    against the spread of tune-period trial results")
    print("  - N is the number of INDEPENDENT trials. Correlated sweeps make the")
    print("    effective number far smaller than the row count, so read the row")
    print("    matching how many genuinely distinct ideas were tried.")
    print("  - robust to which trials count. Excluding the unrelated families")
    print("    (asia, pullback) makes it HARSHER, not kinder: rounds 4-5's indicator")
    print("    variants scatter more widely than those tightly clustered sweeps.")
    print("  - V[SR] is the OBSERVED spread, which mixes estimation noise with real")
    print("    differences in strategy quality. The theorem wants the spread under")
    print("    no skill, so this overstates V[SR] to the extent some trials were")
    print("    genuinely better or worse. That cuts in the strategy's favour and is")
    print("    not resolved here.")
    print("  - it ignores two pieces of evidence of a different kind: the sealed")
    print("    2008-15 lockbox, which rejected a competing candidate, and round 7's")
    print("    shuffle test, where 0 of 30 order-destroyed histories came near the")
    print("    real result. Neither enters a selection-bias calculation.")


if __name__ == "__main__":
    main()
