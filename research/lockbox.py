"""Final one-time test on 2008-2015 (never used for any tuning)."""
import os, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L

bars = L.load(os.path.join(HERE, "..", "data", "xauusd_h1_2008_2015.csv"))
print("bars", len(bars), bars[0]["t"], "->", bars[-1]["t"])
lab = L.Lab(bars)
_orig = L.FAMILIES["ha"]
def gen_ab(lab_, p):
    for i, d, entry, stop, exp, cof in _orig(lab_, p):
        k = p.get("buf_atr")
        if k:
            b = lab_.b[i]
            entry = (b["h"] if d == 1 else b["l"]) + d * k * (lab_.F.hatr[i] or 0)
        yield i, d, entry, stop, exp, cof
L.FAMILIES["ha_ab"] = gen_ab

M = {"part_r": 1.0, "part_frac": 0.5, "target_r": 2.0}
SETS = [
    ("Video's original rules", "ha", {}, {"ha_exit": True}),
    ("Current live rules", "ha", {"h4": True, "breakout": False, "swing": 5}, M),
    ("Candidate: + 0.3x ATR entry buffer", "ha_ab", {"h4": True, "breakout": False, "swing": 5, "buf_atr": 0.3}, M),
]
for name, fam, p, m in SETS:
    tr = L.backtest(lab, fam, p, m)
    s = L.summarise(tr)
    print(f"\n{name}: {L.fmt(s)}")
    by = collections.defaultdict(list)
    for t in tr: by[t["t"].year].append(t["r"])
    print("   " + "  ".join(f"{y}:{sum(v):+.1f}R" for y, v in sorted(by.items())))
