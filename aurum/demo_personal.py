"""Stand-in personal data so the whole personal pipeline can be exercised before the owner's file arrives.

It exports the live bot's replayed trades (signals.py) as a MetaTrader-style CSV in broker server time
(New York + 7h), with the S/L column holding the FINAL stop the way brokers export it (moved to entry
after the +1R partial). Every result built from it is labelled DEMO. It is never presented as the owner.
"""
from __future__ import annotations

import pickle

import pandas as pd

from .config import CACHE, STORE

DEMO_DIR = STORE / "personal_demo"


def build_demo_export() -> str:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    B = pickle.loads((CACHE / "bot_trades.pkl").read_bytes())
    def srv(ts):   # UTC -> New York + 7h (MetaTrader-style server clock)
        return (pd.to_datetime(ts).dt.tz_localize("UTC").dt.tz_convert("America/New_York").dt.tz_localize(None)
                + pd.Timedelta(hours=7))
    fill = B["entry_time"] - pd.Timedelta(minutes=30)          # the stop order filled inside that hour
    sl = B["stop_px"].where(~B["partial_done"], B["entry"])    # brokers export the final (moved) stop
    out = pd.DataFrame({
        "Open Time": srv(fill).dt.strftime("%Y.%m.%d %H:%M:%S"), "Type": B["direction"].map({1: "buy", -1: "sell"}),
        "Volume": 1.0, "Symbol": "XAUUSD", "Open Price": B["entry"].round(2), "S/L": sl.round(2),
        "T/P": (B["entry"] + B["direction"] * 2 * B["risk"]).round(2),
        "Close Time": srv(B["exit_time"] - pd.Timedelta(minutes=30)).dt.strftime("%Y.%m.%d %H:%M:%S"),
        "Close Price": B["exit_px"].round(2), "Profit": (B["r"] * B["risk"] * 100).round(2),
        "Comment": B["strategy"]})
    p = DEMO_DIR / "demo_broker_export.csv"
    out.to_csv(p, index=False)
    return str(p)
