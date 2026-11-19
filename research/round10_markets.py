"""Round 10: do the three gold strategies work on other markets?

The bot only trades gold, so it averages about one trend setup and 0.7
inside-day setups a week. More markets would mean more signals, but only if the
edge carries over. Round 3 already showed the hourly trend rules fail on silver
and the four FX majors. Nobody has tested the inside-day breakout or the 4-hour
trigger (round 9, E2) anywhere but gold.

This is the cleanest test left in the project: none of these rules was ever
tuned on any of these markets, so every result is out of sample for the rules.

PRE-REGISTERED (fixed before any result was seen)
-------------------------------------------------
Strategies, exactly as live on gold, nothing re-tuned:
  trend      the hourly Heikin Ashi rules incl. the 4H cloud (signals.evaluate)
  insideday  inside-day breakout, close at the next daily close (round 5)
  h4         the 4-hour trigger (signals.h4_setup, round 9 E2)

Markets (21 + gold as the reference), Dukascopy H1 bid candles 2008-now:
  FX        EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD
            EURJPY GBPJPY EURGBP AUDJPY
  Metals    XAGUSD
  Energy    WTI, Brent
  Indices   S&P 500, Nasdaq 100, Dow, DAX, FTSE 100, Nikkei 225
  Crypto    BTCUSD
  Left out: gold priced in other currencies (XAU/EUR etc.) - it is the same
  trade as XAUUSD, so it adds correlated signals, not new ones.

Fair comparison:
  - Costs are a share of price (round trip, typical retail ECN), so they stay
    right as prices move over 18 years: see MARKETS. Gold's $0.35 on $2,000 is
    1.75 basis points.
  - The three dollar buffers in the gold config ($0.30 entry, 4H entry and 4H
    stop buffers) are scaled by the market's median H1 ATR / gold's.
  - Days roll at 17:00 New York and candles outside gold's trading hours are
    dropped, for every market.

Pass mark, for each market x strategy (63 tests):
  - at least 150 trades and an average of at least +0.05R after costs
  - a positive average in every period with 10+ trades (2008-15, 2016-22,
    2023-24, 2025-26), and at least three such periods
  - one-sided p < 0.05 / 63 = 0.0008 that the average is above zero
A pass earns a nursery candidate slot (silent tracking) and nothing more,
the same policy as round 9.
"""
import collections
import csv
import gzip
import math
import os
import statistics as st
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import round5_standalone as R5  # noqa: E402
import round9_entries as R9  # noqa: E402
import signals as S  # noqa: E402

UTC = timezone.utc
DATA = os.path.join(HERE, "..", "data")
D = lambda y: datetime(y, 1, 1, tzinfo=UTC)
PERIODS = [("2008-15", D(2008), D(2016)), ("2016-22", D(2016), D(2023)),
           ("2023-24", D(2023), D(2025)), ("2025-26", D(2025), D(2030))]
BASE_P = {"session": False, "h4": True, "breakout": False, "swing": 5}
MG = {"part_r": 1.0, "part_frac": 0.5, "target_r": 2.0}
N_TESTS = 63
ALPHA = 0.05 / N_TESTS

# name: (files, round-trip cost in basis points of price)
MARKETS = {
    "XAUUSD (reference)": (["xauusd_h1_2008_2015.csv", "xauusd_h1.csv"], 1.75),
    "EURUSD": (["eurusd_h1.csv"], 1.0),
    "GBPUSD": (["gbpusd_h1.csv"], 1.2),
    "USDJPY": (["usdjpy_h1.csv"], 1.0),
    "AUDUSD": (["audusd_h1.csv"], 1.5),
    "USDCAD": (["markets/usdcad_h1.csv.gz"], 1.5),
    "USDCHF": (["markets/usdchf_h1.csv.gz"], 1.5),
    "NZDUSD": (["markets/nzdusd_h1.csv.gz"], 2.0),
    "EURJPY": (["markets/eurjpy_h1.csv.gz"], 1.5),
    "GBPJPY": (["markets/gbpjpy_h1.csv.gz"], 2.5),
    "EURGBP": (["markets/eurgbp_h1.csv.gz"], 1.5),
    "AUDJPY": (["markets/audjpy_h1.csv.gz"], 2.0),
    "XAGUSD": (["xagusd_h1.csv"], 10.0),
    "WTI oil": (["markets/lightcmdusd_h1.csv.gz"], 5.0),
    "Brent oil": (["markets/brentcmdusd_h1.csv.gz"], 5.0),
    "S&P 500": (["markets/usa500idxusd_h1.csv.gz"], 1.0),
    "Nasdaq 100": (["markets/usatechidxusd_h1.csv.gz"], 1.0),
    "Dow": (["markets/usa30idxusd_h1.csv.gz"], 1.0),
    "DAX": (["markets/deuidxeur_h1.csv.gz"], 1.0),
    "FTSE 100": (["markets/gbridxgbp_h1.csv.gz"], 1.5),
    "Nikkei 225": (["markets/jpnidxjpy_h1.csv.gz"], 2.0),
    "BTCUSD": (["markets/btcusd_h1.csv.gz"], 5.0),
}


def load(path):
    """Same filtering as lab.load, for plain or gzipped files."""
    op = gzip.open if path.endswith(".gz") else open
    bars = []
    with op(path, "rt") as f:
        for r in csv.DictReader(f):
            t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            if not S.market_open(t):
                continue
            o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            if h - l <= 0 and o == c:
                continue
            bars.append({"t": t, "o": o, "h": h, "l": l, "c": c})
    return bars


def median_atr(lab):
    return st.median(x for x in lab.F.hatr if x)


def run_orders(lab, gen, bps):
    """One trade at a time; cost = bps of the entry price, charged per trade."""
    trades, busy_until = [], -1
    for sig in gen:
        i, d, entry, stop, expiry = sig[:5]
        cof = sig[5] if len(sig) > 5 else False
        if i <= busy_until:
            continue
        fi = L.fill(lab, i, d, entry, expiry, cof)
        if fi is None:
            continue
        L.COST = bps * 1e-4 * entry
        res = L.manage(lab, fi, d, entry, stop, MG)
        if res is None:
            continue
        r, _held, xi = res
        busy_until = xi
        trades.append({"t": lab.b[i]["t"], "d": d, "r": r})
    return trades


def run_insideday(lab, bps):
    orig = R5.rec

    def rec(trades, t, d, entry, exit_, unit):
        if unit and unit > 0 and not math.isnan(unit):
            trades.append({"t": t, "d": d, "r": ((exit_ - entry) * d - bps * 1e-4 * entry) / unit})
    R5.rec = rec
    try:
        return R5.range_break(lab.F.daily, R5.inside)
    finally:
        R5.rec = orig


def judge(trades):
    rs = [t["r"] for t in trades]
    s = S.stats(rs)
    per = {}
    for p, a, b in PERIODS:
        x = [t["r"] for t in trades if a <= t["t"] < b]
        per[p] = (len(x), sum(x) / len(x) if x else None)
    if s.get("n", 0) < 2:
        return s, per, 1.0, False
    sd = st.stdev(rs)
    tstat = s["avg"] / (sd / math.sqrt(len(rs))) if sd > 0 else 0
    p = 0.5 * math.erfc(tstat / math.sqrt(2))
    counted = [v for n, v in per.values() if n >= 10]
    ok = (s["n"] >= 150 and s["avg"] >= 0.05 and len(counted) >= 3
          and all(v > 0 for v in counted) and p < ALPHA)
    return s, per, p, ok


def gold_median_atr():
    files = MARKETS["XAUUSD (reference)"][0]
    bars = sorted((b for f in files for b in load(os.path.join(DATA, f))), key=lambda b: b["t"])
    return median_atr(L.Lab(bars))


def main(only=None):
    gold_atr = gold_median_atr()   # the dollar buffers are scaled against gold, whatever runs
    rows, streams = [], {}
    for name, (files, bps) in MARKETS.items():
        if only and name not in only:
            continue
        paths = [os.path.join(DATA, f) for f in files]
        if not all(os.path.exists(p) for p in paths):
            print(f"{name}: data missing, skipped", flush=True)
            continue
        bars = sorted((b for p in paths for b in load(p)), key=lambda b: b["t"])
        lab = L.Lab(bars)
        k = median_atr(lab) / gold_atr
        for key in ("entry_buffer", "h4_entry_buffer", "h4_stop_buffer"):
            lab.cfg[key] = S.CONFIG[key] * k
        tests = {
            "trend": lambda: run_orders(lab, L.gen_ha(lab, BASE_P), bps),
            "insideday": lambda: run_insideday(lab, bps),
            "h4": lambda: run_orders(lab, R9.e2_h4_trigger(lab), bps),
        }
        for strat, fn in tests.items():
            tr = fn()
            s, per, p, ok = judge(tr)
            streams[(name, strat)] = tr
            row = {"market": name, "strategy": strat, "from": f"{bars[0]['t']:%Y-%m}",
                   "cost_bps": bps, "n": s.get("n", 0), "win": round(s.get("win", 0), 1),
                   "avg": round(s.get("avg", 0), 3), "total": round(s.get("total", 0), 1),
                   "pf": round(s.get("pf", 0), 2) if s.get("n") else 0,
                   **{f"{pn}_avg": (round(v, 3) if v is not None else "") for pn, (n, v) in per.items()},
                   **{f"{pn}_n": n for pn, (n, v) in per.items()},
                   "p": f"{p:.2g}", "verdict": "PASS" if ok else ""}
            rows.append(row)
            print(f"{name:20s} {strat:9s} n={row['n']:5d} win={row['win']:5.1f}% avg={row['avg']:+.3f} PF={row['pf']:.2f} | "
                  + " ".join(f"{pn} {('%+.3f' % v) if v is not None else '  -   '}({n})" for pn, (n, v) in per.items())
                  + f" | p={p:.2g} {row['verdict']}", flush=True)

    out = os.path.join(HERE, "results_round10_markets.csv" if not only else "results_round10_partial.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader(); w.writerows(rows)

    # how the passes relate to gold's live streams and to each other (monthly R)
    passes = [(r["market"], r["strategy"]) for r in rows if r["verdict"] and not r["market"].startswith("XAU")]
    if passes:
        def monthly(tr):
            m = collections.defaultdict(float)
            for t in tr:
                m[(t["t"].year, t["t"].month)] += t["r"]
            return m
        gold = [("XAUUSD (reference)", "trend"), ("XAUUSD (reference)", "insideday")]
        keys = gold + passes
        ms = {k: monthly(streams[k]) for k in keys if k in streams}
        months = sorted(set().union(*ms.values()))
        print("\nMonthly correlation of passes with gold's live strategies:")
        for k in passes:
            cs = []
            for g in gold:
                if g in ms:
                    cs.append(f"{g[1]} {st.correlation([ms[k][m] for m in months], [ms[g][m] for m in months]):+.2f}")
            print(f"  {k[0]} {k[1]}: " + ", ".join(cs))


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
