"""Round 34: new rules for gold on 15-minute candles (pre-registered 23 Nov 2026;
committed before round 33's results and before any 15-minute candle was read).

Bradley: the 15-minute setups don't need to follow the hourly rules; find rules
that work on that timeframe, to run alongside the originals. A search needs a
held-out test, so this round is fixed in two stages.

Data: Dukascopy XAUUSD 15-minute candles 2008-2026 (data/xauusd_m15_*.csv.gz).
Search 2008-2018. Hold-out 2019-2026, used once, only for the chosen variants.

Common to every rule. Context from completed higher candles only: the daily
trend (signals.daily_trend: daily Heikin Ashi and the 50-day EMA agree) and the
last closed 4-hour Heikin Ashi candle's colour; "with the trend" means both
agree with the trade. Entry by stop order ($0.30 beyond the level), live for
the next 8 candles. Stop and exits as live: half off at 1R with the stop to
entry, the rest at 2R; on the fill candle only the stop is checked; afterwards
the stop first, then 1R, then 2R. Intraday: anything open is closed at the
close of the 20:45 UK candle, and no order is placed after 19:00 UK. One trade
at a time per rule. Cost $0.35 a trade. ATR = 14-candle ATR on 15 minutes.

Families and variants (the search picks one variant per family):
  P Trend pullback: with the trend, RSI(n) on 15-minute closes falls below L and
    the next candle closes back above L (mirror for sells). Buy-stop above that
    candle's high; stop below the lowest low of the last 5 candles - 0.2 x ATR.
    Variants: (n, L) in (2, 10), (2, 20), (14, 30), (14, 35).
  D Donchian breakout: with the trend, a 15-minute close above the highest high
    of the previous N candles. Buy-stop above that candle's high; stop as P.
    Variants: N in 20, 48, 96.
  A Asian-range breakout: the range of 00:00-07:00 UK candles. From 07:00 UK a
    buy-stop above the range high (sell-stop below the low); first fill only,
    one trade a day; stop at the range's other side. Variants: with the trend
    only, either direction; range kept only if its width is under 1.0 or 1.5 x
    the 14-day average daily range (4 variants).
  N New York opening range: the range of the 13:30-14:00 or 13:30-14:30 UK
    candles; then as A (with the trend only, either direction) (4 variants).

Search: per family, the variant with the highest average R over 2008-2018
among those with at least 200 trades there (none qualifying: the family fails).

Hold-out tests (4, one per family), pass all of: 150+ trades in 2019-2026;
average R above zero with a one-sided t-test p < 0.05 / 4; positive in both
2019-22 and 2023-26.

hypotheses_tested rises by 15 (the variants searched; 1,384 -> 1,399). A pass
goes in as a candidate first (staff channel, live evidence before members).
"""
import csv
import glob
import gzip
import json
import math
import os
import statistics as st
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402

UTC = timezone.utc
UK = S.UK
M15 = timedelta(minutes=15)
COST, BUF, EXPIRY = 0.35, 0.30, 8
SEARCH_END = datetime(2019, 1, 1, tzinfo=UTC)
ALPHA = 0.05 / 4


def load():
    bars = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "xauusd_m15_*.csv.gz"))):
        with gzip.open(p, "rt") as f:
            for r in csv.DictReader(f):
                t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
                o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
                if h - l <= 0 and o == c:
                    continue
                bars[t] = {"t": t, "o": o, "h": h, "l": l, "c": c}
    return [bars[t] for t in sorted(bars) if S.market_open(t)]


class Ctx:
    """Per-candle context from completed higher candles only."""
    def __init__(self, bars):
        self.bars = bars
        n = len(bars)
        daily = S.aggregate(bars, S.trading_day, S.day_end)
        h4 = S.aggregate(bars, S.h4_key, S.h4_end)
        h4ha = S.heikin_ashi(h4)
        self.trend, self.h4dir, self.adr = [0] * n, [0] * n, [None] * n
        dk = hk = -1
        cache = {}
        for i, b in enumerate(bars):
            close = b["t"] + M15
            while dk + 1 < len(daily) and daily[dk + 1]["end"] <= close:
                dk += 1
            while hk + 1 < len(h4) and h4[hk + 1]["end"] <= close:
                hk += 1
            if dk >= 60:
                if dk not in cache:
                    sub = daily[:dk + 1]
                    cache[dk] = (S.daily_trend(sub, S.CONFIG), sum(d["h"] - d["l"] for d in sub[-14:]) / 14)
                self.trend[i], self.adr[i] = cache[dk]
            if hk >= 0:
                x = h4ha[hk]
                self.h4dir[i] = 1 if x["c"] > x["o"] else -1 if x["c"] < x["o"] else 0
        tr = S.true_ranges(bars)
        self.atr = [None] * n
        s = 0.0
        for i in range(n):
            s += tr[i] - (tr[i - 14] if i >= 14 else 0)
            if i >= 14:
                self.atr[i] = s / 14

    def with_trend(self, i, d):
        return self.trend[i] == d and self.h4dir[i] == d


def rsi(closes, n):
    out = [None] * len(closes)
    g = l = 0.0
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        up, dn = max(ch, 0.0), max(-ch, 0.0)
        if i <= n:
            g += up / n; l += dn / n
            if i == n:
                out[i] = 100 - 100 / (1 + g / l) if l else 100.0
        else:
            g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n
            out[i] = 100 - 100 / (1 + g / l) if l else 100.0
    return out


def uk(t):
    return t.astimezone(UK)


def simulate(bars, signals):
    """signals: list of (i, d, entry, stop, until_i) - an order placed at the close
    of candle i, live for candles i+1..until_i. One trade at a time."""
    out, busy_until = [], -1
    for i, d, entry, stop, until in signals:
        if i <= busy_until:
            continue
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        j, filled = i + 1, None
        while j < len(bars) and j <= until:
            b = bars[j]
            if (b["h"] >= entry) if d == 1 else (b["l"] <= entry):
                filled = j
                break
            j += 1
        if filled is None:
            continue
        fill = max(entry, bars[filled]["o"]) if d == 1 else min(entry, bars[filled]["o"])
        risk = abs(fill - stop)
        if risk <= 0:
            continue
        booked, done, cur_stop = 0.0, 0.0, stop
        r, k = None, filled
        while k < len(bars):
            b = bars[k]
            hit_stop = (b["l"] <= cur_stop) if d == 1 else (b["h"] >= cur_stop)
            if hit_stop:
                r = booked + (1 - done) * (cur_stop - fill) * d / risk; break
            if k > filled:
                t1, t2 = fill + d * risk, fill + d * 2 * risk
                if not done and ((b["h"] >= t1) if d == 1 else (b["l"] <= t1)):
                    booked, done, cur_stop = 0.5, 0.5, fill
                if (b["h"] >= t2) if d == 1 else (b["l"] <= t2):
                    r = booked + (1 - done) * 2; break
            lt = uk(b["t"])
            if (lt.hour, lt.minute) >= (20, 45) or (k + 1 < len(bars) and bars[k + 1]["t"] - b["t"] > timedelta(hours=2)):
                r = booked + (1 - done) * (b["c"] - fill) * d / risk; break
            k += 1
        if r is None:
            continue
        out.append({"t": bars[i]["t"], "d": d, "r": r - COST / risk})
        busy_until = k
    return out


def placeable(bars, i):
    lt = uk(bars[i]["t"] + M15)
    return lt.hour < 19 and lt.hour >= 1


def fam_pullback(bars, C, n, L):
    rs = rsi([b["c"] for b in bars], n)
    sig = []
    for i in range(6, len(bars)):
        if rs[i] is None or rs[i - 1] is None or C.atr[i] is None or not placeable(bars, i):
            continue
        for d in (1, -1):
            dipped = rs[i - 1] < L and rs[i] >= L if d == 1 else rs[i - 1] > 100 - L and rs[i] <= 100 - L
            if dipped and C.with_trend(i, d):
                seg = bars[i - 4:i + 1]
                if d == 1:
                    sig.append((i, 1, bars[i]["h"] + BUF, min(x["l"] for x in seg) - 0.2 * C.atr[i], i + EXPIRY))
                else:
                    sig.append((i, -1, bars[i]["l"] - BUF, max(x["h"] for x in seg) + 0.2 * C.atr[i], i + EXPIRY))
    return sig


def fam_donchian(bars, C, N):
    sig = []
    for i in range(N + 1, len(bars)):
        if C.atr[i] is None or not placeable(bars, i):
            continue
        prev = bars[i - N:i]
        for d in (1, -1):
            brk = bars[i]["c"] > max(x["h"] for x in prev) if d == 1 else bars[i]["c"] < min(x["l"] for x in prev)
            if brk and C.with_trend(i, d):
                seg = bars[i - 4:i + 1]
                if d == 1:
                    sig.append((i, 1, bars[i]["h"] + BUF, min(x["l"] for x in seg) - 0.2 * C.atr[i], i + EXPIRY))
                else:
                    sig.append((i, -1, bars[i]["l"] - BUF, max(x["h"] for x in seg) + 0.2 * C.atr[i], i + EXPIRY))
    return sig


def fam_range(bars, C, start, end, trend_only, max_adr):
    """Range of the UK-time window [start, end) on each UK date; orders from end
    until 19:00 UK, first fill only (both orders sent as one signal each, the
    simulator takes whichever comes first in time)."""
    by_day = {}
    for i, b in enumerate(bars):
        lt = uk(b["t"])
        by_day.setdefault(lt.date(), []).append((i, lt))
    sig = []
    for day, items in sorted(by_day.items()):
        win = [i for i, lt in items if start <= (lt.hour, lt.minute) < end]
        after = [i for i, lt in items if (lt.hour, lt.minute) >= end and lt.hour < 19]
        if len(win) < 2 or not after:
            continue
        i0 = win[-1]
        hi, lo = max(bars[i]["h"] for i in win), min(bars[i]["l"] for i in win)
        adr = C.adr[i0]
        if adr is None or hi - lo <= 0 or hi - lo > max_adr * adr:
            continue
        until = after[-1]
        if trend_only:
            # only the order on the trend's side is placed
            d = C.trend[i0] if C.trend[i0] == C.h4dir[i0] and C.trend[i0] != 0 else 0
            if not d:
                continue
            sig.append((i0, d, hi + BUF if d == 1 else lo - BUF, lo if d == 1 else hi, until))
            continue
        # both orders, one cancels the other: the side that is reached first
        first = None
        for j in after:
            up, dn = bars[j]["h"] >= hi + BUF, bars[j]["l"] <= lo - BUF
            if up or dn:
                first = 1 if up and not dn else -1 if dn and not up else (1 if bars[j]["o"] >= (hi + lo) / 2 else -1)
                break
        if first is None:
            continue
        sig.append((i0, first, hi + BUF if first == 1 else lo - BUF, lo if first == 1 else hi, until))
    return sig


FAMILIES = {
    "P": [("P rsi2<10", lambda b, C: fam_pullback(b, C, 2, 10)), ("P rsi2<20", lambda b, C: fam_pullback(b, C, 2, 20)),
          ("P rsi14<30", lambda b, C: fam_pullback(b, C, 14, 30)), ("P rsi14<35", lambda b, C: fam_pullback(b, C, 14, 35))],
    "D": [(f"D donchian {n}", (lambda n: lambda b, C: fam_donchian(b, C, n))(n)) for n in (20, 48, 96)],
    "A": [(f"A asia {'trend' if tr else 'any'} <{m}adr", (lambda tr, m: lambda b, C: fam_range(b, C, (0, 0), (7, 0), tr, m))(tr, m))
          for tr in (True, False) for m in (1.0, 1.5)],
    "N": [(f"N ny {e[0]}:{e[1]:02d} {'trend' if tr else 'any'}", (lambda e, tr: lambda b, C: fam_range(b, C, (13, 30), e, tr, 99))(e, tr))
          for e in ((14, 0), (14, 30)) for tr in (True, False)],
}


def summary(tr):
    rs = [t["r"] for t in tr]
    if len(rs) < 3:
        return len(rs), float("nan"), float("nan"), 1.0
    m, sd = st.mean(rs), st.stdev(rs)
    t = m / (sd / math.sqrt(len(rs)))
    return len(rs), m, t, 0.5 * math.erfc(t / math.sqrt(2))


def main():
    bars = load()
    print(f"{len(bars):,} 15-minute candles {bars[0]['t']:%Y-%m-%d} -> {bars[-1]['t']:%Y-%m-%d}")
    C = Ctx(bars)
    rows = []
    for fam, variants in FAMILIES.items():
        best = None
        print(f"\nFamily {fam}, search 2008-2018:")
        trades = {}
        for name, fn in variants:
            tr = simulate(bars, fn(bars, C))
            trades[name] = tr
            s = [t for t in tr if t["t"] < SEARCH_END]
            n, m, t, p = summary(s)
            print(f"  {name:22s} n={n:5d} avg {m:+.3f}R t={t:+.2f}")
            if n >= 200 and (best is None or m > best[1]):
                best = (name, m)
        if best is None:
            print("  no variant with 200+ trades: fail")
            rows.append({"family": fam, "verdict": "fail"}); continue
        h = [t for t in trades[best[0]] if t["t"] >= SEARCH_END]
        n, m, t, p = summary(h)
        a = [x["r"] for x in h if x["t"] < datetime(2023, 1, 1, tzinfo=UTC)]
        b = [x["r"] for x in h if x["t"] >= datetime(2023, 1, 1, tzinfo=UTC)]
        ok = n >= 150 and m > 0 and p < ALPHA and a and b and st.mean(a) > 0 and st.mean(b) > 0
        yrs = (bars[-1]["t"] - SEARCH_END).days / 365.25
        print(f"  HOLD-OUT {best[0]}: n={n} ({n / yrs / 52:.2f}/week) avg {m:+.3f}R win "
              f"{100 * sum(x['r'] > 0 for x in h) / max(1, n):.0f}% t={t:+.2f} p={p:.2g} | 2019-22 "
              f"{st.mean(a) if a else float('nan'):+.3f} ({len(a)}), 2023-26 {st.mean(b) if b else float('nan'):+.3f} ({len(b)}) | "
              f"{'PASS' if ok else 'fail'}")
        rows.append({"family": fam, "chosen": best[0], "search_avg": round(best[1], 3), "n": n, "avg": round(m, 3),
                     "p": f"{p:.2g}", "per_week": round(n / yrs / 52, 2),
                     "h1": round(st.mean(a), 3) if a else None, "h2": round(st.mean(b), 3) if b else None,
                     "verdict": "PASS" if ok else "fail"})
    passed = [r["chosen"] for r in rows if r["verdict"] == "PASS"]
    print(f"\n{len(passed)} of {len(rows)} families pass the hold-out" + (": " + ", ".join(passed) if passed else ""))
    json.dump(rows, open(os.path.join(HERE, "round34_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
