"""Round 6 (17 Nov 2026): six pre-registered ideas the earlier rounds never tried.

WHY THESE SIX, AND WHY ONLY SIX
-------------------------------
research/results*.csv records 1,063 tested configurations. At a nominal p<0.05
you would expect ~53 of them to look good by luck, so the scarce resource here
is not compute, it is credibility. Rounds 4 and 5 swept 41 popular indicators
and found exactly one that helped. Sweeping more of the same is the worst use
of the remaining evidence, so this round tests a small set, each with a
mechanical reason to exist, and pays the multiple-testing price for six tests
rather than hundreds.

Two of them come from something the data said rather than from a hunch. The
live rules keep four context checks as information only, and the grade built
from them turned out to be *inverted*: over 2008-26 grade A (all four pass)
averages +0.12R while grade B averages +0.20R. The backtest separately shows
that requiring the session filter or the ADX filter makes things worse. Nobody
has tested the complement: what if those conditions are not weak filters but
backwards ones?

PRE-REGISTERED HYPOTHESES (fixed before any result was seen)
    H1 outside-hours only   trade only 20:00-07:00 UK, the inverse of the
                            session filter that hurts when required
    H2 quiet-trend only     trade only when H1 ADX < 20, the inverse of the
                            trend-strength filter that hurts when required
    H3 room-aware target    one exit at +1R when the next daily level is
                            closer than 1.5 daily ATR, otherwise the usual
                            half at +1R and the rest at +2R. A level in the
                            way caps what the trade can reach.
    H4 skip after a loss    ignore the next setup after a losing trade, on the
                            theory that losses cluster in chop
    H5 stop at the candle   stop beyond the signal candle alone (swing=1)
                            instead of the last 5 candles. The no-wick candle's
                            extreme is the natural invalidation point, and a
                            tighter stop means more R per point of movement.
    H6 stop at two candles  the same idea, one notch looser (swing=2)

PASS RULE (fixed before any result was seen)
    1. beats the baseline's average R in BOTH tune (2016-22) and validate
       (2023-24) by at least 0.02R, the bar rounds 2-5 used
    2. keeps at least 60% of the baseline's trades, so a "winner" cannot just
       be a smaller sample
    3. p < 0.05/6 = 0.0083 (Bonferroni over this round's six tests). Subset
       hypotheses (H1, H2, H4) use a label-permutation test, which is exact for
       subsets; the rest use a two-sample bootstrap on the difference of means
    4. not worse than the baseline on 2008-15 or 2025-26. Both have been looked
       at before, so they are a consistency check, never proof

WHAT A PASS EARNS
    A nursery CANDIDATE slot (nursery.json, tier "candidate"): tracked
    silently on live data, no alerts, no size. It is not a live rule change.
    The README says it plainly - all the gold data has now been seen, so there
    is no sealed holdout left to confirm anything on. The only honest
    confirmation left is forward live evidence, which is what the nursery is
    for. Promotion needs 30+ live trades at p<0.05, judged by gate().

Run: python3 research/round6.py
"""
import collections
import csv
import os
import random
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import signals as S  # noqa: E402

UTC = timezone.utc
P2016 = datetime(2016, 1, 1, tzinfo=UTC)
TUNE_END = L.TUNE_END          # 2023-01-01
VAL_END = L.VAL_END            # 2025-01-01
ALPHA = 0.05
N_TESTS = 6
ALPHA_C = ALPHA / N_TESTS
MG = {"part_r": 1.0, "part_frac": 0.5, "target_r": 2.0}
TIGHT = {"part_r": None, "part_frac": 0.0, "target_r": 1.0}


# --------------------------------------------------------------------------
def run(lab, veto=None, mg_for=None, swing=None, skip_after_loss=False):
    """Replay the live rules with one hypothesis applied.

    veto(i, d, s, lab)       -> True to drop a setup
    mg_for(s, datr)          -> management dict for this trade
    swing                    -> override stop_swing_bars
    skip_after_loss          -> ignore the setup after a losing trade
    One trade at a time, exactly as the live bot and lab.backtest do.
    """
    cfg = dict(lab.cfg)
    cfg["filters"] = dict(cfg["filters"])
    if swing is not None:
        cfg["stop_swing_bars"] = swing
    F = lab.F
    trades, busy_until, last_loss = [], -1, False
    for i in range(len(lab.b)):
        if i <= busy_until or not F.warm(i):
            continue
        for d in (1, -1):
            s = S.evaluate(F, i, d, cfg)
            if not s:
                continue
            if skip_after_loss and last_loss:
                last_loss = False      # only the one immediately after
                break
            if veto and veto(i, d, s, lab):
                break
            dc = F.daily_ctx(i)
            mg = mg_for(s, dc["datr"] if dc else None) if mg_for else MG
            fi = L.fill(lab, i, d, s["entry"], cfg["entry_expiry_bars"], True)
            if fi is None:
                break
            res = L.manage(lab, fi, d, s["entry"], s["stop"], mg)
            if res is None:
                break
            r, _held, xi = res
            busy_until = xi
            last_loss = r < 0
            trades.append({"t": lab.b[i]["t"], "d": d, "r": r, "i": i})
            break
    return trades


def periods(trades):
    out = collections.OrderedDict()
    out["2008-15"] = [t["r"] for t in trades if t["t"] < P2016]
    out["tune 2016-22"] = [t["r"] for t in trades if P2016 <= t["t"] < TUNE_END]
    out["val 2023-24"] = [t["r"] for t in trades if TUNE_END <= t["t"] < VAL_END]
    out["2025-26"] = [t["r"] for t in trades if t["t"] >= VAL_END]
    out["all"] = [t["r"] for t in trades]
    return out


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def perm_p_subset(base_trades, keys, b=4000, seed=11):
    """Label permutation: is the chosen subset's mean higher than you would get
    by labelling the same number of baseline trades at random? Exact for a
    subset of one set of trades."""
    rs = [t["r"] for t in base_trades]
    chosen = [t["r"] for t in base_trades if t["i"] in keys]
    k = len(chosen)
    if k < 5 or k >= len(rs):
        return None
    obs = mean(chosen)
    rnd = random.Random(seed)
    hits = sum(1 for _ in range(b) if mean(rnd.sample(rs, k)) >= obs)
    return (hits + 1) / (b + 1)


def boot_p_diff(a, b_, n=4000, seed=11):
    """Two-sample bootstrap: P(variant mean <= baseline mean). The two trade
    sets overlap, so treat this as indicative rather than exact."""
    if len(a) < 5 or len(b_) < 5:
        return None
    rnd = random.Random(seed)
    obs = mean(a) - mean(b_)
    if obs <= 0:
        return 1.0
    hits = 0
    for _ in range(n):
        ra = mean([rnd.choice(a) for _ in a])
        rb = mean([rnd.choice(b_) for _ in b_])
        if ra - rb <= 0:
            hits += 1
    return (hits + 1) / (n + 1)


# --------------------------------------------------------------------------
def main():
    merged = {}
    for p in [os.path.join(HERE, "..", "data", "xauusd_h1_2008_2015.csv"),
              os.path.join(HERE, "..", "data", "xauusd_h1.csv")]:
        if os.path.exists(p):
            for b in L.load(p):
                merged[b["t"]] = b
    bars = [merged[k] for k in sorted(merged)]
    print(f"bars {len(bars):,}  {bars[0]['t']:%Y-%m-%d} -> {bars[-1]['t']:%Y-%m-%d}")
    lab = L.Lab(bars)

    print("\nbaseline: the live rules")
    base = run(lab)
    bp = periods(base)
    for k, v in bp.items():
        print(f"   {k:14} n={len(v):4d} avgR={mean(v):+.3f}")

    uk = lab.uk

    def out_hours(i, d, s, lab_):
        h = uk[i].hour
        return 7 <= h < 20          # veto the session the filter would require

    def quiet(i, d, s, lab_):
        a = lab_.F.adx[i]
        return a is None or a >= 20  # veto strong-trend bars

    def room_target(s, datr):
        if datr and s.get("room") is not None and s["room"] < 1.5 * datr:
            return TIGHT
        return MG

    tests = [
        ("H1 outside-hours only (20-07 UK)", dict(veto=out_hours), "subset"),
        ("H2 quiet trend only (H1 ADX < 20)", dict(veto=quiet), "subset"),
        ("H3 room-aware target (1R if room < 1.5 daily ATR)", dict(mg_for=room_target), "boot"),
        ("H4 skip the setup after a losing trade", dict(skip_after_loss=True), "subset"),
        ("H5 stop beyond the signal candle (swing=1)", dict(swing=1), "boot"),
        ("H6 stop beyond two candles (swing=2)", dict(swing=2), "boot"),
    ]

    rows = []
    print(f"\npass rule: better in tune AND val by >=0.02R, >=60% of the trades, "
          f"p<{ALPHA_C:.4f}, and not worse in 2008-15 or 2025-26")
    for name, kw, ptype in tests:
        tr = run(lab, **kw)
        pp = periods(tr)
        if ptype == "subset":
            keys = {t["i"] for t in tr}
            p = perm_p_subset(base, keys)
        else:
            p = boot_p_diff(pp["all"], bp["all"])
        d_tune = mean(pp["tune 2016-22"]) - mean(bp["tune 2016-22"])
        d_val = mean(pp["val 2023-24"]) - mean(bp["val 2023-24"])
        kept = len(pp["all"]) / max(1, len(bp["all"]))
        consistent = (mean(pp["2008-15"]) >= mean(bp["2008-15"])
                      and mean(pp["2025-26"]) >= mean(bp["2025-26"]))
        passed = (d_tune >= 0.02 and d_val >= 0.02 and kept >= 0.60
                  and p is not None and p < ALPHA_C and consistent)
        print(f"\n{name}")
        for k, v in pp.items():
            print(f"   {k:14} n={len(v):4d} avgR={mean(v):+.3f}")
        print(f"   d_tune={d_tune:+.3f} d_val={d_val:+.3f} kept={kept:.0%} "
              f"p={'n/a' if p is None else f'{p:.4f}'} consistent={consistent} "
              f"-> {'PASS' if passed else 'no'}")
        rows.append({
            "test": name, "n_all": len(pp["all"]), "avgR_all": round(mean(pp["all"]), 4),
            "n_2008_15": len(pp["2008-15"]), "avgR_2008_15": round(mean(pp["2008-15"]), 4),
            "n_tune": len(pp["tune 2016-22"]), "avgR_tune": round(mean(pp["tune 2016-22"]), 4),
            "n_val": len(pp["val 2023-24"]), "avgR_val": round(mean(pp["val 2023-24"]), 4),
            "n_2025_26": len(pp["2025-26"]), "avgR_2025_26": round(mean(pp["2025-26"]), 4),
            "d_tune": round(d_tune, 4), "d_val": round(d_val, 4),
            "kept": round(kept, 3), "p": None if p is None else round(p, 5),
            "alpha_corrected": round(ALPHA_C, 5), "consistent": consistent, "passed": passed,
        })

    rows.insert(0, {
        "test": "BASELINE live rules", "n_all": len(bp["all"]), "avgR_all": round(mean(bp["all"]), 4),
        "n_2008_15": len(bp["2008-15"]), "avgR_2008_15": round(mean(bp["2008-15"]), 4),
        "n_tune": len(bp["tune 2016-22"]), "avgR_tune": round(mean(bp["tune 2016-22"]), 4),
        "n_val": len(bp["val 2023-24"]), "avgR_val": round(mean(bp["val 2023-24"]), 4),
        "n_2025_26": len(bp["2025-26"]), "avgR_2025_26": round(mean(bp["2025-26"]), 4),
        "d_tune": 0.0, "d_val": 0.0, "kept": 1.0, "p": None,
        "alpha_corrected": round(ALPHA_C, 5), "consistent": True, "passed": False,
    })
    out = os.path.join(HERE, "results_round6.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {out}")
    winners = [r["test"] for r in rows if r["passed"]]
    print("PASSED:", ", ".join(winners) if winners else "none")
    print("A pass earns a nursery candidate slot, not a live rule change.")


if __name__ == "__main__":
    main()
