"""Check the live Ether inside-day code against the round 16 research.

Replays every closed hour of Ether through signals.ib_step with the live market
config, and compares the closed trades with research/round16_eth_checks.py's
realistic version (24/7 data, weekday signals). Costs are set to zero on both
sides so the trades must match exactly: same setup day, side, entry and exit.
Then reports the live code's figures at the configured cost.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import signals as S  # noqa: E402
import round10_btc_checks as B  # noqa: E402
import round10_markets as R10  # noqa: E402
import round16_eth_checks as E  # noqa: E402


def live_trades(cfg, bars):
    F = S.Features(bars, cfg)
    st, out = {}, []
    for i in range(len(bars)):
        if not F.warm(i):
            continue
        for e in S.ib_step(F, i, st, cfg):
            if e["type"] in ("ib_stop", "ib_close"):
                out.append({"sig": e["idea"]["sig_time"], "d": e["idea"]["dir"], "r": e["r"],
                            "strategy": e["idea"]["strategy"]})
    return out


def main():
    bars = B.load_247(E.ETH)
    cfg = S.market_cfg("eth")
    live0 = live_trades(dict(cfg, cost_per_trade=0.0), bars)
    lab = B.make_lab(bars, R10.gold_median_atr())
    res0 = [t for t in R10.run_insideday(lab, 0) if t["t"].weekday() < 5]
    a = {(t["sig"][:16], t["d"]): round(t["r"], 4) for t in live0}
    b = {(t["t"].isoformat()[:16], t["d"]): round(t["r"], 4) for t in res0}
    common = set(a) & set(b)
    same_r = sum(abs(a[k] - b[k]) < 1e-3 for k in common)
    print(f"live {len(a)} trades, research {len(b)}, same setup and side {len(common)}, same R {same_r}")
    for k in sorted(set(a) ^ set(b))[:10]:
        print("  only in", "live" if k in a else "research", k)
    live = live_trades(cfg, bars)
    n = len(live)
    win = 100 * sum(t["r"] > 0 for t in live) / n
    avg = sum(t["r"] for t in live) / n
    print(f"live code at ${cfg['cost_per_trade']} a trade: n={n} win={win:.0f}% avg {avg:+.3f}R, "
          f"strategy {live[0]['strategy']}")


if __name__ == "__main__":
    main()
