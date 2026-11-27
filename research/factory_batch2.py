"""Strategy factory, batch 2 (rules fixed 27 Nov 2026, before either part was
run). Bradley approved both batch 2 proposals from research/factory_batch1.md.

Part A, costs at the London open. Spreads are wider in the first minutes of the
London session, so batch 1's five near misses, all London first-hour range
breaks, are re-run with 1.5 times their costs:
  EURUSD short, 3-candle exit;  EURJPY short, daily Heikin Ashi filter (F2),
  3-candle exit;  GBPUSD long, 10-candle exit;  WTI both ways, F2, 2-ATR trail;
  Gold short, 2-ATR trail.
A rule holds if, at 1.5 times costs, its 2020-26 average is at least +0.05R,
positive in each of 2020-22 and 2023-26 with at least 20 trades, and its
2008-19 average is above zero. Rules that hold are proposed as silent nursery
candidates (#candidate-tracking), judged by the live gate only; 2020-26 has
been seen for them, so no new p-value is claimed and hypotheses_tested is not
raised for this part.

Part B, a diverse cut list. Batch 1's harness, build test and cut, unchanged,
except: the London first-hour range family (orb) is left off the cut list (its
2020-26 test is used up), and at most 3 rules per entry family go to the cut.
hypotheses_tested rises by the number sent to the cut.

Writes research/factory_batch2.json (part B) and prints part A.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import factory as F  # noqa: E402

NEAR = [("EURUSD", "short", [], "X5"), ("EURJPY", "short", ["F2"], "X5"), ("GBPUSD", "long", [], "X6"),
        ("WTI", "both", ["F2"], "X8"), ("Gold", "short", [], "X8")]


def part_a():
    print("Part A: near misses at 1.5x costs")
    out = []
    for mk, ds, fs, x in NEAR:
        m = F.Market(mk)
        m.bps *= 1.5
        r = {"market": mk, "v": ["orb", "H1", 0, ""], "dirs": ds, "f": fs, "x": x}
        ev, take, R, xi = F.rule_trades(m, r, {})
        ep, yr = m.ep[ev[0][take]], m.year[ev[0][take]]
        b, c = take[ep < F.BUILD_END], take[ep >= F.BUILD_END]
        parts, ok = [], len(c) > 0 and R[c].mean() >= 0.05 and len(b) > 0 and R[b].mean() > 0
        for bn, y0, y1 in F.CUT_BLOCKS:
            bb = take[(yr >= y0) & (yr < y1)]
            if len(bb) >= 20:
                ok &= R[bb].mean() > 0
            parts.append(f"{bn} {R[bb].mean():+.3f} ({len(bb)})" if len(bb) else f"{bn} none")
        line = (f"  {F.describe(r)} at {m.bps:.2f}bp: 2008-19 {R[b].mean():+.3f}R ({len(b)}), "
                f"2020-26 {R[c].mean():+.3f}R ({len(c)}) | " + " | ".join(parts) + f" | {'holds' if ok else 'fails'}")
        print(line, flush=True)
        out.append({"rule": F.describe(r), "spec": r, "cost_bps": m.bps, "build": round(float(R[b].mean()), 3),
                    "n_build": int(len(b)), "cut": round(float(R[c].mean()), 3), "n_cut": int(len(c)),
                    "periods": parts, "verdict": "holds" if ok else "fails"})
    return out


if __name__ == "__main__":
    a = part_a()
    import json
    json.dump(a, open(os.path.join(HERE, "factory_batch2_costs.json"), "w"), indent=1)
    F.main(batch="batch2", exclude=("orb",), family_cap=3)
