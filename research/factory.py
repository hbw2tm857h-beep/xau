"""Strategy factory, batch harness (rules fixed 27 Nov 2026, before any rule was
run). Design and bars: research/FACTORY.md, approved by Bradley on 27 Nov 2026.

This file fixes the details the design leaves open. Everything below was
written before the first run.

Data. Hourly Dukascopy candles for the 19 approved markets (gold, silver, WTI,
Brent, copper, S&P 500, Nasdaq 100, Dow, DAX, FTSE 100, Nikkei 225, EURUSD,
GBPUSD, USDJPY, AUDUSD, GBPJPY, EURJPY, Bitcoin, Ether), with weekend candles
and flat candles dropped (round 10's loader). Each market is charged its round
10/16 round-trip cost in basis points of the entry price. Days and 4-hour
blocks roll at 17:00 New York, as the live bot builds them.

Entries (28 variants; every entry is traded long, short or both):
  breakout   tf H1 or D1, N 10/20/55: a candle closes above the highest high
             (below the lowest low) of the N candles before it, and the candle
             before did not. Entry at that close.
  pullback   tf H1 or D1, N 20/50: the N-candle EMA is above (below) its value 5
             candles ago, the candle's low (high) touches the EMA and it closes
             back above (below) it. Entry at that close.
  inside     tf D1 or H4: a candle inside the previous one (high <= and low >=,
             not both equal). Buy-stop at its high and sell-stop at its low for
             the next candle of that timeframe; the first touched fills (at the
             open if it gaps through); if one hourly candle touches both, the
             setup is skipped. Stop: the other side of the inside candle.
  ibs        D1: IBS = (close - low) / (high - low); under 0.2 buy the close,
             over 0.8 sell it.
  run        tf H1 or D1, N 3/4/5, follow or fade: exactly N closes in a row
             above (below) the one before. Follow trades with the run, fade
             against it, at that close.
  squeeze    tf H1 or D1: within the last 5 candles, one whose previous ATR(14)
             was the lowest of the 20 before it; then a breakout of the prior
             10 candles as above.
  orb        H1: the range of the first hour of the market's main session
             (08:00 London for FX, metals, oil, copper, DAX, FTSE and crypto;
             10:00 New York for US indices; 09:00 Tokyo for the Nikkei). The
             first of the next 6 hourly candles to break it fills at the break
             (or the open if it gaps); one candle touching both sides skips.
             Stop: the other side of the range.
  Every other entry's stop, its natural invalidation in this design, is 1 ATR(14)
  of the entry's timeframe from the entry.

Filters (none, one, or two of; ATR-high and ATR-low never together; 21 sets),
each read from the last daily candle completed at the entry:
  F1 the daily close is on the trade's side of its 50-day EMA
  F2 the daily Heikin Ashi candle has the trade's colour
  F3 the 252-day return has the trade's sign
  F4 daily ATR(14) above its median of the last 252 days; F5 below it
  F6 room: at least 1 daily ATR from the entry to the 20-day high (low) for a buy (sell)

Exits (8), simulated on hourly candles from the fill; the stop is checked first
whenever a stop and a target share a candle; on a stop-order fill candle only
the stop is checked:
  X1/X2/X3 target at 1R/2R/3R
  X4 half at 1R, the stop moves to entry, the rest at 2R (the live gold exit)
  X5/X6 close after 3/10 candles of the entry's timeframe
  X7 close at the next 17:00 New York daily close after the entry
  X8 trailing stop 2 ATR(14 of the entry timeframe, at entry) under the highest
     high (over the lowest low) since entry, never looser than the first stop
  Every trade is closed at the close after 240 hourly candles (480 for D1 and H4
  entries) if nothing else ended it.
R = direction x (exit - entry) / risk - cost / risk, risk = |entry - stop|.
One trade at a time per rule: a signal while the rule's trade is open is skipped.

Rules per market: 28 entries x 3 directions x 21 filter sets x 8 exits = 14,112.

Build test, entries 2008-2019 (2011 for indices, 2017 for crypto, as the data
starts), all of: at least 200 trades (100 for D1 entries); average at least
+0.05R; average still positive at double costs; positive in each of 2008-11,
2012-15 and 2016-19 that has at least 20 trades, with at least one such block;
plateau: every grid neighbour (one step in N, or the next target or time exit)
with trades averages above zero.

Ranking and the cut list: build survivors ranked by t-statistic. In rank order
a rule is skipped if its daily R in 2008-19 correlates above 0.5 with a rule
already listed, or if 500 random-entry shuffles (the same directions, risks
and exit on random hourly closes in 2008-19) reach its average 5% of the time
or more. The first 20 listed go to the cut; fewer if fewer qualify.

Cut, entries 1 Jan 2020 to Nov 2026, all of: average at least +0.05R;
one-sided p < 0.05 / K (K = the number sent to the cut); positive in each of
2020-22 and 2023-26 that has at least 20 trades; daily R correlation below 0.3
with each of gold trend, gold inside-day, btc_trend, eth_inside_day and us_ibs
(each replayed by its own code on 2020-26).

Writes research/factory_batch1.md and research/factory_batch1.json. Research
only: nothing in the bot changes. Passing rules go to Bradley as nursery
candidates (silent, #candidate-tracking).
"""
import csv
import gzip
import json
import math
import os
import statistics as st
import sys
import time as _time
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from zoneinfo import ZoneInfo

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as swv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402

UTC, NY = timezone.utc, ZoneInfo("America/New_York")
DATA = os.path.join(ROOT, "data")
LON, TOK = ZoneInfo("Europe/London"), ZoneInfo("Asia/Tokyo")
BUILD_END = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
BLOCKS = [("2008-11", 2008, 2012), ("2012-15", 2012, 2016), ("2016-19", 2016, 2020)]
CUT_BLOCKS = [("2020-22", 2020, 2023), ("2023-26", 2023, 2030)]
MAX_CUT = 20
SHUFFLES = 500
SEED = 27

M = lambda f: os.path.join("markets", f + "_h1.csv.gz")
MARKETS = {   # name: (files, cost bps, ORB session (zone, hour))
    "Gold": (["xauusd_h1_2008_2015.csv", "xauusd_h1.csv"], 1.75, (LON, 8)),
    "Silver": (["xagusd_h1.csv"], 10.0, (LON, 8)),
    "WTI": ([M("lightcmdusd")], 5.0, (LON, 8)),
    "Brent": ([M("brentcmdusd")], 5.0, (LON, 8)),
    "Copper": ([M("coppercmdusd")], 5.0, (LON, 8)),
    "S&P 500": ([M("usa500idxusd")], 1.0, (NY, 10)),
    "Nasdaq 100": ([M("usatechidxusd")], 1.0, (NY, 10)),
    "Dow": ([M("usa30idxusd")], 1.0, (NY, 10)),
    "DAX": ([M("deuidxeur")], 1.0, (LON, 8)),
    "FTSE 100": ([M("gbridxgbp")], 1.5, (LON, 8)),
    "Nikkei 225": ([M("jpnidxjpy")], 2.0, (TOK, 9)),
    "EURUSD": (["eurusd_h1.csv"], 1.0, (LON, 8)),
    "GBPUSD": (["gbpusd_h1.csv"], 1.2, (LON, 8)),
    "USDJPY": (["usdjpy_h1.csv"], 1.0, (LON, 8)),
    "AUDUSD": (["audusd_h1.csv"], 1.5, (LON, 8)),
    "GBPJPY": ([M("gbpjpy")], 2.5, (LON, 8)),
    "EURJPY": ([M("eurjpy")], 1.5, (LON, 8)),
    "Bitcoin": ([M("btcusd")], 5.0, (LON, 8)),
    "Ether": ([M("ethusd")], 8.0, (LON, 8)),
}
FILTERS = ["F1", "F2", "F3", "F4", "F5", "F6"]
FSETS = [()] + [(f,) for f in FILTERS] + [c for c in combinations(FILTERS, 2) if set(c) != {"F4", "F5"}]
EXITS = ["X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8"]
DIRSETS = ["long", "short", "both"]
GRID = {"breakout": [10, 20, 55], "pullback": [20, 50], "run": [3, 4, 5]}
EXIT_NEIGH = {"X1": ["X2"], "X2": ["X1", "X3"], "X3": ["X2"], "X5": ["X6"], "X6": ["X5"]}


# ----------------------------------------------------------------- data
def load(name):
    files, bps, sess = MARKETS[name]
    merged = {}
    for f in files:
        p = os.path.join(DATA, f)
        op = gzip.open if p.endswith(".gz") else open
        with op(p, "rt") as fh:
            for r in csv.DictReader(fh):
                t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
                if not S.market_open(t):
                    continue
                o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
                if h - l <= 0 and o == c:
                    continue
                merged[t] = (o, h, l, c)
    ts = sorted(merged)
    a = np.array([merged[t] for t in ts])
    return ts, a[:, 0], a[:, 1], a[:, 2], a[:, 3]


def group(ts, keyfn):
    """Group id per hourly candle, plus the last hourly index of each group."""
    gid, last, keys, k_prev = np.empty(len(ts), dtype=np.int64), [], [], None
    for i, t in enumerate(ts):
        k = keyfn(t)
        if k != k_prev:
            keys.append(k)
            if k_prev is not None:
                last.append(i - 1)
            k_prev = k
        gid[i] = len(keys) - 1
    last.append(len(ts) - 1)
    return gid, np.array(last)


def ohlc(gid, last, O, H, L, C):
    first = np.r_[0, last[:-1] + 1]
    return (O[first], np.maximum.reduceat(H, first), np.minimum.reduceat(L, first), C[last])


def atr(h, l, c, p=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    out = np.full(len(h), np.nan)
    cs = np.cumsum(tr)
    out[p - 1:] = (cs[p - 1:] - np.r_[0, cs[:-p]]) / p
    return out


def ema(x, p):
    out, k, v = np.empty(len(x)), 2 / (p + 1), x[0]
    for i, xi in enumerate(x):
        v = xi * k + v * (1 - k)
        out[i] = v
    return out


def prior_ext(h, l, n):
    """Highest high and lowest low of the n candles before each candle."""
    hi, lo = np.full(len(h), np.nan), np.full(len(h), np.nan)
    if len(h) > n:
        hi[n:] = swv(h, n).max(axis=1)[:-1]
        lo[n:] = swv(l, n).min(axis=1)[:-1]
    return hi, lo


class Market:
    def __init__(self, name):
        self.name = name
        self.ts, self.O, self.H, self.L, self.C = load(name)
        self.n = len(self.ts)
        self.bps = MARKETS[name][1]
        self.ep = np.array([t.timestamp() for t in self.ts])
        self.year = np.array([t.year for t in self.ts])
        self.tf = {"H1": (np.arange(self.n), np.arange(self.n))}
        self.tf["D1"] = group(self.ts, S.trading_day)
        self.tf["H4"] = group(self.ts, S.h4_key)
        self.bars = {"H1": (self.O, self.H, self.L, self.C)}
        for k in ("D1", "H4"):
            self.bars[k] = ohlc(*self.tf[k], self.O, self.H, self.L, self.C)
        self.atr = {k: atr(*self.bars[k][1:]) for k in self.bars}
        self._daily()

    def _daily(self):
        o, h, l, c = self.bars["D1"]
        gid, last = self.tf["D1"]
        k = np.arange(len(c))
        e50 = ema(c, 50)
        hac = (o + h + l + c) / 4
        hao = np.empty(len(c)); hao[0] = (o[0] + c[0]) / 2
        for i in range(1, len(c)):
            hao[i] = (hao[i - 1] + hac[i - 1]) / 2
        r252 = np.full(len(c), np.nan); r252[252:] = c[252:] - c[:-252]
        a = self.atr["D1"]
        med = np.full(len(c), np.nan)
        if len(c) > 252:
            med[251:] = np.median(swv(a, 252), axis=1)
        hi20, lo20 = np.full(len(c), np.nan), np.full(len(c), np.nan)
        hi20[19:] = swv(h, 20).max(axis=1); lo20[19:] = swv(l, 20).min(axis=1)
        self.dfeat = {"up50": c > e50, "ha": hac > hao, "r252": r252, "atr": a, "med": med,
                      "hi20": hi20, "lo20": lo20, "k": k, "ok": k >= 252}
        # last daily candle completed at the close of each hourly candle
        self.cday = np.where(np.arange(self.n) == last[gid], gid, gid - 1)


# ----------------------------------------------------------------- entries
def variants():
    out = []
    for tf in ("H1", "D1"):
        for n in GRID["breakout"]:
            out.append(("breakout", tf, n, ""))
        for n in GRID["pullback"]:
            out.append(("pullback", tf, n, ""))
        for n in GRID["run"]:
            for mode in ("follow", "fade"):
                out.append(("run", tf, n, mode))
        out.append(("squeeze", tf, 0, ""))
    out += [("inside", "D1", 0, ""), ("inside", "H4", 0, ""), ("ibs", "D1", 0, ""), ("orb", "H1", 0, "")]
    return out


def close_events(m, tf, longs, shorts):
    """Entries at a timeframe candle's close: (hourly index, dir, entry, stop)."""
    gid, last = m.tf[tf]
    c, a = m.bars[tf][3], m.atr[tf]
    rows = []
    for d, mask in ((1, longs), (-1, shorts)):
        ks = np.nonzero(mask & ~np.isnan(a))[0]
        for k in ks:
            rows.append((last[k], d, c[k], c[k] - d * a[k], 0, a[k]))
    return rows


def entries(m, v):
    fam, tf, n, mode = v
    o, h, l, c = m.bars[tf]
    if fam in ("breakout", "squeeze"):
        nn = n or 10
        hi, lo = prior_ext(h, l, nn)
        up, dn = c > hi, c < lo
        up[1:] &= ~up[:-1]; dn[1:] &= ~dn[:-1]
        if fam == "squeeze":
            a = m.atr[tf]
            sq = np.zeros(len(c), bool)
            prev = np.r_[np.nan, a[:-1]]
            win = np.full(len(c), np.nan)
            win[20:] = swv(prev, 20).min(axis=1)[:-1] if len(c) > 20 else np.nan
            sq = prev <= win
            arm = np.zeros(len(c), bool)
            for s in range(5):
                arm[s:] |= sq[:len(c) - s]
            up &= arm; dn &= arm
        return close_events(m, tf, up, dn)
    if fam == "pullback":
        e = ema(c, n)
        rise = np.r_[np.zeros(5, bool), e[5:] > e[:-5]]
        fall = np.r_[np.zeros(5, bool), e[5:] < e[:-5]]
        return close_events(m, tf, rise & (l <= e) & (c > e), fall & (h >= e) & (c < e))
    if fam == "run":
        upc = np.r_[False, c[1:] > c[:-1]]
        dnc = np.r_[False, c[1:] < c[:-1]]
        def runlen(x):
            r = np.zeros(len(x), int)
            for i in range(len(x)):
                r[i] = r[i - 1] + 1 if x[i] and i else (1 if x[i] else 0)
            return r
        ru, rd = runlen(upc) == n, runlen(dnc) == n
        return close_events(m, tf, ru, rd) if mode == "follow" else close_events(m, tf, rd, ru)
    if fam == "ibs":
        rng = h - l
        ibs = np.where(rng > 0, (c - l) / np.where(rng > 0, rng, 1), 0.5)
        return close_events(m, tf, ibs < 0.2, ibs > 0.8)
    rows = []
    if fam == "inside":
        gid, last = m.tf[tf]
        first = np.r_[0, last[:-1] + 1]
        a = m.atr[tf]
        for k in range(1, len(c) - 1):
            if not (h[k] <= h[k - 1] and l[k] >= l[k - 1] and not (h[k] == h[k - 1] and l[k] == l[k - 1])):
                continue
            rows += stop_fill(m, first[k + 1], last[k + 1], h[k], l[k], a[k])
        return rows
    if fam == "orb":
        zone, hour = MARKETS[m.name][2]
        a = m.atr["H1"]
        for i, t in enumerate(m.ts):
            lt = t.astimezone(zone)
            if lt.hour == hour and lt.minute == 0 and i + 1 < m.n:
                rows += stop_fill(m, i + 1, min(i + 6, m.n - 1), m.H[i], m.L[i], a[i])
        return rows


def stop_fill(m, j0, j1, hi, lo, a):
    for j in range(j0, j1 + 1):
        up, dn = m.H[j] >= hi, m.L[j] <= lo
        if up and dn:
            return []
        if up:
            return [(j, 1, max(hi, m.O[j]), lo, 1, a)]
        if dn:
            return [(j, -1, min(lo, m.O[j]), hi, 1, a)]
    return []


# ----------------------------------------------------------------- exits
def time_exit(m, tf, i, steps):
    """Hourly index of the close `steps` candles of `tf` after the candle containing i."""
    gid, last = m.tf[tf]
    g = gid[i] + steps
    return last[g] if g < len(last) else -1


def day_close_after(m, i):
    gid, last = m.tf["D1"]
    g = gid[i] if last[gid[i]] > i else gid[i] + 1
    return last[g] if g < len(last) else -1


def simulate(m, ev, tf, x, cost_bps=None):
    """R and exit index for events ev = arrays (i, d, entry, stop, fill, atr)."""
    i, d, en, sp, fill, av = ev
    bps = m.bps if cost_bps is None else cost_bps
    cap = 240 if tf == "H1" else 480
    E = len(i)
    R, xi = np.full(E, np.nan), np.full(E, -1)
    if not E:
        return R, xi
    base = np.where(fill == 1, i, i + 1)
    cols = np.arange(cap + 1)
    for s in range(0, E, 4000):
        sl = slice(s, s + 4000)
        b, dd, e, stp, f, aa = base[sl], d[sl], en[sl], sp[sl], fill[sl], av[sl]
        idx = b[:, None] + cols[None, :]
        inb = idx < m.n
        idc = np.minimum(idx, m.n - 1)
        hh, ll, cc = m.H[idc], m.L[idc], m.C[idc]
        risk = np.abs(e - stp)
        long_ = (dd == 1)[:, None]
        fav = np.where(long_, hh, -ll)              # favourable extreme, sign-adjusted
        adv = np.where(long_, ll, -hh)              # adverse extreme
        ss = (dd * stp)[:, None]
        ee = (dd * e)[:, None]
        stop_hit = (adv <= ss) & inb
        first = lambda mask: np.where(mask.any(1), mask.argmax(1), 10 ** 9)
        out_px = np.full(len(b), np.nan); out_c = np.full(len(b), -1)
        end_col = np.minimum(cap, m.n - 1 - b)
        complete = (m.n - 1 - b) >= 0
        if x in ("X1", "X2", "X3", "X4"):
            k = {"X1": 1, "X2": 2, "X3": 3, "X4": 2}[x]
            tgt = ee + (k * risk)[:, None]
            th = (fav >= tgt) & inb
            th[:, 0] &= (f == 0)
            ts_, tt = first(stop_hit), first(th)
            if x != "X4":
                hit_s = ts_ <= np.minimum(tt, end_col)
                hit_t = ~hit_s & (tt <= end_col)
                out_px = np.where(hit_s, stp, np.where(hit_t, e + dd * k * risk, cc[np.arange(len(b)), end_col]))
                out_c = np.where(hit_s, ts_, np.where(hit_t, tt, end_col))
                r = dd * (out_px - e) / risk
            else:
                p1 = (fav >= ee + risk[:, None]) & inb
                p1[:, 0] &= (f == 0)
                tp = first(p1)
                r = np.empty(len(b)); out_c = np.empty(len(b), int)
                stop_first = ts_ <= np.minimum(tp, end_col)
                be_hit = (adv <= ee) & inb
                for q in range(len(b)):
                    if stop_first[q]:
                        r[q], out_c[q] = -1.0, ts_[q]
                    elif tp[q] > end_col[q]:
                        r[q] = dd[q] * (cc[q, end_col[q]] - e[q]) / risk[q]; out_c[q] = end_col[q]
                    else:
                        t2 = np.nonzero(th[q, tp[q]:end_col[q] + 1])[0]
                        tb = np.nonzero(be_hit[q, tp[q] + 1:end_col[q] + 1])[0]
                        t2 = tp[q] + t2[0] if len(t2) else 10 ** 9
                        tb = tp[q] + 1 + tb[0] if len(tb) else 10 ** 9
                        if t2 < tb and t2 <= end_col[q]:
                            r[q], out_c[q] = 1.5, t2
                        elif tb <= end_col[q]:
                            r[q], out_c[q] = 0.5, tb
                        else:
                            r[q] = 0.5 + 0.5 * dd[q] * (cc[q, end_col[q]] - e[q]) / risk[q]; out_c[q] = end_col[q]
        elif x in ("X5", "X6", "X7"):
            ii = i[sl]
            if x == "X7":
                te = np.array([day_close_after(m, q) for q in ii])
            else:
                te = np.array([time_exit(m, tf, q, 3 if x == "X5" else 10) for q in ii])
            tcol = np.where(te >= 0, te - b, end_col)
            tcol = np.clip(tcol, 0, end_col)
            ts_ = first(stop_hit)
            hit_s = ts_ <= tcol
            out_c = np.where(hit_s, ts_, tcol)
            out_px = np.where(hit_s, stp, cc[np.arange(len(b)), tcol])
            r = dd * (out_px - e) / risk
        else:   # X8 trailing
            prevmax = np.maximum.accumulate(np.concatenate([np.broadcast_to(ee, (len(b), 1)), fav[:, :-1]], 1), axis=1)
            trail = np.maximum(ss, prevmax - (2 * aa)[:, None])
            hit = (adv <= trail) & inb
            th_ = first(hit)
            hit_s = th_ <= end_col
            colx = np.where(hit_s, th_, end_col)
            trail_px = dd * trail[np.arange(len(b)), np.minimum(colx, cap)]
            out_px = np.where(hit_s, trail_px, cc[np.arange(len(b)), end_col])
            out_c = colx
            r = dd * (out_px - e) / risk
        cost = bps * 1e-4 * e / risk
        complete = complete & ((np.asarray(out_c) < end_col) | (b + cap <= m.n - 1))   # unresolved at the data's end: left out
        rr = np.where(complete & (risk > 0), r - cost, np.nan)
        R[sl] = rr
        xi[sl] = b + out_c
    return R, xi


# ----------------------------------------------------------------- rules
def filter_flags(m, ev):
    i, d, en = ev[0], ev[1], ev[2]
    k = m.cday[i]
    f = m.dfeat
    okk = (k >= 0)
    kk = np.maximum(k, 0)
    ok = okk & f["ok"][kk]
    up = d == 1
    out = {
        "F1": np.where(up, f["up50"][kk], ~f["up50"][kk]),
        "F2": np.where(up, f["ha"][kk], ~f["ha"][kk]),
        "F3": np.where(up, f["r252"][kk] > 0, f["r252"][kk] < 0),
        "F4": f["atr"][kk] > f["med"][kk],
        "F5": f["atr"][kk] < f["med"][kk],
        "F6": np.where(up, f["hi20"][kk] - en >= f["atr"][kk], en - f["lo20"][kk] >= f["atr"][kk]),
    }
    return ok, out


def one_at_a_time(i, fill, xi):
    take, last = [], -1
    for q in range(len(i)):
        if i[q] > last or (i[q] == last and not fill[q]):
            take.append(q)
            last = xi[q]
    return np.array(take, dtype=int)


def stats(r):
    n = len(r)
    if n < 2:
        return n, (float(r.mean()) if n else 0.0), 0.0
    sd = r.std(ddof=1)
    return n, float(r.mean()), float(r.mean() / (sd / math.sqrt(n))) if sd > 0 else 0.0


def run_market(name):
    t0 = _time.time()
    m = Market(name)
    out = []
    for v in variants():
        rows = entries(m, v)
        if not rows:
            continue
        rows.sort(key=lambda x: x[0])
        ev = tuple(np.array(col) for col in zip(*rows))
        ev = (ev[0].astype(int), ev[1].astype(int), ev[2], ev[3], ev[4].astype(int), ev[5])
        sims = {x: simulate(m, ev, v[1], x) for x in EXITS}
        ok, flags = filter_flags(m, ev)
        ep = m.ep[ev[0]]
        yr = m.year[ev[0]]
        costR = m.bps * 1e-4 * ev[2] / np.abs(ev[2] - ev[3])
        for ds in DIRSETS:
            dmask = ok & (ev[1] == 1 if ds == "long" else (ev[1] == -1 if ds == "short" else True))
            for fs in FSETS:
                mask = dmask.copy()
                for fn in fs:
                    mask &= flags[fn]
                for x in EXITS:
                    R, xi = sims[x]
                    sel = np.nonzero(mask & ~np.isnan(R))[0]
                    if len(sel) < 30:
                        continue
                    take = sel[one_at_a_time(ev[0][sel], ev[4][sel], xi[sel])]
                    b = take[ep[take] < BUILD_END]
                    if len(b) < 30:
                        continue
                    n, mu, t = stats(R[b])
                    blocks = []
                    for bn, y0, y1 in BLOCKS:
                        bb = b[(yr[b] >= y0) & (yr[b] < y1)]
                        blocks.append((len(bb), float(R[bb].mean()) if len(bb) else 0.0))
                    out.append({"market": name, "v": list(v), "dirs": ds, "f": list(fs), "x": x,
                                "n": n, "mean": mu, "t": t, "dbl": mu - float(costR[b].mean()), "blocks": blocks})
    print(f"  {name}: {m.n} candles, {len(out)} rules with 30+ build trades, {(_time.time() - t0) / 60:.1f} min",
          flush=True)
    return out


def key(r):
    return (r["market"], tuple(r["v"]), r["dirs"], tuple(r["f"]), r["x"])


def neighbours(r):
    fam, tf, n, mode = r["v"]
    out = []
    g = GRID.get(fam)
    if g:
        j = g.index(n)
        for jj in (j - 1, j + 1):
            if 0 <= jj < len(g):
                out.append(dict(r, v=[fam, tf, g[jj], mode]))
    for x in EXIT_NEIGH.get(r["x"], []):
        out.append(dict(r, x=x))
    return [key(q) for q in out]


def build_pass(r, lookup):
    daily = r["v"][1] == "D1"
    if r["n"] < (100 if daily else 200) or r["mean"] < 0.05 or r["dbl"] <= 0:
        return False
    counted = [mu for n, mu in r["blocks"] if n >= 20]
    if not counted or min(counted) <= 0:
        return False
    for nk in neighbours(r):
        q = lookup.get(nk)
        if q is not None and q["mean"] <= 0:
            return False
    return True


# ----------------------------------------------------------------- survivors
def rule_trades(m, r, cache):
    """Hourly entry index, R, exit index and dir of a rule's one-at-a-time trades."""
    v = tuple(r["v"])
    if v not in cache:
        rows = sorted(entries(m, v), key=lambda x: x[0])
        ev = tuple(np.array(col) for col in zip(*rows))
        cache[v] = (ev[0].astype(int), ev[1].astype(int), ev[2], ev[3], ev[4].astype(int), ev[5])
    ev = cache[v]
    R, xi = simulate(m, ev, v[1], r["x"])
    ok, flags = filter_flags(m, ev)
    ds = r["dirs"]
    mask = ok & (ev[1] == 1 if ds == "long" else (ev[1] == -1 if ds == "short" else True)) & ~np.isnan(R)
    for fn in r["f"]:
        mask &= flags[fn]
    sel = np.nonzero(mask)[0]
    take = sel[one_at_a_time(ev[0][sel], ev[4][sel], xi[sel])]
    return ev, take, R, xi


def daily_series(m, xi, R, idx, lo, hi):
    out = {}
    for q in idx:
        t = m.ts[min(xi[q], m.n - 1)]
        if lo <= t.timestamp() < hi:
            d = t.date()
            out[d] = out.get(d, 0.0) + R[q]
    return out


def corr(a, b):
    days = sorted(set(a) | set(b))
    if len(days) < 30:
        return 0.0
    x = np.array([a.get(d, 0.0) for d in days]); y = np.array([b.get(d, 0.0) for d in days])
    if x.std() == 0 or y.std() == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def shuffle_p(m, r, ev, take, R):
    rng = np.random.default_rng(SEED)
    b = take[m.ep[ev[0][take]] < BUILD_END]
    actual = R[b].mean()
    risks = np.abs(ev[2][b] - ev[3][b])
    dirs = ev[1][b]
    atrs = ev[5][b]
    pool = np.nonzero((m.ep < BUILD_END) & (np.arange(m.n) < m.n - 500))[0]
    tf = r["v"][1]
    pool = pool[~np.isnan(m.atr[tf][m.tf[tf][0][pool]])] if tf != "H1" else pool
    hits = 0
    for s in range(SHUFFLES):
        ii = np.sort(rng.choice(pool, len(b), replace=False))
        en = m.C[ii]
        ev2 = (ii, dirs, en, en - dirs * risks, np.zeros(len(b), int), atrs)
        R2, _ = simulate(m, ev2, tf, r["x"])
        if np.nanmean(R2) >= actual:
            hits += 1
    return (hits + 1) / (SHUFFLES + 1)


def reference_streams():
    """Daily R in 2020-26 of each live and shadow strategy, by its own code."""
    sys.path.insert(0, HERE)
    import similar_setups as SS
    lo = datetime(2020, 1, 1, tzinfo=UTC)
    out = {}

    def from_journal(j, strat):
        d = {}
        for e in j:
            if e.get("strategy", "trend") == strat and e.get("exit_time") and e.get("r") is not None:
                t = datetime.fromisoformat(e["exit_time"])
                if t >= lo:
                    d[t.date()] = d.get(t.date(), 0.0) + e["r"]
        return d

    gold = S.closed_h1(S.load_history(S.CONFIG), datetime.now(UTC))
    j = SS.replay(S.CONFIG, gold)
    out["gold trend"] = from_journal(j, "trend")
    out["gold inside-day"] = from_journal(j, "inside_day")
    for key_, mk, strat in (("btc", "btcusd", "btc_trend"), ("eth", "ethusd", "eth_inside_day")):
        cfg = dict(S.CONFIG, **S.CONFIG["markets"][key_]["cfg"])
        ts, o, h, l, c = load("Bitcoin" if key_ == "btc" else "Ether")
        bars = [{"t": t, "o": a, "h": b, "l": cc, "c": dd} for t, a, b, cc, dd in zip(ts, o, h, l, c)]
        out[strat] = from_journal(SS.replay(cfg, bars, scale=True), strat)
    ts, o, h, l, c = load("S&P 500")
    sess = {}
    for t, a, b, cc, dd in zip(ts, o, h, l, c):
        lt = t.astimezone(NY)
        if 9 <= lt.hour < 16:
            k = lt.date()
            s = sess.setdefault(k, {"o": a, "h": b, "l": cc, "c": dd})
            s["h"], s["l"], s["c"] = max(s["h"], b), min(s["l"], cc), dd
    days = [dict(v, t=datetime(k.year, k.month, k.day, tzinfo=UTC),
                 t_close=datetime(k.year, k.month, k.day, 16, tzinfo=NY).astimezone(UTC)) for k, v in sorted(sess.items())]
    d = {}
    for tr in S.ibs_trades(days, 1.0):
        if tr["t_exit"] >= lo:
            d[tr["t_exit"].date()] = d.get(tr["t_exit"].date(), 0.0) + tr["r"]
    out["us_ibs"] = d
    return out


def describe(r):
    fam, tf, n, mode = r["v"]
    ent = {"breakout": f"{tf} {n}-candle breakout", "pullback": f"{tf} pullback to the {n} EMA",
           "inside": f"{tf} inside-candle break", "ibs": "D1 IBS extreme", "orb": "first-hour range break",
           "run": f"{tf} {n} closes in a row, {mode}", "squeeze": f"{tf} squeeze breakout"}[fam]
    xs = {"X1": "1R target", "X2": "2R target", "X3": "3R target", "X4": "half 1R, rest 2R",
          "X5": "3-candle exit", "X6": "10-candle exit", "X7": "next daily close", "X8": "2-ATR trail"}[r["x"]]
    fl = "+".join(r["f"]) or "no filter"
    return f"{r['market']}: {ent}, {r['dirs']}, {fl}, {xs}"


def main():
    t0 = _time.time()
    names = list(MARKETS)
    print(f"Batch 1: {len(names)} markets x {len(variants()) * len(DIRSETS) * len(FSETS) * len(EXITS)} rules", flush=True)
    with ProcessPoolExecutor(max_workers=8) as px:
        res = [r for rows in px.map(run_market, names) for r in rows]
    lookup = {key(r): r for r in res}
    passed = sorted((r for r in res if build_pass(r, lookup)), key=lambda r: -r["t"])
    generated = len(names) * len(variants()) * len(DIRSETS) * len(FSETS) * len(EXITS)
    print(f"{generated} rules generated, {len(res)} with 30+ build trades, {len(passed)} pass the build test", flush=True)

    mk, caches, listed, lseries, log = {}, {}, [], [], []
    for r in passed:
        if len(listed) >= MAX_CUT:
            break
        m = mk.setdefault(r["market"], Market(r["market"]))
        ev, take, R, xi = rule_trades(m, r, caches.setdefault(r["market"], {}))
        ser = daily_series(m, xi, R, take, 0, BUILD_END)
        cmax = max((corr(ser, s) for s in lseries), default=0.0)
        if cmax > 0.5:
            log.append((describe(r), f"skipped: correlation {cmax:.2f} with a listed rule"))
            continue
        p = shuffle_p(m, r, ev, take, R)
        if p >= 0.05:
            log.append((describe(r), f"skipped: random entries p = {p:.3f}"))
            continue
        listed.append((r, m, ev, take, R, xi, p)); lseries.append(ser)
        log.append((describe(r), f"listed (random p = {p:.3f})"))
    K = len(listed)
    print(f"{K} sent to the cut", flush=True)

    refs = reference_streams() if K else {}
    alpha = 0.05 / K if K else 0
    cut_rows = []
    for r, m, ev, take, R, xi, p in listed:
        c = take[m.ep[ev[0][take]] >= BUILD_END]
        n, mu, t = stats(R[c])
        pval = 0.5 * math.erfc(t / math.sqrt(2)) if n >= 2 else 1.0
        yr = m.year[ev[0][c]]
        parts, same = [], True
        for bn, y0, y1 in CUT_BLOCKS:
            bb = c[(yr >= y0) & (yr < y1)]
            if len(bb) >= 20:
                same &= R[bb].mean() > 0
            parts.append(f"{bn} {R[bb].mean():+.3f} ({len(bb)})" if len(bb) else f"{bn} none")
        ser = daily_series(m, xi, R, c, BUILD_END, 1e12)
        cors = {k: corr(ser, s) for k, s in refs.items()}
        ok = n >= 2 and mu >= 0.05 and pval < alpha and same and all(v < 0.3 for v in cors.values())
        cut_rows.append({"rule": describe(r), "spec": {k: r[k] for k in ("market", "v", "dirs", "f", "x")},
                         "build": {"n": r["n"], "mean": round(r["mean"], 3), "t": round(r["t"], 2), "random_p": round(p, 3),
                                   "blocks": r["blocks"]},
                         "cut": {"n": n, "mean": round(mu, 3), "p": float(f"{pval:.3g}"), "periods": parts,
                                 "corr": {k: round(v, 2) for k, v in cors.items()}},
                         "verdict": "PASS" if ok else "fail"})
        print(f"  {describe(r)}\n     build {r['n']} {r['mean']:+.3f}R t {r['t']:.1f} | cut {n} {mu:+.3f}R p={pval:.2g} "
              f"| {' | '.join(parts)} | max corr {max(cors.values(), default=0):.2f} | {'PASS' if ok else 'fail'}",
              flush=True)
    summary = {"generated": generated, "with_30_build_trades": len(res), "build_pass": len(passed), "cut": K,
               "alpha": alpha, "passed": sum(1 for x in cut_rows if x["verdict"] == "PASS"),
               "minutes": round((_time.time() - t0) / 60, 1), "rules": cut_rows, "list_log": log,
               "build_pass_top": [dict(describe=describe(r), n=r["n"], mean=round(r["mean"], 3), t=round(r["t"], 2))
                                  for r in passed[:60]]}
    json.dump(summary, open(os.path.join(HERE, "factory_batch1.json"), "w"), indent=1, default=str)
    print(f"\n{summary['passed']} of {K} pass the cut; {summary['minutes']} min", flush=True)


if __name__ == "__main__":
    main()
