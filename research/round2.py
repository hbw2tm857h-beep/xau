"""Round 2: one change at a time vs the current rules, on 2016-2024 only.
Kept only if better in BOTH tune (2016-22) and validate (2023-24)."""
import os, sys, csv
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L

bars = [b for b in L.load(os.path.join(HERE, "..", "data", "xauusd_h1.csv")) if b["t"] < L.VAL_END]
lab = L.Lab(bars)
BASE_P = {"session": False, "h4": True, "breakout": False, "swing": 5}
BASE_M = {"part_r": 1.0, "part_frac": 0.5, "target_r": 2.0}

def run(p_over=None, m_over=None, cfg_over=None):
    p = dict(BASE_P, **(p_over or {}))
    if cfg_over: p["cfg"] = cfg_over
    m = dict(BASE_M, **(m_over or {}))
    m = {k: v for k, v in m.items() if v is not None}
    tu, va, _ = L.split(L.backtest(lab, "ha", p, m))
    return L.summarise(tu), L.summarise(va)

TESTS = [("BASELINE", {}, {}, {})]
for k in (3, 8, 12): TESTS.append((f"swing stop {k} bars", {"swing": k}, {}, {}))
for k in (1.0, 1.5, 2.0, 2.5): TESTS.append((f"ATR stop {k}x", {"atr_stop": k}, {}, {}))
for t in (1.5, 2.5, 3.0): TESTS.append((f"final target {t}R", {}, {"target_r": t}, {}))
for pr in (0.75, 1.25, 1.5): TESTS.append((f"partial at {pr}R", {}, {"part_r": pr}, {}))
for pf in (0.33, 0.67): TESTS.append((f"partial size {int(pf*100)}%", {}, {"part_frac": pf}, {}))
TESTS.append(("rest trails on HA flip (no TP2)", {}, {"target_r": None, "ha_exit": True}, {}))
TESTS.append(("rest TP 3R or HA flip", {}, {"target_r": 3.0, "ha_exit": True}, {}))
TESTS.append(("time stop 48h", {}, {"max_bars": 48}, {}))
TESTS.append(("time stop 24h", {}, {"max_bars": 24}, {}))
TESTS.append(("daily trend: HA only", {}, {}, {"daily_trend_mode": "ha"}))
TESTS.append(("allow later no-wick candles", {}, {}, {"first_no_wick_only": False}))
for g in (0.8, 1.5): TESTS.append((f"body growth >= {g}x", {}, {}, {"min_body_growth": g}))
TESTS.append(("no room requirement", {}, {}, {"require_room": False}))
TESTS.append(("room >= 1.0 daily ATR", {}, {}, {"min_room_atr": 1.0}))
TESTS.append(("flip within 4 bars", {}, {}, {"max_bars_since_flip": 4}))
TESTS.append(("4H candle no wick against", {"h4_nowick": True}, {}, {}))
for a in (20, 25): TESTS.append((f"daily ADX >= {a}", {"daily_adx": a}, {}, {}))
TESTS.append(("normal volatility", {"atr_band": True}, {}, {}))
TESTS.append(("H1 ADX >= 20", {"adx": True}, {}, {}))
TESTS.append(("hours 07-20 UK", {"hours": (7, 20)}, {}, {}))
TESTS.append(("hours 12-20 UK (NY)", {"hours": (12, 20)}, {}, {}))
TESTS.append(("entry expiry 4h", {"expiry": 4}, {}, {}))
TESTS.append(("entry buffer $1.00", {}, {}, {"entry_buffer": 1.0}))
TESTS.append(("require breakout", {"breakout": True}, {}, {}))

rows = []
base = None
for name, po, mo, co in TESTS:
    s, v = run(po, mo, co)
    if base is None: base = (s, v)
    dt, dv = s.get("avg", 0) - base[0]["avg"], v.get("avg", 0) - base[1]["avg"]
    keep = name != "BASELINE" and dt > 0.02 and dv > 0.02 and s["n"] >= 0.6 * base[0]["n"]
    rows.append([name, s["n"], round(s["win"], 1), round(s["avg"], 3), v["n"], round(v["win"], 1), round(v["avg"], 3), round(dt, 3), round(dv, 3), "KEEP" if keep else ""])
    print(f"{name:34s} T n={s['n']:3d} win={s['win']:4.1f}% R={s['avg']:+.3f} | V n={v['n']:3d} win={v['win']:4.1f}% R={v['avg']:+.3f} | dT={dt:+.3f} dV={dv:+.3f} {'KEEP' if keep else ''}", flush=True)
with open(os.path.join(HERE, "results_round2.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["change","tune_n","tune_win","tune_avgR","val_n","val_win","val_avgR","d_tune","d_val","verdict"]); w.writerows(rows)
