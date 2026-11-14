"""Round 3: entry buffer sweep, then combinations on top of the best buffer (2016-2024 only)."""
import os, sys, csv
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L
import signals as S

bars = [b for b in L.load(os.path.join(HERE, "..", "data", "xauusd_h1.csv")) if b["t"] < L.VAL_END]
lab = L.Lab(bars)
BASE_P = {"session": False, "h4": True, "breakout": False, "swing": 5}
BASE_M = {"part_r": 1.0, "part_frac": 0.5, "target_r": 2.0}

# ATR-relative buffer needs a generator tweak: shift entry by k x H1 ATR beyond the candle
_orig = L.FAMILIES["ha"]
def gen_ha_atrbuf(lab_, p):
    k = p.get("buf_atr")
    for i, d, entry, stop, exp, cof in _orig(lab_, p):
        if k:
            b = lab_.b[i]
            entry = (b["h"] if d == 1 else b["l"]) + d * k * (lab_.F.hatr[i] or 0)
        yield i, d, entry, stop, exp, cof
L.FAMILIES["ha_ab"] = gen_ha_atrbuf

def run(p_over=None, m_over=None, cfg_over=None, fam="ha"):
    p = dict(BASE_P, **(p_over or {}))
    if cfg_over: p["cfg"] = dict(cfg_over)
    m = {k: v for k, v in dict(BASE_M, **(m_over or {})).items() if v is not None}
    tu, va, _ = L.split(L.backtest(lab, fam, p, m))
    return L.summarise(tu), L.summarise(va)

rows = []
def show(name, s, v):
    rows.append([name, s["n"], round(s["win"],1), round(s["avg"],3), v["n"], round(v["win"],1), round(v["avg"],3)])
    print(f"{name:44s} T n={s['n']:3d} win={s['win']:4.1f}% R={s['avg']:+.3f} | V n={v['n']:3d} win={v['win']:4.1f}% R={v['avg']:+.3f}", flush=True)

print("== entry buffer ($)")
for b in (0.3, 0.6, 1.0, 1.5, 2.0, 3.0):
    show(f"buffer ${b}", *run(cfg_over={"entry_buffer": b}))
print("== entry buffer (x H1 ATR)")
for k in (0.05, 0.1, 0.2, 0.3, 0.5):
    show(f"buffer {k}x ATR", *run({"buf_atr": k}, fam="ha_ab"))

with open(os.path.join(HERE, "results_round3.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["test","tune_n","tune_win","tune_avgR","val_n","val_win","val_avgR"]); w.writerows(rows)

print("\n== combinations on top of buffer 0.3x ATR (greedy: keep if better in both by > 0.02R, n >= 60% of original)")
cur_p = {"buf_atr": 0.3}; cur_m = {}; cur_c = {}
best = run(cur_p, cur_m, cur_c, fam="ha_ab"); show("BASE: buffer 0.3x ATR", *best)
n_floor = 0.6 * 286
CANDS = [
    ("partial at 1.25R", {}, {"part_r": 1.25}, {}),
    ("partial at 1.5R", {}, {"part_r": 1.5}, {}),
    ("final target 2.5R", {}, {"target_r": 2.5}, {}),
    ("partial size 33%", {}, {"part_frac": 0.33}, {}),
    ("swing stop 3", {"swing": 3}, {}, {}),
    ("swing stop 8", {"swing": 8}, {}, {}),
    ("allow later no-wick candles", {}, {}, {"first_no_wick_only": False}),
    ("daily ADX >= 20", {"daily_adx": 20}, {}, {}),
    ("normal volatility", {"atr_band": True}, {}, {}),
    ("H1 ADX >= 20", {"adx": True}, {}, {}),
    ("hours 07-20 UK", {"hours": (7, 20)}, {}, {}),
    ("require breakout", {"breakout": True}, {}, {}),
    ("4H candle no wick against", {"h4_nowick": True}, {}, {}),
    ("room >= 1.0 daily ATR", {}, {}, {"min_room_atr": 1.0}),
    ("flip within 4 bars", {}, {}, {"max_bars_since_flip": 4}),
]
for rnd in range(3):
    improved = False
    for name, po, mo, co in CANDS:
        p = dict(cur_p, **po); m = dict(cur_m, **mo); c = dict(cur_c, **co)
        if p == cur_p and m == cur_m and c == cur_c:
            continue
        s, v = run(p, m, c, fam="ha_ab")
        dt, dv = s["avg"] - best[0]["avg"], v["avg"] - best[1]["avg"]
        ok = dt > 0.02 and dv > 0.02 and s["n"] >= n_floor
        show(f"  r{rnd+1} + {name}{'  -> KEEP' if ok else ''}", s, v)
        if ok:
            cur_p, cur_m, cur_c, best, improved = p, m, c, (s, v), True
    if not improved:
        break
print("\nFINAL:", cur_p, cur_m, cur_c); show("FINAL", *best)
with open(os.path.join(HERE, "results_round3.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["test","tune_n","tune_win","tune_avgR","val_n","val_win","val_avgR"]); w.writerows(rows)
