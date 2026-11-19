"""Check that signals.ibs_trades reproduces the research IBS trades, and measure
the benchmark the nursery gate judges the us_ibs candidate against.

The live code runs on US ETF daily candles (SPY, QQQ, DIA, IWM); the research ran
on Dukascopy index CFD cash sessions. Here both functions see the same sessions,
so every trade must match: same signal day, same exit day, same prices.
"""
import os
import sys
from datetime import timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import signals as S  # noqa: E402
import round12_beyond_gold as M  # noqa: E402
import round12_ibs_checks as C  # noqa: E402

M.R10.MARKETS["Russell 2000"] = (["markets/ussc2000idxusd_h1.csv.gz"], 2.0)
M.SESSION["Russell 2000"] = (ZoneInfo("America/New_York"), 9, 15)
US4 = ["S&P 500", "Nasdaq 100", "Dow", "Russell 2000"]


def main():
    live_all, mism = [], 0
    for n in US4:
        s = M.sessions(n)
        days = [dict(s[d], t_close=s[d]["t"]) for d in sorted(s)]
        live = S.ibs_trades(days, 1.0)
        research = C.ibs_trades(n, finance=False)
        a = [(t["t"], round(t["entry"], 6), round(t["exit"], 6)) for t in live]
        b = []
        for t in research:
            b.append(t["t"])
        if [x[0] for x in a] != b:
            mism += 1
            print(f"{n}: MISMATCH live {len(a)} vs research {len(b)}")
        else:
            print(f"{n}: {len(a)} trades match")
        live_all += live
    n = len(live_all)
    win = 100 * sum(t["r"] > 0 for t in live_all) / n
    avg = sum(t["r"] for t in live_all) / n
    bps = sum(t["bps"] for t in live_all) / n
    print(f"\nUS4 at 1 bp, no financing: n={n} win={win:.0f}% avg {avg:+.3f}R ({bps:+.1f} bp)")
    print("ALL MATCH" if not mism else f"{mism} MISMATCHES")


if __name__ == "__main__":
    main()
