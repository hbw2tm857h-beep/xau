"""Edge discovery: exhaustive condition scan + walk-forward machine learning.

The scan runs ONLY on the discovery split. Every cell it evaluates is a trial and
is counted in the multiple-testing denominator. Only top cells are promoted to the
experiment engine, which then tests them on later data exactly once.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stats import summarise, benjamini_hochberg
from .config import STORE

NUMERIC_FEATURES = [
    "rel_mom3", "rel_mom6", "rel_mom12", "rel_mom24", "rel_rsi", "rel_run_len", "rel_h4_mom6", "rel_d_mom20",
    "adx", "er10", "er30", "rel_ema20_slope", "rel_ema50_slope", "rel_d_ema50_slope",
    "atr_pct", "atr_ratio", "bb_width_pct", "d_volpct", "range20_atr", "range_atr",
    "rel_body", "rel_clv", "fwd_wick", "back_wick", "stop_atr",
    "rel_dist_ema20", "rel_dist_ema50", "rel_dist_ema200", "rel_pos20", "rel_pos50", "rel_d_ext",
    "room_fwd", "room_in_r", "room_fwd_htf", "room_back_htf", "room_in_r_htf", "dist_prev_day_fwd", "dist_round50", "opp_touches",
    "rel_h4_dist_ema20", "rel_mtf_votes", "vol_rel", "rel_real_yield_chg20", "rel_usd_chg20", "vix",
]
CATEGORICAL = ["session", "regime_trend", "regime_vol", "regime_char", "with_daily", "rel_structure",
               "rel_h4_structure", "rel_d_structure", "liq_fwd", "liq_back"]


def scan(t: pd.DataFrame, bins: int = 3, min_n: int = 40, split: str = "discovery") -> pd.DataFrame:
    """Univariate scan of every (setup, direction, feature-bin) cell on one split.

    Bin edges are computed on that split only, so they are frozen before later data.
    """
    d = t[(t["split"] == split) & ~t["crosses_split"]]
    rows = []
    for (s, dr), g in d.groupby(["setup", "direction"]):
        base = g["r"].mean()
        for f in NUMERIC_FEATURES:
            x = g[f]
            if x.notna().sum() < min_n * bins:
                continue
            edges = np.unique(np.nanquantile(x, np.linspace(0, 1, bins + 1)))
            if len(edges) < 3:
                continue
            edges[0], edges[-1] = -np.inf, np.inf
            for lo, hi in zip(edges[:-1], edges[1:]):
                rr = g.loc[(x >= lo) & (x < hi), "r"].values
                if len(rr) < min_n:
                    continue
                st = summarise(rr)
                rows.append({"setup": s, "direction": int(dr), "feature": f, "op": "between",
                             "lo": float(lo), "hi": float(hi), "n": st["n"], "win": st["win"],
                             "avg_r": st["avg_r"], "t": st["t"], "p": st["p"], "sharpe": st["sharpe"],
                             "base_avg_r": base, "lift": st["avg_r"] - base})
        for f in CATEGORICAL:
            for v, gg in g.groupby(f):
                if len(gg) < min_n:
                    continue
                st = summarise(gg["r"].values)
                rows.append({"setup": s, "direction": int(dr), "feature": f, "op": "==", "lo": v, "hi": v,
                             "n": st["n"], "win": st["win"], "avg_r": st["avg_r"], "t": st["t"], "p": st["p"],
                             "sharpe": st["sharpe"], "base_avg_r": base, "lift": st["avg_r"] - base})
    df = pd.DataFrame(rows)
    df["q"] = benjamini_hochberg(df["p"].values)
    return df.sort_values("t", ascending=False).reset_index(drop=True)


def pair_scan(t: pd.DataFrame, uni: pd.DataFrame, top_k: int = 10, min_n: int = 40,
              split: str = "discovery") -> pd.DataFrame:
    """Two-condition interactions: cross the top-k single cells of each setup/direction.

    Every evaluated pair is a trial (returned so the caller can count it).
    """
    from .hypothesis import mask
    d = t[(t["split"] == split) & ~t["crosses_split"]]
    rows = []
    for (s, dr), g in uni.groupby(["setup", "direction"]):
        cells = g.sort_values("lift", ascending=False).head(top_k)
        specs = [scan_to_spec(r)["conditions"][0] for _, r in cells.iterrows()]
        base = d[(d["setup"] == s) & (d["direction"] == dr)]
        for i in range(len(specs)):
            for j in range(i + 1, len(specs)):
                if specs[i]["f"] == specs[j]["f"]:
                    continue
                conds = [specs[i], specs[j]]
                m = mask(base, {"setup": s, "direction": int(dr), "conditions": conds})
                rr = base.loc[m, "r"].values
                if len(rr) < min_n:
                    continue
                st = summarise(rr)
                rows.append({"setup": s, "direction": int(dr), "feature": f"{specs[i]['f']} & {specs[j]['f']}",
                             "op": "pair", "conds": conds, "n": st["n"], "win": st["win"], "avg_r": st["avg_r"],
                             "t": st["t"], "p": st["p"], "sharpe": st["sharpe"], "base_avg_r": base["r"].mean(),
                             "lift": st["avg_r"] - base["r"].mean()})
    df = pd.DataFrame(rows)
    if len(df):
        df["q"] = benjamini_hochberg(df["p"].values)
        df = df.sort_values("t", ascending=False).reset_index(drop=True)
    return df


def scan_to_spec(row) -> dict:
    if row.get("op") == "pair":
        return {"setup": row["setup"], "direction": int(row["direction"]), "conditions": list(row["conds"]),
                "exit": "base", "origin": "mined_pair",
                "rationale": f"Pair-scan cell t={row['t']:.2f}, lift {row['lift']:+.3f}R on discovery."}
    if row["op"] == "==":
        v = row["lo"]
        v = v.item() if hasattr(v, "item") else v
        cond = {"f": row["feature"], "op": "==", "v": v}
    else:
        lo, hi = row["lo"], row["hi"]
        if np.isinf(lo):
            cond = {"f": row["feature"], "op": "<", "v": round(float(hi), 4)}
        elif np.isinf(hi):
            cond = {"f": row["feature"], "op": ">=", "v": round(float(lo), 4)}
        else:
            cond = {"f": row["feature"], "op": "between", "v": [round(float(lo), 4), round(float(hi), 4)]}
    return {"setup": row["setup"], "direction": int(row["direction"]), "conditions": [cond], "exit": "base",
            "origin": "mined", "rationale": f"Scan cell t={row['t']:.2f}, lift {row['lift']:+.3f}R on discovery."}


# ---------------------------------------------------------------------------- ML
ML_FEATURES = NUMERIC_FEATURES + ["hour", "dow"]


def walk_forward_ml(t: pd.DataFrame, first_test_year: int = 2012, top_frac: float = 0.2,
                    embargo_hours: int = 72, seed: int = 0, cf: pd.DataFrame | None = None) -> dict:
    """Anchored walk-forward meta-labelling.

    For each test year Y: train a gradient-boosted classifier on all trades that
    CLOSED at least ``embargo_hours`` before Y starts, predict P(win) for year Y,
    and keep only the top ``top_frac`` of predicted trades. The model never sees
    the year it is scored on. Returns per-year OOS stats and feature importances.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance

    d = t[t["split"] != "archive"].copy()
    d["setup_code"] = d["setup"].astype("category").cat.codes
    feats = [f for f in ML_FEATURES if f in d] + ["setup_code", "direction"]
    years = sorted(d["year"].unique())
    preds = []
    imp_acc = []
    for y in [y for y in years if y >= first_test_year]:
        start = pd.Timestamp(f"{y}-01-01")
        tr = d[d["exit_time"] < start - pd.Timedelta(hours=embargo_hours)]
        te = d[d["year"] == y]
        if len(tr) < 2000 or not len(te):
            continue
        clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                             min_samples_leaf=200, l2_regularization=1.0, random_state=seed)
        clf.fit(tr[feats], tr["win"])
        p = clf.predict_proba(te[feats])[:, 1]
        thr = np.quantile(clf.predict_proba(tr[feats].iloc[-20000:])[:, 1], 1 - top_frac)  # threshold from TRAIN only
        preds.append(pd.DataFrame({"trade_id": te["trade_id"].values, "year": y, "p": p,
                                   "selected": p >= thr, "r": te["r"].values, "split": te["split"].values}))
        if y in (2018, 2022):
            pi = permutation_importance(clf, te[feats], te["win"], n_repeats=3, random_state=seed,
                                        scoring="roc_auc")
            imp_acc.append(pd.Series(pi.importances_mean, index=feats))
    P = pd.concat(preds, ignore_index=True)
    per_year = []
    for y, g in P.groupby("year"):
        a, s = summarise(g["r"].values), summarise(g.loc[g["selected"], "r"].values)
        per_year.append({"year": int(y), "all_n": a["n"], "all_avg_r": a["avg_r"], "sel_n": s["n"],
                         "sel_avg_r": s["avg_r"], "sel_win": s["win"]})
    imp = (pd.concat(imp_acc, axis=1).mean(axis=1).sort_values(ascending=False)
           if imp_acc else pd.Series(dtype=float))
    from sklearn.metrics import roc_auc_score
    auc = {sp: float(roc_auc_score((g["r"] > 0).astype(int), g["p"])) for sp, g in P.groupby("split")
           if g["r"].gt(0).nunique() > 1}
    sel = P[P["selected"]]
    if cf is not None:
        x = sel.merge(cf, on="trade_id", how="left")
        cols = [c for c in cf.columns if c != "trade_id"]
        # holdout deliberately NOT shown: choosing an exit from it would spend the holdout
        exits = {sp: {c: float(g[c].mean()) for c in cols} for sp, g in x.groupby("split") if sp != "holdout"}
    else:
        exits = {}
    return {
        "selected_by_exit": exits,
        "per_year": per_year,
        "oos_selected": {sp: summarise(g["r"].values) for sp, g in sel.groupby("split")},
        "oos_all": {sp: summarise(g["r"].values) for sp, g in P.groupby("split")},
        "auc": auc,
        "importance": [{"feature": k, "importance": float(v)} for k, v in imp.head(20).items()],
        "predictions": P,
    }
