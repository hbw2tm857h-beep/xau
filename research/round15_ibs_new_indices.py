"""Round 15: IBS band reversion on ten stock indices it has never seen (pre-registered
19 Nov 2026, before the data below was opened).

Round 12's one pass, IBS band reversion (M8), was found on six indices. Fourteen
other tests in rounds 12-14 failed, so 1 of 22 passing could still be luck. The
cleanest check is new markets: ten more stock indices downloaded from Dukascopy
for this test and never used by any earlier round. CAC 40, SMI and South Africa 40
were also requested, but the downloader fails on them.

Rule: exactly round 12's M8, unchanged. Daily cash-session candles built from
hourly bars between the first and last local hours below. Long at the session
close when close < 10-day highest high - 2.5 x 25-day average range and IBS < 0.3;
out at the first close above the previous session's high. No stop.

  Index            id               zone              bars    cost (bp)
  Russell 2000     ussc2000idxusd   America/New_York  9-15    2.0
  Euro Stoxx 50    eusidxeur        Europe/Berlin     9-16    1.5
  IBEX 35          espidxeur        Europe/Madrid     9-16    2.0
  AEX              nldidxeur        Europe/Amsterdam  9-16    2.0
  FTSE MIB         itaidxeur        Europe/Rome       9-16    2.0
  ASX 200          ausidxaud        Australia/Sydney  10-15   2.0
  Hang Seng        hkgidxhkd        Asia/Hong_Kong    10-15   2.0
  China A50        chiidxusd        Asia/Shanghai     10-14   3.0
  Singapore        sgdidxsgd        Asia/Singapore    9-16    3.0
  WIG 20           plnidxpln        Europe/Warsaw     9-16    3.0

Financing as round 12: (US policy rate + 2.5%)/365 a night, used for every
index as a single approximation.

This is ONE confirmatory test of an already-selected rule, so the bar is a plain
one-sided p < 0.05 on the pooled trades, with 150+ trades and a positive average
in every period with 10+ trades. Per-index results are reported but not judged.
"""
import csv
import os
import statistics as st
import sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import round10_markets as R10  # noqa: E402
import round12_beyond_gold as M  # noqa: E402
import round12_ibs_checks as C  # noqa: E402

NEW = {
    "Russell 2000": ("ussc2000idxusd", "America/New_York", 9, 15, 2.0),
    "Euro Stoxx 50": ("eusidxeur", "Europe/Berlin", 9, 16, 1.5),
    "IBEX 35": ("espidxeur", "Europe/Madrid", 9, 16, 2.0),
    "AEX": ("nldidxeur", "Europe/Amsterdam", 9, 16, 2.0),
    "FTSE MIB": ("itaidxeur", "Europe/Rome", 9, 16, 2.0),
    "ASX 200": ("ausidxaud", "Australia/Sydney", 10, 15, 2.0),
    "Hang Seng": ("hkgidxhkd", "Asia/Hong_Kong", 10, 15, 2.0),
    "China A50": ("chiidxusd", "Asia/Shanghai", 10, 14, 3.0),
    "Singapore": ("sgdidxsgd", "Asia/Singapore", 9, 16, 3.0),
    "WIG 20": ("plnidxpln", "Europe/Warsaw", 9, 16, 3.0),
}
M.ALPHA = 0.05

for name, (iid, zone, h0, h1, cost) in NEW.items():
    R10.MARKETS[name] = ([f"markets/{iid}_h1.csv.gz"], cost)
    M.SESSION[name] = (ZoneInfo(zone), h0, h1)


def main():
    trades = [t for n in NEW for t in C.ibs_trades(n)]
    s = C.summary("Ten new indices, pooled", trades)
    print("   PASS" if s["ok"] else "   fail")
    rows = []
    for n in NEW:
        x = [t for t in trades if t["idx"] == n]
        if not x:
            print(f"   {n}: no trades"); continue
        si = M.judge(sorted(x, key=lambda t: t["t"]))
        first = min(t["t"] for t in x)
        print(f"   {n:14s} from {first:%Y-%m} n={si['n']:4d} win={si['win']:4.1f}% net={si['avg']:+7.2f}bp p={si.get('p', 1):.2g}")
        rows.append({"index": n, "n": si["n"], "win": round(si["win"], 1), "avg_bps_net": round(si["avg"], 2),
                     "p": f"{si.get('p', 1):.2g}"})
    rows.append({"index": "POOLED", "n": s["n"], "win": round(s["win"], 1), "avg_bps_net": round(s["avg"], 2),
                 "p": f"{s['p']:.2g}"})
    print("\nRandom entries, same holds (300 runs)")
    saved = dict(M.SESSION)
    for k in list(M.SESSION):
        if k not in NEW:
            del M.SESSION[k]
    means = C.random_control(trades)
    M.SESSION.clear(); M.SESSION.update(saved)
    mu = st.mean(t["bps"] for t in trades)
    print(f"   real {mu:+.2f}bp | random mean {st.mean(means):+.2f}bp | {sum(m >= mu for m in means)} of 300 reached it")
    with open(os.path.join(HERE, "results_round15_ibs_new_indices.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
