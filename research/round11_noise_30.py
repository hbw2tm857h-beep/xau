"""Round 11: the Nasdaq noise-area pass, re-tested on candles that start at
09:30 New York - the US cash open - as a live feed such as QQQ delivers them
(09:30, 10:30 ... 14:30, then a half-hour 15:30-16:00 candle). The round 11
test used Dukascopy's on-the-hour candles; a live feed cannot match those, so
the rules must hold on these too. Rules, costs and pass mark unchanged.
Input: Dukascopy 30-minute Nasdaq 100 CFD candles (data/markets/usatechidxusd_m30.csv.gz)."""
import csv, gzip, os, sys, statistics as st
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import round11_literature as R11  # noqa: E402
NY, UTC = ZoneInfo("America/New_York"), timezone.utc
PATH = os.path.join(HERE, "..", "data", "markets", "usatechidxusd_m30.csv.gz")


def cash_hours(path=PATH):
    groups = {}
    with gzip.open(path, "rt") as f:
        for r in csv.DictReader(f):
            t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            x = t.astimezone(NY)
            mins = x.hour * 60 + x.minute
            if x.weekday() >= 5 or not (570 <= mins < 960):      # 09:30-16:00 NY
                continue
            slot = (mins - 570) // 60                              # 0 = 09:30-10:30 ... 6 = 15:30-16:00
            o, h, l, c = (float(r[k]) for k in ("open", "high", "low", "close"))
            if h - l <= 0 and o == c:
                continue
            k = (x.date(), slot)
            g = groups.get(k)
            if g is None:
                start = datetime(x.year, x.month, x.day, 9, 30, tzinfo=NY).astimezone(UTC)
                groups[k] = {"t": start + timedelta(hours=slot), "o": o, "h": h, "l": l, "c": c, "n": 1}
            else:
                g["h"] = max(g["h"], h); g["l"] = min(g["l"], l); g["c"] = c; g["n"] += 1
    # keep only complete sessions (7 candles), as a live feed would deliver them
    by_day = {}
    for (d, s), g in sorted(groups.items()):
        by_day.setdefault(d, []).append(g)
    return [g for d, gs in sorted(by_day.items()) if len(gs) == 7 for g in gs]


def session(t):
    return t.astimezone(NY).date()


def main():
    bars = cash_hours()
    print(f"{len(bars):,} candles, {len(bars)//7:,} full sessions, {bars[0]['t']:%Y-%m-%d} -> {bars[-1]['t']:%Y-%m-%d}")
    for cost in (1.0, 2.0, 3.0):
        tr = R11.noise_area(bars, cost, session)
        s = R11.judge(tr)
        print(f"09:30 candles, {cost:g} bp: n={s['n']} ({s['per_week']:.1f}/wk) net={s['avg']:+.2f}bp win={s['win']:.1f}% | "
              + " ".join(f"{pn} {('%+.2f' % v) if v is not None else '  -  '}" for pn, (k, v) in s["per"].items())
              + f" | yrs+ {s['pos_years']}/{s['years']} | p={s['p']:.2g}")
        if cost == 1.0:
            lo = [t["bps"] for t in tr if t["d"] == 1]; sh = [t["bps"] for t in tr if t["d"] == -1]
            print(f"   longs {st.mean(lo):+.2f}bp (n={len(lo)}) | shorts {st.mean(sh):+.2f}bp (n={len(sh)})")


if __name__ == "__main__":
    main()


def check_live_code():
    """signals.noise_trades (the bot) must match round11_literature.noise_area."""
    import signals as S
    bars = cash_hours()
    a = R11.noise_area(bars, 1.0, session)
    b = S.noise_trades(bars, 1.0, 14)
    same = len(a) == len(b) and all(abs(x["bps"] - y["bps"]) < 1e-9 and x["d"] == y["d"] for x, y in zip(a, b))
    rs = [t["r"] for t in b]
    print(f"live code: {len(b)} trades, identical to research: {same} | avg R {st.mean(rs):+.4f}, "
          f"win {100 * sum(r > 0 for r in rs) / len(rs):.0f}%, median 1R = {st.median(t['sigma'] for t in b) * 1e4:.1f} bp")


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "check":
    check_live_code()
