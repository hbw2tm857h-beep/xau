"""Out-of-market test: the exact live gold rules on markets they were never tuned on.

Pre-declared before looking at any result (no tuning per market):
- Rules: identical to the live gold rules (4H agreement, no breakout requirement,
  5-bar swing stop, half off at +1R + stop to entry, rest at +2R, 12h order expiry).
- Entry buffer: 0.04 x H1 ATR (gold's $0.30 is about 0.04 x its typical H1 ATR).
- Round-trip cost per trade (spread + slippage, typical retail):
    XAGUSD 0.03 | EURUSD 0.00012 | GBPUSD 0.00018 | USDJPY 0.015 | AUDUSD 0.00014
- Pass mark: average R > +0.05 over 2008-2026 with at least 300 trades and a
  positive result in both halves (2008-2016, 2017-2026).
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

MARKETS = {
    "XAUUSD (reference)": (["xauusd_h1_2008_2015.csv", "xauusd_h1.csv"], 0.35),
    "XAGUSD": (["xagusd_h1.csv"], 0.03),
    "EURUSD": (["eurusd_h1.csv"], 0.00012),
    "GBPUSD": (["gbpusd_h1.csv"], 0.00018),
    "USDJPY": (["usdjpy_h1.csv"], 0.015),
    "AUDUSD": (["audusd_h1.csv"], 0.00014),
}
P = {"h4": True, "breakout": False, "swing": 5, "buf_atr": 0.04}
M = {"part_r": 1.0, "part_frac": 0.5, "target_r": 2.0}
MID = datetime(2017, 1, 1, tzinfo=timezone.utc)

_orig = L.FAMILIES["ha"]


def gen_ab(lab_, p):
    for i, d, entry, stop, exp, cof in _orig(lab_, p):
        b = lab_.b[i]
        entry = (b["h"] if d == 1 else b["l"]) + d * p["buf_atr"] * (lab_.F.hatr[i] or 0)
        yield i, d, entry, stop, exp, cof


L.FAMILIES["ha_ab"] = gen_ab

results = {}
for name, (files, cost) in MARKETS.items():
    paths = [os.path.join(HERE, "..", "data", f) for f in files]
    if not all(os.path.exists(p) for p in paths):
        print(f"{name}: data missing")
        continue
    bars = []
    for p in paths:
        bars += L.load(p)
    bars.sort(key=lambda b: b["t"])
    L.COST = cost
    lab = L.Lab(bars)
    tr = L.backtest(lab, "ha_ab", P, M)
    s = L.summarise(tr)
    a = L.summarise([t for t in tr if t["t"] < MID])
    b = L.summarise([t for t in tr if t["t"] >= MID])
    by = collections.defaultdict(float)
    for t in tr:
        by[t["t"].year] += t["r"]
    pos_years = sum(1 for v in by.values() if v > 0)
    passed = s.get("n", 0) >= 300 and s["avg"] > 0.05 and a.get("avg", -1) > 0 and b.get("avg", -1) > 0
    results[name] = (s, a, b, pos_years, len(by), passed, tr)
    print(f"\n{name}: {L.fmt(s)}  {'PASS' if passed else 'fail'}")
    print(f"   2008-16: {L.fmt(a)}")
    print(f"   2017-26: {L.fmt(b)}")
    print(f"   positive years {pos_years}/{len(by)}: " + " ".join(f"{y % 100:02d}:{v:+.1f}" for y, v in sorted(by.items())))
