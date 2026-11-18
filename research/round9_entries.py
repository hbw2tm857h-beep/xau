"""Round 9: four entry mechanisms the earlier rounds never tried.

WHAT IS ALREADY RULED OUT
-------------------------
"Try other entries" has largely been done. 672 of the 1,070 recorded trials
were non-Heikin-Ashi entries and both families lost money:

  asia     336 configs, mean tune avg R -0.085. Asia-range (00:00-07:00 UK)
           breakout at London AND fade mode, which is a failed-breakout
           reversal, across range filters, trend filters and stop placements.
  pullback 336 configs, mean tune avg R -0.063. Daily trend + H1 the right
           side of EMA50 + dip to EMA20 + Heikin Ashi confirmation.

Round 5 then ran ten well-known standalone systems. Nine failed: Turtle 1 and
2, Connors RSI-2, Bollinger reversion, NR7 breakout, Turtle Soup, golden/death
cross, London opening-range breakout and Eastern-hours long. One passed, the
inside-day breakout, and it is live.

So mean reversion, failed breakouts, opening-range, channel breakout and moving
average crosses are all tested and dead on this instrument. Proposing them again
would be re-running a failed experiment with a bigger multiple-testing bill.

THE FOUR PRE-REGISTERED IDEAS (fixed before any result was seen)
---------------------------------------------------------------
Each has to be mechanically distinct from the above and have a reason to exist.

  E1 H1 inside bar     The one mechanism that passed is a volatility
                       contraction on D1. NR7, its close cousin, failed on D1.
                       Nobody has tried the contraction on the HOURLY chart.
                       This is the strongest prior available: the same
                       mechanism as the live inside-day setup, one timeframe
                       down. Buy-stop at the inside bar's high, sell-stop at
                       its low, first to trade cancels the other.

  E2 4H trigger        Everything in the project triggers on H1 or D1. The 4H
                       Heikin Ashi candle is used as a FILTER but never as the
                       TRIGGER. This runs the adopted logic one timeframe up:
                       the same first-candle-of-a-new-colour, no-wick-against,
                       bigger-body trigger, read on 4H, with the daily trend
                       still agreeing. Fewer, slower signals.

  E3 Rolling squeeze   The asia family tested a breakout from a fixed clock
                       window. This tests a breakout from a contraction
                       wherever it actually happens: the last 12 hourly bars'
                       range in the bottom quarter of its own trailing
                       distribution, then a break of that range. Adaptive, not
                       a time-of-day box.

  E4 Sunday gap fill   Gold opens Sunday evening away from Friday's close.
                       Nothing in the project trades the weekend gap. FX and
                       metals gaps tend to fill, so the mechanically motivated
                       version is mean reversion toward the Friday close, taken
                       only when the gap is large enough to matter.

PASS RULE (fixed before any result was seen)
--------------------------------------------
These are standalone strategies, not variants of the trend rules, so the test
is whether each stands on its own, using the bar round 5 applied to the
inside-day setup:
  1. positive average R in ALL FOUR periods: 2008-15, tune 2016-22,
     val 2023-24, 2025-26
  2. at least 100 completed trades
  3. one-sided bootstrap p < 0.05/4 = 0.0125 (Bonferroni over this round)

Round 8 is the reason the in-sample figure gets no weight of its own: with
1,070 recorded trials, the expected best in-sample Sharpe under no skill is
roughly three times what the live rules actually achieved. Consistency across
periods is the only in-sample evidence worth anything here.

WHAT A PASS EARNS
-----------------
A nursery candidate slot (tier "candidate" in nursery.json): tracked silently
on live data, no alerts, no size, promoted only on 30+ live trades. Not a live
rule change, and not a claim of edge.

Run: python3 research/round9_entries.py
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import round6 as R6  # noqa: E402
import round7_synthetic as R7  # noqa: E402
import signals as S  # noqa: E402

ALPHA = 0.05 / 4
MG = R6.MG
BUF = 0.30          # same entry buffer as the live rules
MIN_TRADES = 100


# --------------------------------------------------------------------------
# Entry generators: each yields (signal bar i, direction, entry, stop, expiry)
# --------------------------------------------------------------------------
def e1_inside_bar(lab):
    """H1 inside bar: both orders live, first to trade cancels the other."""
    b = lab.b
    for i in range(1, len(b)):
        if not lab.F.warm(i):
            continue
        if b[i]["h"] < b[i - 1]["h"] and b[i]["l"] > b[i - 1]["l"]:
            rng = b[i]["h"] - b[i]["l"]
            if rng <= 0:
                continue
            # the side that trades first wins; emit both and let the runner pick
            yield i, 1, b[i]["h"], b[i]["l"], 2
            yield i, -1, b[i]["l"], b[i]["h"], 2


def e2_h4_trigger(lab):
    """The adopted trigger read on the 4-hour Heikin Ashi candle.

    Calls signals.h4_setup, the live implementation, so this test and the
    production bot cannot drift apart. The same arrangement lab.py already
    uses for the hourly rules via signals.evaluate.
    """
    F, cfg = lab.F, lab.cfg
    seen = -1
    for i in range(len(lab.b)):
        if not F.warm(i):
            continue
        k = F.h4_idx[i]
        if k < 1 or k == seen:
            continue
        seen = k                      # act once per closed 4H candle
        for d in (1, -1):
            s = S.h4_setup(F, i, k, d, cfg)
            if s:
                yield i, d, s["entry"], s["stop"], cfg["h4_expiry_bars"]
                break


def e3_squeeze(lab, win=12, look=200, pct=0.25):
    """Breakout from a contraction wherever it happens, not at a set hour."""
    b = lab.b
    ranges = [None] * len(b)
    for i in range(win, len(b)):
        hi = max(z["h"] for z in b[i - win + 1:i + 1])
        lo = min(z["l"] for z in b[i - win + 1:i + 1])
        ranges[i] = hi - lo
    for i in range(win + look, len(b)):
        if not lab.F.warm(i) or ranges[i] is None:
            continue
        hist = [r for r in ranges[i - look:i] if r is not None]
        if len(hist) < look // 2:
            continue
        hist.sort()
        if ranges[i] > hist[int(len(hist) * pct)]:
            continue              # not contracted enough
        hi = max(z["h"] for z in b[i - win + 1:i + 1])
        lo = min(z["l"] for z in b[i - win + 1:i + 1])
        if hi - lo <= 0:
            continue
        yield i, 1, hi + BUF, lo, 6
        yield i, -1, lo - BUF, hi, 6


def e4_sunday_gap(lab, min_gap_atr=0.15):
    """Mean reversion toward Friday's close after a weekend gap."""
    b, uk = lab.b, lab.uk
    for i in range(1, len(b)):
        if not lab.F.warm(i):
            continue
        gap_hours = (b[i]["t"] - b[i - 1]["t"]).total_seconds() / 3600
        if gap_hours < 20:
            continue                  # not a weekend break
        dc = lab.F.daily_ctx(i)
        datr = dc["datr"] if dc else None
        if not datr:
            continue
        prev_close = b[i - 1]["c"]
        gap = b[i]["o"] - prev_close
        if abs(gap) < min_gap_atr * datr:
            continue
        d = -1 if gap > 0 else 1       # trade back toward Friday's close
        if d == 1:
            entry = b[i]["h"] + BUF
            stop = b[i]["l"] - 0.5 * abs(gap)
        else:
            entry = b[i]["l"] - BUF
            stop = b[i]["h"] + 0.5 * abs(gap)
        if abs(entry - stop) <= 0:
            continue
        yield i, d, entry, stop, 12


# --------------------------------------------------------------------------
def run(lab, gen):
    """One trade at a time, same fill and management code as the live rules."""
    trades, busy_until = [], -1
    for i, d, entry, stop, expiry in gen:
        if i <= busy_until:
            continue
        fi = L.fill(lab, i, d, entry, expiry, False)
        if fi is None:
            continue
        res = L.manage(lab, fi, d, entry, stop, MG)
        if res is None:
            continue
        r, _held, xi = res
        busy_until = xi
        trades.append({"t": lab.b[i]["t"], "d": d, "r": r})
    return trades


def main():
    bars = R7.real_bars()
    print(f"bars {len(bars):,}  {bars[0]['t']:%Y-%m-%d} -> {bars[-1]['t']:%Y-%m-%d}")
    lab = L.Lab(bars)

    base = R6.run(lab)
    bp = R6.periods(base)
    print(f"\nlive trend rules for reference: {len(bp['all'])} trades, "
          f"avg {R6.mean(bp['all']):+.3f}R")

    tests = [
        ("E1 H1 inside bar", lambda: e1_inside_bar(lab)),
        ("E2 4H Heikin Ashi trigger", lambda: e2_h4_trigger(lab)),
        ("E3 rolling 12h squeeze breakout", lambda: e3_squeeze(lab)),
        ("E4 Sunday gap fill", lambda: e4_sunday_gap(lab)),
    ]
    print(f"\npass rule: positive in ALL FOUR periods, >={MIN_TRADES} trades, p<{ALPHA:.4f}")
    rows = []
    for name, mk in tests:
        tr = run(lab, mk())
        pp = R6.periods(tr)
        p = R6.boot_p_diff(pp["all"], [0.0] * max(5, len(pp["all"]))) if pp["all"] else None
        four = [pp["2008-15"], pp["tune 2016-22"], pp["val 2023-24"], pp["2025-26"]]
        all_pos = all(len(x) > 0 and R6.mean(x) > 0 for x in four)
        enough = len(pp["all"]) >= MIN_TRADES
        passed = all_pos and enough and p is not None and p < ALPHA
        print(f"\n{name}")
        for k, v in pp.items():
            print(f"   {k:14} n={len(v):5d} avgR={R6.mean(v):+.3f}")
        print(f"   all four positive={all_pos}  trades={len(pp['all'])}  "
              f"p={'n/a' if p is None else f'{p:.4f}'}  ->  {'PASS' if passed else 'no'}")
        rows.append({
            "test": name, "n_all": len(pp["all"]), "avgR_all": round(R6.mean(pp["all"]), 4),
            "n_2008_15": len(pp["2008-15"]), "avgR_2008_15": round(R6.mean(pp["2008-15"]), 4),
            "n_tune": len(pp["tune 2016-22"]), "avgR_tune": round(R6.mean(pp["tune 2016-22"]), 4),
            "n_val": len(pp["val 2023-24"]), "avgR_val": round(R6.mean(pp["val 2023-24"]), 4),
            "n_2025_26": len(pp["2025-26"]), "avgR_2025_26": round(R6.mean(pp["2025-26"]), 4),
            "all_four_positive": all_pos, "p": None if p is None else round(p, 5),
            "alpha": round(ALPHA, 5), "passed": passed,
        })

    out = os.path.join(HERE, "results_round9.csv")
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
