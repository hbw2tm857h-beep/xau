"""Is gold's edge just the 2008-2026 bull market? Split by direction and by gold's yearly trend."""
import os, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L
bars = L.load(os.path.join(HERE, "..", "data", "xauusd_h1_2008_2015.csv")) + L.load(os.path.join(HERE, "..", "data", "xauusd_h1.csv"))
bars.sort(key=lambda b: b["t"])
lab = L.Lab(bars)
tr = L.backtest(lab, "ha", {"h4": True, "breakout": False, "swing": 5}, {"part_r": 1.0, "part_frac": 0.5, "target_r": 2.0})
print("ALL   ", L.fmt(L.summarise(tr)))
print("LONGS ", L.fmt(L.summarise([t for t in tr if t["d"] == 1])))
print("SHORTS", L.fmt(L.summarise([t for t in tr if t["d"] == -1])))
# yearly gold return to classify up / down years
first, last = {}, {}
for b in bars:
    y = b["t"].year; first.setdefault(y, b["o"]); last[y] = b["c"]
yr = {y: last[y] / first[y] - 1 for y in first}
down = {y for y, r in yr.items() if r < 0}
print("\nGold down years:", sorted(down))
print("Trades in DOWN years:", L.fmt(L.summarise([t for t in tr if t["t"].year in down])))
print("  shorts in down years:", L.fmt(L.summarise([t for t in tr if t["t"].year in down and t["d"] == -1])))
print("Trades in UP years:  ", L.fmt(L.summarise([t for t in tr if t["t"].year not in down])))
