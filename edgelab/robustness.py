"""Robustness and data-snooping controls for the whole hypothesis family.

reality_check   White's Reality Check plus a studentised variant (Hansen's SPA idea):
                is the BEST hypothesis tested on discovery data better than what the
                best of N zero-edge strategies would show by luck? Uses a stationary
                bootstrap of daily R series, so serial correlation and overlap between
                hypotheses are respected. Romano-Wolf step-down gives which (if any)
                individual hypotheses survive at family-wise 5%.
stress          per-discovery stress tests: threshold neighbourhood (plateau or spike?),
                cost multipliers, year-by-year consistency, Monte-Carlo drawdown.
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd

from .hypothesis import mask, trade_r
from .stats import summarise, mc_drawdown


def daily_matrix(t: pd.DataFrame, cf, specs: list[dict], split: str = "discovery") -> tuple[np.ndarray, list[int]]:
    sel = (t["split"] == split) & ~t["crosses_split"]
    days = pd.DatetimeIndex(t.loc[sel, "tc"]).floor("D")
    all_days = pd.DatetimeIndex(sorted(days.unique()))
    cols, keep = [], []
    for j, s in enumerate(specs):
        try:
            m = mask(t, s) & sel
        except KeyError:
            continue
        if m.sum() < 30:
            continue
        r = trade_r(t, cf, s.get("exit", "base"))[m]
        d = pd.Series(r.values, index=pd.DatetimeIndex(t.loc[m, "tc"]).floor("D")).groupby(level=0).sum()
        cols.append(d.reindex(all_days, fill_value=0.0).values)
        keep.append(j)
    return (np.column_stack(cols) if cols else np.empty((len(all_days), 0))), keep


def _stationary_idx(n: int, n_boot: int, mean_block: float, rng) -> np.ndarray:
    p = 1.0 / mean_block
    idx = np.empty((n_boot, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, n_boot)
    jump = rng.random((n_boot, n)) < p
    fresh = rng.integers(0, n, (n_boot, n))
    for k in range(1, n):
        idx[:, k] = np.where(jump[:, k], fresh[:, k], (idx[:, k - 1] + 1) % n)
    return idx


def reality_check(X: np.ndarray, n_boot: int = 1000, mean_block: float = 10.0, seed: int = 0) -> dict:
    """X: days x hypotheses (daily R). Returns RC / studentised p-values and Romano-Wolf survivors."""
    n, k = X.shape
    if k == 0:
        return {"n_hypotheses": 0}
    rng = np.random.default_rng(seed)
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=1)
    sd[sd == 0] = np.inf
    idx = _stationary_idx(n, n_boot, mean_block, rng)
    stat = np.sqrt(n) * mu
    tstat = stat / sd
    boot_max, boot_tmax = np.empty(n_boot), np.empty(n_boot)
    boot_t = np.empty((n_boot, k), dtype=np.float32)
    for b in range(n_boot):
        mb = X[idx[b]].mean(axis=0) - mu                       # centred under H0: mean = 0
        boot_max[b] = (np.sqrt(n) * mb).max()
        tb = np.sqrt(n) * mb / sd
        boot_t[b] = tb
        boot_tmax[b] = tb.max()
    best = int(np.argmax(tstat))
    p_rc = float((boot_max >= stat.max()).mean())
    p_spa = float((boot_tmax >= tstat.max()).mean())
    # Romano-Wolf step-down on studentised stats
    order = np.argsort(-tstat)
    active = np.ones(k, bool)
    survivors = []
    for j in order:
        crit = np.quantile(boot_t[:, active].max(axis=1), 0.95)
        if tstat[j] > crit:
            survivors.append(int(j)); active[j] = False
        else:
            break
    return {"n_hypotheses": k, "n_days": n, "best_index": best, "best_t": float(tstat[best]),
            "best_daily_mean": float(mu[best]), "p_reality_check": p_rc, "p_studentised": p_spa,
            "rw_survivors": survivors, "boot_tmax_95": float(np.quantile(boot_tmax, 0.95))}


def _perturb(spec: dict, t: pd.DataFrame, frac: float) -> list[dict]:
    out = []
    for i, c in enumerate(spec.get("conditions", [])):
        if c["op"] not in (">", ">=", "<", "<=", "between") or c["f"] not in t:
            continue
        x = t.loc[t["split"] == "discovery", c["f"]]
        iqr = float(x.quantile(0.75) - x.quantile(0.25)) or float(x.std() or 1.0)
        for sgn in (-1, 1):
            s2 = deepcopy(spec)
            v = s2["conditions"][i]["v"]
            if isinstance(v, list):
                s2["conditions"][i]["v"] = [v[0] + sgn * frac * iqr, v[1] + sgn * frac * iqr]
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                s2["conditions"][i]["v"] = v + sgn * frac * iqr
            else:
                continue
            out.append(s2)
    return out


def stress(t: pd.DataFrame, cf, spec: dict, reveal_holdout: bool) -> dict:
    """Stress tests on data the hypothesis is allowed to see."""
    allowed = ["discovery", "validation"] + (["holdout"] if reveal_holdout else [])
    base_m = mask(t, spec) & t["split"].isin(allowed)
    r = trade_r(t, cf, spec.get("exit", "base"))
    out = {"allowed_splits": allowed}
    # 1. neighbourhood: does a small shift of each threshold keep the result? (plateau vs spike)
    nb = []
    for frac in (0.1, 0.25):
        for s2 in _perturb(spec, t, frac):
            m2 = mask(t, s2) & t["split"].isin(allowed)
            st = summarise(r[m2].dropna().values)
            nb.append({"shift_iqr": frac, "conditions": s2["conditions"], "n": st["n"], "avg_r": st["avg_r"]})
    out["neighbourhood"] = nb
    out["neighbourhood_positive_share"] = float(np.mean([x["avg_r"] > 0 for x in nb if x["n"]])) if nb else None
    # 2. costs: r_gross - m * cost (exact for base exits; base-trade cost used as proxy otherwise)
    g = t[base_m]
    gross = (r[base_m] + g["cost_r"]).values
    out["costs"] = [{"mult": m, "avg_r": float(np.mean(gross - m * g["cost_r"].values)) if len(g) else None}
                    for m in (0.0, 1.0, 1.5, 2.0, 3.0)]
    be = [c for c in out["costs"] if c["avg_r"] is not None and c["avg_r"] <= 0]
    out["breakeven_cost_mult"] = (float(np.mean(gross) / g["cost_r"].mean()) if len(g) and g["cost_r"].mean() > 0 else None)
    # 3. years
    yr = r[base_m].groupby(t.loc[base_m, "year"]).agg(["mean", "size"])
    yr = yr[yr["size"] >= 5]
    out["years_positive_share"] = float((yr["mean"] > 0).mean()) if len(yr) else None
    out["n_years"] = int(len(yr))
    # 4. drawdown under reshuffles
    rr = r[base_m].dropna().values
    out["mc_dd_95"] = mc_drawdown(rr, 500) if len(rr) > 10 else None
    # verdict
    flags = []
    if out["neighbourhood_positive_share"] is not None and out["neighbourhood_positive_share"] < 0.6:
        flags.append("spike: small threshold shifts kill it")
    if out["breakeven_cost_mult"] is not None and out["breakeven_cost_mult"] < 1.5:
        flags.append("cost-fragile: dies below 1.5x assumed costs")
    if out["years_positive_share"] is not None and out["years_positive_share"] < 0.55:
        flags.append("inconsistent: fewer than 55% of years positive")
    out["flags"] = flags
    out["robust"] = not flags
    return out
