"""Hypothesis specification + evaluation on the trade universe.

A hypothesis is a JSON-serialisable spec:
    {"setup": "momentum_bar" | ["a","b"] | "*",
     "direction": 1 | -1 | 0 (both),
     "conditions": [{"f": "rel_mom24", "op": ">", "v": 2.0}, ...],
     "exit": "base" | any counterfactual variant name (e.g. "target_3r"),
     "rationale": "...", "origin": "mined|conventional|taxonomy|lookalike|mutation|contradiction|ml|user"}
Conditions only reference columns known at the decision time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stats import summarise, max_drawdown, deflated_sharpe, bootstrap_ci

STOP_SCALE = {"stop_0.5x": 0.5, "stop_1.5x": 1.5, "stop_2x": 2.0}


def describe(spec: dict) -> str:
    s = spec.get("setup", "*")
    s = "any setup" if s == "*" else (", ".join(s) if isinstance(s, list) else s)
    d = {1: "LONG", -1: "SHORT", 0: "long or short"}[int(spec.get("direction", 0))]
    conds = " AND ".join(_cond_text(c) for c in spec.get("conditions", [])) or "no extra condition"
    ex = spec.get("exit", "base")
    return f"{d} {s} when {conds}" + ("" if ex == "base" else f" [exit: {ex}]")


def _cond_text(c):
    v = c["v"]
    if isinstance(v, float):
        v = round(v, 3)
    if isinstance(v, list) and len(v) == 2 and c["op"] == "between":
        return f"{c['f']} in [{_r(v[0])}, {_r(v[1])})"
    return f"{c['f']} {c['op']} {v}"


def _r(x):
    return round(x, 3) if isinstance(x, float) else x


def mask(t: pd.DataFrame, spec: dict) -> pd.Series:
    m = pd.Series(True, index=t.index)
    s = spec.get("setup", "*")
    if s != "*":
        m &= t["setup"].isin(s if isinstance(s, list) else [s])
    d = int(spec.get("direction", 0))
    if d:
        m &= t["direction"] == d
    for c in spec.get("conditions", []):
        col = t[c["f"]]
        op, v = c["op"], c["v"]
        if op == ">":
            m &= col > v
        elif op == ">=":
            m &= col >= v
        elif op == "<":
            m &= col < v
        elif op == "<=":
            m &= col <= v
        elif op == "==":
            m &= col == v
        elif op == "!=":
            m &= col != v
        elif op == "in":
            m &= col.isin(v)
        elif op == "between":
            m &= (col >= v[0]) & (col < v[1])
        else:
            raise ValueError(op)
    return m.fillna(False)


def trade_r(t: pd.DataFrame, cf: pd.DataFrame | None, exit_: str = "base") -> pd.Series:
    """R per trade under an exit variant, in the variant's OWN risk units."""
    if exit_ == "base" or cf is None:
        return t["r"]
    col = t[["trade_id"]].merge(cf[["trade_id", exit_]], on="trade_id", how="left")[exit_]
    col.index = t.index
    if exit_ in STOP_SCALE:
        col = col / STOP_SCALE[exit_]
    elif exit_ == "stop_atr2":
        col = col * t["stop_atr"] / 2.0
    return col


def evaluate(t: pd.DataFrame, cf: pd.DataFrame | None, spec: dict, splits=("discovery",),
             n_trials: int = 1, var_sr: float = 0.01, embargo: bool = True) -> dict:
    m = mask(t, spec)
    if embargo:
        m &= ~t["crosses_split"]
    r_all = trade_r(t, cf, spec.get("exit", "base"))
    out = {}
    for sp in splits:
        sel = m & (t["split"] == sp)
        rr = r_all[sel].dropna().values
        s = summarise(rr)
        if spec.get("exit", "base") == "base":
            g = summarise(t.loc[sel, "r_gross"].dropna().values)
            s["avg_r_gross"], s["t_gross"] = g["avg_r"], g["t"]
        s["dsr"] = deflated_sharpe(rr, n_trials, var_sr) if len(rr) >= 10 else np.nan
        # baseline = same setup/direction population without the conditions
        base_spec = {**spec, "conditions": []}
        bm = mask(t, base_spec) & (t["split"] == sp)
        s["baseline_avg_r"] = float(r_all[bm].mean()) if bm.any() else np.nan
        s["lift_r"] = s["avg_r"] - s["baseline_avg_r"] if s["n"] else np.nan
        s["coverage"] = float(sel.sum() / bm.sum()) if bm.sum() else np.nan
        out[sp] = s
    return out


def regime_breakdown(t: pd.DataFrame, cf, spec: dict, splits=("discovery", "validation", "holdout")) -> list[dict]:
    m = mask(t, spec) & t["split"].isin(splits)
    r = trade_r(t, cf, spec.get("exit", "base"))
    rows = []
    for key in ("regime_trend", "regime_vol", "regime_char", "session"):
        for k, g in r[m].groupby(t.loc[m, key]):
            s = summarise(g.values)
            rows.append({"dimension": key, "regime": k, "n": s["n"], "win": s["win"], "avg_r": s["avg_r"]})
    return rows


def yearly(t, cf, spec):
    m = mask(t, spec)
    r = trade_r(t, cf, spec.get("exit", "base"))
    return [{"year": int(y), "n": len(g), "avg_r": float(g.mean()), "total_r": float(g.sum())}
            for y, g in r[m].groupby(t.loc[m, "year"])]


def full_report(t: pd.DataFrame, cf, spec: dict, n_trials: int, var_sr: float, n_examples: int = 6,
                reveal_holdout: bool = False) -> dict:
    """The 10-point discovery report.

    Holdout (and the 2003-07 archive) are only included when the hypothesis has
    earned its one look by passing validation; otherwise "out-of-sample" means
    the validation split alone.
    """
    from .ledger import hyp_id
    splits = ("archive", "discovery", "validation", "holdout") if reveal_holdout else ("discovery", "validation")
    ev = evaluate(t, cf, spec, splits, n_trials, var_sr)
    m = mask(t, spec)
    r = trade_r(t, cf, spec.get("exit", "base"))
    later = ["validation", "holdout"] if reveal_holdout else ["validation"]
    ins = t[m & t["split"].isin(["discovery"] + later)]
    rr = r[ins.index]
    order = ins.assign(_r=rr).sort_values("tc")
    winners = order[order["_r"] > 0]
    losers = order[order["_r"] <= 0]
    pick = lambda df: df.sample(min(n_examples, len(df)), random_state=1)["trade_id"].tolist() if len(df) else []  # noqa
    oos_r = r[m & t["split"].isin(later)].dropna().values
    is_r = r[m & (t["split"] == "discovery")].dropna().values
    return {
        "hyp_id": hyp_id(spec), "definition": describe(spec), "spec": spec,
        "examples": pick(winners), "counterexamples": pick(losers),
        "sample_size": {k: v["n"] for k, v in ev.items()},
        "win_rate": {k: v["win"] for k, v in ev.items()},
        "avg_r": {k: v["avg_r"] for k, v in ev.items()},
        "expected_value_r": {k: v["ev"] for k, v in ev.items()},
        "max_drawdown_r": {k: v["max_dd"] for k, v in ev.items()},
        "max_drawdown_all_r": max_drawdown(order["_r"].dropna().values),
        "regimes": regime_breakdown(t, cf, spec, ("discovery", *later)),
        "yearly": [y for y in yearly(t, cf, spec) if reveal_holdout or y["year"] < 2022],
        "holdout_revealed": reveal_holdout,
        "in_sample": ev["discovery"], "out_of_sample": summarise(oos_r),
        "oos_bootstrap_ci": bootstrap_ci(oos_r, block=5) if len(oos_r) > 10 else (np.nan, np.nan),
        "is_bootstrap_ci": bootstrap_ci(is_r, block=5) if len(is_r) > 10 else (np.nan, np.nan),
        "by_split": ev,
        "equity": [{"t": str(x), "r": float(y)} for x, y in zip(order["tc"], order["_r"].fillna(0).cumsum())][::max(1, len(order) // 400)],
    }
