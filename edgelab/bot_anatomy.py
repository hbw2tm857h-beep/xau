"""Anatomy of the live bot's losing trades (signals.py), using the lab's tools.

1. replay   : run the bot's OWN strategy code (step / h4_step / ib_step from signals.py)
              over 2008-2026 and capture every trade with its signal bar, entry, stop, exit, R.
2. context  : attach the lab's decision-time context to each trade (momentum, structure,
              higher-timeframe levels, regimes, the 40 ex-ante mistake flags) and in-trade
              path statistics from M15 (MFE, MAE, time to +0.5R, what happened after exit).
3. anatomy  : what losers share that winners do not, before entry (ex-ante) and in the
              first hours of the trade (early warning) - discovery data, checked on validation.
4. remedies : test simple, pre-declared rules for the bot (skip on warning signs, early
              exit when the trade does not work) on discovery -> validation -> holdout once.

Holdout (2022-01 .. 2026-11-23) is read exactly once, for the final rules, and logged in
the experiment ledger. The bot's R includes its own $0.35 cost model.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import timezone

import numpy as np
import pandas as pd

from .config import ROOT, STORE, DESIGN_SPLITS
from .stats import summarise, benjamini_hochberg, jsonable
from .trades import CONTEXT, add_relative
from .taxonomy import flag_trades, M as MISTAKES

UTC = timezone.utc


def _signals():
    if "signals" in sys.modules:
        return sys.modules["signals"]
    spec = importlib.util.spec_from_file_location("signals", ROOT / "signals.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["signals"] = mod
    spec.loader.exec_module(mod)
    return mod


def replay(extra_m15_h1: pd.DataFrame | None = None) -> tuple[pd.DataFrame, object]:
    """Every closed trade of the bot's trend, h4_trend and inside_day strategies."""
    S = _signals()
    cfg = dict(S.CONFIG)
    import os
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        h1 = S.load_history(cfg)
    finally:
        os.chdir(cwd)
    F = S.Features(h1, cfg)
    start = next(i for i in range(len(F.h1)) if F.warm(i))
    st, st_h4, st_ib = {}, {}, {}
    open_sig = {}
    rows = []
    for i in range(start, len(F.h1)):
        evs = S.step(F, i, st, cfg) + S.h4_step(F, i, st_h4, cfg) + S.ib_step(F, i, st_ib, dict(cfg, inside_day=True))
        for e in evs:
            typ = e["type"]
            idea = e.get("idea") or {}
            strat = idea.get("strategy") or ("inside_day" if typ.startswith("ib_") else
                                             "h4_trend" if typ.startswith("h4_") else "trend")
            if typ in ("signal", "h4_signal", "ib_signal"):
                open_sig[strat] = i
            if typ in ("stop", "target", "exit", "h4_stop", "h4_target", "ib_stop", "ib_close"):
                sig_t = pd.Timestamp(idea["sig_time"]).tz_convert(None) if pd.Timestamp(idea["sig_time"]).tzinfo else pd.Timestamp(idea["sig_time"])
                rows.append({
                    "strategy": strat, "direction": int(idea["dir"]), "sig_time": sig_t,
                    "entry_time": pd.Timestamp(idea.get("entry_time") or e["t"]).tz_convert(None),
                    "exit_time": pd.Timestamp(e["t"]).tz_convert(None),
                    "entry": float(idea["entry"]), "stop0": float(idea.get("stop0", idea.get("stop"))),
                    "risk": float(idea.get("risk") or abs(idea["entry"] - idea["stop"])),
                    "exit_px": float(e.get("price", np.nan)), "r": float(e["r"]), "how": typ,
                    "partial_done": bool(idea.get("done")), "grade": idea.get("grade"),
                })
    T = pd.DataFrame(rows)
    # stop as planned at signal time: entry - dir * risk (the idea's stop moves to entry after the partial)
    T["stop_px"] = T["entry"] - T["direction"] * T["risk"]
    return T, F


def attach_context(T: pd.DataFrame, f: pd.DataFrame, path) -> pd.DataFrame:
    """Lab context at the signal bar + path stats on M15 (in-trade and 24h after exit)."""
    tc = f["tc"].values
    idx = np.searchsorted(tc, T["sig_time"].values.astype("datetime64[ns]"), side="right") - 1
    T = T.copy()
    T["idx"] = idx
    ctx = f.loc[idx, CONTEXT].reset_index(drop=True)
    T = pd.concat([T.reset_index(drop=True), ctx], axis=1)
    T["setup"] = T["strategy"].map({"trend": "bot_trend", "h4_trend": "bot_h4_trend", "inside_day": "bot_inside_day"})
    T["family"] = "continuation"
    T["stop_atr"] = T["risk"] / T["atr"]
    T["ref_level"] = T["entry"]
    # path statistics
    mfe, mae, t05, mfe3, mae3, post_hit, post_mae, post_mfe = ([] for _ in range(8))
    for r in T.itertuples():
        a = path.start_index(r.entry_time - pd.Timedelta(hours=1))  # bot entry_time is the fill bar's close
        b = path.start_index(r.exit_time)
        d, e0, rk = r.direction, r.entry, r.risk
        hi, lo = path.h[a:b], path.l[a:b]
        if len(hi) == 0:
            hi, lo = path.h[a:a + 1], path.l[a:a + 1]
        fav = ((hi - e0) if d > 0 else (e0 - lo)) / rk
        adv = ((e0 - lo) if d > 0 else (hi - e0)) / rk
        mfe.append(float(fav.max())); mae.append(float(adv.max()))
        j = np.flatnonzero(fav >= 0.5)
        t05.append(float((path.t[a + j[0]] - path.t[a]) / np.timedelta64(1, "h")) if len(j) else np.nan)
        k3 = min(len(fav), 12)                           # first 3 hours on M15
        mfe3.append(float(fav[:k3].max())); mae3.append(float(adv[:k3].max()))
        pe = path.start_index(r.exit_time + pd.Timedelta(hours=24))
        ph, pl = path.h[b:pe], path.l[b:pe]
        tgt = e0 + d * 2 * rk
        post_hit.append(bool(((ph >= tgt) if d > 0 else (pl <= tgt)).any()) if len(ph) else False)
        post_mae.append(float((((e0 - pl.min()) if d > 0 else (ph.max() - e0)) / rk)) if len(ph) else np.nan)
        post_mfe.append(float((((ph.max() - e0) if d > 0 else (e0 - pl.min())) / rk)) if len(ph) else np.nan)
    T["mfe_r"], T["mae_r"], T["hours_to_half_r"] = mfe, mae, t05
    T["mfe3h"], T["mae3h"] = mfe3, mae3
    T["post_hit_target"], T["post_mae_r"], T["post_mfe_r"] = post_hit, post_mae, post_mfe
    T["exit_reason"] = T["how"].map(lambda h: "stop" if h.endswith("stop") else ("target" if h.endswith("target") else "time"))
    T["r_gross"] = T["r"]
    T["cost_r"] = 0.35 / T["risk"]
    T["win"] = (T["r"] > 0).astype(int)
    T["crosses_split"] = False
    T["trade_id"] = [f"BOT{s[:2].upper()}{'L' if d > 0 else 'S'}-{t:%Y%m%d%H}" for s, d, t in
                     zip(T["strategy"], T["direction"], T["sig_time"])]
    T = add_relative(T)
    fl = flag_trades(T, None)
    for c in fl.columns:
        T[f"flag_{c}"] = fl[c].values
    return T


FEATURES = ["rel_mom6", "rel_mom12", "rel_mom24", "rel_rsi", "adx", "er10", "er30", "atr_pct", "atr_ratio",
            "bb_width_pct", "range20_atr", "range_atr", "rel_body", "rel_clv", "fwd_wick", "back_wick", "stop_atr",
            "rel_dist_ema20", "rel_dist_ema50", "rel_dist_ema200", "rel_pos50", "rel_d_ext", "rel_d_mom20",
            "rel_d_ema50_slope", "room_fwd", "room_fwd_htf", "room_in_r_htf", "rel_h4_dist_ema20", "rel_h4_mom6",
            "rel_mtf_votes", "rel_structure", "rel_h4_structure", "rel_d_structure", "dist_round50", "hour",
            "vol_rel", "d_volpct", "rel_real_yield_chg20", "rel_usd_chg20", "vix"]


def ex_ante_anatomy(T: pd.DataFrame) -> pd.DataFrame:
    """For each feature: do losers differ from winners? Discovery effect, then the same on validation."""
    rows = []
    for strat in ["ALL"] + sorted(T["strategy"].unique()):
        g = T if strat == "ALL" else T[T["strategy"] == strat]
        for f_ in FEATURES:
            out = {"strategy": strat, "feature": f_}
            for sp in DESIGN_SPLITS:
                x = g[g["split"] == sp]
                w, l = x.loc[x["r"] > 0, f_].dropna(), x.loc[x["r"] <= 0, f_].dropna()
                if len(w) < 15 or len(l) < 15:
                    out[f"{sp}_effect"] = np.nan; out[f"{sp}_p"] = np.nan; continue
                from scipy import stats as st
                sd = x[f_].std()
                out[f"{sp}_effect"] = float((w.mean() - l.mean()) / sd) if sd else np.nan
                out[f"{sp}_p"] = float(st.mannwhitneyu(w, l).pvalue)
                out[f"{sp}_win_mean"], out[f"{sp}_loss_mean"] = float(w.mean()), float(l.mean())
            rows.append(out)
    A = pd.DataFrame(rows)
    A["q_disc"] = benjamini_hochberg(A["discovery_p"].values)
    A["replicates"] = (np.sign(A["discovery_effect"]) == np.sign(A["validation_effect"])) & (A["q_disc"] < 0.1) & (A["validation_p"] < 0.1)
    return A.sort_values("discovery_p")


def flag_anatomy(T: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for m in MISTAKES:
        col = f"flag_{m.id}"
        if col not in T:
            continue
        out = {"id": m.id, "name": m.name, "phase": m.phase}
        for sp in DESIGN_SPLITS:
            x = T[T["split"] == sp]
            on = x[col].astype(bool)
            out[f"{sp}_n"] = int(on.sum())
            out[f"{sp}_share_losers"] = float(on[x["r"] <= 0].mean()) if (x["r"] <= 0).any() else np.nan
            out[f"{sp}_share_winners"] = float(on[x["r"] > 0].mean()) if (x["r"] > 0).any() else np.nan
            out[f"{sp}_r_flagged"] = float(x.loc[on, "r"].mean()) if on.any() else np.nan
            out[f"{sp}_r_clean"] = float(x.loc[~on, "r"].mean()) if (~on).any() else np.nan
        rows.append(out)
    return pd.DataFrame(rows)


def early_warning(T: pd.DataFrame) -> dict:
    """In-trade anatomy: how do losers look in their first hours vs winners?"""
    out = {}
    d = T[T["split"].isin(DESIGN_SPLITS)]
    for lab, g in (("winners", d[d["r"] > 0]), ("losers", d[d["r"] <= 0])):
        out[lab] = {"n": len(g), "mfe3h": float(g["mfe3h"].mean()), "mae3h": float(g["mae3h"].mean()),
                    "share_half_r_within_3h": float((g["hours_to_half_r"] <= 3).mean()),
                    "median_hours_to_half_r": float(g["hours_to_half_r"].median()),
                    "share_never_half_r": float(g["hours_to_half_r"].isna().mean())}
    # conditional win rate on the first-3h behaviour (the 'is it working?' signal)
    bins = [-0.01, 0.25, 0.5, 1.0, 99]
    d = d.assign(b=pd.cut(d["mfe3h"], bins))
    out["by_mfe3h"] = [{"mfe3h": str(k), "n": len(g), "win": float(g["win"].mean()), "avg_r": float(g["r"].mean())}
                       for k, g in d.groupby("b", observed=True)]
    return out


def loss_types(T: pd.DataFrame) -> list[dict]:
    """Essence of losses: one primary ex-post type per losing trade (first matching rule)."""
    d = T[T["split"].isin(DESIGN_SPLITS) & (T["r"] <= 0)].copy()
    def kind(r):
        if r["mfe_r"] < 0.25:
            return "never worked (failed immediately)" if r["post_mae_r"] > 1.5 else "never worked, then drifted back"
        if r["post_hit_target"]:
            return "stop hunted (target reached after the stop)"
        if r["mfe_r"] >= 1.0:
            return "worked, then reversed through breakeven" if r["partial_done"] else "worked +1R, then reversed"
        return "partial move then reversal"
    d["loss_type"] = d.apply(kind, axis=1)
    out = []
    for k, g in d.groupby("loss_type"):
        out.append({"type": k, "n": len(g), "share": len(g) / len(d), "avg_r": float(g["r"].mean()),
                    "by_strategy": g["strategy"].value_counts().to_dict(),
                    "short_share": float((g["direction"] < 0).mean())})
    return sorted(out, key=lambda x: -x["n"])


def early_exit_r(T: pd.DataFrame, path, hours: int, min_r: float) -> np.ndarray:
    """R under: 'at the close of the H-th H1 bar after the fill, if the trade has never traded
    +min_r R, close it at market'. Uses only information available at that close. The bot's
    $0.35 cost is charged once (same as the original trade)."""
    out = T["r"].values.astype(float).copy()
    for k, r in enumerate(T.itertuples()):
        check = r.entry_time + pd.Timedelta(hours=hours)          # entry_time = close of the fill bar
        if r.exit_time <= check:
            continue                                               # already closed: rule never fires
        a = path.start_index(r.entry_time - pd.Timedelta(hours=1))
        b = path.start_index(check)
        hi, lo = path.h[a:b], path.l[a:b]
        if not len(hi):
            continue
        d, e0, rk = r.direction, r.entry, r.risk
        mfe = ((hi.max() - e0) if d > 0 else (e0 - lo.min())) / rk
        if mfe >= min_r:
            continue
        px = path.c[b - 1]                                         # last close before the check time
        out[k] = d * (px - e0) / rk - 0.35 / rk
    return out


def rule_grid(T: pd.DataFrame, path, hours=(2, 3, 4, 6, 8, 12), mins=(0.25, 0.5, 0.75)) -> pd.DataFrame:
    rows = []
    for h in hours:
        for m in mins:
            rr = early_exit_r(T, path, h, m)
            for strat in ["ALL"] + sorted(T["strategy"].unique()):
                sel = (T["strategy"] == strat).values if strat != "ALL" else np.ones(len(T), bool)
                for sp in DESIGN_SPLITS:
                    s2 = sel & (T["split"] == sp).values
                    new, old = rr[s2], T["r"].values[s2]
                    dlt = new - old
                    from scipy import stats as st
                    rows.append({"hours": h, "min_r": m, "strategy": strat, "split": sp, "n": int(s2.sum()),
                                 "old_avg_r": float(old.mean()), "new_avg_r": float(new.mean()),
                                 "delta": float(dlt.mean()),
                                 "t": float(dlt.mean() / (dlt.std(ddof=1) / np.sqrt(len(dlt)))) if dlt.std() > 0 else 0.0,
                                 "old_win": float((old > 0).mean()), "new_win": float((new > 0).mean()),
                                 "old_dd": float(_dd(old)), "new_dd": float(_dd(new)),
                                 "fired": float((dlt != 0).mean())})
    return pd.DataFrame(rows)


def _dd(r):
    eq = np.concatenate([[0], np.cumsum(r)])
    return np.max(np.maximum.accumulate(eq) - eq)


def exit_variants(T: pd.DataFrame, path, f: pd.DataFrame) -> pd.DataFrame:
    """Re-run each bot trade from its actual fill with the lab simulator (M15) under exit policies.

    'bot' mirrors the live rules: half off at +1R with the stop to entry, rest at +2R. The other
    policies keep the entry, stop and the +1R partial and change only the second half.
    """
    from .simulator import simulate
    from .config import CostModel
    co = CostModel(spread_min=0.35, spread_bps=0.0, slip_atr=0.0)     # $0.35 round trip ~ the bot's cost model
    co_half = CostModel(spread_min=0.35, spread_bps=0.0, slip_atr=0.0)
    atr = f["atr"].values
    rows = []
    for r in T.itertuples():
        s = path.start_index(r.entry_time - pd.Timedelta(hours=1))
        kw = dict(entry_type="stop", order_price=r.entry, expiry_minutes=60, costs=co, min_risk_atr=0.0)
        a = float(atr[r.idx])
        d, st = r.direction, r.stop_px
        leg1 = simulate(path, s, d, st, 0.0, 48 * 60, a, target_r=1.0, **kw)
        if not leg1.get("filled"):
            rows.append({"trade_id": r.trade_id}); continue
        legs = {
            "rest_2r": simulate(path, s, d, st, 0.0, 48 * 60, a, target_r=2.0, breakeven_at_r=1.0, **kw),
            "rest_3r": simulate(path, s, d, st, 0.0, 96 * 60, a, target_r=3.0, breakeven_at_r=1.0, **kw),
            "rest_trail2": simulate(path, s, d, st, None, 96 * 60, a, trail_atr=2.0, trail_after_r=1.0, breakeven_at_r=1.0, **kw),
            "rest_trail3": simulate(path, s, d, st, None, 96 * 60, a, trail_atr=3.0, trail_after_r=1.0, breakeven_at_r=1.0, **kw),
        }
        out = {"trade_id": r.trade_id, "leg1": leg1["r"]}
        for k, v in legs.items():
            out[k] = 0.5 * leg1["r"] + 0.5 * v["r"]
        out["all_trail3"] = legs["rest_trail3"]["r"]
        rows.append(out)
    return pd.DataFrame(rows)


def build_model(T: pd.DataFrame, rules: dict | None = None) -> dict:
    """The compact, stdlib-readable summary the live bot uses for its notes.

    Only discovery + validation trades are summarised (the holdout stays sealed)."""
    d = T[T["split"].isin(DESIGN_SPLITS)]
    out = {"built_from": f"{d['sig_time'].min():%Y-%m-%d} .. {d['sig_time'].max():%Y-%m-%d} (discovery + validation)",
           "definition": "tf_conflict = H1 EMA20/50, 4H EMA20/50 and daily EMA50 10-day slope do not all agree (lab mistake T2)",
           "strategies": {}}
    bins = [(-99.0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 99.0)]
    for s, g in d.groupby("strategy"):
        fl = g["flag_T2"].astype(bool)
        rec = {"flagged": _brief(g.loc[fl, "r"]), "clean": _brief(g.loc[~fl, "r"]), "all": _brief(g["r"]),
               "by_mfe3h": []}
        for lo, hi in bins:
            x = g[(g["mfe3h"] > lo) & (g["mfe3h"] <= hi)]
            if len(x) >= 10:
                rec["by_mfe3h"].append({"lo": lo, "hi": hi, **_brief(x["r"])})
        out["strategies"][s] = rec
    if rules:
        out["rules_tested"] = rules
    return jsonable(out)


def _brief(r: pd.Series) -> dict:
    r = r.dropna()
    return {"n": int(len(r)), "win": float((r > 0).mean()) if len(r) else None, "avg_r": float(r.mean()) if len(r) else None}


def parity(T: pd.DataFrame) -> dict:
    """Does the live bot's stdlib anatomy_flags() agree with the lab's flag_T2 on the same bars?"""
    S = _signals()
    import os
    cwd = os.getcwd(); os.chdir(ROOT)
    try:
        h1 = S.load_history(S.CONFIG)
    finally:
        os.chdir(cwd)
    F = S.Features(h1, S.CONFIG)
    times = {b["t"].replace(tzinfo=None) + pd.Timedelta(hours=1): i for i, b in enumerate(F.h1)}
    agree = n = 0
    for r in T.itertuples():
        i = times.get(r.sig_time.to_pydatetime())
        if i is None:
            continue
        a = S.anatomy_flags(F, i)
        if a is None:
            continue
        n += 1
        agree += int(a["tf_conflict"] == bool(r.flag_T2))
    return {"checked": n, "agree": agree, "agreement": agree / n if n else None}


def report(lab) -> dict:
    """Everything the dashboard's 'Your bot' tab shows. Uses only discovery+validation for design
    views; the forward section scores the live definitions on trades after 2026-11-23."""
    import pickle
    from .config import CACHE, SPLITS
    p = CACHE / "bot_trades.pkl"
    if p.exists():
        B = pickle.loads(p.read_bytes())
    else:
        T, _ = replay()
        B = attach_context(T, lab.f, lab.path)
        p.write_bytes(pickle.dumps(B))
    d = B[B["split"].isin(DESIGN_SPLITS)]
    per = []
    for s, g in d.groupby("strategy"):
        per.append({"strategy": s, "n": len(g), "win": float(g["win"].mean()), "avg_r": float(g["r"].mean()),
                    "never_half_r_losers": float(g.loc[g["r"] <= 0, "hours_to_half_r"].isna().mean()),
                    "never_half_r_winners": float(g.loc[g["r"] > 0, "hours_to_half_r"].isna().mean())})
    A = ex_ante_anatomy(B)
    FA = flag_anatomy(B)
    FA = FA[(FA["phase"] == "ex_ante") & (FA["discovery_n"] >= 30)]
    FA["delta_disc"] = FA["discovery_r_flagged"] - FA["discovery_r_clean"]
    FA["delta_valid"] = FA["validation_r_flagged"] - FA["validation_r_clean"]
    fwd = B[B["sig_time"] >= pd.Timestamp(SPLITS["forward"][0])]
    fwd_rows = [{"strategy": s, "n": len(g), "flagged_n": int(g["flag_T2"].sum()),
                 "flagged_avg_r": float(g.loc[g["flag_T2"].astype(bool), "r"].mean()) if g["flag_T2"].any() else None,
                 "clean_avg_r": float(g.loc[~g["flag_T2"].astype(bool), "r"].mean()) if (~g["flag_T2"].astype(bool)).any() else None}
                for s, g in fwd.groupby("strategy")]
    rules = json.loads((STORE / "bot_rules.json").read_text()) if (STORE / "bot_rules.json").exists() else {}
    model = json.loads((STORE / "bot_anatomy_model.json").read_text()) if (STORE / "bot_anatomy_model.json").exists() else {}
    return jsonable({
        "n_trades": len(B), "per_strategy": per, "loss_types": loss_types(B), "early": early_warning(B),
        "ex_ante": A.head(25).to_dict("records"), "ex_ante_replicated": int(A["replicates"].sum()),
        "flags": FA.sort_values("delta_disc")[["id", "name", "discovery_n", "delta_disc", "validation_n", "delta_valid"]].to_dict("records"),
        "rules": rules, "model": model, "forward": fwd_rows, "forward_from": SPLITS["forward"][0],
    })
