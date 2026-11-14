import os, sys, time, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import lab as L
t0=time.time()
bars=L.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "xauusd_h1.csv"))
lab=L.Lab(bars)
print("bars",len(bars),"setup",round(time.time()-t0,1),"s", flush=True)
MG = {
 "ha_exit":       {"ha_exit":True},
 "part1R+ha":     {"part_r":1.0,"part_frac":0.5,"ha_exit":True},
 "part0.5R+ha":   {"part_r":0.5,"part_frac":0.5,"ha_exit":True},
 "tp1R":          {"target_r":1.0},
 "tp1.5R":        {"target_r":1.5},
}
for name, mg in MG.items():
    tr=L.backtest(lab,"ha",{},mg)
    tu,va,ho=L.split(tr)
    print(f"HA video | {name:12s} | TUNE {L.fmt(L.summarise(tu))} | VAL {L.fmt(L.summarise(va))}", flush=True)
print("time",round(time.time()-t0,1))
