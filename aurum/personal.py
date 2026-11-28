"""Personal edge reconstruction: what distinguishes the owner's good decisions from bad ones.

Inputs: store/personal/trades_normalized.csv (from ingest.py).

Integrity rules
  * Every trade is reconstructed from information available at its open time: the last CLOSED H1
    bar plus the part of the current hour seen so far on M15. Anything later is used only to label
    the outcome, and every ex-post label says so.
  * The owner's trades are split chronologically: the first 60% are "personal discovery", the
    rest "personal validation". Personal rules are designed on the first part and must hold in the
    second. Every personal test is written to the experiment ledger, failures included.
  * Market-level transfers (to Aurum's discoveries or the bot) are tested on market discovery and
    validation data only and frozen for the forward split. The market holdout stays sealed.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
from scipy import stats as st

from .config import STORE, SPLITS
from .stats import summarise, bootstrap_ci, jsonable, benjamini_hochberg
from .trades import CONTEXT, add_relative
from .taxonomy import flag_trades, M as MISTAKES

P_DIR = STORE / "personal"
DISC_FRAC = 0.6

KEY_FEATURES = ["rel_mom6", "rel_mom24", "rel_rsi", "adx", "er30", "atr_pct", "rel_dist_ema20", "rel_dist_ema50",
                "rel_d_ext", "rel_d_ema50_slope", "rel_pos50", "room_fwd", "room_fwd_htf", "rel_h4_dist_ema20",
                "rel_mtf_votes", "rel_structure", "rel_h4_structure", "rel_d_structure", "bb_width_pct",
                "range20_atr", "stop_atr", "hour", "live_bar_move", "vol_rel"]


# ------------------------------------------------------------------------------------------ reconstruct
def reconstruct(u: pd.DataFrame, f: pd.DataFrame, path, n_random: int = 40, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    tc = f["tc"].values
    atr_all = f["atr"].values
    # typical initial stop of THIS trader in ATR, from trades whose initial stop is known
    ii = np.clip(np.searchsorted(tc, u["open_time"].values.astype("datetime64[ns]"), side="right") - 1, 0, len(tc) - 1)
    known = u["stop"].notna().values
    ratios = (np.abs(u["entry"].values - u["stop"].values) / atr_all[ii])[known]
    med_stop_atr = float(np.nanmedian(ratios)) if known.sum() >= 5 else None
    rows = []
    for k, x in u.iterrows():
        ot, ct = pd.Timestamp(x["open_time"]), pd.Timestamp(x["close_time"]) if pd.notna(x["close_time"]) else None
        i = int(np.searchsorted(tc, np.datetime64(ot), side="right")) - 1     # last CLOSED H1 bar
        if i < 250:
            continue
        d, e0 = int(x["direction"]), float(x["entry"])
        atr = float(atr_all[i])
        stop = x["stop"] if pd.notna(x["stop"]) else np.nan
        risk = abs(e0 - stop) if pd.notna(stop) else np.nan
        if pd.notna(risk) and risk > 0:
            r_basis, unit = "stop", risk
        elif med_stop_atr:
            r_basis, unit = "estimated_stop", med_stop_atr * atr   # this trader's typical stop, in today's ATR
        else:
            r_basis, unit = "atr_units", atr
        a = path.start_index(ot)
        b = path.start_index(ct) if ct is not None else a
        hi, lo = path.h[a:max(b, a + 1)], path.l[a:max(b, a + 1)]
        xp = float(x["exit"]) if pd.notna(x["exit"]) else float(path.c[max(b - 1, a)])
        r = d * (xp - e0) / unit
        mfe = ((hi.max() - e0) if d > 0 else (e0 - lo.min())) / unit
        mae = ((e0 - lo.min()) if d > 0 else (hi.max() - e0)) / unit
        jm = int(np.argmax(hi) if d > 0 else np.argmin(lo))
        # what was visible inside the current hour (M15 bars that had closed before the open time)
        h_open = path.start_index(pd.Timestamp(tc[i]))
        seen = slice(h_open, a)
        live = ((path.c[a - 1] - path.o[h_open]) / atr) * d if a > h_open else 0.0
        # after the exit (labels only)
        pe = path.start_index((ct or ot) + pd.Timedelta(hours=24))
        ph, pl = path.h[b:pe], path.l[b:pe]
        post_fav = (((ph.max() - e0) if d > 0 else (e0 - pl.min())) / unit) if len(ph) else np.nan
        post_adv = (((e0 - pl.min()) if d > 0 else (ph.max() - e0)) / unit) if len(ph) else np.nan
        # entry timing: where the entry sat inside the price range of the 2h before / after it
        w0, w1 = path.start_index(ot - pd.Timedelta(hours=2)), path.start_index(ot + pd.Timedelta(hours=2))
        rh, rl = path.h[w0:w1].max(), path.l[w0:w1].min()
        timing = ((e0 - rl) / (rh - rl) if d > 0 else (rh - e0) / (rh - rl)) if rh > rl else np.nan
        # random-timing benchmark: same day +/-24h, same side, same distance to stop and same holding time
        hold = max(15.0, ((ct - ot).total_seconds() / 60) if ct is not None else 60.0)
        rand = []
        for _ in range(n_random):
            s = int(np.clip(a + rng.integers(-96, 97), 1, len(path.t) - 2))
            m0 = path.o[s]
            e_ = np.searchsorted(path.t, path.t[s] + np.timedelta64(int(hold), "m"))
            hh, ll = path.h[s:e_ + 1], path.l[s:e_ + 1]
            if not len(hh):
                continue
            stp = m0 - d * unit
            hit = (ll <= stp) if d > 0 else (hh >= stp)
            j = np.flatnonzero(hit)
            ex_ = stp if len(j) else path.c[min(e_, len(path.c) - 1)]
            rand.append(d * (ex_ - m0) / unit)
        rows.append({
            "trade_id": x["trade_id"], "idx": i, "direction": d, "entry": e0, "exit": xp, "stop_px": stop,
            "stop_kind": x.get("stop_kind"), "r_basis": r_basis, "risk": unit, "stop_atr": unit / atr,
            "open_time": ot, "close_time": ct, "hours_held": hold / 60, "r": r, "r_atr": d * (xp - e0) / atr,
            "mfe_r": mfe, "mae_r": mae, "hours_to_mfe": float((path.t[a + jm] - path.t[a]) / np.timedelta64(1, "h")),
            "post_mfe_r": post_fav, "post_mae_r": post_adv, "entry_timing": timing, "live_bar_move": live,
            "random_r": float(np.mean(rand)) if rand else np.nan,
            "timing_alpha": r - float(np.mean(rand)) if rand else np.nan,
            "pnl": x.get("pnl"), "volume": x.get("volume"), "owner_setup": x.get("owner_setup"),
            "notes": x.get("notes"), "tags": x.get("tags"), "source": x.get("source"),
        })
    T = pd.DataFrame(rows)
    if not len(T):
        return T
    ctx = f.loc[T["idx"].values, CONTEXT].reset_index(drop=True)
    T = pd.concat([T, ctx], axis=1)
    T["setup"], T["family"] = "personal", "personal"
    T["win"] = (T["r"] > 0).astype(int)
    T["exit_reason"] = np.where(T["r"] <= -0.9, "stop", np.where(T["r"] > 0, "target", "time"))
    T["post_hit_target"] = T["post_mfe_r"] >= 2
    T["cost_r"], T["r_gross"], T["crosses_split"] = 0.0, T["r"], False
    T["ref_level"] = T["entry"]
    T = add_relative(T)
    fl = flag_trades(T, None)
    T = pd.concat([T, fl.add_prefix("flag_")], axis=1)
    n = len(T)
    T = T.sort_values("open_time").reset_index(drop=True)
    T["p_split"] = np.where(np.arange(n) < int(math.ceil(n * DISC_FRAC)), "p_discovery", "p_validation")
    T["market_split"] = T["split"]
    return T


# ------------------------------------------------------------------------------------------ directional
def _diff_ci(a, b, n_boot=4000, seed=0):
    rng = np.random.default_rng(seed)
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 5 or len(b) < 5:
        return (np.nan, np.nan)
    d = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(n_boot)]
    return tuple(np.percentile(d, [2.5, 97.5]))


def _perm_p(a, b, n=4000, seed=0):
    rng = np.random.default_rng(seed)
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 5 or len(b) < 5:
        return np.nan
    obs = a.mean() - b.mean()
    pool = np.concatenate([a, b])
    cnt = 0
    for _ in range(n):
        rng.shuffle(pool)
        cnt += (pool[:len(a)].mean() - pool[len(a):].mean()) >= obs
    return (cnt + 1) / (n + 1)


def directional(T: pd.DataFrame) -> dict:
    """Battery of tests that try to DISPROVE 'I am better at shorts'."""
    S, L = T[T["direction"] < 0], T[T["direction"] > 0]
    out = {"n_short": len(S), "n_long": len(L)}
    rcol = "r"
    out["short"], out["long"] = summarise(S[rcol]), summarise(L[rcol])
    gap = S[rcol].mean() - L[rcol].mean() if len(S) and len(L) else np.nan
    out["gap"] = gap
    out["gap_ci"] = _diff_ci(S[rcol], L[rcol])
    out["perm_p"] = _perm_p(S[rcol], L[rcol])
    out["ks_p"] = float(st.ks_2samp(S[rcol], L[rcol]).pvalue) if len(S) > 4 and len(L) > 4 else np.nan
    # 1. regime composition vs within-regime skill
    from .behaviour import oaxaca
    out["oaxaca"] = oaxaca(T.assign(r=T[rcol]))
    # 2. timing skill: beyond random entries on the same day, side and stop distance
    out["timing_alpha"] = {"short": summarise(S["timing_alpha"].dropna()), "long": summarise(L["timing_alpha"].dropna()),
                           "gap_ci": _diff_ci(S["timing_alpha"].dropna(), L["timing_alpha"].dropna())}
    # 3. stability: does the gap have the same sign in both halves of the owner's history?
    halves = {}
    for h, g in T.groupby("p_split"):
        s_, l_ = g[g["direction"] < 0][rcol], g[g["direction"] > 0][rcol]
        halves[h] = {"gap": float(s_.mean() - l_.mean()) if len(s_) and len(l_) else None, "n_short": len(s_), "n_long": len(l_)}
    out["halves"] = halves
    yrs = T.assign(y=T["open_time"].dt.year).groupby("y").apply(
        lambda g: (g.loc[g["direction"] < 0, rcol].mean() - g.loc[g["direction"] > 0, rcol].mean())
        if (g["direction"] < 0).sum() >= 3 and (g["direction"] > 0).sum() >= 3 else np.nan, include_groups=False).dropna()
    out["years_short_better"] = {"share": float((yrs > 0).mean()) if len(yrs) else None, "n_years": int(len(yrs))}
    # 4. dimensions
    dims = {}
    for c, lab in (("entry_timing", "entry timing (0 = best price within +/-2h)"), ("mfe_r", "max favourable excursion (R)"),
                   ("mae_r", "max adverse excursion (R)"), ("hours_held", "hours held"), ("rel_mom6", "momentum with the trade, 6h (ATR)"),
                   ("rel_structure", "H1 structure with the trade"), ("rel_mtf_votes", "timeframes agreeing with the trade"),
                   ("atr_pct", "volatility percentile"), ("rel_d_ext", "stretch from daily EMA50 in trade direction"),
                   ("with_daily", "with the daily trend (share)")):
        if c in T:
            dims[c] = {"label": lab, "short": float(S[c].mean()), "long": float(L[c].mean()),
                       "p": float(st.mannwhitneyu(S[c].dropna(), L[c].dropna()).pvalue) if S[c].notna().sum() > 4 and L[c].notna().sum() > 4 else None}
    out["dimensions"] = dims
    bins = np.arange(-3, 4.01, 0.5)
    out["r_hist"] = {"bins": bins.tolist(), "short": np.histogram(S[rcol].clip(-3, 3.99), bins)[0].tolist(),
                     "long": np.histogram(L[rcol].clip(-3, 3.99), bins)[0].tolist()}
    # 5. power: smallest gap this sample could detect (80% power, 5% two-sided)
    sd = T[rcol].std()
    out["min_detectable_gap"] = float(2.8 * sd * math.sqrt(1 / max(len(S), 1) + 1 / max(len(L), 1))) if len(S) and len(L) else None
    # verdict
    lo, hi = out["gap_ci"]
    ta_lo = out["timing_alpha"]["gap_ci"][0]
    same_sign = all((h["gap"] or 0) > 0 for h in halves.values()) if halves else False
    comp_share = out["oaxaca"]["composition_effect"] / gap if gap else np.nan
    if len(S) < 20 or len(L) < 20:
        v = "insufficient data"
    elif lo > 0 and same_sign and (ta_lo == ta_lo and ta_lo > 0):
        v = "SUPPORTED: shorts are better, beyond regime mix and market timing, in both halves"
    elif lo > 0 and comp_share > 0.5:
        v = "EXPLAINED AWAY: shorts did better mostly because of WHEN they were taken (regime mix)"
    elif lo > 0:
        v = "PARTLY SUPPORTED: shorts did better, but not beyond random timing or not in both halves"
    elif hi < 0:
        v = "CONTRADICTED: longs did better"
    else:
        v = "NOT SUPPORTED: no detectable difference" + (f" (this sample can only detect gaps above {out['min_detectable_gap']:.2f}R)"
                                                        if out["min_detectable_gap"] else "")
    out["verdict"] = v
    out["composition_share"] = comp_share
    return out


# ------------------------------------------------------------------------------------------ fingerprint
CATS = ["incorrect direction (avoidable)", "right direction, poor timing", "good entry, poor exit",
        "regime misread", "risk management", "valid trade that lost", "good trade", "lucky win"]
REGIME_FLAGS = {"T1", "T3", "T4", "X4", "K5", "C1", "V1", "T7", "T8", "T2"}


def fingerprint(T: pd.DataFrame, avoidable_ids: set[str]) -> pd.DataFrame:
    """Two separate questions per trade.

    1. Was the DECISION avoidable? Only warning signs that are confirmed harmful (lab-wide, or in the
       owner's own discovery AND validation trades) count, and they are all visible at entry.
    2. HOW did it fail? (ex-post: uses prices after entry, only to describe the failure)
    A loss with no avoidable warning and no process fault is a valid trade that lost: variance.
    """
    out = []
    known = T[T["r_basis"] == "stop"]
    lo_s, hi_s = (known["stop_atr"].quantile(0.05), known["stop_atr"].quantile(0.95)) if len(known) >= 20 else (0, np.inf)
    risk_money = pd.to_numeric(T["volume"], errors="coerce") * T["risk"]
    med_money = risk_money.median()
    for r, rm in zip(T.itertuples(), risk_money.values):
        ante = sorted(m for m in avoidable_ids if bool(getattr(r, f"flag_{m}", False)))
        # process faults judged against the trader's OWN norms
        risk_bad = (r.r_basis == "stop" and (r.stop_atr < lo_s or r.stop_atr > hi_s)) or r.r < -1.3 or \
                   (med_money == med_money and rm == rm and rm > 2 * med_money)
        gave_back = r.mfe_r >= 1.0
        early = (r.post_mfe_r or 0) >= 1.5 and r.mfe_r < 1.0
        wrong = r.mfe_r < 0.3 and (r.post_mae_r or 0) > 1.0
        how = "gave back a winner" if gave_back else ("stopped, then it went" if early else
                                                       ("went straight against" if wrong else "chopped out"))
        labels = []
        if r.r <= 0:
            if risk_bad:
                labels.append("risk management")
            if ante:
                if set(ante) & REGIME_FLAGS:
                    labels.append("regime misread")
                if wrong:
                    labels.append("incorrect direction (avoidable)")
            if gave_back:
                labels.append("good entry, poor exit")
            elif early:
                labels.append("right direction, poor timing")
            if not labels:
                labels.append("valid trade that lost")
        else:
            labels.append("lucky win" if ante and r.mfe_r < 1.0 else "good trade")
            if (r.post_mfe_r or 0) >= r.r + 2:
                labels.append("good entry, poor exit")      # exited long before the move finished
        out.append({"trade_id": r.trade_id, "primary": labels[0], "labels": labels, "how_it_failed": how if r.r <= 0 else None,
                    "avoidable_flags": ante, "avoidable": bool(ante) and r.r <= 0,
                    "unpredictable": labels[0] == "valid trade that lost"})
    return pd.DataFrame(out)


# ------------------------------------------------------------------------------------------ discriminators
def discriminators(T: pd.DataFrame) -> pd.DataFrame:
    """What separates the owner's winners from losers: found on personal discovery, checked on validation."""
    rows = []
    for c in KEY_FEATURES:
        if c not in T:
            continue
        rec = {"feature": c}
        for sp in ("p_discovery", "p_validation"):
            g = T[T["p_split"] == sp]
            w, l = g.loc[g["r"] > 0, c].dropna(), g.loc[g["r"] <= 0, c].dropna()
            if len(w) < 8 or len(l) < 8:
                rec[sp + "_effect"] = rec[sp + "_p"] = np.nan
                continue
            sd = g[c].std()
            rec[sp + "_effect"] = float((w.mean() - l.mean()) / sd) if sd else np.nan
            rec[sp + "_p"] = float(st.mannwhitneyu(w, l).pvalue)
            rec[sp + "_win_mean"], rec[sp + "_loss_mean"] = float(w.mean()), float(l.mean())
        rows.append(rec)
    D = pd.DataFrame(rows)
    if len(D) and "p_discovery_p" in D:
        D["q"] = benjamini_hochberg(D["p_discovery_p"].values)
        D["replicates"] = (np.sign(D["p_discovery_effect"]) == np.sign(D["p_validation_effect"])) & \
                          (D["p_discovery_p"] < 0.05) & (D["p_validation_p"] < 0.10)
    return D.sort_values("p_discovery_p") if len(D) else D


# ------------------------------------------------------------------------------------------ own setups
def natural_setups(T: pd.DataFrame, k_range=range(3, 8)) -> dict:
    """Bottom-up: cluster the owner's decisions by context, without forcing them into lab setup names."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    feats = [c for c in ["rel_mom6", "rel_mom24", "rel_dist_ema50", "rel_d_ext", "adx", "er30", "atr_pct",
                         "rel_pos50", "rel_mtf_votes", "hour"] if c in T]
    X = T[feats].astype(float)
    ok = X.notna().all(axis=1)
    if ok.sum() < 30:
        return {"clusters": [], "note": "fewer than 30 complete trades"}
    Z = ((X - X[ok].mean()) / X[ok].std().replace(0, 1))[ok].values
    best = None
    for k in k_range:
        if k >= ok.sum() // 5:
            break
        km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(Z)
        s = silhouette_score(Z, km.labels_)
        if best is None or s > best[0]:
            best = (s, k, km)
    s, k, km = best
    lab = pd.Series(-1, index=T.index)
    lab[ok] = km.labels_
    T = T.assign(cluster=lab)
    out = []
    for c, g in T[T["cluster"] >= 0].groupby("cluster"):
        prof = {f: float(g[f].mean()) for f in feats}
        desc = []
        if prof["rel_mom6"] > 1: desc.append("with strong short-term momentum")
        if prof["rel_mom6"] < -1: desc.append("against short-term momentum (fading)")
        if prof["rel_d_ext"] > 1.5: desc.append("extended in the trade direction on the daily")
        if prof["rel_d_ext"] < -1.5: desc.append("against a daily extension (mean reversion)")
        if prof["adx"] > 30: desc.append("in a strong trend")
        if prof["adx"] < 18: desc.append("in a quiet / ranging market")
        if prof["rel_mtf_votes"] >= 2: desc.append("timeframes aligned with the trade")
        if prof["rel_mtf_votes"] <= -2: desc.append("timeframes against the trade")
        halves = {sp: summarise(gg["r"])["avg_r"] for sp, gg in g.groupby("p_split")}
        out.append({"cluster": int(c), "n": len(g), "short_share": float((g["direction"] < 0).mean()),
                    "description": ", ".join(desc) or "mixed context", "profile": prof, "perf": summarise(g["r"]),
                    "avg_r_by_half": halves, "owner_labels": g["owner_setup"].dropna().astype(str).value_counts().head(3).to_dict()})
    return {"k": int(k), "silhouette": float(s), "features": feats, "clusters": sorted(out, key=lambda x: -x["n"]),
            "assignment": dict(zip(T["trade_id"], lab.astype(int)))}


# ------------------------------------------------------------------------------------------ edge transfer
def edge_transfer(T: pd.DataFrame, discoveries: list[dict], taxonomy: list[dict]) -> dict:
    """Which Aurum findings explain the owner's results, and which are contradicted by them."""
    from .hypothesis import mask, describe
    rows = []
    for d in discoveries:
        spec = dict(d["spec"])
        spec["setup"] = "*"                       # the owner's trades are not lab setups: test the CONDITIONS
        try:
            m = mask(T, spec)
        except KeyError:
            continue
        if m.sum() < 8:
            continue
        inside, outside = T.loc[m, "r"], T.loc[~m & ((T["direction"] == spec.get("direction")) | (spec.get("direction", 0) == 0)), "r"]
        rows.append({"hyp_id": d["hyp_id"], "lab_status": d["status"], "condition": describe({**spec, "exit": "base"}),
                     "owner_n": int(m.sum()), "owner_avg_r_inside": float(inside.mean()),
                     "owner_avg_r_outside": float(outside.mean()) if len(outside) else None,
                     "agrees": bool(inside.mean() > (outside.mean() if len(outside) else 0))})
    tx = []
    for t in taxonomy:
        col = f"flag_{t['id']}"
        if col not in T or t.get("phase") != "ex_ante":
            continue
        on = T[col].astype(bool)
        if on.sum() < 8 or (~on).sum() < 8:
            continue
        dr = float(T.loc[on, "r"].mean() - T.loc[~on, "r"].mean())
        lab_v = t.get("verdict", "")
        rel = "agrees" if ((dr < 0 and lab_v.startswith("confirmed")) or (dr > 0 and lab_v.startswith("CONTRA"))) else \
              ("CONTRADICTS the lab" if (dr > 0 and lab_v.startswith("confirmed")) or (dr < 0 and lab_v.startswith("CONTRA")) else "lab says no effect")
        tx.append({"id": t["id"], "name": t["name"], "lab_verdict": lab_v, "owner_n": int(on.sum()),
                   "owner_delta_r": dr, "relation": rel})
    seen, uniq = set(), []
    for x in sorted(rows, key=lambda x: -x["owner_n"]):
        if x["condition"] not in seen:
            seen.add(x["condition"]); uniq.append(x)
    return {"discoveries": uniq, "mistakes": sorted(tx, key=lambda x: x["owner_delta_r"])}


# ------------------------------------------------------------------------------------------ decisions
def decisions(T: pd.DataFrame, fp: pd.DataFrame, D: pd.DataFrame, taxonomy: list[dict], f: pd.DataFrame, k: int = 400) -> list[dict]:
    """Per-trade reconstruction: what was visible, relevant, misleading, avoidable, unpredictable."""
    tv = {t["id"]: t for t in taxonomy}
    relevant_feats = D[D.get("replicates", pd.Series(False, index=D.index)) == True]["feature"].tolist() if len(D) else []  # noqa: E712
    if not relevant_feats and len(D):
        relevant_feats = D.head(3)["feature"].tolist()
    fpi = fp.set_index("trade_id")
    out = []
    for r in T.tail(k).itertuples():
        i = int(r.idx)
        w = f.iloc[max(0, i - 72):i + 1]
        after = f.iloc[i + 1:i + 1 + 48]
        flags = [m.id for m in MISTAKES if m.phase == "ex_ante" and bool(getattr(r, f"flag_{m.id}", False))]
        misleading = [{"id": x, "name": tv[x]["name"], "lab_verdict": tv[x]["verdict"]} for x in flags
                      if x in tv and not tv[x]["verdict"].startswith("confirmed")]
        p = fpi.loc[r.trade_id] if r.trade_id in fpi.index else None
        out.append({
            "trade_id": r.trade_id, "open_time": str(r.open_time), "direction": int(r.direction), "r": float(r.r),
            "r_basis": r.r_basis, "owner_setup": r.owner_setup, "notes": r.notes,
            "visible": {k_: _f(getattr(r, k_, None)) for k_ in ("rel_mom6", "rel_mom24", "rel_rsi", "adx", "atr_pct",
                                                                 "rel_d_ext", "rel_mtf_votes", "rel_structure", "room_fwd_htf",
                                                                 "regime", "session", "live_bar_move")},
            "relevant": {k_: _f(getattr(r, k_, None)) for k_ in relevant_feats},
            "misleading": misleading,
            "avoidable": [{"id": x, "name": tv[x]["name"]} for x in (p["avoidable_flags"] if p is not None else [])],
            "primary_label": p["primary"] if p is not None else None, "labels": p["labels"] if p is not None else [],
            "unpredictable": bool(p["unpredictable"]) if p is not None else None,
            "chart_before": [[str(t)[:16], round(o, 2), round(h, 2), round(l, 2), round(c, 2)]
                             for t, o, h, l, c in zip(w["t"], w["open"], w["high"], w["low"], w["close"])],
            "chart_after": [[str(t)[:16], round(o, 2), round(h, 2), round(l, 2), round(c, 2)]
                            for t, o, h, l, c in zip(after["t"], after["open"], after["high"], after["low"], after["close"])],
            "entry": float(r.entry), "exit": float(r.exit), "stop": _f(r.stop_px), "close_time": str(r.close_time),
        })
    return out


def _f(x):
    if x is None:
        return None
    if isinstance(x, (float, np.floating)):
        return None if np.isnan(x) else round(float(x), 3)
    if isinstance(x, (np.integer, int)):
        return int(x)
    return x


# ------------------------------------------------------------------------------------------ ledger
def log_personal_tests(T: pd.DataFrame, D: pd.DataFrame, source: str) -> int:
    """Every personal discriminator becomes a recorded test (discovery -> validation), failures included."""
    from .ledger import Ledger, hyp_id
    L = Ledger()
    n = 0
    for _, r in D.iterrows():
        if pd.isna(r.get("p_discovery_p")):
            continue
        spec = {"setup": "personal", "direction": 0, "conditions": [{"f": r["feature"], "op": "discriminates_wins", "v": None}],
                "exit": "as_traded", "origin": "personal", "rationale": f"Owner winners vs losers differ on {r['feature']} ({source})."}
        hid = hyp_id({**spec, "source": source})
        if L.tested(hid, "personal_discovery"):
            continue
        for sp in ("p_discovery", "p_validation"):
            L.append({"hyp_id": hid, "description": f"[{source}] owner wins vs losses differ on {r['feature']}",
                      "spec": spec, "origin": "personal", "split": "personal_" + sp[2:],
                      "status": ("replicated" if r.get("replicates") else "not_replicated") if sp == "p_validation" else
                      ("candidate" if r[sp + "_p"] < 0.05 else "no_effect"),
                      "stats": {"n": None, "avg_r": None, "t": None, "p": r.get(sp + "_p"), "effect": r.get(sp + "_effect")}})
        n += 1
    return n


# ------------------------------------------------------------------------------------------ report
def run(lab, R: dict, source_path=None, label: str = "owner") -> dict:
    """Full personal report. ``label`` is 'owner' for real data or 'demo' for the stand-in."""
    path = source_path or (P_DIR / "trades_normalized.csv")
    if not path.exists():
        return {"status": "no_data"}
    u = pd.read_csv(path, parse_dates=["open_time", "close_time"])
    if not len(u):
        return {"status": "no_data"}
    T = reconstruct(u, lab.f, lab.path)
    if len(T) < 10:
        return {"status": "too_few_trades", "n": len(T)}
    tax = R.get("taxonomy", [])
    lab_confirmed = {t["id"] for t in tax if t.get("phase") == "ex_ante" and str(t.get("verdict", "")).startswith("confirmed")}
    owner_confirmed: set[str] = set()
    D = discriminators(T)
    # owner-specific harmful flags (found on personal discovery, hold on validation) are avoidable too
    for m in MISTAKES:
        c = f"flag_{m.id}"
        if m.phase != "ex_ante" or c not in T:
            continue
        gd, gv = T[T["p_split"] == "p_discovery"], T[T["p_split"] == "p_validation"]
        ond, onv = gd[c].astype(bool), gv[c].astype(bool)
        if min(ond.sum(), (~ond).sum(), onv.sum(), (~onv).sum()) < 8:
            continue
        td = st.ttest_ind(gd.loc[ond, "r"], gd.loc[~ond, "r"], equal_var=False)
        tv_ = st.ttest_ind(gv.loc[onv, "r"], gv.loc[~onv, "r"], equal_var=False)
        if td.statistic < 0 and td.pvalue < 0.05 and tv_.statistic < 0 and tv_.pvalue < 0.20:
            owner_confirmed.add(m.id)
    confirmed = lab_confirmed | owner_confirmed
    fp = fingerprint(T, confirmed)
    T = T.merge(fp[["trade_id", "primary"]], on="trade_id", how="left")
    n_logged = log_personal_tests(T, D, label)
    fp_summary = []
    for lab_, g in fp.groupby("primary"):
        sub = T[T["primary"] == lab_]
        fp_summary.append({"label": lab_, "n": len(g), "share": len(g) / len(fp), "avg_r": float(sub["r"].mean()),
                           "short_share": float((sub["direction"] < 0).mean())})
    by_side = {s: fp.merge(T[["trade_id", "direction"]], on="trade_id").query("direction == @d")["primary"]
               .value_counts(normalize=True).round(3).to_dict() for s, d in (("short", -1), ("long", 1))}
    rep = {
        "status": "ok", "label": label, "n": len(T),
        "date_range": [str(T["open_time"].min()), str(T["open_time"].max())],
        "r_basis": T["r_basis"].value_counts().to_dict(),
        "summary": summarise(T["r"]), "by_half": {sp: summarise(g["r"]) for sp, g in T.groupby("p_split")},
        "directional": directional(T),
        "fingerprint": sorted(fp_summary, key=lambda x: -x["n"]), "fingerprint_by_side": by_side,
        "avoidable_share_of_losses": float(fp.merge(T[["trade_id", "r"]], on="trade_id").query("r <= 0")["avoidable"].mean()),
        "unpredictable_share_of_losses": float(fp.merge(T[["trade_id", "r"]], on="trade_id").query("r <= 0")["unpredictable"].mean()),
        "discriminators": D.head(25).to_dict("records") if len(D) else [],
        "avoidable_flags": {"lab_confirmed": sorted(lab_confirmed), "owner_confirmed": sorted(owner_confirmed)},
        "how_losses_failed": fp.dropna(subset=["how_it_failed"])["how_it_failed"].value_counts(normalize=True).round(3).to_dict(),
        "by_r_basis": {b: summarise(g["r"]) for b, g in T.groupby("r_basis")},
        "natural_setups": {k: v for k, v in natural_setups(T).items() if k != "assignment"},
        "edge_transfer": edge_transfer(T, R.get("discoveries", []), tax),
        "decisions": decisions(T, fp, D, tax, lab.f, k=150),
        "tests_logged": n_logged,
    }
    return jsonable(rep)
