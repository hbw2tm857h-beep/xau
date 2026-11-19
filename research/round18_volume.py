"""Round 18: does volume improve the strategies? (pre-registered 19 Nov 2026,
before any volume data was downloaded)

Bradley asked for a live volume-based probability. Spot gold, FX and index CFDs
have no exchange volume, and the free sources for real US ETF volume either block
scripts or start too late. So volume here means Dukascopy's own volume on each
hourly candle: a proxy for activity, not the exchange's figure. Tick-style volume
of this kind is the usual stand-in on spot markets, but a pass would still need
checking against real volume before it could become a rule.

Each test asks whether a volume condition picks out better trades from a strategy
already in the bot. The strategies themselves are not re-tested.

  V1 US IBS, capitulation volume. RVOL = the signal session's volume (sum of its
     hourly volumes) / the average of the previous 20 sessions. Claim: signals
     with RVOL >= 1.5 beat those below. S&P 500, Nasdaq 100, Dow, Russell 2000.
  V2 Gold trend, volume confirmation. RVOL = the trigger candle's volume / the
     average of the previous 24 hourly candles. Claim: RVOL >= 1.0 beats < 1.0.
  V3 Gold trend, VPIN (Easley, Lopez de Prado & O'Hara 2012), bulk volume
     classification on hourly candles: buy share = Phi(return / sd of the last 100
     hourly returns); VPIN = sum over the last 50 candles of |2 x buy share - 1| x
     volume / total volume. Claim: setups when VPIN is above its median over the
     previous 500 candles beat the rest (informed flow behind the move).
  V4 Gold inside-day, quiet inside days. RVOL = the inside day's volume / the
     average of the previous 20 days. Claim: RVOL < 1.0 beats >= 1.0 (a quiet
     inside day is a tighter coil).
  V5 Ether inside-day, the same split as V4, on the realistic version (24/7 data,
     weekday signals).

Pass, for each test: the favoured group has 100+ trades and a positive average
in every period with 10+ trades; it beats the other group in at least three of
the four periods; and a one-sided Welch t-test on the difference gives
p < 0.05 / 5 = 0.01. A pass would be a candidate filter, tracked beside the
unfiltered strategy, never a change to live rules on its own.
"""
import csv
import gzip
import math
import os
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import lab as L  # noqa: E402
import round10_btc_checks as B  # noqa: E402
import round10_markets as R10  # noqa: E402
import round12_beyond_gold as M  # noqa: E402
import round12_ibs_checks as C  # noqa: E402

UTC = timezone.utc
VOL = os.path.join(HERE, "..", "data", "volume")
ALPHA = 0.05 / 5
M.R10.MARKETS["Russell 2000"] = (["markets/ussc2000idxusd_h1.csv.gz"], 2.0)
M.SESSION["Russell 2000"] = (ZoneInfo("America/New_York"), 9, 15)
US4 = {"S&P 500": "usa500idxusd", "Nasdaq 100": "usatechidxusd", "Dow": "usa30idxusd", "Russell 2000": "ussc2000idxusd"}


def load_vol(iid):
    out = {}
    with gzip.open(os.path.join(VOL, f"{iid}_h1_vol.csv.gz"), "rt") as f:
        for r in csv.DictReader(f):
            out[datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)] = float(r["volume"])
    return out


def welch(a, b):
    ma, mb = st.mean(a), st.mean(b)
    va, vb = st.variance(a) / len(a), st.variance(b) / len(b)
    t = (ma - mb) / math.sqrt(va + vb) if va + vb > 0 else 0
    return t, 0.5 * math.erfc(t / math.sqrt(2))


def verdict(label, trades, key, favoured):
    """trades carry t, a result under `key`, and 'flag' (True = favoured group)."""
    a = [t for t in trades if t["flag"] is favoured]
    b = [t for t in trades if t["flag"] is (not favoured)]
    ra, rb = [t[key] for t in a], [t[key] for t in b]
    t, p = welch(ra, rb)
    per, wins = [], 0
    for pn, lo, hi in M.PERIODS:
        xa = [t[key] for t in a if lo <= t["t"] < hi]
        xb = [t[key] for t in b if lo <= t["t"] < hi]
        if len(xa) >= 10 and len(xb) >= 10:
            wins += st.mean(xa) > st.mean(xb)
        per.append((pn, len(xa), st.mean(xa) if xa else None, st.mean(xb) if xb else None))
    counted = [m for _pn, n, m, _ in per if n >= 10]
    ok = len(a) >= 100 and all(m > 0 for m in counted) and wins >= 3 and p < ALPHA
    print(f"{label:44s} favoured n={len(a):4d} avg={st.mean(ra):+.3f} | other n={len(rb):4d} avg={st.mean(rb):+.3f} | "
          f"diff t={t:+.2f} p={p:.2g} | " + " ".join(
              f"{pn} {'%+.3f' % ma if ma is not None else '-'}/{'%+.3f' % mb if mb is not None else '-'}"
              for pn, _n, ma, mb in per) + f" | {'PASS' if ok else 'fail'}")
    return {"test": label, "n_favoured": len(a), "avg_favoured": round(st.mean(ra), 4), "n_other": len(rb),
            "avg_other": round(st.mean(rb), 4), "t": round(t, 2), "p": f"{p:.2g}", "verdict": "PASS" if ok else ""}


def daily_vol(vol, end):
    return sum(vol.get(end - timedelta(hours=h), 0.0) for h in range(1, 25))


def v1():
    trades = []
    for name, iid in US4.items():
        vol = load_vol(iid)
        zone, h0, h1 = M.SESSION[name]
        s = M.sessions(name)
        days = sorted(s)
        sv = {}
        for d in days:
            start = datetime.combine(d, datetime.min.time(), zone).replace(hour=h0).astimezone(UTC)
            sv[d] = sum(vol.get(start + timedelta(hours=k), 0.0) for k in range(h1 - h0 + 1))
        by_close = {s[d]["t"]: k for k, d in enumerate(days)}
        for t in C.ibs_trades(name):
            k = by_close[t["t"]]
            prev = [sv[days[j]] for j in range(max(0, k - 20), k) if sv[days[j]] > 0]
            if len(prev) < 15 or sv[days[k]] <= 0:
                continue
            trades.append(dict(t, flag=sv[days[k]] / st.mean(prev) >= 1.5))
    return verdict("V1 US IBS, RVOL >= 1.5", trades, "bps", True)


def gold_lab():
    bars = sorted((b for f in R10.MARKETS["XAUUSD (reference)"][0] for b in R10.load(os.path.join(R10.DATA, f))), key=lambda b: b["t"])
    return L.Lab(bars)


def v2_v3(lab, trend):
    vol = load_vol("xauusd")
    hours = sorted(vol)
    idx = {t: i for i, t in enumerate(hours)}
    vols = [vol[t] for t in hours]
    closes = {b["t"]: b["c"] for b in lab.b}
    rets = []
    for k, t in enumerate(hours):
        c0, c1 = closes.get(hours[k - 1]) if k else None, closes.get(t)
        rets.append(math.log(c1 / c0) if c0 and c1 else 0.0)
    vpin = [None] * len(hours)
    for k in range(150, len(hours)):
        sd = st.pstdev(rets[k - 100:k]) or 1e-9
        num = den = 0.0
        for j in range(k - 49, k + 1):
            buy = 0.5 * math.erfc(-rets[j] / sd / math.sqrt(2))
            num += abs(2 * buy - 1) * vols[j]
            den += vols[j]
        vpin[k] = num / den if den else None
    t2, t3 = [], []
    for tr in trend:
        k = idx.get(tr["t"])
        if k is None or k < 650:
            continue
        prev = [v for v in vols[k - 24:k] if v > 0]
        if len(prev) >= 20 and vols[k] > 0:
            t2.append(dict(tr, flag=vols[k] / st.mean(prev) >= 1.0))
        hist = [v for v in vpin[k - 500:k] if v is not None]
        if vpin[k] is not None and len(hist) >= 400:
            t3.append(dict(tr, flag=vpin[k] > st.median(hist)))
    return (verdict("V2 Gold trend, trigger RVOL >= 1.0", t2, "r", True),
            verdict("V3 Gold trend, VPIN above median", t3, "r", True))


def inside_split(trades, vol, label):
    out = []
    for tr in trades:
        end = tr["t"]
        dv = daily_vol(vol, end)
        prev = [daily_vol(vol, end - timedelta(days=k)) for k in range(1, 29)]
        prev = [v for v in prev if v > 0][:20]
        if len(prev) < 15 or dv <= 0:
            continue
        out.append(dict(tr, flag=dv / st.mean(prev) < 1.0))
    return verdict(label, out, "r", True)


def main():
    rows = [v1()]
    lab = gold_lab()
    trend = R10.run_orders(lab, L.gen_ha(lab, R10.BASE_P), 1.75)
    rows += list(v2_v3(lab, trend))
    rows.append(inside_split(R10.run_insideday(lab, 1.75), load_vol("xauusd"), "V4 Gold inside-day, quiet day (RVOL < 1)"))
    eth = B.load_247(os.path.join(R10.DATA, "markets", "ethusd_h1.csv.gz"))
    eth_tr = [t for t in R10.run_insideday(B.make_lab(eth, R10.gold_median_atr()), 8) if t["t"].weekday() < 5]
    rows.append(inside_split(eth_tr, load_vol("ethusd"), "V5 Ether inside-day, quiet day (RVOL < 1)"))
    with open(os.path.join(HERE, "results_round18_volume.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
