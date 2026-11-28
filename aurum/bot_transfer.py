"""Bot knowledge transfer: which Aurum findings could improve signals.py, tested on the bot's own trades.

Candidates come from validated or replicated lab findings and from the owner's profile:
  warnings   - confirmed ex-ante mistakes, as an extra line on alerts (information only)
  avoid      - skipping a setup under a demonstrably harmful condition
  confirm    - waiting for the fill candle to close beyond the entry (atlas: best entry ingredient)
  exits      - exit-management variants (atlas: trailing after +1R)

Protocol: each candidate is evaluated on discovery and validation bot trades and recorded in the ledger
(failures included). A candidate that improves both periods is FROZEN and from then on scored only on
bot trades after its freeze time (forward split). The holdout stays sealed (the three Round-4 rules
already used their one look). Nothing here changes signals.py; recommendations carry an evidence grade:
  A  improved discovery + validation + at least 30 forward trades, all positive
  B  improved discovery + validation, forward still accumulating
  C  improved in one period only
  D  no improvement or harmful
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from .config import STORE, SPLITS
from .stats import jsonable

FROZEN = STORE / "bot_frozen.json"
WARN_IDS = ["L3", "V3", "K5", "T4", "T8", "E3", "T2"]


def _confirm_fill(B: pd.DataFrame, path, f: pd.DataFrame) -> pd.Series:
    """Only keep the trade if the fill candle closes beyond the entry in the trade direction
    (otherwise skip: 0R). The trade itself is unchanged when kept."""
    tc = f["tc"].values
    c = f["close"].values
    out = []
    for r in B.itertuples():
        j = int(np.searchsorted(tc, np.datetime64(r.entry_time), side="right")) - 1   # the fill candle
        ok = (c[j] - r.entry) * r.direction > 0 if 0 <= j < len(c) else True
        out.append(r.r if ok else 0.0)
    return pd.Series(out, index=B.index)


def candidates(B: pd.DataFrame, EV: pd.DataFrame, path, f: pd.DataFrame) -> list[dict]:
    X = B.merge(EV, on="trade_id", how="left")
    X.index = B.index
    out = []
    for fid in WARN_IDS:
        col = f"flag_{fid}"
        if col not in B:
            continue
        for strat in sorted(B["strategy"].unique()):
            out.append({"kind": "warning", "name": f"{strat}: warn when {fid} is present", "strategy": strat,
                        "flag": fid, "new": None, "old": B["r"]})
            out.append({"kind": "avoid", "name": f"{strat}: skip when {fid} is present", "strategy": strat,
                        "flag": fid, "new": pd.Series(np.where(B[col].astype(bool), 0.0, B["r"]), index=B.index),
                        "old": B["r"]})
    conf = _confirm_fill(B, path, f)
    for strat in sorted(B["strategy"].unique()):
        out.append({"kind": "confirm", "name": f"{strat}: only keep fills whose candle closes beyond the entry",
                    "strategy": strat, "new": conf, "old": B["r"]})
        for ex, lab in (("all_trail3", "whole trade on a 3 ATR trail after +1R"), ("rest_trail3", "half at +1R, rest on a 3 ATR trail"),
                        ("rest_3r", "half at +1R, rest at +3R")):
            if ex in X:
                out.append({"kind": "exit", "name": f"{strat}: {lab}", "strategy": strat, "new": X[ex], "old": X["rest_2r"]})
    return out


def evaluate(B: pd.DataFrame, cands: list[dict]) -> list[dict]:
    res = []
    for c in cands:
        rec = {k: c[k] for k in ("kind", "name", "strategy") if k in c}
        rec["flag"] = c.get("flag")
        ok_periods = 0
        for sp in ("discovery", "validation"):
            m = (B["strategy"] == c["strategy"]) & (B["split"] == sp)
            if c["kind"] == "warning":
                on = B.loc[m, f"flag_{c['flag']}"].astype(bool)
                fl, cl = B.loc[m & on.reindex(B.index, fill_value=False), "r"], B.loc[m & ~on.reindex(B.index, fill_value=True), "r"]
                d = float(fl.mean() - cl.mean()) if len(fl) >= 10 and len(cl) >= 10 else np.nan
                rec[sp] = {"n_flagged": int(len(fl)), "flagged_avg_r": float(fl.mean()) if len(fl) else None,
                           "clean_avg_r": float(cl.mean()) if len(cl) else None, "delta": d}
                ok_periods += int(d == d and d < -0.05)
            else:
                new, old = c["new"][m].astype(float), c["old"][m].astype(float)
                dd = (new - old).dropna()
                t = float(dd.mean() / (dd.std(ddof=1) / np.sqrt(len(dd)))) if len(dd) > 2 and dd.std() > 0 else 0.0
                rec[sp] = {"n": int(len(dd)), "old_avg_r": float(old.mean()), "new_avg_r": float(new.mean()),
                           "delta": float(dd.mean()) if len(dd) else np.nan, "t": t,
                           "old_total": float(old.sum()), "new_total": float(new.sum())}
                ok_periods += int(len(dd) >= 20 and dd.mean() > 0)
        rec["periods_improved"] = ok_periods
        res.append(rec)
    return res


def freeze_and_forward(B: pd.DataFrame, cands: list[dict], res: list[dict]) -> list[dict]:
    """Freeze candidates that improved both periods; score all frozen ones on forward bot trades."""
    from .ledger import Ledger, hyp_id
    frozen = json.loads(FROZEN.read_text()) if FROZEN.exists() else []
    have = {x["name"] for x in frozen}
    now_end = str(B["sig_time"].max())
    L = Ledger()
    for c, r in zip(cands, res):
        spec = {"setup": f"bot_{r['strategy']}", "direction": 0, "conditions": [], "exit": r["name"],
                "origin": "bot_transfer", "rationale": r["name"]}
        hid = hyp_id(spec)
        if not L.tested(hid, "discovery"):
            for sp in ("discovery", "validation"):
                s = r.get(sp) or {}
                L.append({"hyp_id": hid, "description": r["name"], "spec": spec, "origin": "bot", "split": sp,
                          "status": "bot_candidate_pass" if r["periods_improved"] == 2 else "bot_candidate_fail",
                          "stats": {"n": s.get("n", s.get("n_flagged")), "avg_r": s.get("delta"), "t": s.get("t"),
                                    "p": None, "win": None, "sharpe": None}})
        if r["periods_improved"] == 2 and r["name"] not in have:
            frozen.append({"name": r["name"], "kind": r["kind"], "strategy": r["strategy"], "flag": r.get("flag"),
                           "frozen_at": now_end, "frozen_on": time.strftime("%Y-%m-%d")})
            have.add(r["name"])
    FROZEN.write_text(json.dumps(jsonable(frozen), indent=1))
    by_name = {c["name"]: c for c in cands}
    for fz in frozen:
        c = by_name.get(fz["name"])
        m = (B["strategy"] == fz["strategy"]) & (B["sig_time"] > pd.Timestamp(fz["frozen_at"]))
        if c is None or c["kind"] == "warning":
            on = B.loc[m, f"flag_{fz['flag']}"].astype(bool) if fz.get("flag") else pd.Series(dtype=bool)
            fz["forward"] = {"n": int(m.sum()), "flagged_avg_r": float(B.loc[m, "r"][on].mean()) if on.any() else None,
                             "clean_avg_r": float(B.loc[m, "r"][~on].mean()) if (~on).any() else None}
        else:
            dd = (c["new"][m] - c["old"][m]).dropna()
            fz["forward"] = {"n": int(len(dd)), "delta": float(dd.mean()) if len(dd) else None}
    return frozen


def grade(r: dict, fz: dict | None) -> str:
    if r["periods_improved"] < 2:
        return "C" if r["periods_improved"] == 1 else "D"
    fwd = (fz or {}).get("forward") or {}
    if fwd.get("n", 0) >= 30:
        good = (fwd.get("delta") or 0) > 0 if r["kind"] != "warning" else \
               ((fwd.get("flagged_avg_r") or 0) < (fwd.get("clean_avg_r") or 0))
        return "A" if good else "D"
    return "B"


def run(lab) -> dict:
    import pickle
    from .config import CACHE
    from .bot_anatomy import exit_variants
    B = pickle.loads((CACHE / "bot_trades.pkl").read_bytes())
    p = CACHE / "bot_exits.pkl"
    EV = pickle.loads(p.read_bytes()) if p.exists() else exit_variants(B, lab.path, lab.f)
    if not p.exists():
        p.write_bytes(pickle.dumps(EV))
    cands = candidates(B, EV, lab.path, lab.f)
    res = evaluate(B, cands)
    frozen = freeze_and_forward(B, cands, res)
    fz = {x["name"]: x for x in frozen}
    for r in res:
        r["grade"] = grade(r, fz.get(r["name"]))
        r["forward"] = (fz.get(r["name"]) or {}).get("forward")
    recs = sorted([r for r in res if r["grade"] in ("A", "B")], key=lambda r: (r["grade"], r["kind"]))
    out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "n_candidates": len(res),
           "grades": pd.Series([r["grade"] for r in res]).value_counts().to_dict(),
           "recommendations": recs, "all": res,
           "policy": "Nothing is applied automatically. Grade B items may be shown as alert information; behaviour "
                     "changes need grade A (forward-confirmed) and the owner's decision."}
    (STORE / "bot_recommendations.json").write_text(json.dumps(jsonable(out), indent=1))
    return jsonable(out)
