import os, sys, time, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import lab as L
bars=L.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "xauusd_h1.csv")); lab=L.Lab(bars)
MG = {
 "ha_exit":     {"ha_exit":True},
 "part1R+ha":   {"part_r":1.0,"part_frac":0.5,"ha_exit":True},
 "tp1R":        {"target_r":1.0},
 "tp1.5R":      {"target_r":1.5},
 "tp2R":        {"target_r":2.0},
 "part1R+tp2R": {"part_r":1.0,"part_frac":0.5,"target_r":2.0},
 "tp1R_eod":    {"target_r":1.0,"max_bars":10},
}
GRIDS = {
 "asia": L.grid({"mode":["break","fade"],"trend":[True,False],"min_rng":[0.1,0.2],"max_rng":[0.6,1.0],"stop":["opp","mid"],"last_hour":[10,13]}),
 "pullback": L.grid({"confirm":["flip","any"],"nowick":[True,False],"swing":[3,5,8],"session":[True,False],"touch_bars":[1,3]}),
 "ha": L.grid({"session":[False,True],"h4":[False,True],"breakout":[True,False],"swing":[3,5,8]}),
}
rows=[]
for fam, g in GRIDS.items():
    for p in g:
        if fam=="asia" and p["mode"]=="fade" and p["stop"]=="mid": continue
        for mname, mg in MG.items():
            tr=L.backtest(lab,fam,p,mg)
            tu,va,ho=L.split(tr)
            s=L.summarise(tu); v=L.summarise(va)
            rows.append({"family":fam,"params":str(p),"mgmt":mname,
                "tune_n":s.get("n",0),"tune_win":round(s.get("win",0),1),"tune_avgR":round(s.get("avg",0),3),"tune_pf":round(s.get("pf",0),2) if s.get("n") else 0,"tune_dd":round(s.get("dd",0),1),
                "val_n":v.get("n",0),"val_win":round(v.get("win",0),1),"val_avgR":round(v.get("avg",0),3),"val_pf":round(v.get("pf",0),2) if v.get("n") else 0})
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.csv"),"w",newline="") as f:
    w=csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print("combos tried:", len(rows))
ok=[r for r in rows if r["tune_n"]>=150]
ok.sort(key=lambda r:-r["tune_avgR"])
print("\nTOP 15 BY TUNE avgR (n>=150) -- with their VALIDATION result")
for r in ok[:15]:
    print(f"{r['family']:8s} {r['mgmt']:12s} T n={r['tune_n']} win={r['tune_win']} R={r['tune_avgR']:+.3f} PF={r['tune_pf']} | V n={r['val_n']} win={r['val_win']} R={r['val_avgR']:+.3f} | {r['params']}")
hw=[r for r in ok if r["tune_win"]>=65]; hw.sort(key=lambda r:-r["tune_avgR"])
print("\nHIGH WIN-RATE (tune win>=65%, n>=150):")
for r in hw[:10]:
    print(f"{r['family']:8s} {r['mgmt']:12s} T n={r['tune_n']} win={r['tune_win']} R={r['tune_avgR']:+.3f} | V n={r['val_n']} win={r['val_win']} R={r['val_avgR']:+.3f} | {r['params']}")
