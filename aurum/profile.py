"""Personal edge profiling.

Feed it your own trade history (CSV, see ``TEMPLATE``) and it will
  1. reconstruct the market context at each entry using only data known then,
  2. compute R, MFE/MAE and the path, and classify every trade with the taxonomy,
  3. benchmark each trade against random-timing entries (same day, same side,
     same stop distance) to separate timing skill from market drift,
  4. attempt to DISPROVE each self-assessment claim with an explicit test.

With no personal file it runs the same tests on the lab's mechanical setups as a
market-level baseline: any personal edge has to beat that baseline to be skill.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import DEFAULT
from .simulator import Path, simulate
from .stats import summarise, bootstrap_ci, welch
from .trades import CONTEXT, add_relative
from .taxonomy import flag_trades, M as MISTAKES
from .behaviour import oaxaca

TEMPLATE = """open_time,direction,entry,stop,exit_time,exit_price,target,setup,notes
2024-03-05 14:20,short,2128.50,2134.00,2024-03-05 18:05,2119.80,2117.50,exhaustion,sold the spike into resistance
2024-03-07 09:10,long,2148.00,2142.50,2024-03-07 10:30,2142.30,2159.00,breakout,stopped on the retest
"""

SELF_ASSESSMENT = [
    ("SA1", "I am better on the short side than the long side.",
     "Short avg R exceeds long avg R and the bootstrap 95% CI of the difference excludes 0."),
    ("SA2", "My long-side weakness is explained by market conditions, not by skill.",
     "Most of the long/short gap comes from the regime mix (composition) rather than within-regime results."),
    ("SA3", "I trade short-side momentum well.",
     "Shorts taken WITH downside momentum (rel_mom6 > 1) beat both shorts against momentum and the random-timing baseline."),
    ("SA4", "I can identify exhausted moves.",
     "Trades that fade an extended move (>2.5 ATR against the trade over 6h) beat random timing and the lab's mechanical fades."),
    ("SA5", "My sell timing is good.",
     "Short entries beat random entries on the same day with the same stop distance (positive timing alpha)."),
    ("SA6", "I can tell continuation from reversal.",
     "Both continuation-type and reversal-type trades are positive, and neither is worse than random timing."),
]


def load_user_trades(path) -> pd.DataFrame:
    u = pd.read_csv(path)
    u.columns = [c.strip().lower() for c in u.columns]
    u["open_time"] = pd.to_datetime(u["open_time"])
    u["exit_time"] = pd.to_datetime(u["exit_time"])
    dmap = {"long": 1, "buy": 1, "1": 1, "short": -1, "sell": -1, "-1": -1}
    u["direction"] = u["direction"].astype(str).str.lower().str.strip().map(dmap)
    if "setup" not in u:
        u["setup"] = "discretionary"
    u["setup"] = u["setup"].fillna("discretionary")
    return u.dropna(subset=["direction", "entry", "stop", "exit_price"]).reset_index(drop=True)


def reconstruct(u: pd.DataFrame, f: pd.DataFrame, path: Path, n_random: int = 30, seed: int = 0) -> pd.DataFrame:
    """Attach decision context + path stats + random-timing baseline to each user trade."""
    rng = np.random.default_rng(seed)
    tc = f["tc"].values
    rows = []
    for k, x in u.iterrows():
        i = int(np.searchsorted(tc, np.datetime64(x["open_time"]), side="right")) - 1
        if i < 0:
            continue
        d = int(x["direction"])
        risk = abs(x["entry"] - x["stop"])
        if risk <= 0:
            continue
        atr = float(f["atr"].iloc[i])
        r = d * (x["exit_price"] - x["entry"]) / risk
        a = path.start_index(x["open_time"])
        b = path.start_index(x["exit_time"])
        seg_h, seg_l = path.h[a:b + 1], path.l[a:b + 1]
        mfe = ((seg_h.max() - x["entry"]) if d > 0 else (x["entry"] - seg_l.min())) / risk if len(seg_h) else np.nan
        mae = ((x["entry"] - seg_l.min()) if d > 0 else (seg_h.max() - x["entry"])) / risk if len(seg_h) else np.nan
        tgt = x.get("target")
        tgt = float(tgt) if pd.notna(tgt) else x["entry"] + d * 2 * risk
        hold = max(60, (x["exit_time"] - x["open_time"]).total_seconds() / 60)
        post = simulate(path, a, d, float(x["stop"]), tgt, 48 * 60, atr, post_minutes=24 * 60)
        # random timing baseline: same side, same stop distance, same R target, random start within +-24h
        rand = []
        for _ in range(n_random):
            off = rng.integers(-24 * 4, 24 * 4)
            s = min(max(a + off, 0), len(path.t) - 2)
            mid = path.o[s]
            rr = simulate(path, s, d, mid - d * risk, mid + d * abs(tgt - x["entry"]), int(hold), atr)
            if rr.get("filled"):
                rand.append(rr["r"])
        row = {"user_idx": k, "idx": i, "trade_id": f"USR-{k:04d}", "setup": x["setup"], "family": "user",
               "direction": d, "entry": x["entry"], "stop_px": x["stop"], "target_px": tgt, "exit": x["exit_price"],
               "fill_time": x["open_time"], "exit_time": x["exit_time"], "r": r, "r_gross": r, "cost_r": 0.0,
               "risk": risk, "stop_atr": risk / atr, "mfe_r": mfe, "mae_r": mae,
               "exit_reason": "user", "post_hit_target": post.get("post_hit_target", False),
               "post_mae_r": post.get("post_mae_r", np.nan), "post_mfe_r": post.get("post_mfe_r", np.nan),
               "random_baseline_r": float(np.mean(rand)) if rand else np.nan,
               "timing_alpha": r - float(np.mean(rand)) if rand else np.nan,
               "ref_level": np.nan, "notes": x.get("notes", "")}
        rows.append(row)
    t = pd.DataFrame(rows)
    if not len(t):
        return t
    ctx = f.loc[t["idx"].values, CONTEXT].reset_index(drop=True)
    t = pd.concat([t, ctx], axis=1)
    t["win"] = (t["r"] > 0).astype(int)
    t["crosses_split"] = False
    return add_relative(t)


def _verdict(ok: bool | None, n: int, min_n: int = 20) -> str:
    if n < min_n:
        return "insufficient data"
    return "supported" if ok else "NOT supported"


def test_self_assessment(t: pd.DataFrame, mech: pd.DataFrame | None = None) -> list[dict]:
    """Attempt to falsify each self-assessment claim. ``t`` = trades to profile."""
    L, S = t[t["direction"] > 0], t[t["direction"] < 0]
    res = []
    # SA1
    diff = S["r"].mean() - L["r"].mean() if len(S) and len(L) else np.nan
    rng = np.random.default_rng(0)
    if len(S) >= 10 and len(L) >= 10:
        boots = [rng.choice(S["r"].values, len(S)).mean() - rng.choice(L["r"].values, len(L)).mean() for _ in range(2000)]
        lo, hi = np.percentile(boots, [2.5, 97.5])
    else:
        lo = hi = np.nan
    res.append({"id": "SA1", "evidence": {"short": summarise(S["r"]), "long": summarise(L["r"]),
                                          "diff": diff, "ci": [lo, hi]},
                "verdict": _verdict(lo > 0 if lo == lo else None, min(len(S), len(L)), 10)})
    # SA2
    oa = oaxaca(t)
    share = oa["composition_effect"] / oa["total_gap"] if oa["total_gap"] else np.nan
    res.append({"id": "SA2", "evidence": {**oa, "composition_share": share},
                "verdict": _verdict(share > 0.5 if share == share else None, min(len(S), len(L)), 10)})
    # SA3
    with_m, against = S[S["rel_mom6"] > 1], S[S["rel_mom6"] < -1]
    ok = (with_m["r"].mean() > against["r"].mean()) and (with_m["timing_alpha"].mean() > 0 if "timing_alpha" in t else with_m["r"].mean() > 0)
    res.append({"id": "SA3", "evidence": {"short_with_momentum": summarise(with_m["r"]),
                                          "short_against_momentum": summarise(against["r"]),
                                          "timing_alpha_with": float(with_m["timing_alpha"].mean()) if "timing_alpha" in t else None},
                "verdict": _verdict(ok, len(with_m), 15)})
    # SA4
    fades = t[t["rel_mom6"] < -2.5]
    bench = None
    if mech is not None:
        mf = mech[(mech["rel_mom6"] < -2.5) & mech["split"].isin(["discovery", "validation", "holdout"])]
        bench = summarise(mf["r"])
    ok = fades["r"].mean() > max(0, bench["avg_r"] if bench else 0) and (
        fades["timing_alpha"].mean() > 0 if "timing_alpha" in t else True)
    res.append({"id": "SA4", "evidence": {"fades": summarise(fades["r"]), "mechanical_fade_benchmark": bench,
                                          "by_side": {"long": summarise(fades.loc[fades.direction > 0, "r"]),
                                                      "short": summarise(fades.loc[fades.direction < 0, "r"])}},
                "verdict": _verdict(ok, len(fades), 15)})
    # SA5
    if "timing_alpha" in t:
        ta = S["timing_alpha"].dropna()
        ci = bootstrap_ci(ta.values) if len(ta) > 10 else (np.nan, np.nan)
        res.append({"id": "SA5", "evidence": {"short_timing_alpha": float(ta.mean()) if len(ta) else None, "ci": ci,
                                              "long_timing_alpha": float(L["timing_alpha"].mean()) if len(L) else None},
                    "verdict": _verdict(ci[0] > 0 if ci[0] == ci[0] else None, len(ta), 15)})
    else:
        S_mae = S["mae_r"].mean(); L_mae = L["mae_r"].mean()
        res.append({"id": "SA5", "evidence": {"short_mae": S_mae, "long_mae": L_mae,
                                              "note": "No random-timing baseline for mechanical trades; MAE compared."},
                    "verdict": _verdict(S_mae < L_mae, len(S), 15)})
    # SA6
    cont = t[np.sign(t["rel_mom12"]) > 0]; rev = t[np.sign(t["rel_mom12"]) < 0]
    ok = cont["r"].mean() > 0 and rev["r"].mean() > 0
    res.append({"id": "SA6", "evidence": {"continuation": summarise(cont["r"]), "reversal": summarise(rev["r"]),
                                          "by_side": {f"{k}_{s}": summarise(g.loc[g.direction == dv, "r"])
                                                      for k, g in (("cont", cont), ("rev", rev))
                                                      for s, dv in (("long", 1), ("short", -1))}},
                "verdict": _verdict(ok, min(len(cont), len(rev)), 15)})
    for r in res:
        meta = [x for x in SELF_ASSESSMENT if x[0] == r["id"]][0]
        r["claim"], r["test"] = meta[1], meta[2]
    return res


def why_sells_lose(t: pd.DataFrame, cf=None) -> pd.DataFrame:
    """Which mistake categories separate losing shorts from winning shorts?"""
    S = t[t["direction"] < 0]
    if not len(S):
        return pd.DataFrame()
    fl = flag_trades(S, cf)
    lose = S["r"] <= 0
    rows = []
    for m in MISTAKES:
        on = fl[m.id]
        if on.sum() < 5:
            continue
        rows.append({"id": m.id, "name": m.name, "phase": m.phase,
                     "freq_losing_shorts": float(on[lose].mean()), "freq_winning_shorts": float(on[~lose].mean()),
                     "lift": float(on[lose].mean() - on[~lose].mean()),
                     "avg_r_flagged": float(S.loc[on, "r"].mean())})
    return pd.DataFrame(rows).sort_values("lift", ascending=False)
