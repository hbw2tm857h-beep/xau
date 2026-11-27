"""Incremental XAUUSD data updater (Dukascopy public datafeed, BID minute candles -> M15).

Appends complete UTC days after the last bar in data/xauusd_m15_<year>.csv.gz. The
values match the existing files exactly (same feed, same BID side). H1 is then built
from M15 by ``data.load_h1`` for anything after the H1 files end, so one feed keeps
the whole lab current. Rate-limited politely; failures are reported, never fatal.
"""
from __future__ import annotations

import gzip
import io
import lzma
import struct
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from .config import DATA

URL = "https://datafeed.dukascopy.com/datafeed/XAUUSD/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"  # month is 0-based
POINT = 1000.0


def _get(url: str, tries: int = 6) -> bytes | None:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "edgelab-research/0.2"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            time.sleep(2 + 3 * i)          # 429 / 5xx: back off
        except Exception:
            time.sleep(2 + 3 * i)
    return None


def fetch_day(day: date) -> pd.DataFrame | None:
    """Minute candles for one UTC day -> M15 OHLC. Empty frame for no-trade days, None on failure."""
    b = _get(URL.format(y=day.year, m=day.month - 1, d=day.day))
    if b is None:
        return None
    if not b:
        return pd.DataFrame(columns=["time_utc", "open", "high", "low", "close"])
    raw = lzma.decompress(b)
    rows = [struct.unpack(">5if", raw[i:i + 24]) for i in range(0, len(raw) - 23, 24)]
    base = datetime(day.year, day.month, day.day)
    m = pd.DataFrame(rows, columns=["s", "o", "c", "l", "h", "v"])
    m = m[m["v"] > 0]                        # zero-volume minutes are filler, not trades
    if not len(m):
        return pd.DataFrame(columns=["time_utc", "open", "high", "low", "close"])
    m["t"] = pd.to_datetime(base) + pd.to_timedelta(m["s"], unit="s")
    g = m.groupby(m["t"].dt.floor("15min"))
    out = pd.DataFrame({"open": g["o"].first() / POINT, "high": g["h"].max() / POINT,
                        "low": g["l"].min() / POINT, "close": g["c"].last() / POINT})
    out = out.reset_index().rename(columns={"t": "time_utc"})
    out["time_utc"] = out["time_utc"].dt.strftime("%Y-%m-%d %H:%M")
    return out.round(3)


def _year_file(y: int):
    return DATA / f"xauusd_m15_{y}.csv.gz"


def last_bar() -> pd.Timestamp:
    files = sorted(DATA.glob("xauusd_m15_*.csv.gz"))
    df = pd.read_csv(files[-1])
    return pd.Timestamp(df["time_utc"].iloc[-1])


def update(until: date | None = None, max_days: int = 120, verbose: bool = True) -> dict:
    """Fetch complete days after the last stored bar up to ``until`` (default: yesterday UTC)."""
    until = until or (datetime.now(timezone.utc).date() - timedelta(days=1))
    start = last_bar().date()                # re-fetch the last stored day (it may have been partial)
    days = [start + timedelta(days=i) for i in range((until - start).days + 1)][:max_days]
    got, failed = {}, []
    for d in days:
        if d.weekday() == 5:                 # Saturday: market closed
            continue
        df = fetch_day(d)
        if df is None:
            failed.append(str(d))
            continue
        if len(df):
            got.setdefault(d.year, []).append(df)
        time.sleep(0.4)
    added = 0
    for y, parts in got.items():
        new = pd.concat(parts, ignore_index=True)
        p = _year_file(y)
        old = pd.read_csv(p) if p.exists() else pd.DataFrame(columns=new.columns)
        merged = (pd.concat([old, new], ignore_index=True).drop_duplicates("time_utc", keep="last")
                  .sort_values("time_utc"))
        added += len(merged) - len(old)
        buf = io.StringIO()
        merged.to_csv(buf, index=False)
        with gzip.open(p, "wt") as fh:
            fh.write(buf.getvalue())
    res = {"from": str(start), "to": str(until), "days_requested": len(days), "bars_added": int(added),
           "failed_days": failed, "last_bar": str(last_bar())}
    if verbose:
        print(f"[update] {res}")
    return res
