import os, sys, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import lab as L
bars=L.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "xauusd_h1.csv")); lab=L.Lab(bars)
P={"session":False,"h4":True,"breakout":False,"swing":5}
MG={
 "tp1R":{"target_r":1.0},
 "tp0.75R":{"target_r":0.75},
 "tp0.5R":{"target_r":0.5},
 "part1R+tp2R":{"part_r":1.0,"part_frac":0.5,"target_r":2.0},
 "part0.5R+tp1.5R":{"part_r":0.5,"part_frac":0.5,"target_r":1.5},
 "part0.75R+tp1.5R":{"part_r":0.75,"part_frac":0.5,"target_r":1.5},
 "part0.5R+tp1R":{"part_r":0.5,"part_frac":0.5,"target_r":1.0},
 "part1R+tp1.5R":{"part_r":1.0,"part_frac":0.5,"target_r":1.5},
}
out=[]
for m,mg in MG.items():
    tu,va,ho=L.split(L.backtest(lab,"ha",P,mg))
    s=L.summarise(tu); v=L.summarise(va)
    out.append((m,s,v))
    print(f"{m:17s} TUNE {L.fmt(s)} | VAL {L.fmt(v)}")
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results_stage3.csv"),"w",newline="") as f:
    w=csv.writer(f); w.writerow(["mgmt","tune_n","tune_win","tune_avgR","val_n","val_win","val_avgR"])
    for m,s,v in out: w.writerow([m,s['n'],round(s['win'],1),round(s['avg'],3),v['n'],round(v['win'],1),round(v['avg'],3)])
