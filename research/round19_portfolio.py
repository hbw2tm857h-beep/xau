"""Round 19: the five alerted strategies as one portfolio (19 Nov 2026).

Not a search for new rules. Nothing here changes a strategy or adds to the
multiple-testing count. It measures what the strategies found in rounds 1-16
are worth together, which is the lever the maths points to once per-trade
edges are fixed: Sharpe_total ~ sqrt(sum of Sharpe^2) for uncorrelated streams.

Streams, every trade from the live code replaying history (research/
similar_setups.py), results in R, booked in the month the trade closed:
  gold trend, gold inside-day, Bitcoin trend, Ether inside-day, US IBS
  (US IBS has no stop; its 1R is the 25-day average daily range, the unit
  the bot journals it in).

Common window: the months in which all five can trade (Ether starts the
latest). Sizing assumption for every stream: 1R = 1% of the account.

Reported:
  - each stream's monthly mean, volatility, annualised Sharpe, worst drawdown
  - the monthly correlation matrix
  - portfolios: gold only (today's live set), all five at equal 1% risk,
    inverse-volatility (risk parity) weights, and mean-variance weights
    (proportional to inverse(covariance) x mean, long only)
  - the uncorrelated approximation sqrt(sum Sharpe^2), as a check

Mean-variance weights are fitted on the same history they are judged on, so
they flatter themselves; equal-risk and risk-parity weights use no return
information and are the honest comparison. A split-half check refits the
mean-variance weights on the first half and judges them on the second.
"""
import os
import statistics as st
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import round10_btc_checks as B  # noqa: E402
import round12_beyond_gold as M  # noqa: E402
import similar_setups as SS  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

UTC = timezone.utc


def monthly(trades):
    """trades: list of (exit datetime, r) -> {(y, m): sum r}"""
    out = {}
    for t, r in trades:
        k = (t.year, t.month)
        out[k] = out.get(k, 0.0) + r
    return out


def streams():
    now = datetime.now(UTC)
    jg = SS.replay(S.CONFIG, S.closed_h1(S.load_history(S.CONFIG), now))
    jb = SS.replay(S.market_cfg("btc"), B.load_247(os.path.join(ROOT, "data", "markets", "btcusd_h1.csv.gz")), scale=True)
    je = SS.replay(S.market_cfg("eth"), B.load_247(os.path.join(ROOT, "data", "markets", "ethusd_h1.csv.gz")), scale=True)
    pick = lambda j, name: [(datetime.fromisoformat(x["exit_time"]), x["r"]) for x in j if x.get("strategy", "trend") == name]
    M.R10.MARKETS["Russell 2000"] = (["markets/ussc2000idxusd_h1.csv.gz"], 2.0)
    M.SESSION["Russell 2000"] = (ZoneInfo("America/New_York"), 9, 15)
    ibs = []
    for name in ("S&P 500", "Nasdaq 100", "Dow", "Russell 2000"):
        s = M.sessions(name)
        days = [dict(s[d], t_close=s[d]["t"]) for d in sorted(s)]
        ibs += [(t["t_exit"], t["r"]) for t in S.ibs_trades(days, S.CONFIG["ibs"]["cost_bps"])]
    return {
        "Gold trend": pick(jg, "trend"),
        "Gold inside-day": pick(jg, "inside_day"),
        "Bitcoin trend": pick(jb, "btc_trend"),
        "Ether inside-day": pick(je, "eth_inside_day"),
        "US IBS": ibs,
    }


def stats(x):
    x = np.asarray(x)
    eq = np.cumsum(x)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0], eq])) - np.concatenate([[0], eq])))
    sr = float(x.mean() / x.std(ddof=1) * np.sqrt(12)) if x.std(ddof=1) > 0 else 0.0
    return {"mean": float(x.mean()), "vol": float(x.std(ddof=1)), "sharpe": sr, "total": float(x.sum()), "maxdd": dd}


def mv_weights(X):
    mu, cov = X.mean(axis=0), np.cov(X, rowvar=False)
    w = np.linalg.solve(cov, mu)
    for _ in range(len(mu)):                  # long only: drop negatives and refit the rest
        if (w >= 0).all():
            break
        keep = w > 0
        w = np.zeros_like(mu)
        w[keep] = np.linalg.solve(cov[np.ix_(keep, keep)], mu[keep])
    return w / w.sum() * len(mu)              # scaled so the average weight is 1 (1% risk)


def show(label, x, months):
    s = stats(x)
    print(f"  {label:36s} {s['mean']:+.2f}R/mo  vol {s['vol']:.2f}  Sharpe {s['sharpe']:.2f}  "
          f"total {s['total']:+.0f}R  worst drop {s['maxdd']:.1f}R  over {months} months")
    return s


def main():
    raw = {k: monthly(v) for k, v in streams().items()}
    names = list(raw)
    starts = {k: min(v) for k, v in raw.items()}
    first = max(starts.values())
    last = min(max(v) for v in raw.values())
    months = []
    y, m = first
    while (y, m) <= last:
        months.append((y, m)); y, m = (y + (m == 12), m % 12 + 1)
    X = np.array([[raw[k].get(mm, 0.0) for k in names] for mm in months])
    print(f"Common window {first[0]}-{first[1]:02d} to {last[0]}-{last[1]:02d}: {len(months)} months "
          f"(each stream's own start: " + ", ".join(f"{k} {v[0]}" for k, v in starts.items()) + ")\n")

    print("Each stream, 1R = 1% risk")
    srs = []
    for i, k in enumerate(names):
        srs.append(show(k, X[:, i], len(months))["sharpe"])

    print("\nMonthly correlation")
    C = np.corrcoef(X, rowvar=False)
    print("  " + " " * 18 + "".join(f"{k[:10]:>11s}" for k in names))
    for i, k in enumerate(names):
        print(f"  {k:18s}" + "".join(f"{C[i, j]:+11.2f}" for j in range(len(names))))

    print("\nPortfolios")
    gold = X[:, 0] + 0.5 * X[:, 1]
    show("Gold only (trend 1%, inside-day 0.5%)", gold, len(months))
    show("All five, 1% each", X.sum(axis=1), len(months))
    inv = 1 / X.std(axis=0, ddof=1)
    w_rp = inv / inv.sum() * len(names)
    show("All five, risk parity", X @ w_rp, len(months))
    w_mv = mv_weights(X)
    show("All five, mean-variance (in-sample)", X @ w_mv, len(months))
    print(f"  sqrt(sum Sharpe^2), if uncorrelated: {np.sqrt(np.sum(np.square(np.clip(srs, 0, None)))):.2f}")
    print("  weights (risk %):  " + "  ".join(f"{k} rp {a:.2f} / mv {b:.2f}" for k, a, b in zip(names, w_rp, w_mv)))

    print("\nSplit-half check: weights fitted on the first half, judged on the second")
    h = len(months) // 2
    w1 = mv_weights(X[:h])
    inv1 = 1 / X[:h].std(axis=0, ddof=1); rp1 = inv1 / inv1.sum() * len(names)
    for label, x in (("gold only", X[h:, 0] + 0.5 * X[h:, 1]), ("equal 1%", X[h:].sum(axis=1)),
                     ("risk parity (first-half vols)", X[h:] @ rp1), ("mean-variance (first-half fit)", X[h:] @ w1)):
        show(label, x, len(months) - h)


if __name__ == "__main__":
    main()
