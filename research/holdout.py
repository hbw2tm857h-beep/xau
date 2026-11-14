import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import lab as L
bars=L.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "xauusd_h1.csv")); lab=L.Lab(bars)
P={"session":False,"h4":True,"breakout":False,"swing":5}
MG={"part_r":1.0,"part_frac":0.5,"target_r":2.0}
tr=L.backtest(lab,"ha",P,MG)
tu,va,ho=L.split(tr)
for name,x in (("TUNE 2016-22",tu),("VALIDATE 2023-24",va),("HOLDOUT 2025-26",ho),("ALL",tr)):
    print(f"{name:17s} {L.fmt(L.summarise(x))}")
# by year
import collections
by=collections.defaultdict(list)
for t in tr: by[t['t'].year].append(t['r'])
print("\nBy year:")
for y in sorted(by): s=L.S.stats(by[y]); print(f"  {y}: n={s['n']:3d} win={s['win']:4.0f}% avgR={s['avg']:+.3f} total={s['total']:+.1f}R")
# cost sensitivity
for c in (0.2,0.5,0.8):
    L.COST=c; s=L.summarise(L.backtest(lab,"ha",P,MG)); print(f"cost ${c}: {L.fmt(s)}")
L.COST=0.35
# baseline video rules for contrast
s=L.summarise(L.backtest(lab,"ha",{},{"ha_exit":True})); print("\nVideo rules, 10y:", L.fmt(s))
