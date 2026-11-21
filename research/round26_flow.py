"""Round 26: free order-flow proxies as filters on the live trend setups.

Spot gold has no central volume or order book, so true order flow needs paid
CME futures tick data. Before paying for that, two free proxies are tested:

  CFTC Commitments of Traders (data/macro/cot_gold_mm_oi.csv: long, short and open
  interest from the CFTC open-data API, publicreporting.cftc.gov, which accepts scripts): weekly
  managed-money (hedge fund) positions in COMEX gold. A report is dated
  Tuesday and released Friday; it is used only from the following Monday
  00:00 UTC, so nothing is seen before it was public.
  Dukascopy traded volume (data/volume/xauusd_h1_vol.csv.gz, from round 18): one venue's
  volume per hourly candle - a proxy for participation, not the whole market.

PRE-REGISTERED (fixed before any result was seen), each tested alone:
  C1 COT flow       managed-money net position rose (buys) / fell (sells) in
                    the latest report vs the one before
  C2 COT crowding   skip buys when managed-money net / open interest is in the
                    top 10% of the last 156 reports (3 years); skip sells in the
                    bottom 10%
  C3 COT trend      managed-money net position is long (buys) / short (sells)
  V1 Volume         the signal candle's volume is above the average of the
                    previous 20 candles
  V2 Session VWAP   the signal candle closes above the trading day's VWAP
                    (17:00 New York roll, typical price x volume) for buys,
                    below for sells

Adoption, as round 5, with Bonferroni for 5 tests:
  1. better average R than the live rules by > 0.02 in BOTH 2016-22 and
     2023-24, keeping at least 60% of the 2016-22 trades
  2. also better in 2008-15 and 2025-26
  3. over 2008-26 total R must not fall, and dropping the same number of live
     trades at random matches the gain in < 1% of 10,000 tries (0.05 / 5)
A pass becomes a nursery candidate, never a live change on backtest alone.
"""
import bisect
import csv
import gzip
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import round5 as R5  # noqa: E402  (registers the "pred" family)
import signals as S  # noqa: E402

UTC = timezone.utc
DATA = os.path.join(HERE, "..", "data")
D = R5.D
ALPHA = 0.05 / 5


def load_cot():
    rows = []
    with open(os.path.join(DATA, "macro", "cot_gold_mm_oi.csv")) as f:
        for r in csv.DictReader(f):
            d = datetime.strptime(r["report_date"], "%Y-%m-%d").replace(tzinfo=UTC)
            net = int(r["mm_long"]) - int(r["mm_short"])
            rows.append({"avail": d + timedelta(days=6), "net": net, "ratio": net / int(r["open_interest"])})
    for k, r in enumerate(rows):
        r["chg"] = r["net"] - rows[k - 1]["net"] if k else 0
        win = [x["ratio"] for x in rows[max(0, k - 155):k + 1]]
        r["pct"] = 100.0 * sum(1 for v in win if v <= r["ratio"]) / len(win) if len(win) >= 52 else None
    return rows


def load_volume():
    out = {}
    with gzip.open(os.path.join(DATA, "volume", "xauusd_h1_vol.csv.gz"), "rt") as f:
        for r in csv.DictReader(f):
            out[datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)] = float(r["volume"])
    return out


def make_tests(ds, cot, vol):
    lab = ds.lab
    b = lab.b
    avail = [r["avail"] for r in cot]

    def report(i):
        k = bisect.bisect_right(avail, b[i]["t"] + S.H1) - 1
        return cot[k] if k >= 1 else None

    v = [vol.get(x["t"]) for x in b]

    def vol_up(i):
        if v[i] is None or i < 20:
            return False
        prev = [x for x in v[i - 20:i] if x is not None]
        return len(prev) >= 15 and v[i] > sum(prev) / len(prev)

    vwap, num, den, day = [None] * len(b), 0.0, 0.0, None   # session VWAP up to and incl. bar i
    for i, x in enumerate(b):
        k = S.trading_day(x["t"])
        if k != day:
            day, num, den = k, 0.0, 0.0
        if v[i]:
            num += (x["h"] + x["l"] + x["c"]) / 3 * v[i]; den += v[i]
        vwap[i] = num / den if den else None

    def c2(i, d):
        r = report(i)
        if not r or r["pct"] is None:
            return True
        return not ((d == 1 and r["pct"] >= 90) or (d == -1 and r["pct"] <= 10))

    return [
        ("C1 COT flow agrees", lambda i, d: bool(report(i)) and report(i)["chg"] * d > 0),
        ("C2 COT not crowded", c2),
        ("C3 COT net position agrees", lambda i, d: bool(report(i)) and report(i)["net"] * d > 0),
        ("V1 Signal candle volume above average", lambda i, d: vol_up(i)),
        ("V2 Right side of session VWAP", lambda i, d: vwap[i] is not None and (b[i]["c"] - vwap[i]) * d > 0),
    ]


def main():
    cot, vol = load_cot(), load_volume()
    sets = {"new": R5.Dataset(os.path.join(DATA, "xauusd_h1.csv")),
            "old": R5.Dataset(os.path.join(DATA, "xauusd_h1_2008_2015.csv"))}
    tests = {k: make_tests(ds, cot, vol) for k, ds in sets.items()}

    def run(k, pred=None):
        lab = sets[k].lab
        if pred is None:
            return L.backtest(lab, "ha", R5.BASE_P, R5.M)
        return L.backtest(lab, "pred", {"pred": pred}, R5.M)

    base = {k: run(k) for k in sets}
    bstat = {pk: R5.period_stats(base[src], a, b) for pk, (src, a, b) in R5.PERIODS.items()}
    base_all = [t["r"] for t in base["old"] if t["t"] < D(2016)] + [t["r"] for t in base["new"]]
    print("Live rules: " + " | ".join(f"{pk} {s['avg']:+.3f} (n={s['n']})" for pk, s in bstat.items())
          + f" | 2008-26 n={len(base_all)} total {sum(base_all):+.1f}R")
    rows = []
    for idx, (name, _) in enumerate(tests["new"]):
        tr = {k: run(k, tests[k][idx][1]) for k in sets}
        st_ = {pk: R5.period_stats(tr[src], a, b) for pk, (src, a, b) in R5.PERIODS.items()}
        d = {pk: st_[pk].get("avg", -9) - bstat[pk]["avg"] for pk in st_}
        s1 = d["tune"] > 0.02 and d["val"] > 0.02 and st_["tune"].get("n", 0) >= 0.6 * bstat["tune"]["n"]
        s2 = s1 and d["2008-15"] > 0 and d["2025-26"] > 0
        allr = [t["r"] for t in tr["old"] if t["t"] < D(2016)] + [t["r"] for t in tr["new"]]
        p = None
        if s2:
            gain = sum(allr) / len(allr) - sum(base_all) / len(base_all)
            p = R5.perm_p(base_all, min(len(allr), len(base_all)), gain)
        s3 = s2 and sum(allr) >= sum(base_all) and p is not None and p < ALPHA
        verdict = "PASS" if s3 else ("stage 3 fail" if s2 else ("stage 2 fail" if s1 else "no"))
        rows.append({"test": name, **{f"{pk}_R": round(s.get("avg", 0), 3) for pk, s in st_.items()},
                     **{f"{pk}_n": s.get("n", 0) for pk, s in st_.items()},
                     "all_n": len(allr), "all_total": round(sum(allr), 1), "perm_p": p, "verdict": verdict})
        print(f"{name:40s} " + " ".join(f"{pk} {s.get('avg', 0):+.3f}({d[pk]:+.3f})" for pk, s in st_.items())
              + f" | kept {st_['tune'].get('n', 0)}/{bstat['tune']['n']} | all n={len(allr)} {sum(allr):+.1f}R"
              + (f" | p={p}" if p is not None else "") + f" | {verdict}", flush=True)
    with open(os.path.join(HERE, "results_round26_flow.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
