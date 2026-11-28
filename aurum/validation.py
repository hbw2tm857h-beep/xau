"""Validation: leakage audits, walk-forward, robustness.

truncation_audit  : recompute the whole decision frame on data cut at a random bar
                    k and check that every feature at k is identical to the
                    full-history value. Any difference = future information leak.
walk_forward_rule : anchored walk-forward for a fixed rule (no refitting) and for
                    rules whose threshold is re-fit on past data only.
robustness        : cost stress, parameter neighbourhood, regime and year splits.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stats import summarise


def truncation_audit(h1: pd.DataFrame, n_cuts: int = 4, seed: int = 0, tol: float = 1e-6,
                     window: int = 6000) -> pd.DataFrame:
    """Return per-column mismatch counts (should all be zero, except documented EW warm-up)."""
    from .frame import build_frame
    rng = np.random.default_rng(seed)
    # work on a recent window to keep it fast; values far from the cut are what matter
    base = h1.iloc[-(window + 2000):].reset_index(drop=True)
    full = build_frame(base, verbose=False)
    rows = []
    for k in rng.integers(window // 2, len(base) - 50, n_cuts):
        cut = build_frame(base.iloc[: k + 1].reset_index(drop=True), verbose=False)
        a, b = full.iloc[k], cut.iloc[k]
        assert a["t"] == b["t"]
        for c in full.columns:
            va, vb = a[c], b[c]
            if isinstance(va, (float, np.floating)) or isinstance(vb, (float, np.floating)):
                bad = not ((pd.isna(va) and pd.isna(vb)) or (np.isfinite(va) and np.isfinite(vb)
                                                            and abs(va - vb) <= tol * max(1, abs(va))))
            else:
                bad = not ((pd.isna(va) and pd.isna(vb)) or va == vb)
            rows.append({"cut": int(k), "column": c, "mismatch": bool(bad), "full": va, "truncated": vb})
    df = pd.DataFrame(rows)
    return df.groupby("column").agg(mismatches=("mismatch", "sum"), checks=("mismatch", "size")).reset_index()


def setup_truncation_audit(h1: pd.DataFrame, n_cuts: int = 3, seed: int = 1, window: int = 6000) -> dict:
    """Signals emitted at bar k must not change when bars after k are removed."""
    from .frame import build_frame
    from .setups import generate_decisions
    base = h1.iloc[-(window + 2000):].reset_index(drop=True)
    full = generate_decisions(build_frame(base, verbose=False))
    rng = np.random.default_rng(seed)
    bad = 0
    checked = 0
    for k in rng.integers(window // 2, len(base) - 50, n_cuts):
        cut = generate_decisions(build_frame(base.iloc[: k + 1].reset_index(drop=True), verbose=False))
        # compare decisions in the last 200 bars before the cut (cooldown state included)
        lo = k - 200
        a = full[(full["idx"] > lo) & (full["idx"] <= k)][["idx", "setup", "direction", "stop"]].round(6)
        b = cut[(cut["idx"] > lo) & (cut["idx"] <= k)][["idx", "setup", "direction", "stop"]].round(6)
        m = a.merge(b, how="outer", indicator=True)
        bad += int((m["_merge"] != "both").sum())
        checked += len(m)
    return {"decisions_checked": checked, "mismatches": bad}


def walk_forward_rule(t: pd.DataFrame, rule_mask: pd.Series, first_year: int = 2010) -> pd.DataFrame:
    """Year-by-year results of a FIXED rule: each year is out-of-sample w.r.t. the previous ones."""
    rows = []
    for y in range(first_year, int(t["year"].max()) + 1):
        g = t[rule_mask & (t["year"] == y)]
        s = summarise(g["r"].values)
        rows.append({"year": y, **{k: s[k] for k in ("n", "win", "avg_r", "total_r", "max_dd")}})
    return pd.DataFrame(rows)


def walk_forward_threshold(t: pd.DataFrame, base_mask: pd.Series, feature: str, side: str = ">",
                           first_year: int = 2012, q_grid=(0.5, 0.6, 0.7, 0.8), embargo_h: int = 72) -> pd.DataFrame:
    """Re-fit a single threshold each year on past trades only, then apply to the next year."""
    rows = []
    for y in range(first_year, int(t["year"].max()) + 1):
        start = pd.Timestamp(f"{y}-01-01")
        past = t[base_mask & (t["exit_time"] < start - pd.Timedelta(hours=embargo_h)) & (t["split"] != "archive")]
        nxt = t[base_mask & (t["year"] == y)]
        if len(past) < 200 or not len(nxt):
            continue
        best, best_thr = -np.inf, None
        for q in q_grid:
            thr = past[feature].quantile(q if side == ">" else 1 - q)
            sel = past[feature] > thr if side == ">" else past[feature] < thr
            if sel.sum() >= 50 and past.loc[sel, "r"].mean() > best:
                best, best_thr = past.loc[sel, "r"].mean(), thr
        if best_thr is None:
            continue
        sel = nxt[feature] > best_thr if side == ">" else nxt[feature] < best_thr
        s = summarise(nxt.loc[sel, "r"].values)
        rows.append({"year": y, "threshold": float(best_thr), "train_avg_r": float(best), "n": s["n"],
                     "avg_r": s["avg_r"], "win": s["win"]})
    return pd.DataFrame(rows)


def cost_stress(t: pd.DataFrame, rule_mask: pd.Series, mults=(0.0, 1.0, 2.0, 3.0)) -> list[dict]:
    """Re-price costs linearly: r(m) = r_gross - m * cost_r."""
    g = t[rule_mask]
    out = []
    for m in mults:
        r = g["r_gross"] - m * g["cost_r"]
        s = summarise(r.values)
        out.append({"cost_mult": m, "n": s["n"], "avg_r": s["avg_r"], "win": s["win"], "pf": s["pf"]})
    return out
