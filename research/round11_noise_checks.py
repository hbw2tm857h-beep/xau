"""Round 11: stress tests on the one pass, noise-area momentum on the Nasdaq 100.
Rules unchanged; this only asks how fragile the result is."""
import os, sys, statistics as st, math, collections, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import round10_btc_checks as B, round10_markets as R10, round11_literature as R11, round7_synthetic as R7

def load(name):
    return B.load_247(os.path.join(R10.DATA, "markets", name))

def show(label, tr):
    s = R11.judge(tr)
    print(f"{label:46s} n={s['n']:5d} net={s['avg']:+6.2f}bp win={s['win']:4.1f}% | "
          + " ".join(f"{pn} {('%+.2f' % v) if v is not None else '  -  '}" for pn, (k, v) in s["per"].items())
          + f" | yrs+ {s['pos_years']}/{s['years']} | p={s['p']:.2g}")
    return s

ndx, spx = load("usatechidxusd_h1.csv.gz"), load("usa500idxusd_h1.csv.gz")
base = R11.noise_area(ndx, 1.0, R11.ndx_session)
show("Nasdaq, as tested (1 bp)", base)
for c in (2.0, 3.0):
    show(f"Nasdaq, costs {c:g} bp", R11.noise_area(ndx, c, R11.ndx_session))
show("Nasdaq, longs only", [t for t in base if t["d"] == 1])
show("Nasdaq, shorts only", [t for t in base if t["d"] == -1])
show("S&P 500 (published market), 1 bp", R11.noise_area(spx, 1.0, R11.ndx_session))
show("Dow, 1 bp", R11.noise_area(load("usa30idxusd_h1.csv.gz"), 1.0, R11.ndx_session))
# day-by-day risk at constant size (sum of the day's trades, in bp)
days = collections.defaultdict(float)
for t in base:
    days[t["t"].date()] += t["bps"]
x = list(days.values()); eq = pk = dd = 0
for v in x:
    eq += v; pk = max(pk, eq); dd = max(dd, pk - eq)
print(f"Nasdaq days traded {len(x)}, avg {st.mean(x):+.2f} bp/day, daily Sharpe x sqrt(252) = {st.mean(x)/st.stdev(x)*math.sqrt(252):.2f}, "
      f"total {sum(x):+.0f} bp, max drop {dd:.0f} bp")
# shuffle test: same hourly candles in random order (only the session structure kept)
rnd = random.Random(5); vals = []
for _ in range(20):
    sh = R7.shuffled_bars(ndx, rnd)
    tr = R11.noise_area(sh, 1.0, R11.ndx_session)
    vals.append(st.mean(t["bps"] for t in tr))
real = st.mean(t["bps"] for t in base)
print(f"Shuffle: real {real:+.2f} bp | shuffled mean {st.mean(vals):+.2f} sd {st.stdev(vals):.2f} best {max(vals):+.2f} | "
      f"{sum(v >= real for v in vals)}/20 reached real")
