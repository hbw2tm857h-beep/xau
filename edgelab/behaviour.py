"""Why does price behave the way it does around decisions? Market-level studies.

These are not strategies. They measure conditional forward behaviour of XAUUSD
so that setup results can be explained (e.g. "breakouts fail because momentum
mean-reverts at this horizon" or "shorts work in a different way to longs").
All conditioning variables are causal; forward returns are the outcome only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stats import summarise, welch


def forward_returns(f: pd.DataFrame, horizons=(1, 3, 6, 12, 24)) -> pd.DataFrame:
    out = pd.DataFrame(index=f.index)
    for h in horizons:
        out[f"fwd{h}"] = (f["close"].shift(-h) - f["close"]) / f["atr"]
    # forward max adverse / favourable excursion over 12 bars, in ATR
    hi = f["high"][::-1].rolling(12, min_periods=1).max()[::-1].shift(-1)
    lo = f["low"][::-1].rolling(12, min_periods=1).min()[::-1].shift(-1)
    out["fwd_up12"] = (hi - f["close"]) / f["atr"]
    out["fwd_dn12"] = (f["close"] - lo) / f["atr"]
    return out


def momentum_persistence(f: pd.DataFrame, fr: pd.DataFrame, look="mom6", horizon="fwd12",
                         split_col="split", splits=("discovery", "validation", "holdout")) -> pd.DataFrame:
    """Forward move conditional on past move, separately for up-moves and down-moves.

    Positive 'continuation' means the next move goes the same way as the past move.
    """
    d = pd.concat([f[[look, split_col, "regime_trend"]], fr[[horizon]]], axis=1).dropna()
    d = d[d[split_col].isin(splits)]
    bins = [-np.inf, -4, -3, -2, -1, -0.5, 0.5, 1, 2, 3, 4, np.inf]
    d["bin"] = pd.cut(d[look], bins)
    drift = d[horizon].mean()            # gold's unconditional drift over the horizon
    rows = []
    for b, g in d.groupby("bin", observed=True):
        sign = np.sign(g[look].mean())
        cont = g[horizon] * sign
        rows.append({"bin": str(b), "n": len(g), "mean_past": float(g[look].mean()),
                     "mean_fwd": float(g[horizon].mean()), "continuation": float(cont.mean()),
                     "p_continue": float((cont > 0).mean()),
                     "excess_continuation": float(((g[horizon] - drift) * sign).mean()),
                     "t": float(((g[horizon] - drift) * sign).mean() / (cont.std() / np.sqrt(len(cont)))) if len(cont) > 2 else np.nan})
    return pd.DataFrame(rows)


def directional_asymmetry(f: pd.DataFrame, fr: pd.DataFrame) -> dict:
    """Do down-moves behave differently from up-moves in gold? ('stairs up, elevator down')."""
    d = pd.concat([f, fr], axis=1)
    d = d[d["split"].isin(["discovery", "validation", "holdout"])].dropna(subset=["mom6", "fwd12"])
    out = {}
    # 1. speed: average absolute bar return on down bars vs up bars
    body = d["close"] - d["open"]
    out["avg_up_bar_atr"] = float((body[body > 0] / d["atr"][body > 0]).mean())
    out["avg_down_bar_atr"] = float((-body[body < 0] / d["atr"][body < 0]).mean())
    big = d["range_atr"] > 2
    out["share_big_bars_down"] = float((body[big] < 0).mean())
    # 2. continuation after strong moves, by side
    rows = []
    for thr in (2, 3, 4):
        for side, m in (("up", d["mom6"] > thr), ("down", d["mom6"] < -thr)):
            g = d[m]
            s = 1 if side == "up" else -1
            cont = g["fwd12"] * s
            drift = d["fwd12"].mean()
            rows.append({"threshold_atr": thr, "side": side, "n": len(g), "continuation_atr": float(cont.mean()),
                         "excess_continuation_atr": float(((g["fwd12"] - drift) * s).mean()),
                         "p_continue": float((cont > 0).mean()),
                         "fwd_adverse12": float((g["fwd_dn12"] if side == "up" else g["fwd_up12"]).mean()),
                         "fwd_favourable12": float((g["fwd_up12"] if side == "up" else g["fwd_dn12"]).mean())})
    out["after_strong_moves"] = rows
    # 3. exhaustion: after RSI extremes + extension, which side reverts more?
    rows = []
    for side, m in (("overbought", (d["rsi"] > 75) & (d["dist_ema20"] > 2.5)),
                    ("oversold", (d["rsi"] < 25) & (d["dist_ema20"] < -2.5))):
        g = d[m]
        rev = g["fwd12"] * (-1 if side == "overbought" else 1)
        rows.append({"state": side, "n": len(g), "reversion_atr": float(rev.mean()),
                     "p_revert": float((rev > 0).mean())})
    out["exhaustion"] = rows
    # 4. regime decomposition: share of time in each daily trend regime
    out["regime_share"] = d["regime_trend"].value_counts(normalize=True).round(3).to_dict()
    return out


def setup_side_profile(t: pd.DataFrame, splits=("discovery", "validation", "holdout")) -> pd.DataFrame:
    """Long vs short for every setup, with regime control."""
    d = t[t["split"].isin(splits)]
    rows = []
    for s, g in d.groupby("setup"):
        L, S = g[g["direction"] > 0], g[g["direction"] < 0]
        tt, p = welch(S["r"], L["r"])
        rows.append({"setup": s, "family": g["family"].iloc[0], "n_long": len(L), "n_short": len(S),
                     "avg_r_long": L["r"].mean(), "avg_r_short": S["r"].mean(),
                     "win_long": L["win"].mean(), "win_short": S["win"].mean(),
                     "mfe_long": L["mfe_r"].mean(), "mfe_short": S["mfe_r"].mean(),
                     "minutes_to_mfe_long": L["mfe_minutes"].median(), "minutes_to_mfe_short": S["mfe_minutes"].median(),
                     "short_minus_long": S["r"].mean() - L["r"].mean(), "p_value": p})
    return pd.DataFrame(rows).sort_values("short_minus_long", ascending=False)


def oaxaca(t: pd.DataFrame, group_col: str = "regime_trend") -> dict:
    """Decompose (short avgR - long avgR) into 'where they trade' vs 'how they do there'.

    composition effect = sum_g (wS_g - wL_g) * rL_g   (different regime mix)
    skill effect       = sum_g  wS_g * (rS_g - rL_g)  (better within the same regime)
    """
    L, S = t[t["direction"] > 0], t[t["direction"] < 0]
    wL = L[group_col].value_counts(normalize=True)
    wS = S[group_col].value_counts(normalize=True)
    rL = L.groupby(group_col)["r"].mean()
    rS = S.groupby(group_col)["r"].mean()
    groups = sorted(set(wL.index) | set(wS.index))
    comp = sum((wS.get(g, 0) - wL.get(g, 0)) * rL.get(g, 0) for g in groups)
    skill = sum(wS.get(g, 0) * (rS.get(g, 0) - rL.get(g, 0)) for g in groups)
    return {"total_gap": float(S["r"].mean() - L["r"].mean()), "composition_effect": float(comp),
            "within_regime_effect": float(skill),
            "by_regime": [{"regime": g, "w_long": float(wL.get(g, 0)), "w_short": float(wS.get(g, 0)),
                           "r_long": float(rL.get(g, np.nan)), "r_short": float(rS.get(g, np.nan))} for g in groups]}


def conventional_scoreboard(t: pd.DataFrame, cat_stats: pd.DataFrame) -> pd.DataFrame:
    """Each setup's conventional claim, tested before and after costs on every split."""
    from .setups import SETUPS
    rows = []
    for name, s in SETUPS.items():
        g = t[t["setup"] == name]
        row = {"setup": name, "claim": s.claim, "family": s.family}
        for sp in ("discovery", "validation", "holdout"):
            x = g[g["split"] == sp]
            row[f"gross_{sp}"] = x["r_gross"].mean()
            row[f"net_{sp}"] = x["r"].mean()
            row[f"n_{sp}"] = len(x)
        oos = g[g["split"].isin(["validation", "holdout"])]
        gross = summarise(oos["r_gross"].values)
        row["oos_gross_t"] = gross["t"]
        if gross["t"] > 2:
            row["verdict"] = "SUPPORTED before costs" + (" and after" if oos["r"].mean() > 0 else ", but costs erase it")
        elif gross["t"] < -2:
            row["verdict"] = "CONTRADICTED: the opposite tends to happen"
        else:
            row["verdict"] = "No evidence (coin-flip before costs)"
        rows.append(row)
    return pd.DataFrame(rows)


def event_paths(f: pd.DataFrame, t: pd.DataFrame, pre: int = 24, post: int = 48,
                splits=("discovery", "validation", "holdout")) -> dict:
    """Average trade-relative price path (in ATR at decision) around every setup trigger.

    k < 0 shows what led INTO the setup; k > 0 what followed. Winners/losers are split
    by the trade outcome purely for description.
    """
    c = f["close"].values
    a = f["atr"].values
    n = len(c)
    ks = np.arange(-pre, post + 1)
    out = {"k": ks.tolist(), "paths": {}}
    d = t[t["split"].isin(splits)]
    for (s, dr), g in d.groupby(["setup", "direction"]):
        idx = g["idx"].values
        idx = idx[(idx >= pre) & (idx < n - post)]
        if len(idx) < 30:
            continue
        M = (c[idx[:, None] + ks[None, :]] - c[idx][:, None]) * dr / a[idx][:, None]
        win = g.set_index("idx").loc[idx, "win"].values.astype(bool) if g["idx"].is_unique else None
        rec = {"n": int(len(idx)), "mean": np.round(M.mean(0), 3).tolist(),
               "q25": np.round(np.percentile(M, 25, 0), 3).tolist(),
               "q75": np.round(np.percentile(M, 75, 0), 3).tolist()}
        if win is not None and win.any() and (~win).any():
            rec["win"] = np.round(M[win].mean(0), 3).tolist()
            rec["loss"] = np.round(M[~win].mean(0), 3).tolist()
        # where is the average path at +12h relative to drift? (does the setup's idea play out?)
        rec["fwd12"] = float(M[:, pre + 12].mean())
        rec["fwd48"] = float(M[:, pre + 48].mean())
        out["paths"][f"{s}|{int(dr)}"] = rec
    # unconditional drift benchmark (trade-relative for longs; shorts are its negative)
    sample = np.arange(pre, n - post, 7)
    M = (c[sample[:, None] + ks[None, :]] - c[sample][:, None]) / a[sample][:, None]
    out["drift_long"] = np.round(M.mean(0), 3).tolist()
    return out
