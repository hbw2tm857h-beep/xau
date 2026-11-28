"""The Mistake x Remedy atlas: every combination of ex-ante mistakes x every composite remedy.

Cells
  combo   : one ex-ante mistake, every pair, and every triple with enough support
  remedy  : 160 composite remedies + skip + opposite (see remedies.py)
  scope   : all trades, longs, shorts, and every setup x direction (singles and pairs);
            triples are evaluated on the three pooled scopes only
For each cell, on DISCOVERY data only:
  ev      : expectancy of the remedied trades (own R, after costs)        -> "is it profitable?"
  delta   : paired improvement over the trade as taken (same trades)      -> "does the remedy help?"
with t-statistics and one-sided p-values. Every evaluated cell is a trial.

Then, with nothing re-fitted (cells are categorical, there is nothing to tune):
  * Benjamini-Hochberg across the whole family, separately for ev and delta;
  * every BH survivor, and the 2,000 strongest cells, are re-measured on VALIDATION;
  * replication rate is compared with the 50% sign agreement expected if nothing were real;
  * the best replicated cells are handed to the experiment engine for their one holdout look.
The holdout is never read here.

Also a hindsight map (descriptive only): for trades with each EX-POST diagnosis, which remedy
would have helped. It explains losers; it cannot be traded because the diagnosis is not known
at entry.
"""
from __future__ import annotations

import json
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats as st

from .remedies import REMEDIES, BASE, describe as rdescribe
from .stats import benjamini_hochberg
from .taxonomy import M as MISTAKES

MIN_N = 40


def _flags(t: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    ids = [m.id for m in MISTAKES if m.phase == "ex_ante" and f"flag_{m.id}" in t]
    return ids, t[[f"flag_{i}" for i in ids]].values.astype(np.float32)


def _stats(n, s, ss):
    """mean, t, one-sided p (mean > 0) from count, sum and sum of squares (vectorised)."""
    n = np.asarray(n, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = s / n
        var = (ss - n * mean ** 2) / (n - 1)
        se = np.sqrt(np.maximum(var, 1e-12) / n)
        t = mean / se
    p = st.t.sf(t, np.maximum(n - 1, 1))
    return mean, t, p


def _cells_for_rows(F, C, D, combo_rows: list[tuple[tuple[int, ...], np.ndarray]]):
    """For each combo (tuple of flag indices, row mask) return n, sums for C and D."""
    out = []
    for combo, rows in combo_rows:
        if rows.sum() < MIN_N:
            continue
        c, dd = C[rows], D[rows]
        out.append((combo, int(rows.sum()), c.sum(0), (c * c).sum(0), dd.sum(0), (dd * dd).sum(0)))
    return out


def _scope_cells(F, C, D, triples: bool):
    K = F.shape[1]
    Fb = F.astype(bool)
    combos = [((i,), Fb[:, i]) for i in range(K)]
    pair_masks = {}
    for i, j in combinations(range(K), 2):
        m = Fb[:, i] & Fb[:, j]
        if m.sum() >= MIN_N:
            combos.append(((i, j), m)); pair_masks[(i, j)] = m
    if triples:
        for (i, j), m in pair_masks.items():
            for k in range(j + 1, K):
                mk = m & Fb[:, k]
                if mk.sum() >= MIN_N:
                    combos.append(((i, j, k), mk))
    return _cells_for_rows(F, C, D, combos)


def build(t: pd.DataFrame, rm: pd.DataFrame, setups_scope: bool = True) -> dict:
    ids, Fall = _flags(t)
    R = rm.set_index("trade_id").loc[t["trade_id"], REMEDIES].values.astype(np.float32)
    base = rm.set_index("trade_id").loc[t["trade_id"], BASE].values.astype(np.float32)
    Dall = R - base[:, None]
    split = t["split"].values
    scopes = [("all", np.ones(len(t), bool), True), ("long", t["direction"].values > 0, True),
              ("short", t["direction"].values < 0, True)]
    if setups_scope:
        for (s, d), g in t.groupby(["setup", "direction"]):
            scopes.append((f"{s}|{'L' if d > 0 else 'S'}", (t["setup"].values == s) & (t["direction"].values == d), False))
    rows = []
    for name, sm, tri in scopes:
        m = sm & (split == "discovery") & ~t["crosses_split"].values
        cells = _scope_cells(Fall[m], R[m], Dall[m], tri)
        for combo, n, s, ss, sd, ssd in cells:
            ev, ev_t, ev_p = _stats(n, s, ss)
            dl, dl_t, dl_p = _stats(n, sd, ssd)
            rows.append(pd.DataFrame({
                "scope": name, "combo": "+".join(ids[c] for c in combo), "k": len(combo), "remedy": REMEDIES,
                "n": n, "ev": ev, "ev_t": ev_t, "ev_p": ev_p, "delta": dl, "delta_t": dl_t, "delta_p": dl_p}))
    A = pd.concat(rows, ignore_index=True)
    A = A[A["remedy"] != BASE].reset_index(drop=True)          # base vs base is not a remedy
    A.loc[A["remedy"] == "skip", ["ev_p"]] = np.nan             # skip has ev 0 by definition
    A["ev_q"] = benjamini_hochberg(A["ev_p"].values)
    A["delta_q"] = benjamini_hochberg(A["delta_p"].values)
    return {"ids": ids, "cells": A, "R": R, "D": Dall, "F": Fall, "scopes": scopes}


def validate(t: pd.DataFrame, atlas: dict, top: int = 2000) -> pd.DataFrame:
    """Re-measure selected discovery cells on validation, definitions unchanged."""
    A = atlas["cells"]
    sel = A[(A["ev_q"] < 0.05) | (A["delta_q"] < 0.05)]
    strongest = pd.concat([A.nlargest(top // 2, "ev_t"), A.nlargest(top // 2, "delta_t")])
    sel = pd.concat([sel, strongest]).drop_duplicates(["scope", "combo", "remedy"])
    ids = atlas["ids"]
    col = {r: j for j, r in enumerate(REMEDIES)}
    scope_mask = {name: sm for name, sm, _ in atlas["scopes"]}
    vm = (t["split"].values == "validation") & ~t["crosses_split"].values
    Fb = atlas["F"].astype(bool)
    out = []
    for (scope, combo), g in sel.groupby(["scope", "combo"]):
        m = scope_mask[scope] & vm
        for c in combo.split("+"):
            m = m & Fb[:, ids.index(c)]
        n = int(m.sum())
        for _, r in g.iterrows():
            j = col[r["remedy"]]
            x, dlt = atlas["R"][m, j], atlas["D"][m, j]
            if n >= 10:
                ev_t = x.mean() / (x.std(ddof=1) / np.sqrt(n)) if x.std() > 0 else np.nan
                dl_t = dlt.mean() / (dlt.std(ddof=1) / np.sqrt(n)) if dlt.std() > 0 else np.nan
            else:
                ev_t = dl_t = np.nan
            out.append({**r.to_dict(), "v_n": n, "v_ev": float(x.mean()) if n else np.nan, "v_ev_t": ev_t,
                        "v_delta": float(dlt.mean()) if n else np.nan, "v_delta_t": dl_t})
    V = pd.DataFrame(out)
    V["ev_replicates"] = (V["ev"] > 0) & (V["v_ev"] > 0) & (V["v_ev_t"] >= 1.65)
    V["delta_replicates"] = (V["delta"] > 0) & (V["v_delta"] > 0) & (V["v_delta_t"] >= 1.65)
    return V


def hindsight_map(t: pd.DataFrame, rm: pd.DataFrame) -> pd.DataFrame:
    """Descriptive: for trades carrying each EX-POST diagnosis (discovery+validation), mean improvement per remedy."""
    R = rm.set_index("trade_id").loc[t["trade_id"], REMEDIES]
    base = R[BASE].values
    m0 = t["split"].isin(["discovery", "validation"]).values
    rows = []
    for mk in MISTAKES:
        if mk.phase == "ex_ante" or f"flag_{mk.id}" not in t:
            continue
        m = m0 & t[f"flag_{mk.id}"].values.astype(bool)
        if m.sum() < 30:
            continue
        imp = (R.values[m] - base[m, None]).mean(0)
        best = int(np.argmax(np.where(np.array(REMEDIES) == BASE, -np.inf, imp)))
        rows.append({"id": mk.id, "name": mk.name, "n": int(m.sum()), "best_remedy": REMEDIES[best],
                     "best_remedy_text": rdescribe(REMEDIES[best]), "best_improvement": float(imp[best]),
                     **{f"imp|{r}": float(v) for r, v in zip(REMEDIES, imp)}})
    return pd.DataFrame(rows)


def summarise_atlas(t: pd.DataFrame, atlas: dict, V: pd.DataFrame, H: pd.DataFrame) -> dict:
    A = atlas["cells"]
    ids = atlas["ids"]
    names = {m.id: m.name for m in MISTAKES}
    n_cells = int(len(A))
    # heatmaps (discovery and validation) for single mistakes x remedies on pooled scopes
    heat = {}
    vm = (t["split"].values == "validation") & ~t["crosses_split"].values
    scope_mask = {name: sm for name, sm, _ in atlas["scopes"]}
    for scope in ("all", "long", "short"):
        sub = A[(A["scope"] == scope) & (A["k"] == 1)].pivot(index="combo", columns="remedy", values="delta")
        sub = sub.reindex(index=[i for i in ids if i in sub.index], columns=[r for r in REMEDIES if r != BASE])
        vrows = []
        for c in sub.index:
            m = scope_mask[scope] & vm & atlas["F"][:, ids.index(c)].astype(bool)
            vrows.append(atlas["D"][m].mean(0) if m.sum() >= 10 else np.full(len(REMEDIES), np.nan))
        vd = pd.DataFrame(vrows, index=sub.index, columns=REMEDIES).reindex(columns=sub.columns)
        heat[scope] = {"rows": list(sub.index), "cols": list(sub.columns),
                       "disc": np.round(sub.values.astype(float), 3).tolist(),
                       "valid": np.round(vd.values.astype(float), 3).tolist()}
    # best remedy per single mistake (pooled), with validation
    best = []
    S = A[(A["scope"] == "all") & (A["k"] == 1) & (A["remedy"] != "skip")]
    for c, g in S.groupby("combo"):
        g = g.sort_values("delta_t", ascending=False)
        r = g.iloc[0]
        m = vm & atlas["F"][:, ids.index(c)].astype(bool)
        j = REMEDIES.index(r["remedy"])
        best.append({"id": c, "name": names.get(c, c), "n": int(r["n"]), "remedy": r["remedy"],
                     "remedy_text": rdescribe(r["remedy"]), "delta": float(r["delta"]), "delta_t": float(r["delta_t"]),
                     "ev": float(r["ev"]), "v_n": int(m.sum()),
                     "v_delta": float(atlas["D"][m, j].mean()) if m.sum() else None,
                     "v_ev": float(atlas["R"][m, j].mean()) if m.sum() else None,
                     "base_ev": float(atlas["R"][(atlas["scopes"][0][1]) & (t["split"].values == "discovery")
                                                 & atlas["F"][:, ids.index(c)].astype(bool),
                                                 REMEDIES.index(BASE)].mean())})
    # replication statistics
    def rep_rate(col_disc, col_val):
        top = V[V[col_disc] > 0]
        return float((np.sign(top[col_val]) > 0).mean()) if len(top) else None
    topV = V.copy()
    topV["remedy_text"] = topV["remedy"].map(rdescribe)
    topV["combo_text"] = topV["combo"].map(lambda c: " + ".join(names.get(x, x) for x in c.split("+")))
    ev_top = topV[topV["ev_replicates"]].sort_values("v_ev_t", ascending=False).head(60)
    dl_top = topV[topV["delta_replicates"]].sort_values("v_delta_t", ascending=False).head(60)
    # remedy families: average delta of each entry/stop/exit component across all single-mistake cells
    comp = []
    S1 = A[(A["scope"] == "all") & (A["k"] == 1) & A["remedy"].str.contains(r"\|")]
    parts = S1["remedy"].str.split("|", expand=True)
    for pos, lab in ((0, "entry"), (1, "stop"), (2, "exit")):
        for v, g in S1.groupby(parts[pos]):
            comp.append({"part": lab, "value": v, "mean_delta": float(g["delta"].mean()),
                         "share_positive": float((g["delta"] > 0).mean())})
    return {
        "n_cells": n_cells, "n_combos": int(A[["scope", "combo"]].drop_duplicates().shape[0]),
        "n_remedies": len(REMEDIES) - 1, "by_k": A.groupby("k").size().to_dict(),
        "ev_bh_survivors": int((A["ev_q"] < 0.05).sum()), "delta_bh_survivors": int((A["delta_q"] < 0.05).sum()),
        "positive_ev_cells": int((A["ev"] > 0).sum()), "positive_ev_p05": int((A["ev_p"] < 0.05).sum()),
        "expected_p05_under_null": float(0.05 * A["ev_p"].notna().sum()),
        "validated_cells": int(len(V)), "ev_replicated": int(V["ev_replicates"].sum()),
        # if nothing were real, about 5% of the re-measured cells would clear t >= 1.65 in validation by luck
        "ev_replicated_expected": float(0.05 * (V["ev"] > 0).sum()),
        "delta_replicated_expected": float(0.05 * (V["delta"] > 0).sum()),
        "delta_replicated": int(V["delta_replicates"].sum()),
        "ev_sign_agreement": rep_rate("ev", "v_ev"), "delta_sign_agreement": rep_rate("delta", "v_delta"),
        "heat": heat, "best_per_mistake": sorted(best, key=lambda x: -x["delta_t"]),
        "top_ev": ev_top.drop(columns=[c for c in ev_top.columns if c.endswith("_p") or c.endswith("_q")]).to_dict("records"),
        "top_delta": dl_top.drop(columns=[c for c in dl_top.columns if c.endswith("_p") or c.endswith("_q")]).to_dict("records"),
        "components": comp,
        "hindsight": H[["id", "name", "n", "best_remedy", "best_remedy_text", "best_improvement"]].to_dict("records") if len(H) else [],
        "hindsight_heat": {"rows": H["id"].tolist(), "cols": [r for r in REMEDIES if r != BASE],
                           "z": np.round(H[[f"imp|{r}" for r in REMEDIES if r != BASE]].values, 3).tolist()} if len(H) else {},
        "mistake_names": names,
    }


def to_specs(V: pd.DataFrame, k: int = 40) -> list[dict]:
    """Best replicated cells -> engine hypotheses (they still face the holdout, once)."""
    from .setups import SETUPS
    cand = V[V["ev_replicates"]].sort_values("v_ev_t", ascending=False).head(k)
    specs = []
    for _, r in cand.iterrows():
        sc = r["scope"]
        if sc == "all":
            setup, d = "*", 0
        elif sc in ("long", "short"):
            setup, d = "*", 1 if sc == "long" else -1
        else:
            s, side = sc.split("|")
            setup, d = s, 1 if side == "L" else -1
        conds = [{"f": f"flag_{c}", "op": "==", "v": True} for c in r["combo"].split("+")]
        specs.append({"setup": setup, "direction": d, "conditions": conds, "exit": r["remedy"], "origin": "atlas",
                      "rationale": f"Atlas cell replicated in validation: mistakes {r['combo']} with remedy "
                                   f"'{rdescribe(r['remedy'])}' (disc EV {r['ev']:+.3f}, valid EV {r['v_ev']:+.3f})."})
    return specs
