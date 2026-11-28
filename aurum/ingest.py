"""Personal trade-history ingestion: broker exports, CSV, manual records, screenshots.

Drop files in aurum/inbox/ and run `python -m aurum ingest`.

Supported
  * MetaTrader 5 "Trade History Report" (HTML or XLSX, Positions section)
  * MetaTrader 4 "Statement" (HTML, Closed Transactions)
  * cTrader / generic broker CSV or XLSX (columns matched by name, see SYNONYMS)
  * TradingView "List of trades" export (entry/exit row pairs)
  * aurum/inbox/manual_trades.csv (template: `python -m aurum template`)
  * screenshots (aurum/inbox/screenshots/*.png|jpg): queued in store/personal/screenshot_queue.json;
    a Claude session reads each image and appends rows to manual_trades.csv with
    source "screenshot:<file>" and a confidence. Nothing from a screenshot is used until confirmed=yes.

Every trade is normalised to one schema, de-duplicated, filtered to gold, and its clock is aligned
to UTC by testing broker time-zone offsets against the actual XAUUSD candles: the right offset is
the one where entry and exit prices fall inside the candles at the stated times. Stops are graded:
'initial' (declared), 'broker_final' (an export's S/L, possibly moved), 'moved' (on the profit side of
entry, so not the initial risk) or 'missing'. R is computed only from a usable stop; otherwise the
ATR-normalised result is used and flagged.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ROOT, STORE

INBOX = ROOT / "aurum" / "inbox"
OUT = STORE / "personal"
COLUMNS = ["trade_id", "source", "source_file", "account", "symbol", "direction", "open_time", "close_time",
           "entry", "exit", "volume", "stop", "stop_kind", "target", "pnl", "commission", "swap",
           "owner_setup", "notes", "tags", "confidence", "confirmed"]

SYNONYMS = {
    "open_time": ["open time", "opening time", "entry time", "time open", "open date", "date opened", "opened",
                  "open_time", "entry date", "date/time open", "time"],
    "close_time": ["close time", "closing time", "exit time", "time close", "close date", "date closed", "closed",
                   "close_time", "exit date"],
    "direction": ["type", "side", "direction", "action", "opening direction", "buy/sell"],
    "entry": ["open price", "entry price", "price open", "opening price", "entry", "open", "price"],
    "exit": ["close price", "exit price", "closing price", "price close", "exit", "close"],
    "stop": ["initial sl", "initial stop", "initial_stop", "s/l", "s / l", "sl", "stop", "stop loss", "stoploss"],
    "target": ["initial tp", "t/p", "t / p", "tp", "take profit", "target"],
    "magic": ["magic", "magic number", "expert id"],
    "broker_id": ["position", "position id", "ticket", "order", "deal"],
    "server_offset": ["server utc offset h"],
    "volume": ["volume", "size", "lots", "quantity", "qty", "closing quantity", "amount"],
    "pnl": ["profit", "pnl", "p&l", "net profit", "net usd", "realized pnl", "gross profit", "net", "result"],
    "commission": ["commission", "fees", "fee"],
    "swap": ["swap", "rollover", "financing"],
    "symbol": ["symbol", "item", "instrument", "market", "ticker"],
    "account": ["account", "login"],
    "owner_setup": ["setup", "strategy", "playbook", "pattern"],
    "notes": ["notes", "comment", "comments", "reason", "journal"],
    "tags": ["tags", "labels", "mistake", "mistakes"],
}
GOLD = re.compile(r"xau|gold", re.I)


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _dir(v):
    s = _norm(v)
    if s in ("1", "+1") or s.startswith(("buy", "long", "b ")) or s == "b":
        return 1
    if s in ("-1",) or s.startswith(("sell", "short", "s ")) or s == "s":
        return -1
    return np.nan


def _num(x):
    if pd.isna(x):
        return np.nan
    s = str(x).replace(" ", "").replace(" ", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return np.nan


def map_columns(df: pd.DataFrame) -> dict:
    cols = {_norm(c): c for c in df.columns}
    out = {}
    for key, names in SYNONYMS.items():
        for n in names:
            if n in cols and cols[n] not in out.values():
                out[key] = cols[n]
                break
    return out


def from_generic(df: pd.DataFrame, source: str, path: Path) -> pd.DataFrame:
    m = map_columns(df)
    need = {"open_time", "direction", "entry"}
    if not need <= set(m):
        raise ValueError(f"{path.name}: could not find columns {sorted(need - set(m))} (have {list(df.columns)})")
    o = pd.DataFrame({k: df[v] for k, v in m.items()})
    o["source"], o["source_file"] = source, path.name
    return o


def from_mt5_report(path: Path) -> pd.DataFrame:
    """MT5 HTML/XLSX report: the Positions block (Time, Position, Symbol, Type, Volume, Price, S/L, T/P,
    Time, Price, Commission, Swap, Profit)."""
    tables = pd.read_html(path) if path.suffix.lower() in (".htm", ".html") else [pd.read_excel(path, header=None)]
    rows = []
    for t in tables:
        t = t.astype(str)
        hdr = None
        for i in range(len(t)):
            vals = [_norm(x) for x in t.iloc[i].tolist()]
            if "position" in vals and "symbol" in vals and vals.count("time") >= 2:
                hdr = i
                break
            if "ticket" in vals and "item" in vals and "open time" in vals:      # MT4 statement
                return _from_mt4(t, i, path)
        if hdr is None:
            continue
        names = [_norm(x) for x in t.iloc[hdr].tolist()]
        for j in range(hdr + 1, len(t)):
            r = t.iloc[j].tolist()
            vals = [_norm(x) for x in r]
            if vals[0] in ("orders", "deals", "nan", "") and not re.match(r"\d{4}\.\d{2}\.\d{2}", vals[0]):
                if vals[0] in ("orders", "deals"):
                    break
                continue
            try:
                ti = [k for k, n in enumerate(names) if n == "time"]
                pi = [k for k, n in enumerate(names) if n == "price"]
                rows.append({"open_time": r[ti[0]], "close_time": r[ti[1]], "symbol": r[names.index("symbol")],
                             "direction": r[names.index("type")], "volume": r[names.index("volume")],
                             "entry": r[pi[0]], "exit": r[pi[1]],
                             "stop": r[names.index("s / l")] if "s / l" in names else np.nan,
                             "target": r[names.index("t / p")] if "t / p" in names else np.nan,
                             "commission": r[names.index("commission")] if "commission" in names else np.nan,
                             "swap": r[names.index("swap")] if "swap" in names else np.nan,
                             "pnl": r[names.index("profit")] if "profit" in names else np.nan,
                             "broker_id": r[names.index("position")]})
            except (ValueError, IndexError):
                continue
        break
    o = pd.DataFrame(rows)
    o["source"], o["source_file"], o["stop_kind"] = "mt5_report", path.name, "broker_final"
    return o


def _from_mt4(t: pd.DataFrame, hdr: int, path: Path) -> pd.DataFrame:
    names = [_norm(x) for x in t.iloc[hdr].tolist()]
    pi = [k for k, n in enumerate(names) if n == "price"]
    rows = []
    for j in range(hdr + 1, len(t)):
        r = t.iloc[j].tolist()
        if _norm(r[names.index("type")]) not in ("buy", "sell"):
            continue
        rows.append({"open_time": r[names.index("open time")], "close_time": r[names.index("close time")],
                     "symbol": r[names.index("item")], "direction": r[names.index("type")],
                     "volume": r[names.index("size")], "entry": r[pi[0]], "exit": r[pi[1]],
                     "stop": r[names.index("s / l")] if "s / l" in names else np.nan,
                     "target": r[names.index("t / p")] if "t / p" in names else np.nan,
                     "pnl": r[names.index("profit")], "broker_id": r[names.index("ticket")]})
    o = pd.DataFrame(rows)
    o["source"], o["source_file"], o["stop_kind"] = "mt4_statement", path.name, "broker_final"
    return o


def from_tradingview(df: pd.DataFrame, path: Path) -> pd.DataFrame:
    """TradingView 'List of trades': one row per entry and per exit, joined by 'Trade #'."""
    m = {_norm(c): c for c in df.columns}
    num, typ = m["trade #"], m["type"]
    dt = next(m[c] for c in m if c.startswith("date"))
    px = next(m[c] for c in m if c.startswith("price"))
    pnl = next((m[c] for c in m if c.startswith("profit") or c.startswith("net p&l")), None)
    rows = []
    for k, g in df.groupby(num):
        ent = g[g[typ].astype(str).str.lower().str.startswith("entry")]
        ex = g[g[typ].astype(str).str.lower().str.startswith("exit")]
        if not len(ent) or not len(ex):
            continue
        rows.append({"open_time": ent[dt].iloc[0], "close_time": ex[dt].iloc[0], "entry": ent[px].iloc[0],
                     "exit": ex[px].iloc[0], "direction": "long" if "long" in str(ent[typ].iloc[0]).lower() else "short",
                     "pnl": ex[pnl].iloc[0] if pnl else np.nan, "broker_id": k})
    o = pd.DataFrame(rows)
    o["source"], o["source_file"] = "tradingview", path.name
    return o


def read_file(path: Path) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf in (".htm", ".html"):
        return from_mt5_report(path)
    df = pd.read_excel(path) if suf in (".xlsx", ".xls") else pd.read_csv(path, sep=None, engine="python")
    cols = {_norm(c) for c in df.columns}
    if suf in (".xlsx", ".xls") and not ({"open_time", "open time", "time"} & cols):
        return from_mt5_report(path)          # MT5 'Report -> Excel' has a title block above the table
    if "trade #" in cols:
        return from_tradingview(df, path)
    src = "manual" if path.name.startswith("manual") else ("aurum_export" if "initial sl" in cols else "csv")
    return from_generic(df, src, path)


def screenshot_queue() -> list[dict]:
    """Screenshots waiting to be transcribed (by a Claude session that can read images)."""
    OUT.mkdir(parents=True, exist_ok=True)
    qp = OUT / "screenshot_queue.json"
    done = set()
    man = INBOX / "manual_trades.csv"
    if man.exists():
        m = pd.read_csv(man)
        if "source" in m:
            done = {s.split(":", 1)[1] for s in m["source"].dropna().astype(str) if s.startswith("screenshot:")}
    q = [{"file": p.name, "status": "transcribed" if p.name in done else "pending"}
         for p in sorted((INBOX / "screenshots").glob("*")) if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    qp.write_text(json.dumps(q, indent=1))
    return q


def normalise(raw: pd.DataFrame) -> pd.DataFrame:
    o = raw.copy()
    for c in COLUMNS:
        if c not in o:
            o[c] = np.nan
    o["direction"] = o["direction"].map(_dir)
    for c in ("entry", "exit", "volume", "stop", "target", "pnl", "commission", "swap", "confidence"):
        o[c] = o[c].map(_num)
    for c in ("open_time", "close_time"):
        o[c] = pd.to_datetime(o[c].astype(str).str.replace(".", "-", regex=False), errors="coerce", format="mixed")
    o["symbol"] = o["symbol"].fillna("XAUUSD").astype(str)
    o = o[o["symbol"].str.contains(GOLD)]
    o = o.dropna(subset=["open_time", "direction", "entry"])
    # who placed it: magic 0 = by hand, anything else = an expert advisor
    if "magic" in o:
        mg = pd.to_numeric(o["magic"], errors="coerce")
        o["placed_by"] = np.where(mg.isna(), "unknown", np.where(mg == 0, "manual", "ea:" + mg.fillna(0).astype("int64").astype(str)))
    else:
        o["placed_by"] = "unknown"
    # stop quality
    kind = o["stop_kind"].fillna("initial")
    has = o["stop"].notna() & (o["stop"] > 0)
    wrong_side = has & ((o["stop"] - o["entry"]) * o["direction"] >= 0)
    o["stop_kind"] = np.where(~has, "missing", np.where(wrong_side, "moved", kind))
    o.loc[~has | wrong_side, "stop"] = np.nan
    # manual screenshot rows need confirmation
    scr = o["source"].astype(str).str.startswith("screenshot")
    o["confirmed"] = np.where(scr, o["confirmed"].astype(str).str.lower().isin(["yes", "true", "1"]), True)
    key = (o["open_time"].astype(str) + o["direction"].astype(str) + o["entry"].round(2).astype(str))
    o["trade_id"] = ["P-" + hashlib.sha1(k.encode()).hexdigest()[:8] for k in key]
    o = o.drop_duplicates("trade_id")
    return o[COLUMNS + [c for c in o.columns if c not in COLUMNS]].sort_values("open_time").reset_index(drop=True)


def _to_utc(ts: pd.Series, off) -> pd.Series:
    """off: a number of hours to subtract, or 'ny+7' (the common MetaTrader server clock: New York time + 7h,
    i.e. UTC+2 in winter and UTC+3 in summer, switching on US daylight-saving dates)."""
    if off == "ny+7":
        loc = (ts - pd.Timedelta(hours=7)).dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward")
        return loc.dt.tz_convert("UTC").dt.tz_localize(None)
    return ts - pd.Timedelta(hours=float(off))


def align_clock(t: pd.DataFrame, m15: pd.DataFrame, offsets=tuple(np.arange(-12, 14.5, 0.5)) + ("ny+7",)):
    """Find the broker clock (offset in hours to subtract, or 'ny+7') that puts prices inside the candles."""
    bars = m15.set_index("t")[["high", "low"]]
    tv = bars.index.values
    hi, lo = bars["high"].values, bars["low"].values
    scores = {}
    for off in offsets:
        ok = n = 0
        for col_t, col_p in (("open_time", "entry"), ("close_time", "exit")):
            ts = _to_utc(t[col_t], off).values.astype("datetime64[ns]")
            m = ~pd.isna(ts) & t[col_p].notna().values
            if not m.any():
                continue
            j = np.searchsorted(tv, ts[m], side="right") - 1
            valid = (j >= 0) & (j < len(tv))
            j = np.clip(j, 0, len(tv) - 1)
            near = np.abs((tv[j] - ts[m]) / np.timedelta64(1, "m")) < 15
            p = t.loc[m, col_p].values
            tol = np.maximum(0.6, p * 1.5e-4)
            jm, jp = np.clip(j - 1, 0, len(tv) - 1), np.clip(j + 1, 0, len(tv) - 1)   # +/- one M15 candle
            hh = np.maximum.reduce([hi[jm], hi[j], hi[jp]])
            ll = np.minimum.reduce([lo[jm], lo[j], lo[jp]])
            inside = (p <= hh + tol) & (p >= ll - tol) & valid & near
            ok += int(inside.sum()); n += int(m.sum())
        scores[off if isinstance(off, str) else float(off)] = ok / n if n else 0.0
    best = max(scores, key=scores.get)
    return best, {"best_offset_h": best, "match_rate": scores[best],
                  "second_best": sorted(scores.values())[-2] if len(scores) > 1 else None,
                  "utc_match_rate": scores.get(0.0)}


def ingest(paths: list[Path] | None = None, tz_offset: float | None = None, verbose: bool = True,
           out_dir: Path | None = None) -> dict:
    """Read everything in the inbox, normalise, align clocks per source file, save."""
    from .frame import load_m15_cached
    out_dir = out_dir or OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = paths or [p for p in sorted(INBOX.glob("*")) if p.is_file() and p.suffix.lower() in
                      (".csv", ".txt", ".htm", ".html", ".xlsx", ".xls") and not p.name.startswith("README")]
    report = {"files": [], "screenshots": screenshot_queue() if out_dir == OUT else []}
    frames = []
    m15 = load_m15_cached()
    for p in paths:
        try:
            raw = read_file(p)
            n_raw = len(raw)
            t = normalise(raw)
            if tz_offset is not None:
                off, info = tz_offset, {"best_offset_h": tz_offset, "match_rate": None, "forced": True}
            else:
                off, info = align_clock(t, m15)
                if "server_offset" in t and t["server_offset"].notna().any():
                    info["exporter_reported_offset_h"] = float(pd.to_numeric(t["server_offset"], errors="coerce").dropna().iloc[0])
            for c in ("open_time", "close_time"):
                t[c] = _to_utc(t[c], off)
            t["tz_offset_h"] = off
            frames.append(t)
            report["files"].append({"file": p.name, "rows": n_raw, "gold_trades": len(t), "clock": info,
                                    "placed_by": t["placed_by"].value_counts().to_dict(),
                                    "stops": t["stop_kind"].value_counts().to_dict(),
                                    "warning": None if (info.get("match_rate") or 1) >= 0.7 else
                                    "Low price/candle match: check the symbol, the time zone or the price feed."})
        except Exception as e:  # report, never crash the run
            report["files"].append({"file": p.name, "error": str(e)})
    T = pd.concat(frames, ignore_index=True).drop_duplicates("trade_id") if frames else pd.DataFrame(columns=COLUMNS)
    T = T[T["confirmed"].astype(bool)]
    T.to_csv(out_dir / "trades_normalized.csv", index=False)
    report["trades"] = len(T)
    report["date_range"] = [str(T["open_time"].min()), str(T["open_time"].max())] if len(T) else None
    (out_dir / "ingest_report.json").write_text(json.dumps(report, indent=1, default=str))
    if verbose:
        print(json.dumps({k: v for k, v in report.items() if k != "screenshots"}, indent=1, default=str)[:3000])
    return report


MANUAL_TEMPLATE = """open_time,close_time,direction,entry,exit,initial_stop,target,volume,pnl,owner_setup,notes,tags,source,confidence,confirmed
2025-03-05 14:20,2025-03-05 18:05,short,2928.50,2919.80,2934.00,2917.50,0.50,435,exhaustion sell,sold the spike into resistance,,manual,,yes
"""
