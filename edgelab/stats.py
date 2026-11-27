"""Performance statistics and multiple-testing corrections."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats as st


def max_drawdown(r: np.ndarray) -> float:
    """Largest peak-to-trough fall of the cumulative R curve (positive number, in R)."""
    if len(r) == 0:
        return 0.0
    eq = np.concatenate([[0.0], np.cumsum(r)])
    return float(np.max(np.maximum.accumulate(eq) - eq))


def summarise(r, times=None) -> dict:
    r = np.asarray(r, float)
    r = r[~np.isnan(r)]
    n = len(r)
    if n == 0:
        return {"n": 0, "win": np.nan, "avg_r": np.nan, "ev": np.nan, "pf": np.nan, "max_dd": 0.0,
                "total_r": 0.0, "sharpe": np.nan, "t": np.nan, "p": np.nan, "ci_lo": np.nan, "ci_hi": np.nan}
    wins, losses = r[r > 0], r[r <= 0]
    sd = r.std(ddof=1) if n > 1 else np.nan
    t = r.mean() / (sd / math.sqrt(n)) if n > 1 and sd > 0 else np.nan
    p = 1 - st.t.cdf(t, n - 1) if not np.isnan(t) else np.nan        # one-sided: mean > 0
    half = 1.96 * sd / math.sqrt(n) if n > 1 else np.nan
    return {
        "n": n, "win": float((r > 0).mean()), "avg_r": float(r.mean()),
        "ev": float(r.mean()),                                         # EV per trade in R, after costs
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "pf": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else np.inf,
        "max_dd": max_drawdown(r), "total_r": float(r.sum()),
        "sharpe": float(r.mean() / sd) if n > 1 and sd > 0 else np.nan,   # per-trade
        "t": float(t), "p": float(p), "ci_lo": float(r.mean() - half), "ci_hi": float(r.mean() + half),
    }


def bootstrap_ci(r, n_boot: int = 2000, seed: int = 0, block: int = 1) -> tuple[float, float]:
    """Percentile CI of the mean; block>1 uses a moving-block bootstrap (serial correlation)."""
    r = np.asarray(r, float)
    n = len(r)
    if n < 5:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    if block <= 1:
        means = rng.choice(r, (n_boot, n)).mean(axis=1)
    else:
        nb = int(math.ceil(n / block))
        starts = rng.integers(0, n - block + 1, (n_boot, nb))
        idx = (starts[:, :, None] + np.arange(block)).reshape(n_boot, -1)[:, :n]
        means = r[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def mc_drawdown(r, n_sims: int = 2000, seed: int = 0, q: float = 0.95) -> float:
    """95th percentile max drawdown over random re-orderings of the same trades."""
    r = np.asarray(r, float)
    if len(r) < 5:
        return np.nan
    rng = np.random.default_rng(seed)
    dds = [max_drawdown(rng.permutation(r)) for _ in range(n_sims)]
    return float(np.quantile(dds, q))


def benjamini_hochberg(p: np.ndarray) -> np.ndarray:
    """BH q-values (FDR) for an array of p-values (NaN-safe)."""
    p = np.asarray(p, float)
    q = np.full_like(p, np.nan)
    ok = ~np.isnan(p)
    pv = p[ok]
    m = len(pv)
    if m == 0:
        return q
    order = np.argsort(pv)
    ranked = pv[order] * m / (np.arange(m) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.clip(ranked, 0, 1)
    q[ok] = out
    return q


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """E[max SR] among n_trials independent zero-skill strategies (Bailey & Lopez de Prado)."""
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    g = 0.5772156649
    z1 = st.norm.ppf(1 - 1.0 / n_trials)
    z2 = st.norm.ppf(1 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_sr) * ((1 - g) * z1 + g * z2)


def deflated_sharpe(r, n_trials: int, var_sr_trials: float) -> float:
    """Probability that the true per-trade Sharpe > the best expected under pure luck.

    Accounts for the number of hypotheses tried, sample length, skew and kurtosis.
    """
    r = np.asarray(r, float)
    n = len(r)
    if n < 10:
        return np.nan
    sd = r.std(ddof=1)
    if sd == 0:
        return np.nan
    sr = r.mean() / sd
    sk = st.skew(r)
    ku = st.kurtosis(r, fisher=False)
    sr0 = expected_max_sharpe(n_trials, var_sr_trials)
    denom = math.sqrt(max(1e-12, 1 - sk * sr + (ku - 1) / 4 * sr ** 2))
    return float(st.norm.cdf((sr - sr0) * math.sqrt(n - 1) / denom))


def permutation_pvalue(r_in: np.ndarray, r_all: np.ndarray, n_perm: int = 2000, seed: int = 0) -> float:
    """P(random subset of the same size from the base population has mean >= observed)."""
    r_in, r_all = np.asarray(r_in, float), np.asarray(r_all, float)
    k = len(r_in)
    if k == 0 or k >= len(r_all):
        return np.nan
    rng = np.random.default_rng(seed)
    obs = r_in.mean()
    sims = np.array([rng.choice(r_all, k, replace=False).mean() for _ in range(n_perm)])
    return float((np.sum(sims >= obs) + 1) / (n_perm + 1))


def welch(a, b) -> tuple[float, float]:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or len(b) < 3:
        return np.nan, np.nan
    t, p = st.ttest_ind(a, b, equal_var=False)
    return float(t), float(p)


def cohens_d(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return np.nan
    s = math.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
    return float((a.mean() - b.mean()) / s) if s > 0 else np.nan


def by_group(df: pd.DataFrame, key, rcol: str = "r") -> pd.DataFrame:
    rows = []
    for k, g in df.groupby(key, observed=True):
        s = summarise(g[rcol].values)
        s["group"] = k
        rows.append(s)
    return pd.DataFrame(rows)


def jsonable(x):
    """Recursively convert numpy / pandas objects so json.dumps works."""
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if (np.isnan(x) or np.isinf(x)) else round(float(x), 5)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(x))
    return x
