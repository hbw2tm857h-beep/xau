"""Round 4: popular open-source TradingView indicators vs the live gold rules.

Each indicator uses its author's default settings (no tuning) and is tested
three ways, one at a time:
  filter H1  - live rules, plus the indicator on H1 must agree with the trade
  filter H4  - live rules, plus the indicator on the last closed 4H bar agrees
  trigger    - replaces the Heikin Ashi trigger: a fresh H1 flip of the
               indicator, with the same daily trend + 4H HA agreement, entry,
               stop and exits. Compared with an HA flip in the same framework.

Pass mark (same as round 2): average R better by more than 0.02 in BOTH
TUNE (2016-22) and VALIDATE (2023-24), keeping at least 60% of the trades.
Anything that passes is then checked on 2008-15 and 2025-26. Those periods
were seen before, but none of these indicators were chosen or set using them.
To be adopted, a change must beat the live rules in all four periods.
"""
import csv, os, sys
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L
import signals as S
import tv_indicators as T

UTC = timezone.utc
BASE_P = {"session": False, "h4": True, "breakout": False, "swing": 5}
M = {"part_r": 1.0, "part_frac": 0.5, "target_r": 2.0}


def gen_filter(lab, p):
    arr, tf = p["ind"], p["tf"]
    for i, d, entry, stop, exp, cof in L.gen_ha(lab, BASE_P):
        v = arr[i] if tf == "h1" else arr[lab.F.h4_idx[i]]
        if v == d:
            yield i, d, entry, stop, exp, cof


def gen_trigger(lab, p):
    """Fresh flip of `ind` on H1 (or HA colour flip when ind is None)."""
    F, b, arr = lab.F, lab.b, p.get("ind")
    for i in range(2, len(b)):
        if not F.warm(i):
            continue
        for d in (1, -1):
            if arr is None:
                x, px = F.ha[i], F.ha[i - 1]
                flip = (S.bull(x) and S.bear(px)) if d == 1 else (S.bear(x) and S.bull(px))
            else:
                flip = arr[i] == d and arr[i - 1] != d
            if not flip or lab.trend(i) != d:
                continue
            c4 = F.h4_ha[F.h4_idx[i]]
            if not (S.bull(c4) if d == 1 else S.bear(c4)):
                continue
            sw = b[max(0, i - 4):i + 1]; hatr = F.hatr[i] or 0
            if d == 1:
                entry, stop = b[i]["h"] + 0.3, min(z["l"] for z in sw) - 0.2 * hatr
            else:
                entry, stop = b[i]["l"] - 0.3, max(z["h"] for z in sw) + 0.2 * hatr
            yield i, d, entry, stop, 12, False
            break


L.FAMILIES["tv_filter"] = gen_filter
L.FAMILIES["tv_trigger"] = gen_trigger


class Dataset:
    def __init__(self, path, keep=None):
        bars = L.load(path)
        if keep:
            bars = [x for x in bars if keep(x["t"])]
        self.lab = L.Lab(bars)
        self.cache = {}

    def ind(self, name, tf):
        k = (name, tf)
        if k not in self.cache:
            fn = T.INDICATORS[name][0]
            self.cache[k] = T.compute(self.lab.b if tf == "h1" else self.lab.F.h4, fn)
        return self.cache[k]

    def run(self, mode, name=None, tf="h1"):
        lab = self.lab
        if mode == "live":
            return L.backtest(lab, "ha", BASE_P, M)
        if mode == "filter":
            return L.backtest(lab, "tv_filter", {"ind": self.ind(name, tf), "tf": tf}, M)
        return L.backtest(lab, "tv_trigger", {"ind": None if name is None else self.ind(name, "h1")}, M)


def period(trades, a, b):
    return S.stats([t["r"] for t in trades if a <= t["t"] < b])


D = lambda y: datetime(y, 1, 1, tzinfo=UTC)
PERIODS = [("tune", D(2016), D(2023)), ("val", D(2023), D(2025))]
CONFIRM = [("2008-15", D(2008), D(2016)), ("2025-26", D(2025), D(2030))]


def main():
    new = Dataset(os.path.join(HERE, "..", "data", "xauusd_h1.csv"))
    old = Dataset(os.path.join(HERE, "..", "data", "xauusd_h1_2008_2015.csv"))

    tests = [("Live rules (baseline)", "live", None, None),
             ("HA flip trigger, same framework (control)", "trigger", None, None)]
    for name in T.INDICATORS:
        tests.append((f"{name} | filter H1", "filter", name, "h1"))
        tests.append((f"{name} | filter H4", "filter", name, "h4"))
        tests.append((f"{name} | trigger", "trigger", name, "h1"))

    rows, base, ctrl = [], None, None
    for label, mode, name, tf in tests:
        tr = new.run(mode, name, tf)
        s = {k: period(tr, a, b) for k, a, b in PERIODS}
        ref = ctrl if mode == "trigger" and name else base
        if mode == "live":
            base = s
        if mode == "trigger" and name is None:
            ctrl = s
        ref = ref or s
        dt = s["tune"].get("avg", -9) - ref["tune"]["avg"]
        dv = s["val"].get("avg", -9) - ref["val"]["avg"]
        passed = name is not None and dt > 0.02 and dv > 0.02 and s["tune"].get("n", 0) >= 0.6 * ref["tune"]["n"]
        row = {"test": label, "mode": mode,
               "tune_n": s["tune"].get("n", 0), "tune_win": round(s["tune"].get("win", 0), 1), "tune_R": round(s["tune"].get("avg", 0), 3),
               "val_n": s["val"].get("n", 0), "val_win": round(s["val"].get("win", 0), 1), "val_R": round(s["val"].get("avg", 0), 3),
               "d_tune": round(dt, 3), "d_val": round(dv, 3), "stage1": "PASS" if passed else ""}
        if passed or name is None:
            tr_old = old.run(mode, name, tf)
            for k, a, b in CONFIRM:
                st = period(tr_old if k == "2008-15" else tr, a, b)
                row[f"{k}_n"], row[f"{k}_win"], row[f"{k}_R"] = st.get("n", 0), round(st.get("win", 0), 1), round(st.get("avg", 0), 3)
        rows.append(row)
        print(f"{label:52s} T n={row['tune_n']:3d} {row['tune_win']:4.1f}% {row['tune_R']:+.3f} | "
              f"V n={row['val_n']:3d} {row['val_win']:4.1f}% {row['val_R']:+.3f} | dT={dt:+.3f} dV={dv:+.3f} {row['stage1']}"
              + (f" | 08-15 {row['2008-15_R']:+.3f} (n={row['2008-15_n']}) 25-26 {row['2025-26_R']:+.3f} (n={row['2025-26_n']})" if "2008-15_R" in row else ""),
              flush=True)

    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(os.path.join(HERE, "results_round4_tradingview.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
