"""Round 11: published anomalies from SSRN and the academic literature.

Ideas were collected from SSRN, journals and quant-research sites, checked
against the 1,137 configurations already tested, and cut to the nine below:
each is mechanically new to this project and has published evidence. Rules are
taken from the papers as written, adapted only to hourly candles (the papers
mostly use 30-minute or 1-minute data). Fixed before any result was seen.

  L1 Gold intraday momentum      Gao, Han, Li & Zhou (JFE 2018); Chinese gold
                                 futures evidence. Return from the previous
                                 17:00 NY close to the end of the first COMEX
                                 hour (09:00 NY) sets the side of the last full
                                 COMEX hour (12:00-13:00 NY).
  L2 Bitcoin intraday momentum   Shen, Urquhart & Wang (Bitcoin intraday
                                 time-series momentum). Sign of the first UTC
                                 hour (00-01) sets the side of the last (23-24).
  L3 Bitcoin 21-23 UTC long      Padysak & Vojtko (SSRN), QuantifiedStrategies.
                                 Every day. Published with data to 2022, so
                                 2023-26 is after publication.
  L4 Bitcoin Monday Asia open    Concretum (2025). Long from Sunday 19:00 New
                                 York for 24 hours.
  L5 Gold between the fixes      Bell (SSRN 6077836). Long from the 15:00 London
                                 PM fix to the next 10:30 AM fix (hourly: in at
                                 15:00, out at 11:00 London).
  L6-L8 Noise-area momentum      Zarattini, Aziz & Barbon (SSRN 4824172) on
                                 gold, Bitcoin and the Nasdaq 100 (where it was
                                 published: a sanity check of the hourly
                                 adaptation). Band = session open (or previous
                                 close, whichever is further) +/- the average
                                 move from the open at that hour over the last
                                 14 sessions. An hourly close outside the band
                                 enters at the next open; a close back inside
                                 the band exits; flat at the session end.
  L9 Bitcoin at a 20-day extreme Padysak & Vojtko (SSRN 4081000): Bitcoin
                                 trends at its maximum and bounces at its
                                 minimum. Long the next UTC day after a close
                                 at a 20-day high or a 20-day low.

Results are in basis points per trade after costs (gold 1.75, Bitcoin 5,
Nasdaq 1.0), because most of these rules have no stop to measure R against.
Pass: at least 150 trades, a positive average in every period with 10+ trades
(2008-15, 2016-22, 2023-24, 2025-26), and one-sided p < 0.05 / 9 = 0.0056.
"""
import csv
import math
import os
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import round10_btc_checks as B  # noqa: E402
import round10_markets as R10  # noqa: E402

UTC, NY, UK = timezone.utc, ZoneInfo("America/New_York"), ZoneInfo("Europe/London")
D = lambda y: datetime(y, 1, 1, tzinfo=UTC)
PERIODS = [("2008-15", D(2008), D(2016)), ("2016-22", D(2016), D(2023)),
           ("2023-24", D(2023), D(2025)), ("2025-26", D(2025), D(2030))]
N_TESTS = 9
ALPHA = 0.05 / N_TESTS
H = timedelta(hours=1)


def gold():
    files = R10.MARKETS["XAUUSD (reference)"][0]
    return sorted((b for f in files for b in R10.load(os.path.join(R10.DATA, f))), key=lambda b: b["t"])


def by_time(bars):
    return {b["t"]: b for b in bars}


def trade(out, t, d, entry, exit_, cost_bps):
    out.append({"t": t, "d": d, "bps": (exit_ / entry - 1) * d * 1e4 - cost_bps})


# --------------------------------------------------------------------------
def l1_gold_intraday(bars, cost):
    idx, out = by_time(bars), []
    days = sorted({b["t"].astimezone(NY).date() for b in bars})
    for prev, day in zip(days, days[1:]):
        def at(d_, hh):
            return idx.get(datetime(d_.year, d_.month, d_.day, hh, tzinfo=NY).astimezone(UTC))
        c_prev = at(prev, 16)       # candle 16:00-17:00 NY closes the previous trading day
        first = at(day, 8)          # 08:00-09:00 NY: first COMEX hour
        last = at(day, 12)          # 12:00-13:00 NY: last full COMEX hour
        if not (c_prev and first and last) or day.weekday() >= 5:
            continue
        r1 = first["c"] / c_prev["c"] - 1
        if r1 == 0:
            continue
        trade(out, last["t"], 1 if r1 > 0 else -1, last["o"], last["c"], cost)
    return out


def l2_btc_intraday(bars, cost):
    idx, out = by_time(bars), []
    for b in bars:
        if b["t"].hour != 0:
            continue
        last = idx.get(b["t"] + 23 * H)
        r1 = b["c"] / b["o"] - 1
        if last and r1:
            trade(out, last["t"], 1 if r1 > 0 else -1, last["o"], last["c"], cost)
    return out


def l3_btc_2123(bars, cost):
    idx, out = by_time(bars), []
    for b in bars:
        if b["t"].hour == 21 and (b["t"] + H) in idx:
            trade(out, b["t"], 1, b["o"], idx[b["t"] + H]["c"], cost)
    return out


def l4_btc_monday_asia(bars, cost):
    idx, out = by_time(bars), []
    for b in bars:
        t = b["t"].astimezone(NY)
        if t.weekday() == 6 and t.hour == 19:
            x = idx.get(b["t"] + 23 * H)
            if x:
                trade(out, b["t"], 1, b["o"], x["c"], cost)
    return out


def l5_gold_fixes(bars, cost):
    out, i, n = [], 0, len(bars)
    while i < n:
        t = bars[i]["t"].astimezone(UK)
        if t.hour == 15 and t.weekday() < 5:
            j = i + 1
            while j < n and not (bars[j]["t"].astimezone(UK).hour == 10 and bars[j]["t"] > bars[i]["t"] + 12 * H):
                j += 1
            if j < n and bars[j]["t"] - bars[i]["t"] < timedelta(days=4):
                trade(out, bars[i]["t"], 1, bars[i]["o"], bars[j]["c"], cost)
                i = j
        i += 1
    return out


def noise_area(bars, cost, session_of, look=14):
    """Zarattini et al. on hourly candles. session_of(t) -> session key or None."""
    sessions, cur = [], None
    for b in bars:
        k = session_of(b["t"])
        if k is None:
            continue
        if not sessions or sessions[-1][0] != k:
            sessions.append((k, []))
        sessions[-1][1].append(b)
    out, hist = [], []          # hist: per session, list of |close/open-1| by hour index
    prev_close = None
    for k, sb in sessions:
        o = sb[0]["o"]
        moves = [abs(x["c"] / o - 1) for x in sb]
        if len(hist) >= look and prev_close:
            up_ref, dn_ref = max(o, prev_close), min(o, prev_close)
            pos, entry, t0 = 0, None, None
            for h in range(len(sb) - 1):
                vals = [m[h] for m in hist[-look:] if len(m) > h]
                if len(vals) < look // 2:
                    continue
                sig = sum(vals) / len(vals)
                up, dn = up_ref * (1 + sig), dn_ref * (1 - sig)
                c = sb[h]["c"]
                want = 1 if c > up else -1 if c < dn else 0
                if pos and (want != pos):            # back inside the band, or through the other side
                    trade(out, t0, pos, entry, sb[h + 1]["o"], cost)
                    pos = 0
                if not pos and want:
                    pos, entry, t0 = want, sb[h + 1]["o"], sb[h + 1]["t"]
            if pos:
                trade(out, t0, pos, entry, sb[-1]["c"], cost)
        hist.append(moves)
        prev_close = sb[-1]["c"]
    return out


def gold_session(t):
    x = t.astimezone(NY) + timedelta(hours=7)      # 17:00 NY roll
    return x.date() if x.weekday() < 5 else None


def btc_session(t):
    return t.date()


def ndx_session(t):
    x = t.astimezone(NY)
    return x.date() if x.weekday() < 5 and 9 <= x.hour < 16 else None


def l9_btc_extremes(bars, cost, look=20):
    days = {}
    for b in bars:
        days.setdefault(b["t"].date(), []).append(b)
    keys = sorted(days)
    closes = [days[k][-1]["c"] for k in keys]
    out = []
    for i in range(look, len(keys) - 1):
        win = closes[i - look + 1:i + 1]
        if closes[i] in (max(win), min(win)) and len(days[keys[i + 1]]) >= 20:
            nxt = days[keys[i + 1]]
            trade(out, nxt[0]["t"], 1, nxt[0]["o"], nxt[-1]["c"], cost)
    return out


# --------------------------------------------------------------------------
def judge(trades):
    x = [t["bps"] for t in trades]
    n = len(x)
    if n < 3:
        return {"n": n}
    m, sd = st.mean(x), st.stdev(x)
    tstat = m / (sd / math.sqrt(n)) if sd else 0
    p = 0.5 * math.erfc(tstat / math.sqrt(2))
    per = {}
    for pn, a, b in PERIODS:
        y = [t["bps"] for t in trades if a <= t["t"] < b]
        per[pn] = (len(y), st.mean(y) if y else None)
    counted = [v for k, v in per.values() if k >= 10]
    ok = n >= 150 and m > 0 and len(counted) >= 2 and all(v > 0 for v in counted) and p < ALPHA
    years = {}
    for t in trades:
        years[t["t"].year] = years.get(t["t"].year, 0) + t["bps"]
    return {"n": n, "avg": m, "win": 100 * sum(v > 0 for v in x) / n, "p": p, "per": per, "ok": ok,
            "pos_years": sum(v > 0 for v in years.values()), "years": len(years),
            "per_week": n / max(1, (trades[-1]["t"] - trades[0]["t"]).days / 7)}


def main():
    g = gold()
    btc = B.load_247(os.path.join(R10.DATA, "markets", "btcusd_h1.csv.gz"))
    ndx = B.load_247(os.path.join(R10.DATA, "markets", "usatechidxusd_h1.csv.gz"))
    tests = [
        ("L1 Gold intraday momentum", lambda: l1_gold_intraday(g, 1.75)),
        ("L2 Bitcoin intraday momentum", lambda: l2_btc_intraday(btc, 5)),
        ("L3 Bitcoin 21-23 UTC long", lambda: l3_btc_2123(btc, 5)),
        ("L4 Bitcoin Monday Asia open", lambda: l4_btc_monday_asia(btc, 5)),
        ("L5 Gold long between the fixes", lambda: l5_gold_fixes(g, 1.75)),
        ("L6 Noise-area momentum, gold", lambda: noise_area(g, 1.75, gold_session)),
        ("L7 Noise-area momentum, Bitcoin", lambda: noise_area(btc, 5, btc_session)),
        ("L8 Noise-area momentum, Nasdaq 100", lambda: noise_area(ndx, 1.0, ndx_session)),
        ("L9 Bitcoin at a 20-day extreme", lambda: l9_btc_extremes(btc, 5)),
    ]
    rows = []
    for name, fn in tests:
        tr = sorted(fn(), key=lambda t: t["t"])
        s = judge(tr)
        if s["n"] < 3:
            print(f"{name}: too few trades ({s['n']})"); continue
        gross = st.mean(t["bps"] + (1.75 if "Gold" in name or "gold" in name else 1.0 if "Nasdaq" in name else 5) for t in tr)
        row = {"test": name, "n": s["n"], "per_week": round(s["per_week"], 2), "win": round(s["win"], 1),
               "avg_bps_net": round(s["avg"], 2), "avg_bps_gross": round(gross, 2), "p": f"{s['p']:.2g}",
               **{f"{pn}_bps": (round(v, 2) if v is not None else "") for pn, (k, v) in s["per"].items()},
               "pos_years": f"{s['pos_years']}/{s['years']}", "verdict": "PASS" if s["ok"] else ""}
        rows.append(row)
        print(f"{name:36s} n={s['n']:5d} ({s['per_week']:.1f}/wk) win={s['win']:4.1f}% net={s['avg']:+6.2f}bp gross={gross:+6.2f}bp | "
              + " ".join(f"{pn} {('%+.2f' % v) if v is not None else '  -  '}" for pn, (k, v) in s["per"].items())
              + f" | yrs+ {s['pos_years']}/{s['years']} | p={s['p']:.2g} {row['verdict']}", flush=True)
    with open(os.path.join(HERE, "results_round11_literature.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
