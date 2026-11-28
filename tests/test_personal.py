"""Personal-data ingestion: parsing, stop grading and broker-clock detection."""
import numpy as np
import pandas as pd

from aurum.ingest import normalise, align_clock, from_generic, from_tradingview, _to_utc


def _m15(start="2024-03-04", days=5, seed=0):
    t = pd.date_range(start, periods=days * 96, freq="15min")
    rng = np.random.default_rng(seed)
    c = 2000 + np.cumsum(rng.normal(0, 1.5, len(t)))
    return pd.DataFrame({"t": t, "open": c, "high": c + 1.0, "low": c - 1.0, "close": c})


def test_generic_columns_and_moved_stop():
    raw = pd.DataFrame({"Open Time": ["2024.03.04 10:00:00", "2024.03.04 12:00:00"], "Type": ["Buy", "Sell"],
                        "Open Price": [2000.0, 2010.0], "S/L": [1995.0, 2000.0], "Close Price": [2004, 2015],
                        "Close Time": ["2024.03.04 11:00:00", "2024.03.04 13:00:00"], "Symbol": ["XAUUSD", "XAUUSD"]})
    t = normalise(from_generic(raw, "csv", __import__("pathlib").Path("x.csv")))
    assert list(t["direction"]) == [1, -1]
    assert list(t["stop_kind"]) == ["initial", "moved"]          # a sell with S/L below entry was moved
    assert pd.isna(t.loc[1, "stop"])


def test_non_gold_rows_are_dropped():
    raw = pd.DataFrame({"time": ["2024-03-04 10:00"] * 2, "side": ["buy", "buy"], "price": [1.1, 2000.0],
                        "symbol": ["EURUSD", "GOLD"]})
    t = normalise(from_generic(raw, "csv", __import__("pathlib").Path("x.csv")))
    assert len(t) == 1 and t.iloc[0]["entry"] == 2000.0


def test_clock_offset_detected():
    m = _m15()
    picks = m.iloc[[40, 120, 200, 260, 330]]
    shift = 3.0                                                     # broker clock is UTC+3
    trades = pd.DataFrame({"open_time": picks["t"].values + np.timedelta64(3, "h"), "entry": picks["close"].values,
                           "close_time": picks["t"].values + np.timedelta64(4, "h"), "exit": np.nan})
    off, info = align_clock(trades, m)
    assert off == shift and info["match_rate"] == 1.0


def test_ny_plus_7_clock():
    ts = pd.Series(pd.to_datetime(["2024-01-15 10:00", "2024-07-15 10:00"]))
    utc = _to_utc(ts, "ny+7")
    assert list(utc.dt.hour) == [8, 7]                              # UTC+2 in winter, UTC+3 in summer


def test_tradingview_pairs():
    df = pd.DataFrame({"Trade #": [1, 1], "Type": ["Entry Short", "Exit Short"],
                       "Date/Time": ["2024-03-04 10:00", "2024-03-04 12:00"], "Price USD": [2010, 2000],
                       "Profit USD": [None, 1000]})
    t = from_tradingview(df, __import__("pathlib").Path("tv.csv"))
    assert len(t) == 1 and t.iloc[0]["direction"] == "short" and t.iloc[0]["exit"] == 2000


def test_screenshot_rows_need_confirmation():
    raw = pd.DataFrame({"open_time": ["2024-03-04 10:00", "2024-03-04 11:00"], "direction": ["buy", "sell"],
                        "entry": [2000, 2001], "source": ["screenshot:a.png", "manual"], "confirmed": ["", ""]})
    t = normalise(raw)
    assert list(t["confirmed"]) == [False, True]
