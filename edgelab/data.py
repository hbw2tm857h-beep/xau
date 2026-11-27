"""Historical data loading, cleaning, multi-timeframe construction.

Conventions
-----------
* Every frame is indexed 0..n-1 with columns ``t`` (bar OPEN time, UTC, tz-naive)
  and ``tc`` (bar CLOSE time = the moment the bar's information becomes known).
* Higher-timeframe (H4, D1) bars follow the gold convention of a 17:00 New York
  daily close. An HTF bar is attached to a lower-timeframe bar only when the HTF
  bar's *scheduled* close is <= the lower bar's close (``merge_asof`` backward),
  so a still-forming daily candle is never visible.
"""
from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DATA

H1_FILES = ["xauusd_h1_2003_2007.csv.gz", "xauusd_h1_2008_2015.csv", "xauusd_h1.csv"]


def _read(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["t"] = pd.to_datetime(df["time_utc"])
    return df.drop(columns=["time_utc"])


def clean(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Drop duplicate stamps, flat (no-trade) bars and weekend bars."""
    df = df.sort_values("t").drop_duplicates("t", keep="last")
    flat = (df["high"] == df["low"])
    df = df[~flat]
    dow = df["t"].dt.dayofweek
    keep = (dow < 5) | ((dow == 6) & (df["t"].dt.hour >= 21))  # Sat never; Sun after open
    df = df[keep]
    df = df.reset_index(drop=True)
    df["tc"] = df["t"] + pd.Timedelta(minutes=minutes)
    return df[["t", "tc", "open", "high", "low", "close"]]


def load_h1(extend: bool = True) -> pd.DataFrame:
    parts = [_read(DATA / f) for f in H1_FILES if (DATA / f).exists()]
    df = clean(pd.concat(parts, ignore_index=True), 60)
    if extend:
        df = extend_h1_with_m15(df, load_m15())
    vol_path = DATA / "volume" / "xauusd_h1_vol.csv.gz"
    if vol_path.exists():
        v = _read(vol_path)
        df = df.merge(v, on="t", how="left")
    else:
        df["volume"] = np.nan
    return df


def extend_h1_with_m15(h1: pd.DataFrame, m15: pd.DataFrame) -> pd.DataFrame:
    """Append H1 bars built from M15 for any period after the H1 files end (keeps data current)."""
    last = h1["t"].max()
    tail = m15[m15["t"] >= last + pd.Timedelta(hours=1)]
    if not len(tail):
        return h1
    g = tail.groupby(tail["t"].dt.floor("h"))
    add = pd.DataFrame({"t": g["t"].first().dt.floor("h"), "open": g["open"].first(), "high": g["high"].max(),
                        "low": g["low"].min(), "close": g["close"].last(), "n": g["open"].size()})
    add = add[add["n"] == 4].drop(columns="n").reset_index(drop=True)   # complete hours only
    add["tc"] = add["t"] + pd.Timedelta(hours=1)
    add["volume"] = np.nan
    return pd.concat([h1, add[h1.columns]], ignore_index=True)


def load_m15() -> pd.DataFrame:
    files = sorted(DATA.glob("xauusd_m15_*.csv.gz"))
    df = pd.concat([_read(f) for f in files], ignore_index=True)
    return clean(df, 15)


def _ny_session_key(t: pd.Series, hours: int) -> pd.Series:
    """Bucket UTC open times into HTF bins anchored on 17:00 New York."""
    ny = t.dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    shifted = (ny + pd.Timedelta(hours=7)).dt.tz_localize(None)  # 17:00 NY -> 00:00
    return shifted.dt.floor(f"{hours}h")


def resample(df: pd.DataFrame, hours: int) -> pd.DataFrame:
    """Build H4 (hours=4) or D1 (hours=24) bars from a lower timeframe.

    ``tc`` is the *scheduled* close of the bin converted back to UTC, which is
    conservative when the last constituent bar is missing.
    """
    key = _ny_session_key(df["t"], hours)
    g = df.groupby(key, sort=True)
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
        "t": g["t"].first(), "n_bars": g["open"].size(),
    })
    if "volume" in df:
        out["volume"] = g["volume"].sum(min_count=1)
    # scheduled close: bin start + hours, in shifted-NY clock -> back to UTC
    bin_end_ny = (out.index + pd.Timedelta(hours=hours) - pd.Timedelta(hours=7))
    out["tc"] = (pd.DatetimeIndex(bin_end_ny).tz_localize("America/New_York", ambiguous="NaT",
                                                          nonexistent="shift_forward")
                 .tz_convert("UTC").tz_localize(None))
    # fallback for ambiguous DST stamps: last bar close
    last_close = g["t"].last() + (df["tc"].iloc[0] - df["t"].iloc[0])
    out["tc"] = out["tc"].fillna(pd.Series(last_close.values, index=out.index))
    # a bin with only a couple of bars (holiday/weekend stub) is merged away
    out = out[out["n_bars"] >= (2 if hours <= 4 else 6)]
    return out.reset_index(drop=True)[["t", "tc", "open", "high", "low", "close", "n_bars"]
                                       + (["volume"] if "volume" in out else [])]


def attach_htf(low: pd.DataFrame, high: pd.DataFrame, prefix: str, cols: list[str]) -> pd.DataFrame:
    """Attach the last *completed* HTF row to each lower-TF row (no look-ahead)."""
    h = high[["tc"] + cols].rename(columns={c: f"{prefix}{c}" for c in cols})
    h = h.rename(columns={"tc": f"{prefix}tc"}).sort_values(f"{prefix}tc")
    merged = pd.merge_asof(low.sort_values("tc"), h, left_on="tc", right_on=f"{prefix}tc",
                           direction="backward", allow_exact_matches=True)
    return merged


# ---------------------------------------------------------------------------
# Scheduled high-impact events (for news-volatility categories and cost model)
# ---------------------------------------------------------------------------

def _first_fridays(start: int, end: int) -> list[pd.Timestamp]:
    out = []
    for y in range(start, end + 1):
        for m in range(1, 13):
            d = pd.Timestamp(year=y, month=m, day=1)
            d += pd.Timedelta(days=(4 - d.dayofweek) % 7)
            out.append(d)
    return out


@lru_cache(maxsize=1)
def event_windows() -> pd.DataFrame:
    """UTC hour windows [start, end) around FOMC (19:00 NY... ), CPI and NFP (08:30 NY).

    Release times are fixed in New York time and converted to UTC per date, so
    DST is handled. Windows span 1h before to 2h after the release.
    """
    rows = []
    macro = DATA / "macro"

    def add(dates, hh, mm, kind):
        for d in dates:
            ts = pd.Timestamp(f"{pd.Timestamp(d).date()} {hh:02d}:{mm:02d}").tz_localize(
                "America/New_York").tz_convert("UTC").tz_localize(None)
            rows.append((ts - pd.Timedelta(hours=1), ts + pd.Timedelta(hours=2), kind))

    for fname in ["fomc_dates_2003_2007.json", "fomc_dates.json"]:
        p = macro / fname
        if p.exists():
            add(json.loads(p.read_text()), 14, 0, "FOMC")
    p = macro / "cpi_release_dates.json"
    if p.exists():
        add(json.loads(p.read_text()), 8, 30, "CPI")
    add(_first_fridays(2003, 2026), 8, 30, "NFP")
    return pd.DataFrame(rows, columns=["start", "end", "kind"]).sort_values("start").reset_index(drop=True)


def mark_events(t: pd.Series) -> pd.Series:
    """Return the event kind active at each timestamp ('' if none)."""
    ev = event_windows()
    idx = np.searchsorted(ev["start"].values, t.values, side="right") - 1
    out = np.full(len(t), "", dtype=object)
    ok = idx >= 0
    ends = ev["end"].values[np.clip(idx, 0, None)]
    hit = ok & (t.values < ends)
    out[hit] = ev["kind"].values[idx[hit]]
    return pd.Series(out, index=t.index)


def load_macro_daily() -> pd.DataFrame:
    """Daily macro series, shifted one day (published after the close) to stay causal."""
    frames = []
    for name in ["DFII10", "DTWEXBGS", "VIXCLS", "GVZCLS"]:
        p = DATA / "macro" / f"{name}.csv"
        if not p.exists():
            continue
        s = pd.read_csv(p)
        s["date"] = pd.to_datetime(s["observation_date"]) + pd.Timedelta(days=1)
        s[name] = pd.to_numeric(s[name], errors="coerce")
        frames.append(s[["date", name]].set_index("date"))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1).sort_index().ffill()
