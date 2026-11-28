"""End-to-end research run. ``python -m edgelab run``"""
from __future__ import annotations

import json
import pickle
import time
from pathlib import Path as FsPath

import numpy as np
import pandas as pd

from .config import CACHE, STORE, OUTPUT, DEFAULT, SPLITS, RESEARCH_SPLITS, DESIGN_SPLITS
from .frame import load_frame, load_m15_cached
from .simulator import Path
from .setups import generate_decisions, SETUPS
from .trades import simulate_decisions
from .counterfactual import run_counterfactuals, policy_table, hindsight_fix, VARIANTS
from .taxonomy import flag_trades, category_stats, category_table, M as MISTAKES
from .comparison import lookalike_pairs, compare_pairs, replication
from .discovery import scan, pair_scan, walk_forward_ml
from .experiments import Engine
from .ledger import Ledger, legacy_trial_count
from . import behaviour as B
from .stats import summarise, jsonable


def _cached(name, fn, rebuild=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{name}.pkl"
    if p.exists() and not rebuild:
        return pickle.loads(p.read_bytes())
    t0 = time.time()
    obj = fn()
    p.write_bytes(pickle.dumps(obj))
    print(f"[{name}] built in {time.time()-t0:.1f}s")
    return obj


class Lab:
    """Holds the research state for one run (also handy in a notebook)."""

    def __init__(self, rebuild: bool = False):
        self.f = load_frame(rebuild)
        self.m15 = load_m15_cached(rebuild)
        self.path = Path.build(self.f, self.m15)
        self.trades = _cached("trades", lambda: simulate_decisions(generate_decisions(self.f), self.f, self.path), rebuild)
        self.cf = _cached("counterfactuals", lambda: run_counterfactuals(self.trades, self.f, self.path), rebuild)
        flags = flag_trades(self.trades, self.cf)
        self.flags = flags
        for c in flags.columns:
            self.trades[f"flag_{c}"] = flags[c].values
        mp = CACHE / "ml_pred.pkl"
        if mp.exists():
            self.trades = self.trades.merge(pd.read_pickle(mp).rename(columns={"p": "ml_p"}), on="trade_id", how="left")
            self.trades.index = flags.index
        print(f"[lab] {len(self.trades):,} trades, {len(self.cf):,} counterfactual rows")


def run(budget: int = 60, rebuild: bool = False, user_trades: str | None = None, dashboard: bool = True) -> dict:
    t0 = time.time()
    lab = Lab(rebuild)
    T, cf, f = lab.trades, lab.cf, lab.f
    R: dict = {"generated": time.strftime("%Y-%m-%d %H:%M"), "splits": SPLITS, "config": DEFAULT.to_dict()}

    # ------------------------------------------------------------- data coverage
    R["data"] = {"h1_bars": len(f), "h1_from": str(f["t"].min()), "h1_to": str(f["t"].max()),
                 "m15_bars": len(lab.m15), "m15_from": str(lab.m15["t"].min()), "m15_to": str(lab.m15["t"].max()),
                 "trades": len(T), "by_split": T["split"].value_counts().to_dict()}

    # ------------------------------------------------------------- setups
    perf = []
    for (s, d, sp), g in T[T["split"].isin(["archive"] + DESIGN_SPLITS)].groupby(["setup", "direction", "split"]):
        x = summarise(g["r"].values)
        perf.append({"setup": s, "direction": int(d), "split": sp, "gross": float(g["r_gross"].mean()),
                     "cost": float(g["cost_r"].mean()), **x})
    R["setup_perf"] = perf
    R["setups"] = [{"name": k, "family": v.family, "claim": v.claim} for k, v in SETUPS.items()]

    # ------------------------------------------------------------- taxonomy
    cs_d = category_stats(T, lab.flags, "discovery")
    cs_o = category_stats(T[T["split"] == "validation"].assign(split="oos"),
                          lab.flags[T["split"] == "validation"], "oos")
    cs = cs_d.merge(cs_o[["id", "n_flagged", "delta_r", "p_value", "q_value", "verdict"]], on="id",
                    suffixes=("", "_oos"))
    cs["replicated"] = (cs["verdict"] == cs["verdict_oos"]) & cs["verdict"].str.startswith(("confirmed", "CONTRA"))
    R["taxonomy"] = cs.merge(category_table()[["id", "definition"]], on="id").to_dict("records")
    losers = T[(T["r"] < 0) & T["split"].isin(DESIGN_SPLITS)]
    R["mistake_by_setup"] = (lab.flags.loc[losers.index].groupby(losers["setup"]).mean()).round(3).reset_index().to_dict("records")
    hf = hindsight_fix(cf)
    hf = hf.merge(T[["trade_id", "r", "setup", "direction", "split"]], on="trade_id")
    R["hindsight_best_alt"] = hf[(hf["r"] < 0) & hf["split"].isin(DESIGN_SPLITS)]["best_alt"].value_counts(normalize=True).round(4).to_dict()

    # ------------------------------------------------------------- counterfactual policies
    pol_d = policy_table(T, cf, split="discovery")
    pol_o = policy_table(T[T["split"] == "validation"].assign(split="oos"), cf, split="oos")
    R["policy"] = {"variants": VARIANTS,
                   "discovery": pol_d.reset_index().to_dict("records"),
                   "oos": pol_o.reset_index().to_dict("records")}

    # ------------------------------------------------------------- look-alikes
    pairs = lookalike_pairs(T)
    rep = replication(T, pairs)
    R["lookalike"] = rep.head(40).to_dict("records") if len(rep) else []
    by_fam = compare_pairs(T.assign(fam=T["family"]), pairs.assign(fam=T.loc[pairs["loser"].values, "family"].values), by=["fam"])
    R["lookalike_by_family"] = by_fam[by_fam["q_value"] < 0.01].head(40).to_dict("records") if len(by_fam) else []
    R["lookalike_pairs"] = int(len(pairs))

    # ------------------------------------------------------------- behaviour studies
    fr = B.forward_returns(f)
    R["momentum"] = {k: B.momentum_persistence(f, fr, look=k).to_dict("records") for k in ("mom1", "mom6", "mom24")}
    R["asymmetry"] = B.directional_asymmetry(f, fr)
    R["side_profile"] = B.setup_side_profile(T).to_dict("records")
    R["oaxaca"] = B.oaxaca(T[T["split"].isin(DESIGN_SPLITS)])
    R["conventional"] = B.conventional_scoreboard(T, cs).to_dict("records")
    reg = T[T["split"].isin(DESIGN_SPLITS)].groupby(["setup", "regime_trend"])["r"].agg(["mean", "size"]).reset_index()
    R["setup_regime"] = reg.to_dict("records")
    hm = T[T["split"].isin(DESIGN_SPLITS)].groupby(["dow", "hour"])["r"].agg(["mean", "size"]).reset_index()
    hm["loss_rate"] = T[T["split"].isin(DESIGN_SPLITS)].groupby(["dow", "hour"])["win"].mean().values
    R["heat_hour_dow"] = hm.to_dict("records")

    # ------------------------------------------------------------- discovery scan + ML
    sc1 = scan(T)
    pairs_sc = pair_scan(T, sc1)
    sc = pd.concat([sc1, pairs_sc], ignore_index=True).sort_values("t", ascending=False).reset_index(drop=True)
    STORE.mkdir(parents=True, exist_ok=True)
    sc.head(400).drop(columns=["conds"], errors="ignore").to_csv(STORE / "scan_discovery_top.csv", index=False)
    R["scan_pairs"] = {"cells": int(len(pairs_sc)), "observed_p05": int((pairs_sc["p"] < 0.05).sum()),
                       "expected_false_at_p05": None,   # cells are built from pre-selected winners: no valid chance baseline
                       "fdr_survivors": int((pairs_sc["q"] < 0.05).sum()) if len(pairs_sc) else 0}
    sc1 = sc[sc["op"] != "pair"]
    R["scan"] = {"cells": int(len(sc1)), "fdr_survivors": int((sc1["q"] < 0.05).sum()),
                 "expected_false_at_p05": float(0.05 * len(sc1)), "observed_p05": int((sc1["p"] < 0.05).sum()),
                 "top": sc.head(25).drop(columns=["conds"], errors="ignore").to_dict("records")}
    ml = walk_forward_ml(T, cf=cf)
    pred = ml.pop("predictions")
    # seal holdout/forward in the descriptive ML views (the predictions themselves stay usable as a feature)
    ml["per_year"] = [y for y in ml["per_year"] if y["year"] < 2022]
    for k in ("oos_selected", "oos_all", "auc"):
        ml[k] = {sp: v for sp, v in ml[k].items() if sp in DESIGN_SPLITS}
    pred[["trade_id", "p"]].to_pickle(CACHE / "ml_pred.pkl")
    R["ml"] = ml
    T = T.drop(columns=["ml_p"], errors="ignore").merge(pred[["trade_id", "p"]].rename(columns={"p": "ml_p"}), on="trade_id", how="left")
    T["ml_sel"] = T["trade_id"].isin(set(pred.loc[pred["selected"], "trade_id"]))
    lab.trades = T

    # ------------------------------------------------------------- experiment engine
    led = Ledger()
    eng = Engine(T, cf, led, scan_df=sc, lookalike=rep if len(rep) else None, extra_trials=len(sc))
    if not eng.queue and not led.records():
        eng.seed(cs, pol_d)
    eng.seed_momentum_track()
    eng.seed_agenda()
    eng.seed_ml()
    print(f"[engine] running {budget} experiments (queue {len(eng.queue)})")
    eng.run(budget)
    eng.rebuild_reports()
    df = led.frame()
    R["experiments"] = {
        "n_records": len(df), "n_hypotheses": int(df["hyp_id"].nunique()) if len(df) else 0,
        "n_trials_total": eng.n_trials(), "legacy_trials": legacy_trial_count(), "scan_trials": len(sc),
        "status_counts": df.groupby("hyp_id")["status"].last().value_counts().to_dict() if len(df) else {},
        "next": eng.next_proposals(12),
    }
    R["ledger"] = _ledger_rows(led)
    # family-wise data-snooping control across every hypothesis the engine has tested + top scan cells
    from .robustness import daily_matrix, reality_check
    from .hypothesis import describe
    from .discovery import scan_to_spec
    seen, fam = set(), []
    for rec in led.records():
        if rec.get("split") == "discovery" and rec.get("hyp_id") not in seen and rec.get("spec"):
            seen.add(rec["hyp_id"]); fam.append(rec["spec"])
    fam += [scan_to_spec(r) for _, r in sc.head(600).iterrows()]
    X, keep = daily_matrix(T, cf, fam)
    rc = reality_check(X, n_boot=500)
    if rc.get("n_hypotheses"):
        rc["best"] = describe(fam[keep[rc["best_index"]]])
        rc["rw_survivors"] = [describe(fam[keep[j]]) for j in rc["rw_survivors"]]
    R["reality_check"] = rc
    print(f"[reality-check] {rc.get('n_hypotheses')} hypotheses, p={rc.get('p_reality_check')}, studentised p={rc.get('p_studentised')}")
    R["event_paths"] = B.event_paths(f, T)
    from . import forward as FW
    data_end = str(f["tc"].max())
    R["frozen"] = FW.freeze(eng.discoveries, data_end)
    R["forward"] = FW.score(T, cf)
    R["discoveries"] = sorted(eng.discoveries, key=lambda d: -d.get("evidence_score", 0))

    # ------------------------------------------------------------- personal / directional profile
    from . import profile as PF
    up = FsPath(user_trades) if user_trades else (STORE / "my_trades.csv")
    if up.exists():
        u = PF.load_user_trades(up)
        ut = PF.reconstruct(u, f, lab.path)
        R["profile"] = {"source": "personal", "n": len(ut),
                        "tests": PF.test_self_assessment(ut, T),
                        "why_sells_lose": PF.why_sells_lose(ut).to_dict("records")}
    else:
        base = T[T["split"].isin(DESIGN_SPLITS)]
        R["profile"] = {"source": "market_baseline", "n": len(base),
                        "tests": PF.test_self_assessment(base, T),
                        "why_sells_lose": PF.why_sells_lose(base, cf).to_dict("records"),
                        "template": PF.TEMPLATE}

    # ------------------------------------------------------------- audits
    audit_p = STORE / "leakage_audit.json"
    R["audit"] = json.loads(audit_p.read_text()) if audit_p.exists() else None

    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / "lab_results.json").write_text(json.dumps(jsonable(R), default=str))
    print(f"[run] analysis done in {time.time()-t0:.0f}s")
    if dashboard:
        from .dashboard import build
        build(R, lab)
    return R


def _ledger_rows(led: Ledger) -> list[dict]:
    rows = []
    for r in led.records():
        s = r.get("stats", {}) or {}
        rows.append({"ts": r.get("ts"), "hyp_id": r.get("hyp_id"), "split": r.get("split"), "status": r.get("status"),
                     "origin": r.get("origin") or (r.get("spec") or {}).get("origin"),
                     "description": r.get("description"), "n": s.get("n"), "win": s.get("win"),
                     "avg_r": s.get("avg_r"), "t": s.get("t"), "p": s.get("p"), "dsr": s.get("dsr"),
                     "lift_r": s.get("lift_r"), "rationale": (r.get("spec") or {}).get("rationale")})
    return rows
