"""Autonomous experiment engine.

Loop:  pick hypothesis -> define measurable conditions -> test on discovery ->
       (if it passes) validation -> (if it passes) holdout, once ->
       record EVERY outcome -> compare with existing discoveries ->
       look for contradictory evidence -> propose follow-up experiments.

Failures are never discarded: rejected hypotheses stay in the ledger, count
toward the multiple-testing denominator, and strongly negative ones spawn
"contradiction" experiments (is the opposite trade an edge?).
"""
from __future__ import annotations

import json
import math
from copy import deepcopy

import numpy as np
import pandas as pd

from .config import STORE
from .hypothesis import evaluate, full_report, mask, describe
from .ledger import Ledger, hyp_id
from .stats import jsonable
from .setups import SETUPS

QUEUE = STORE / "queue.json"
DISCOVERIES = STORE / "discoveries.json"

GATES = {
    "discovery": {"min_n": 40, "min_avg_r": 0.03, "min_t": 2.0},
    "validation": {"min_n": 20, "min_avg_r": 0.0, "min_t": 1.0},
    "holdout": {"min_n": 15, "min_avg_r": 0.0, "min_t": 1.0},
}
EXIT_VARIANTS = ["target_1r", "target_3r", "breakeven_1r", "stop_1.5x", "time_exit_12h", "retest_limit",
                 "confirm_close", "trail_2atr", "trail_3atr_after_1r", "partial_1r_trail"]


def _passes(s: dict, gate: dict) -> bool:
    return (s["n"] >= gate["min_n"] and (s["avg_r"] or -9) > gate["min_avg_r"]
            and (s["t"] if s["t"] == s["t"] else -9) >= gate["min_t"])


def evidence_score(ev: dict, regimes: list[dict] | None = None) -> float:
    """0-100. Rewards in-sample strength, replication on later data and regime stability."""
    d, v, h = ev.get("discovery"), ev.get("validation"), ev.get("holdout")
    score = 0.0
    if d and d["n"]:
        score += 25 * min(1.0, max(0.0, (d["t"] or 0) / 4))
        score += 5 * (d.get("dsr") or 0)
    for s, w in ((v, 25), (h, 30)):
        if s and s["n"] >= 10 and s["avg_r"] == s["avg_r"]:
            score += w * min(1.0, max(0.0, 0.5 + (s["t"] or 0) / 4)) if s["avg_r"] > 0 else 0
    if regimes:
        rg = [r for r in regimes if r["dimension"] == "regime_trend" and r["n"] >= 15]
        if rg:
            score += 15 * np.mean([r["avg_r"] > 0 for r in rg])
    return round(float(score), 1)


class Engine:
    def __init__(self, trades: pd.DataFrame, cf: pd.DataFrame | None, ledger: Ledger | None = None,
                 scan_df: pd.DataFrame | None = None, lookalike: pd.DataFrame | None = None,
                 extra_trials: int = 0):
        self.t, self.cf = trades, cf
        self.ledger = ledger or Ledger()
        self.scan_df = scan_df
        self.lookalike = lookalike
        self.extra_trials = extra_trials        # scan cells evaluated outside the ledger
        self.queue: list[dict] = json.loads(QUEUE.read_text()) if QUEUE.exists() else []
        self.discoveries: list[dict] = json.loads(DISCOVERIES.read_text()) if DISCOVERIES.exists() else []
        self._scan_ptr = 0

    # ------------------------------------------------------------------ persistence
    def save(self):
        QUEUE.write_text(json.dumps(jsonable(self.queue), indent=1))
        DISCOVERIES.write_text(json.dumps(jsonable(self.discoveries), indent=1))

    def push(self, spec: dict, priority: float):
        hid = hyp_id(spec)
        if any(q["hyp_id"] == hid for q in self.queue) or self.ledger.tested(hid, "discovery"):
            return
        self.queue.append({"hyp_id": hid, "priority": float(priority), "spec": spec})

    # ------------------------------------------------------------------ seeding
    def seed(self, cat_stats: pd.DataFrame | None = None, policy: pd.DataFrame | None = None):
        # 1. conventional claims: every setup as a trader would take it
        for name, s in SETUPS.items():
            for d in (1, -1):
                self.push({"setup": name, "direction": d, "conditions": [], "exit": "base",
                           "origin": "conventional", "rationale": s.claim}, 90)
        claims = [
            ("with_daily", "==", 1, "Trade with the daily trend."),
            ("with_daily", "==", 0, "Countertrend trades should lose (probe)."),
            ("rel_mtf_votes", "==", 3.0, "All three timeframes aligned improves results."),
            ("room_in_r", ">=", 2.0, "Trades need room to the next level to reach target."),
            ("rel_body", ">", 1.0, "Strong-bodied signal candles show conviction."),
            ("session", "==", "london", "London session gives the cleanest moves."),
            ("session", "==", "asia", "Asia session is a trap for directional trades."),
            ("atr_pct", "<", 0.2, "Low-volatility conditions lead to failed moves (probe)."),
            ("vol_rel", ">", 1.5, "Above-average (tick) volume confirms the move."),
        ]
        for f, op, v, why in claims:
            for d in (1, -1):
                self.push({"setup": "*", "direction": d, "conditions": [{"f": f, "op": op, "v": v}],
                           "exit": "base", "origin": "conventional", "rationale": why}, 85)
        self.push({"setup": ["breakout", "range_breakout"], "direction": 0,
                   "conditions": [{"f": "bb_width_pct", "op": "<", "v": 0.3}], "exit": "base",
                   "origin": "conventional", "rationale": "Breakouts after compression work better."}, 85)
        self.push({"setup": ["exhaustion_fade", "engulfing", "rsi_extreme"], "direction": -1,
                   "conditions": [{"f": "bear_div", "op": "==", "v": 1}], "exit": "base",
                   "origin": "conventional", "rationale": "Bearish divergence predicts reversal."}, 85)
        # 2. taxonomy: does avoiding a confirmed ex-ante mistake create an edge?
        if cat_stats is not None:
            for _, r in cat_stats[cat_stats["phase"] == "ex_ante"].iterrows():
                if r["n_flagged"] < 50:
                    continue
                for d in (1, -1):
                    self.push({"setup": "*", "direction": d,
                               "conditions": [{"f": f"flag_{r['id']}", "op": "==", "v": False}], "exit": "base",
                               "origin": "taxonomy",
                               "rationale": f"Avoiding '{r['name']}' ({r['verdict']}) should raise expectancy."}, 70)
        # 3. look-alike differences
        if self.lookalike is not None and len(self.lookalike):
            for _, r in self.lookalike.head(15).iterrows():
                f = r["feature"]
                med = float(self.t.loc[self.t["split"] == "discovery", f].median())
                op = ">" if r["mean_diff"] > 0 else "<"
                for d in (1, -1):
                    self.push({"setup": "*", "direction": d, "conditions": [{"f": f, "op": op, "v": round(med, 4)}],
                               "exit": "base", "origin": "lookalike",
                               "rationale": f"Winners differ from look-alike losers on {f} (effect {r['effect']:+.2f})."}, 75)
        # 4. counterfactual policies that helped a setup on discovery data
        if policy is not None:
            base = policy["base"]
            for ex in [c for c in EXIT_VARIANTS if c in policy]:
                gain = policy[ex] - base
                for (s_, d_), g in gain.items():
                    if g > 0.05 and policy.loc[(s_, d_), "n"] >= 100:
                        self.push({"setup": s_, "direction": int(d_), "conditions": [], "exit": ex,
                                   "origin": "counterfactual",
                                   "rationale": f"Policy replay: '{ex}' added {g:+.3f}R on discovery for {s_}."}, 72)
        # 5. scan
        self.refill_from_scan(40)
        self.save()

    def seed_momentum_track(self):
        """Dedicated follow-up of the replicated 'momentum persists' finding (and the short-side asymmetry)."""
        why = "Taxonomy E2 'late entry' replicated as an ADVANTAGE; fast moves continue beyond drift."
        for setup in ("momentum_burst", "burst_pullback"):
            for d in (1, -1):
                for ex in ("base", "trail_2atr", "partial_1r_trail", "confirm_close"):
                    self.push({"setup": setup, "direction": d, "conditions": [], "exit": ex,
                               "origin": "momentum_track", "rationale": why}, 92)
                for thr in (3.5, 4.5):
                    self.push({"setup": "momentum_burst", "direction": d,
                               "conditions": [{"f": "rel_mom6", "op": ">=", "v": thr}], "exit": "trail_2atr",
                               "origin": "momentum_track",
                               "rationale": f"Only very fast moves (>{thr} ATR/6h) continue; down-moves especially."}, 91)
        for d in (1, -1):
            for f_, op, v, why2 in (("with_daily", "==", 1, "Momentum aligned with the daily trend."),
                                     ("room_fwd_htf", ">", 1.5, "Momentum with room to the next H4/D1 level."),
                                     ("session", "==", "ny_overlap", "Momentum during the deepest liquidity."),
                                     ("atr_pct", ">", 0.6, "Momentum when volatility is already elevated.")):
                self.push({"setup": "momentum_burst", "direction": d, "conditions": [{"f": f_, "op": op, "v": v}],
                           "exit": "trail_2atr", "origin": "momentum_track", "rationale": why2}, 90)
        self.save()

    def seed_ml(self):
        """Walk-forward model selections (ml_sel = top 20% predicted, scored out-of-sample each year).

        The exit list was chosen after seeing the model's per-exit table on all splits, so these
        are post-hoc; they pay the full multiple-testing price like everything else.
        """
        if "ml_sel" not in self.t:
            return
        for ex in ("base", "trail_3atr_after_1r", "trail_2atr", "time_exit_12h", "target_3r"):
            for d in (0, 1, -1):
                self.push({"setup": "*", "direction": d, "conditions": [{"f": "ml_sel", "op": "==", "v": True}],
                           "exit": ex, "origin": "ml",
                           "rationale": "Model trained only on earlier years picked these trades (top 20%); "
                                        "exit chosen post hoc from the per-exit table."}, 93)
        self.save()

    def refill_from_scan(self, k: int):
        from .discovery import scan_to_spec
        if self.scan_df is None or not len(self.scan_df):
            return
        added = 0
        while added < k and self._scan_ptr < len(self.scan_df):
            row = self.scan_df.iloc[self._scan_ptr]
            self._scan_ptr += 1
            if row["avg_r"] <= 0:
                continue
            spec = scan_to_spec(row)
            before = len(self.queue)
            self.push(spec, 50 + min(30, row["t"] * 5))
            added += len(self.queue) > before

    # ------------------------------------------------------------------ one experiment
    def n_trials(self) -> int:
        return self.ledger.n_trials() + self.extra_trials

    def test(self, spec: dict) -> dict:
        hid = hyp_id(spec)
        var_sr = self.ledger.sharpe_var()
        n_trials = self.n_trials() + 1
        rec_base = {"hyp_id": hid, "description": describe(spec), "spec": spec, "origin": spec.get("origin")}
        ev = evaluate(self.t, self.cf, spec, ("discovery",), n_trials, var_sr)
        d = ev["discovery"]
        status = "passed_discovery" if _passes(d, GATES["discovery"]) else (
            "negative_edge" if d["n"] >= 40 and (d.get("t_gross", d["t"]) or 0) <= -2 else "rejected_discovery")
        self.ledger.append({**rec_base, "split": "discovery", "stats": d, "status": status,
                            "n_trials_at_test": n_trials})
        outcome = {"hyp_id": hid, "status": status, "ev": ev, "spec": spec}
        if status == "passed_discovery":
            ev.update(evaluate(self.t, self.cf, spec, ("validation",), n_trials, var_sr))
            v = ev["validation"]
            ok_v = _passes(v, GATES["validation"])
            self.ledger.append({**rec_base, "split": "validation", "stats": v,
                                "status": "passed_validation" if ok_v else "failed_validation"})
            status = "passed_validation" if ok_v else "failed_validation"
            if ok_v and not self.ledger.tested(hid, "holdout"):
                ev.update(evaluate(self.t, self.cf, spec, ("holdout", "archive"), n_trials, var_sr))
                h = ev["holdout"]
                if _passes(h, GATES["holdout"]):
                    status = "validated"
                elif h["n"] and h["avg_r"] > 0:
                    status = "weak_holdout"
                else:
                    status = "contradicted_holdout"
                self.ledger.append({**rec_base, "split": "holdout", "stats": h, "status": status})
                self.ledger.append({**rec_base, "split": "archive", "stats": ev["archive"],
                                    "status": "robustness_check"})
        outcome["status"] = status
        if status in ("validated", "weak_holdout", "passed_validation", "contradicted_holdout", "failed_validation"):
            rep = full_report(self.t, self.cf, spec, n_trials, var_sr,
                              reveal_holdout=status in ("validated", "weak_holdout", "contradicted_holdout"))
            rep["status"] = status
            rep["evidence_score"] = evidence_score(rep["by_split"], rep["regimes"])
            rep["relations"] = self.relate(spec, rep)
            rep["n_trials_at_test"] = n_trials
            self.discoveries = [x for x in self.discoveries if x["hyp_id"] != hid] + [rep]
            outcome["report"] = rep
        return outcome

    # ------------------------------------------------------------------ comparison / contradictions
    def relate(self, spec: dict, rep: dict) -> list[dict]:
        out = []
        m_new = mask(self.t, spec) & (self.t["split"] == "discovery")
        ids_new = set(self.t.loc[m_new, "trade_id"])
        feats_new = {c["f"] for c in spec.get("conditions", [])}
        for other in self.discoveries:
            if other["hyp_id"] == rep["hyp_id"]:
                continue
            m_o = mask(self.t, other["spec"]) & (self.t["split"] == "discovery")
            ids_o = set(self.t.loc[m_o, "trade_id"])
            j = len(ids_new & ids_o) / max(1, len(ids_new | ids_o))
            if j > 0.3:
                out.append({"type": "overlap", "with": other["hyp_id"], "jaccard": round(j, 3),
                            "note": "Largely the same trades — not independent evidence."})
            shared = feats_new & {c["f"] for c in other["spec"].get("conditions", [])}
            if shared and other["spec"].get("direction") == spec.get("direction"):
                same_side = all(_same_side(spec, other["spec"], f) for f in shared)
                sign_new = np.sign(rep["out_of_sample"]["avg_r"] or 0)
                sign_old = np.sign(other["out_of_sample"]["avg_r"] or 0)
                if same_side and sign_new != sign_old:
                    out.append({"type": "contradiction", "with": other["hyp_id"], "features": sorted(shared),
                                "note": "Same condition, opposite out-of-sample result in a different setup."})
        # regime sign flips inside this hypothesis
        rg = [r for r in rep["regimes"] if r["dimension"] == "regime_trend" and r["n"] >= 20]
        signs = {r["regime"]: np.sign(r["avg_r"]) for r in rg}
        if len(set(signs.values()) - {0}) > 1:
            out.append({"type": "regime_dependence", "detail": {k: int(v) for k, v in signs.items()},
                        "note": "Works in some trend regimes and loses in others."})
        return out

    # ------------------------------------------------------------------ proposals
    def propose(self, outcome: dict):
        spec, st = outcome["spec"], outcome["status"]
        base_pri = {"validated": 95, "weak_holdout": 80, "passed_validation": 80, "failed_validation": 55,
                    "contradicted_holdout": 50, "passed_discovery": 50, "negative_edge": 60,
                    "rejected_discovery": 0}[st]
        if st == "negative_edge":
            # contradiction probe: if a condition reliably loses, is the opposite trade an edge?
            s2 = deepcopy(spec)
            s2.update(exit="opposite", origin="contradiction", parent=outcome["hyp_id"],
                      rationale="The original idea loses reliably; test the inverse trade.")
            self.push(s2, base_pri)
            return
        if st == "rejected_discovery":
            return
        # mutations of anything that survived discovery
        for ex in EXIT_VARIANTS:
            if spec.get("exit", "base") == "base":
                s2 = deepcopy(spec); s2.update(exit=ex, origin="mutation", parent=outcome["hyp_id"],
                                               rationale=f"Same entry, exit '{ex}'.")
                self.push(s2, base_pri - 10)
        if self.lookalike is not None and len(spec.get("conditions", [])) < 2:
            used = {c["f"] for c in spec.get("conditions", [])}
            for _, r in self.lookalike.head(6).iterrows():
                if r["feature"] in used:
                    continue
                med = float(self.t.loc[mask(self.t, spec) & (self.t["split"] == "discovery"), r["feature"]].median())
                if not np.isfinite(med):
                    continue
                s2 = deepcopy(spec)
                s2["conditions"] = s2["conditions"] + [{"f": r["feature"], "op": ">" if r["mean_diff"] > 0 else "<",
                                                       "v": round(med, 4)}]
                s2.update(origin="mutation", parent=outcome["hyp_id"],
                          rationale=f"Add look-alike discriminator {r['feature']}.")
                self.push(s2, base_pri - 15)
        # generalisation & contradiction probes
        if spec.get("setup") != "*":
            s2 = deepcopy(spec); s2.update(setup="*", origin="mutation", parent=outcome["hyp_id"],
                                           rationale="Does the condition generalise across all setups?")
            self.push(s2, base_pri - 5)
        if int(spec.get("direction", 0)) != 0:
            s2 = deepcopy(spec); s2.update(direction=-int(spec["direction"]), origin="contradiction",
                                           parent=outcome["hyp_id"],
                                           rationale="Directional asymmetry probe: same condition, other side.")
            self.push(s2, base_pri - 5)

    # ------------------------------------------------------------------ loop
    def run(self, budget: int = 50, verbose: bool = True) -> list[dict]:
        results = []
        for _ in range(budget):
            if len(self.queue) < 5:
                self.refill_from_scan(20)
            if not self.queue:
                break
            self.queue.sort(key=lambda q: -q["priority"])
            item = self.queue.pop(0)
            if self.ledger.tested(item["hyp_id"], "discovery"):
                continue
            try:
                out = self.test(item["spec"])
            except Exception as e:  # record the failure rather than hide it
                self.ledger.append({"hyp_id": item["hyp_id"], "spec": item["spec"], "split": "discovery",
                                    "status": "error", "error": str(e)})
                continue
            self.propose(out)
            results.append(out)
            if verbose:
                d = out["ev"]["discovery"]
                print(f"  {out['status']:<22} n={d['n']:>5} avgR={d['avg_r'] if d['n'] else float('nan'):+.3f} "
                      f"t={d['t'] if d['t']==d['t'] else float('nan'):+.2f}  {describe(item['spec'])[:90]}")
        self.save()
        return results

    def rebuild_reports(self):
        """Regenerate discovery cards from the ledger (e.g. after a report-format change)."""
        last = {}
        for r in self.ledger.records():
            if r.get("hyp_id") and r.get("status") not in ("robustness_check",):
                last[r["hyp_id"]] = r
        holdout_seen = {r["hyp_id"] for r in self.ledger.records() if r.get("split") == "holdout"}
        out = []
        var_sr = self.ledger.sharpe_var()
        for hid, r in last.items():
            st = [x for x in self.ledger.records() if x.get("hyp_id") == hid and x.get("split") == "holdout"]
            status = st[-1]["status"] if st else r["status"]
            if status in ("rejected_discovery", "negative_edge", "error"):
                continue
            n_tr = next((x.get("n_trials_at_test") for x in self.ledger.records()
                         if x.get("hyp_id") == hid and x.get("split") == "discovery"), self.n_trials())
            rep = full_report(self.t, self.cf, r["spec"], n_tr, var_sr, reveal_holdout=hid in holdout_seen)
            rep.update(status=status, n_trials_at_test=n_tr)
            from .robustness import stress
            try:
                rep["stress"] = stress(self.t, self.cf, r["spec"], hid in holdout_seen)
            except Exception as e:  # noqa
                rep["stress"] = {"error": str(e)}
            rep["evidence_score"] = evidence_score(rep["by_split"], rep["regimes"])
            out.append(rep)
        notes = [r for r in self.ledger.records() if r.get("type") == "note" and r.get("hyp_ids")]
        self.discoveries = []
        for rep in out:
            rep["caveats"] = [n["note"] for n in notes if rep["hyp_id"] in n["hyp_ids"]]
            rep["relations"] = self.relate(rep["spec"], rep)
            self.discoveries.append(rep)
        self.save()

    def next_proposals(self, k: int = 10) -> list[dict]:
        q = sorted(self.queue, key=lambda q: -q["priority"])[:k]
        return [{"hyp_id": x["hyp_id"], "priority": x["priority"], "description": describe(x["spec"]),
                 "origin": x["spec"].get("origin"), "rationale": x["spec"].get("rationale")} for x in q]


def _same_side(a: dict, b: dict, f: str) -> bool:
    ca = [c for c in a["conditions"] if c["f"] == f][0]
    cb = [c for c in b["conditions"] if c["f"] == f][0]
    gt = lambda c: c["op"] in (">", ">=")  # noqa
    lt = lambda c: c["op"] in ("<", "<=")  # noqa
    return (gt(ca) and gt(cb)) or (lt(ca) and lt(cb)) or (ca["op"] == cb["op"] == "==" and ca["v"] == cb["v"])
