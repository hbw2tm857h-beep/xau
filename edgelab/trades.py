"""Turn decisions into simulated trades with a full context snapshot."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import DEFAULT, LabConfig
from .simulator import Path, simulate

# context columns copied onto every trade (what was knowable at decision time)
CONTEXT = [
    "tc", "close", "atr", "range_atr", "body", "body_frac", "upper_wick_frac", "lower_wick_frac", "clv",
    "dist_ema20", "dist_ema50", "dist_ema200", "ema20_slope", "ema50_slope", "rsi", "adx", "er10", "er30",
    "bb_pctb", "bb_width", "bb_width_pct", "bb_outside_up_10", "bb_outside_dn_10", "atr_pct", "atr_ratio",
    "mom1", "mom3", "mom6", "mom12", "mom24", "run_len", "range20_atr", "pos_in_range20", "pos_in_range50",
    "bear_div", "bull_div", "vol_rel", "hour", "dow", "session", "asia_range_atr", "dist_round10",
    "dist_round50", "structure", "room_up", "room_dn", "lvl_above_touches", "lvl_below_touches", "eq_highs",
    "eq_lows", "dist_sh1", "dist_sl1", "sh1_age", "sl1_age", "h4_trend", "h4_dist_ema20", "h4_mom6", "h4_dir",
    "h4_structure", "d_ema50_slope", "d_dist_ema50", "d_dist_ema200", "d_er20", "d_mom20", "d_volpct",
    "regime_trend", "regime_vol", "regime_char", "regime", "d_dir", "d_structure", "h1_trend", "d_trend",
    "mtf_align", "mtf_votes", "dist_pdh", "dist_pdl", "d_ext", "event", "event_next", "split", "year",
    "real_yield_chg20", "usd_chg20", "vix", "htf_room_up", "htf_room_dn", "htf_lvl_above", "htf_lvl_below",
]

# Direction-relative versions: positive always means "in favour of the trade"
DIRECTIONAL = ["body", "clv", "dist_ema20", "dist_ema50", "dist_ema200", "ema20_slope", "ema50_slope",
               "mom1", "mom3", "mom6", "mom12", "mom24", "run_len", "structure", "h4_trend", "h4_dist_ema20",
               "h4_mom6", "h4_dir", "h4_structure", "d_ema50_slope", "d_dist_ema50", "d_dist_ema200",
               "d_mom20", "d_dir", "d_structure", "h1_trend", "d_trend", "mtf_votes", "d_ext",
               "real_yield_chg20", "usd_chg20"]


CODE = {"breakout": "BRK", "range_breakout": "RBO", "sweep_reversal": "SWP", "pullback_ema": "PBE", "bb_fade": "BBF",
        "bb_squeeze_breakout": "BBS", "ma_cross": "MAX", "wick_rejection": "WCK", "retest": "RTS", "failed_break": "FBK",
        "exhaustion_fade": "EXH", "momentum_bar": "MOM", "rsi_extreme": "RSI", "session_breakout": "SES",
        "double_top_bottom": "DTB", "engulfing": "ENG", "momentum_burst": "BUR", "burst_pullback": "BPB"}


def add_relative(t: pd.DataFrame) -> pd.DataFrame:
    d = t["direction"].values
    for c in DIRECTIONAL:
        if c in t:
            t["rel_" + c] = t[c].values * d
    t["rel_rsi"] = np.where(d > 0, t["rsi"], 100 - t["rsi"])
    t["rel_pctb"] = np.where(d > 0, t["bb_pctb"], 1 - t["bb_pctb"])
    t["rel_pos20"] = np.where(d > 0, t["pos_in_range20"], 1 - t["pos_in_range20"])
    t["rel_pos50"] = np.where(d > 0, t["pos_in_range50"], 1 - t["pos_in_range50"])
    t["room_fwd"] = np.where(d > 0, t["room_up"], t["room_dn"])        # ATR to next opposing level
    t["room_back"] = np.where(d > 0, t["room_dn"], t["room_up"])
    t["opp_touches"] = np.where(d > 0, t["lvl_above_touches"], t["lvl_below_touches"])
    t["fwd_wick"] = np.where(d > 0, t["upper_wick_frac"], t["lower_wick_frac"])   # wick against trade
    t["back_wick"] = np.where(d > 0, t["lower_wick_frac"], t["upper_wick_frac"])  # rejection wick in favour
    t["liq_fwd"] = np.where(d > 0, t["eq_highs"], t["eq_lows"]).astype(int)        # equal highs ahead
    t["liq_back"] = np.where(d > 0, t["eq_lows"], t["eq_highs"]).astype(int)       # equal lows behind stop
    t["dist_prev_day_fwd"] = np.where(d > 0, t["dist_pdh"], t["dist_pdl"])
    t["with_daily"] = (np.sign(t["d_ema50_slope"].fillna(0)) == d).astype(int)
    t["room_in_r"] = t["room_fwd"] / t["stop_atr"]
    t["room_fwd_htf"] = np.where(d > 0, t["htf_room_up"], t["htf_room_dn"])
    t["room_back_htf"] = np.where(d > 0, t["htf_room_dn"], t["htf_room_up"])
    t["room_in_r_htf"] = t["room_fwd_htf"] / t["stop_atr"]
    return t


def simulate_decisions(dec: pd.DataFrame, f: pd.DataFrame, path: Path, cfg: LabConfig = DEFAULT,
                       post: bool = True) -> pd.DataFrame:
    tc = f["tc"].values
    starts = path.index_at_or_after(tc[dec["idx"].values])
    atr = f["atr"].values
    out = []
    mm = cfg.trade.max_hours * 60
    pm = cfg.trade.post_exit_hours * 60 if post else 0
    for k, row in enumerate(dec.itertuples(index=False)):
        r = simulate(path, int(starts[k]), int(row.direction), float(row.stop), float(row.target), mm,
                     float(atr[row.idx]), costs=cfg.costs, post_minutes=pm, target_r=cfg.trade.target_r)
        out.append(r)
    sim = pd.DataFrame(out)
    t = pd.concat([dec.reset_index(drop=True), sim], axis=1)
    ctx = f.loc[t["idx"].values, CONTEXT].reset_index(drop=True)
    t = pd.concat([t, ctx], axis=1)
    t = t[t["filled"]].reset_index(drop=True)
    t["win"] = (t["r"] > 0).astype(int)
    t = add_relative(t)
    t.insert(0, "trade_id", [f"{CODE.get(s, s[:4].upper())}{'L' if d > 0 else 'S'}-{pd.Timestamp(x):%Y%m%d%H}"
                             for s, d, x in zip(t["setup"], t["direction"], t["tc"])])
    assert t["trade_id"].is_unique, "trade_id collision: extend CODE"
    # embargo: a trade still open at a split boundary is flagged
    t["crosses_split"] = t["exit_time"].map(_split_of_ts) != t["split"]
    return t


def _split_of_ts(ts):
    from .config import SPLITS, SPLIT_ORDER
    for name in SPLIT_ORDER:
        a, b = SPLITS[name]
        if pd.Timestamp(a) <= ts <= pd.Timestamp(b):
            return name
    return ""
