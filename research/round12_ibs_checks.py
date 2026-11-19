"""Round 12 stress tests for the one pass: IBS band reversion on six indices (M8).

1. Each index on its own.
2. Entry at the next session's open instead of the signal close.
3. Double costs, and no financing (to see how much financing takes).
4. Random-entry control: the same number of trades per index, on random days,
   held for the same number of sessions as the real trades. Index drift is the
   obvious alternative explanation for a long-only rule, and this measures it.
5. Clustering: trades on different indices often fire in the same sell-off, so
   the t-stat is recomputed on weekly sums.
6. Worst trades and the longest hold, since the rule has no stop.
7. Monthly correlation with the gold trend setups, the inside-day setup and
   the Nasdaq noise-area candidate.
"""
import math
import os
import random
import statistics as st
import sys
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import round10_markets as R10  # noqa: E402
import round11_literature as R11  # noqa: E402
import round11_noise_30 as N30  # noqa: E402
import round12_beyond_gold as M  # noqa: E402


def ibs_trades(name, entry="close", cost_mult=1.0, finance=True):
    s = M.sessions(name)
    days = sorted(s)
    out, i = [], 25
    while i < len(days) - 1:
        band = max(s[d]["h"] for d in days[i - 9:i + 1]) - 2.5 * st.mean(s[d]["h"] - s[d]["l"] for d in days[i - 24:i + 1])
        c = s[days[i]]
        rng = c["h"] - c["l"]
        if rng > 0 and c["c"] < band and (c["c"] - c["l"]) / rng < 0.3:
            j = i + 1
            while j < len(days) and s[days[j]]["c"] <= s[days[j - 1]]["h"]:
                j += 1
            if j >= len(days):
                break
            x = s[days[j]]
            px = c["c"] if entry == "close" else s[days[i + 1]]["o"]
            t0 = c["t"] if entry == "close" else s[days[i + 1]]["t"] - timedelta(hours=7)
            bps = (x["c"] / px - 1) * 1e4 - M.cost(name) * cost_mult - (M.finance_bps(t0, x["t"]) if finance else 0)
            out.append({"t": c["t"], "bps": bps, "idx": name, "hold": j - i, "i": i})
            i = j + 1
            continue
        i += 1
    return out


def summary(label, tr):
    s = M.judge(sorted(tr, key=lambda t: t["t"]))
    print(f"{label:38s} n={s['n']:5d} win={s['win']:4.1f}% net={s['avg']:+7.2f}bp t={s['t']:+5.2f} p={s['p']:.2g} | "
          + " ".join(f"{pn} {('%+.1f' % v) if v is not None else '-'}" for pn, (k, v) in s["per"].items()))
    return s


def random_control(real, sims=300, seed=7):
    rng = random.Random(seed)
    per = {}
    for n in M.SESSION:
        s = M.sessions(n)
        days = sorted(s)
        holds = [t["hold"] for t in real if t["idx"] == n]
        per[n] = (s, days, holds)
    means = []
    for _ in range(sims):
        x = []
        for n, (s, days, holds) in per.items():
            for h in holds:
                i = rng.randrange(25, len(days) - h - 1)
                e, ex = s[days[i]], s[days[i + h]]
                x.append((ex["c"] / e["c"] - 1) * 1e4 - M.cost(n) - M.finance_bps(e["t"], ex["t"]))
        means.append(st.mean(x))
    return means


def monthly(tr, key):
    m = {}
    for t in tr:
        k = (t["t"].year, t["t"].month)
        m[k] = m.get(k, 0) + t[key]
    return m


def corr(a, b):
    ks = sorted(set(a) | set(b))
    x, y = [a.get(k, 0) for k in ks], [b.get(k, 0) for k in ks]
    mx, my = st.mean(x), st.mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return num / math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))


def main():
    real = [t for n in M.SESSION for t in ibs_trades(n)]
    summary("Base (as pre-registered)", real)
    print("\n1. Each index")
    for n in M.SESSION:
        summary(f"   {n}", [t for t in real if t["idx"] == n])
    print("\n2-3. Execution and costs")
    summary("   Entry at next open", [t for n in M.SESSION for t in ibs_trades(n, entry="open")])
    summary("   Double costs", [t for n in M.SESSION for t in ibs_trades(n, cost_mult=2)])
    summary("   No financing", [t for n in M.SESSION for t in ibs_trades(n, finance=False)])

    print("\n4. Random entries, same holds (300 runs)")
    means = random_control(real)
    mu = st.mean(t["bps"] for t in real)
    beat = sum(m >= mu for m in means)
    print(f"   real {mu:+.2f}bp | random mean {st.mean(means):+.2f}bp sd {st.stdev(means):.2f} | "
          f"{beat} of {len(means)} random runs reached the real figure | z={(mu - st.mean(means)) / st.stdev(means):.1f}")

    print("\n5. Clustering")
    wk = {}
    for t in real:
        k = t["t"].isocalendar()[:2]
        wk.setdefault(k, []).append(t["bps"])
    w = [st.mean(v) for v in wk.values()]
    tw = st.mean(w) / (st.stdev(w) / math.sqrt(len(w)))
    print(f"   {len(w)} weeks with a trade, mean {st.mean(w):+.2f}bp, t={tw:.2f}, p={0.5 * math.erfc(tw / math.sqrt(2)):.2g}")

    print("\n6. Tail")
    xs = sorted(real, key=lambda t: t["bps"])
    print("   worst 5:", ", ".join(f"{t['idx']} {t['t']:%Y-%m-%d} {t['bps']:+.0f}bp ({t['hold']}d)" for t in xs[:5]))
    print(f"   longest hold {max(t['hold'] for t in real)} sessions, median {st.median(t['hold'] for t in real)}")
    print(f"   trades per year {len(real) / 15.2:.0f}; per index per year {len(real) / 15.2 / 6:.1f}")

    print("\n7. Monthly correlation")
    gold_bars = sorted((b for f in R10.MARKETS['XAUUSD (reference)'][0] for b in R10.load(os.path.join(R10.DATA, f))), key=lambda b: b["t"])
    lab = L.Lab(gold_bars)
    trend = R10.run_orders(lab, L.gen_ha(lab, R10.BASE_P), 1.75)
    inside = R10.run_insideday(lab, 1.75)
    noise = R11.noise_area(N30.cash_hours(), 1.0, N30.session)
    ib = monthly(real, "bps")
    for label, tr, key in (("gold trend", trend, "r"), ("inside-day", inside, "r"), ("ndx_noise", noise, "bps")):
        print(f"   IBS vs {label}: {corr(ib, monthly(tr, key)):+.3f}")


if __name__ == "__main__":
    main()
