"""Success vs failure: compare trades that LOOKED the same but ended differently.

1. For each setup+direction, describe trades by 'surface' features — what the
   chart showed a discretionary trader on the signal candle.
2. Pair every loser with its nearest-neighbour winner on those surface features
   (same setup, same direction, same split).
3. Compare the pair on 'hidden' context features. A hidden feature that is
   consistently different inside look-alike pairs is a candidate explanation of
   why identical-looking setups diverge.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as st
from sklearn.neighbors import NearestNeighbors

from .stats import benjamini_hochberg

SURFACE = ["range_atr", "rel_body", "rel_clv", "fwd_wick", "back_wick", "stop_atr", "rel_mom3"]
HIDDEN = {
    "Momentum": ["rel_mom6", "rel_mom12", "rel_mom24", "rel_rsi", "rel_run_len", "rel_h4_mom6", "rel_d_mom20"],
    "Trend strength": ["adx", "er10", "er30", "rel_ema20_slope", "rel_ema50_slope", "rel_d_ema50_slope", "d_er20"],
    "Market structure": ["rel_structure", "rel_h4_structure", "rel_d_structure", "sh1_age", "sl1_age"],
    "Volatility": ["atr_pct", "atr_ratio", "bb_width_pct", "d_volpct", "range20_atr"],
    "Location": ["rel_dist_ema20", "rel_dist_ema50", "rel_dist_ema200", "rel_pos20", "rel_pos50", "rel_d_ext",
                 "room_fwd", "room_back", "room_in_r", "room_fwd_htf", "room_back_htf", "dist_prev_day_fwd", "dist_round50"],
    "Liquidity": ["liq_fwd", "liq_back", "opp_touches"],
    "Session": ["hour", "dow"],
    "MTF alignment": ["rel_mtf_votes", "with_daily", "rel_h4_trend", "rel_h4_dist_ema20"],
    "Volume (tick proxy)": ["vol_rel"],
    "Macro": ["rel_real_yield_chg20", "rel_usd_chg20", "vix"],
}
HIDDEN_ALL = [c for v in HIDDEN.values() for c in v]
GROUP_OF = {c: g for g, v in HIDDEN.items() for c in v}


def lookalike_pairs(t: pd.DataFrame, max_dist: float = 1.0) -> pd.DataFrame:
    pairs = []
    for (s, d, sp), g in t.groupby(["setup", "direction", "split"]):
        g = g.dropna(subset=SURFACE)
        W, L = g[g["r"] > 0], g[g["r"] <= 0]
        if len(W) < 10 or len(L) < 10:
            continue
        mu, sd = g[SURFACE].mean(), g[SURFACE].std().replace(0, 1)
        zw, zl = ((W[SURFACE] - mu) / sd).values, ((L[SURFACE] - mu) / sd).values
        nn = NearestNeighbors(n_neighbors=1).fit(zw)
        dist, j = nn.kneighbors(zl)
        ok = dist[:, 0] < max_dist
        pairs.append(pd.DataFrame({
            "setup": s, "direction": d, "split": sp,
            "loser": L.index.values[ok], "winner": W.index.values[j[ok, 0]], "dist": dist[ok, 0]}))
    return pd.concat(pairs, ignore_index=True) if pairs else pd.DataFrame()


def compare_pairs(t: pd.DataFrame, pairs: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Paired differences (winner - loser) for each hidden feature, optionally per group."""
    feats = [c for c in HIDDEN_ALL if c in t]
    groups = [((), pairs)] if not by else list(pairs.groupby(by))
    rows = []
    for key, p in groups:
        if len(p) < 20:
            continue
        W = t.loc[p["winner"].values, feats].reset_index(drop=True)
        L = t.loc[p["loser"].values, feats].reset_index(drop=True)
        for c in feats:
            dlt = (W[c] - L[c]).dropna()
            if len(dlt) < 20 or dlt.std() == 0:
                continue
            sd_pop = t[c].std()
            tt, pv = st.ttest_1samp(dlt, 0.0)
            nz = dlt[dlt != 0]
            rows.append({
                **({b: (key[i] if isinstance(key, tuple) else key) for i, b in enumerate(by)} if by else {}),
                "feature": c, "group": GROUP_OF.get(c, ""), "n_pairs": len(dlt),
                "winner_mean": float(W[c].mean()), "loser_mean": float(L[c].mean()),
                "mean_diff": float(dlt.mean()), "effect": float(dlt.mean() / sd_pop) if sd_pop else np.nan,
                "consistency": float((nz > 0).mean()) if len(nz) else np.nan,   # share of pairs where winner higher
                "p_value": float(pv),
            })
    df = pd.DataFrame(rows)
    if len(df):
        df["q_value"] = benjamini_hochberg(df["p_value"].values)
        df = df.sort_values("p_value")
    return df


def replication(t: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """A difference only counts if it has the same sign in discovery and in later data."""
    a = compare_pairs(t, pairs[pairs["split"] == "discovery"])
    b = compare_pairs(t, pairs[pairs["split"] == "validation"])   # holdout sealed
    if not len(a) or not len(b):
        return a
    m = a.merge(b[["feature", "mean_diff", "effect", "p_value", "consistency"]], on="feature",
                suffixes=("", "_later"))
    m["replicates"] = (np.sign(m["mean_diff"]) == np.sign(m["mean_diff_later"])) & (m["q_value"] < 0.05) & (m["p_value_later"] < 0.05)
    return m.sort_values(["replicates", "effect"], key=lambda s: s if s.dtype == bool else s.abs(), ascending=False)
