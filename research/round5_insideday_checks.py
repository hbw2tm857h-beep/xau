"""Round 5: robustness checks on the one standalone pass (inside-day breakout).
None of these change the rules; they ask whether the result is fragile."""
import collections, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L, signals as S, round5_standalone as R

labs = {"old": L.Lab(L.load(os.path.join(HERE, "..", "data", "xauusd_h1_2008_2015.csv"))),
        "new": L.Lab(L.load(os.path.join(HERE, "..", "data", "xauusd_h1.csv")))}

def collect(setup, cost=0.35, tag_dir=False):
    R.COST = cost; out = []
    for k, lab in labs.items():
        lo, hi = (R.D(2008), R.D(2016)) if k == "old" else (R.D(2016), R.D(2030))
        db = lab.F.daily
        tr = R.range_break(db, setup)
        out += [t for t in tr if lo <= t["t"] < hi]
    R.COST = 0.35
    return out

def line(name, tr):
    s = S.stats([t["r"] for t in tr])
    print(f"{name:52s} n={s['n']:4d} win={s['win']:5.1f}% avg={s['avg']:+.3f} PF={s['pf']:.2f} total={s['total']:+.1f}R maxDD={s['dd']:.1f}R")
    return s

base = collect(R.inside)
s0 = line("Inside-day breakout ($0.35 costs)", base)
line("  costs $0.80", collect(R.inside, 0.80))
line("  costs $1.50", collect(R.inside, 1.50))
# years
yr = collections.defaultdict(list)
for t in base: yr[t["t"].year].append(t["r"])
pos = sum(1 for v in yr.values() if sum(v) > 0)
print("  by year:", " ".join(f"{y}:{sum(v):+.1f}" for y, v in sorted(yr.items())), f"| positive {pos}/{len(yr)}")
# direction: re-run with a direction tag
def tagged():
    out = []
    for k, lab in labs.items():
        lo, hi = (R.D(2008), R.D(2016)) if k == "old" else (R.D(2016), R.D(2030))
        db = lab.F.daily
        for kk in range(7, len(db) - 1):
            if not R.inside([b["h"] for b in db], [b["l"] for b in db], kk): continue
            j = kk + 1; up = db[j]["h"] > db[kk]["h"]; dn = db[j]["l"] < db[kk]["l"]
            if up and not dn: out.append((db[kk]["end"], 1))
            elif dn and not up: out.append((db[kk]["end"], -1))
    return dict(out)
dmap = tagged()
L_ = [t["r"] for t in base if dmap.get(t["t"]) == 1]; Sh = [t["r"] for t in base if dmap.get(t["t"]) == -1]
amb = [t["r"] for t in base if t["t"] not in dmap]
print(f"  longs n={len(L_)} avg={sum(L_)/len(L_):+.3f} | shorts n={len(Sh)} avg={sum(Sh)/len(Sh):+.3f} | both-sides days n={len(amb)} avg={sum(amb)/len(amb):+.3f}")
# neighbouring setups (not for picking, only to see if the idea is a cliff)
line("  neighbour: NR4 day", collect(lambda h, l, k: (lambda r: r[-1] == min(r) and r.count(r[-1]) == 1)([h[x]-l[x] for x in range(k-3, k+1)])))
line("  neighbour: inside day AND NR7 (ID/NR7)", collect(lambda h, l, k: R.inside(h, l, k) and R.nr7(h, l, k)))
line("  neighbour: 2 inside days in a row", collect(lambda h, l, k: R.inside(h, l, k) and R.inside(h, l, k-1)))
# random-direction control: same days, same entry/stop mechanics, coin-flip side
rs = [t["r"] for t in base]; m = sum(rs)/len(rs); sd = (sum((x-m)**2 for x in rs)/(len(rs)-1))**0.5
print(f"  t-stat of mean = {m/(sd/len(rs)**0.5):.2f}")
rnd = random.Random(3); boots = []
for _ in range(10000):
    smp = [rs[rnd.randrange(len(rs))] for _ in rs]; boots.append(sum(smp)/len(smp))
print(f"  bootstrap: share of resamples with mean <= 0: {sum(1 for b in boots if b <= 0)/len(boots):.4f}")
