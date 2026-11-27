"""THE MISTAKE TAXONOMY.

Every category has
  * a family and an id,
  * a phase:  ex_ante   -> observable at the decision moment (can become a filter)
              ex_post   -> only diagnosable from what happened next (explains, cannot filter)
              execution -> about the fill / costs rather than the idea,
  * a precise, measurable rule on the trade record (+ counterfactual record),
  * a plain-English explanation template.

Ex-ante flags are tested statistically (``category_stats``): a "mistake" that does
not actually lower expectancy is folklore, and the lab reports it as such.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .stats import summarise, welch, benjamini_hochberg

CONT = ("breakout", "range_breakout", "pullback_ema", "bb_squeeze_breakout", "ma_cross", "retest",
        "momentum_bar", "session_breakout")
REV = ("sweep_reversal", "wick_rejection", "failed_break", "exhaustion_fade", "double_top_bottom", "engulfing")
MR = ("bb_fade", "rsi_extreme")
BREAK = ("breakout", "range_breakout", "bb_squeeze_breakout", "session_breakout")


@dataclass
class Mistake:
    id: str
    name: str
    family: str
    phase: str
    definition: str
    rule: Callable[[pd.DataFrame, pd.DataFrame | None], pd.Series]
    explain: str


def _s(t, mask):
    return pd.Series(np.asarray(mask, dtype=bool), index=t.index).fillna(False)


def _in(t, names):
    return t["setup"].isin(names)


def _cf(cf, col, t):
    if cf is None or col not in cf:
        return pd.Series(np.nan, index=t.index)
    return t[["trade_id"]].merge(cf[["trade_id", col]], on="trade_id", how="left")[col].set_axis(t.index)


LOSS = lambda t: t["r"] < 0  # noqa: E731

M: list[Mistake] = [
    # --------------------------------------------------------------- entry location & timing
    Mistake("E1", "Chasing an extended entry", "Entry location", "ex_ante",
            "Entry more than 2 ATR from the H1 20 EMA in the trade direction.",
            lambda t, cf: _s(t, t["rel_dist_ema20"] > 2.0),
            "Price was already {rel_dist_ema20:.1f} ATR beyond the 20 EMA when the trade was entered."),
    Mistake("E2", "Late entry after the move", "Entry location", "ex_ante",
            "More than 3 ATR of movement in the trade direction over the previous 6 bars.",
            lambda t, cf: _s(t, t["rel_mom6"] > 3.0),
            "{rel_mom6:.1f} ATR had already moved in the trade's favour over the prior 6 hours."),
    Mistake("E3", "No location edge (mid-range entry)", "Entry location", "ex_ante",
            "Entry between 40% and 60% of the 50-bar range: neither at support nor resistance.",
            lambda t, cf: _s(t, t["rel_pos50"].between(0.4, 0.6)),
            "Entry sat in the middle of the 50-bar range ({rel_pos50:.0%})."),
    Mistake("E4", "Entering into an opposing level", "Entry location", "ex_ante",
            "Nearest opposing swing level is closer than 1R away.",
            lambda t, cf: _s(t, t["room_in_r"] < 1.0),
            "Only {room_in_r:.2f}R of room before the next opposing swing level."),
    Mistake("E5", "Buying the top of the range / selling the bottom", "Entry location", "ex_ante",
            "Long in the top 10% (short in the bottom 10%) of the 50-bar range with a reversal or mean-reversion setup.",
            lambda t, cf: _s(t, (t["rel_pos50"] > 0.9) & _in(t, REV + MR)),
            "A reversal-type trade entered at the extreme of the range in the trade's own direction."),
    Mistake("E6", "Premature entry", "Entry timing", "ex_post",
            "Stopped out, but the same idea entered 1 or 3 bars later would have made money.",
            lambda t, cf: _s(t, LOSS(t) & ((_cf(cf, "enter_later_1", t) > 0) | (_cf(cf, "enter_later_3", t) > 0))),
            "Right idea, too early: waiting 1-3 bars would have turned this into a winner."),
    Mistake("E7", "Signal arrived late (move was inside the signal bar)", "Entry timing", "ex_post",
            "Losing trade where entering one bar earlier (before the signal existed) would have won.",
            lambda t, cf: _s(t, LOSS(t) & (_cf(cf, "enter_earlier_1", t) > 0.5)),
            "The tradable part of the move happened inside the signal candle itself."),
    # --------------------------------------------------------------- breakouts
    Mistake("B1", "False breakout", "Breakouts", "ex_post",
            "Breakout-type trade stopped out without ever reaching +0.5R.",
            lambda t, cf: _s(t, _in(t, BREAK) & (t["exit_reason"] == "stop") & (t["mfe_r"] < 0.5) & (t["direction"] > 0)),
            "The breakout above the level failed immediately (best excursion {mfe_r:.2f}R)."),
    Mistake("B2", "Failed breakdown", "Breakouts", "ex_post",
            "Breakdown-type short stopped out without ever reaching +0.5R.",
            lambda t, cf: _s(t, _in(t, BREAK) & (t["exit_reason"] == "stop") & (t["mfe_r"] < 0.5) & (t["direction"] < 0)),
            "The breakdown below the level failed immediately (best excursion {mfe_r:.2f}R)."),
    Mistake("B3", "Breakout without compression", "Breakouts", "ex_ante",
            "Breakout taken while Bollinger width was in the top 30% of the last 250 bars (no prior squeeze).",
            lambda t, cf: _s(t, _in(t, BREAK) & (t["bb_width_pct"] > 0.7)),
            "Volatility was already expanded (BB width pct {bb_width_pct:.0%}) — there was no coil to release."),
    Mistake("B4", "Low-conviction breakout candle", "Breakouts", "ex_ante",
            "Breakout candle body under 0.5 ATR or closing in the bottom half of its range.",
            lambda t, cf: _s(t, _in(t, BREAK) & ((t["rel_body"] < 0.5) | (t["rel_clv"] < 0))),
            "The breakout candle was weak: body {rel_body:.2f} ATR, close location {rel_clv:.2f}."),
    Mistake("B5", "Breakout straight into the prior day's extreme", "Breakouts", "ex_ante",
            "Breakout with the previous day's high (for longs) / low (for shorts) less than 1 ATR ahead.",
            lambda t, cf: _s(t, _in(t, BREAK) & t["dist_prev_day_fwd"].between(0, 1.0)),
            "Prior-day extreme only {dist_prev_day_fwd:.2f} ATR ahead."),
    # --------------------------------------------------------------- liquidity
    Mistake("L1", "Stop hunted", "Liquidity", "ex_post",
            "Stopped out, then price reached the original target within 24 hours.",
            lambda t, cf: _s(t, (t["exit_reason"] == "stop") & (t["post_hit_target"] == True)),  # noqa: E712
            "The stop was taken and the market then went on to the original target — the stop was in the wrong place, not the idea."),
    Mistake("L2", "Stop parked at obvious liquidity", "Liquidity", "ex_ante",
            "Stop beyond equal highs/lows that sit behind the trade (a known liquidity pool).",
            lambda t, cf: _s(t, t["liq_back"] == 1),
            "Equal highs/lows sat just behind the stop — the place everyone's stop is."),
    Mistake("L3", "Trading toward unswept liquidity on the wrong side", "Liquidity", "ex_ante",
            "Reversal trade while equal highs/lows in the opposite direction remained unswept nearby.",
            lambda t, cf: _s(t, _in(t, REV + MR) & (t["liq_back"] == 1)),
            "The reversal was taken before the obvious liquidity pool behind it was cleared."),
    Mistake("L4", "Entering on the sweep candle itself", "Liquidity", "ex_ante",
            "Continuation trade whose signal bar has a wick of more than 40% against the trade.",
            lambda t, cf: _s(t, _in(t, CONT) & (t["fwd_wick"] > 0.4)),
            "The signal candle left a {fwd_wick:.0%} wick against the trade — it was itself a rejection."),
    # --------------------------------------------------------------- exhaustion
    Mistake("X1", "Continuation into trend exhaustion", "Exhaustion", "ex_ante",
            "Continuation trade with price more than 3 daily ATR beyond the daily 50 EMA.",
            lambda t, cf: _s(t, _in(t, CONT) & (t["rel_d_ext"] > 3.0)),
            "Price was {rel_d_ext:.1f} daily ATR stretched from the daily 50 EMA."),
    Mistake("X2", "Momentum divergence ignored", "Exhaustion", "ex_ante",
            "Continuation long on a bearish RSI divergence (or short on a bullish one).",
            lambda t, cf: _s(t, _in(t, CONT) & (((t["direction"] > 0) & (t["bear_div"] == 1)) | ((t["direction"] < 0) & (t["bull_div"] == 1)))),
            "A new extreme was printed on weaker momentum (RSI divergence)."),
    Mistake("X3", "Climax-bar entry", "Exhaustion", "ex_ante",
            "Entry right after a bar of more than 2.5 ATR range in the trade direction.",
            lambda t, cf: _s(t, (t["range_atr"] > 2.5) & (t["rel_body"] > 0)),
            "The signal bar was a {range_atr:.1f} ATR climax candle."),
    Mistake("X4", "Fading strong momentum", "Exhaustion", "ex_ante",
            "Reversal/mean-reversion trade against a move with ADX > 35 and efficiency ratio > 0.5.",
            lambda t, cf: _s(t, _in(t, REV + MR) & (t["adx"] > 35) & (t["er10"] > 0.5)),
            "Faded a clean, strong move (ADX {adx:.0f}, ER {er10:.2f}) — momentum was not exhausted."),
    # --------------------------------------------------------------- trend context
    Mistake("T1", "Countertrend entry (daily)", "Trend context", "ex_ante",
            "Trade direction opposite to the daily 50 EMA slope.",
            lambda t, cf: _s(t, t["with_daily"] == 0),
            "Traded against the daily trend (daily EMA50 slope {d_ema50_slope:.2f})."),
    Mistake("T2", "Multi-timeframe conflict", "Trend context", "ex_ante",
            "H1, H4 and D1 trend directions do not agree.",
            lambda t, cf: _s(t, t["mtf_align"] == 0),
            "H1/H4/D1 disagreed (votes {mtf_votes:+.0f})."),
    Mistake("T3", "Trend-following in chop", "Trend context", "ex_ante",
            "Continuation trade with efficiency ratio(30) < 0.15 and ADX < 18.",
            lambda t, cf: _s(t, _in(t, CONT) & (t["er30"] < 0.15) & (t["adx"] < 18)),
            "Market was directionless (ER30 {er30:.2f}, ADX {adx:.0f})."),
    Mistake("T4", "Catching a falling knife (reversal vs strong HTF trend)", "Trend context", "ex_ante",
            "Reversal trade against a daily trend whose 20-day move exceeds 3 daily ATR.",
            lambda t, cf: _s(t, _in(t, REV + MR) & (t["rel_d_mom20"] < -3)),
            "Picked a top/bottom against a {d_mom20:.1f} daily-ATR 20-day trend."),
    Mistake("T5", "Continuation misread as reversal", "Trend context", "ex_post",
            "Reversal trade stopped out after which price extended more than 2R further the other way within 24h.",
            lambda t, cf: _s(t, _in(t, REV + MR) & (t["exit_reason"] == "stop") & (t.get("post_mae_r", 0) > 3.0)),
            "It was a pause, not a top: price kept going {post_mae_r:.1f}R against the reversal."),
    Mistake("T6", "Reversal misread as continuation", "Trend context", "ex_post",
            "Continuation trade stopped out after which price went more than 3R the other way within 24h.",
            lambda t, cf: _s(t, _in(t, CONT) & (t["exit_reason"] == "stop") & (t.get("post_mae_r", 0) > 3.0)),
            "The move had ended: price reversed {post_mae_r:.1f}R against the continuation trade."),
    Mistake("T7", "H1 structure misread", "Market structure", "ex_ante",
            "Long while H1 swing structure is LH/LL (bearish), or short while HH/HL.",
            lambda t, cf: _s(t, t["rel_structure"] < 0),
            "Swing structure on H1 pointed the other way."),
    Mistake("T8", "H4 structure against the trade", "Market structure", "ex_ante",
            "H4 swing structure opposite to the trade.",
            lambda t, cf: _s(t, t["rel_h4_structure"] < 0),
            "H4 swing structure pointed the other way."),
    # --------------------------------------------------------------- support / resistance
    Mistake("S1", "Fading a level that has been tested repeatedly", "Support & resistance", "ex_ante",
            "Reversal at a level touched 4+ times already (levels weaken with each test).",
            lambda t, cf: _s(t, _in(t, REV) & (t["opp_touches"] >= 4)),
            "The level had already been tested {opp_touches:.0f} times."),
    Mistake("S2", "Level broke through (S/R misinterpretation)", "Support & resistance", "ex_post",
            "Level-based reversal stopped out with the level decisively broken (price ran > 1.5R beyond the stop afterwards).",
            lambda t, cf: _s(t, _in(t, ("sweep_reversal", "wick_rejection", "double_top_bottom", "retest")) & (t["exit_reason"] == "stop") & (t.get("post_mae_r", 0) > 2.5)),
            "The level the trade relied on simply failed."),
    Mistake("S3", "Round-number magnet ignored", "Support & resistance", "ex_ante",
            "Entry within 0.3 ATR of a $50 handle.",
            lambda t, cf: _s(t, t["dist_round50"] < 0.3),
            "Entry was sitting on a $50 round number."),
    # --------------------------------------------------------------- consolidation
    Mistake("C1", "Consolidation trap", "Consolidation", "ex_ante",
            "Trade inside a tight 20-bar range (range < 4 ATR) that is not a breakout of it.",
            lambda t, cf: _s(t, (t["range20_atr"] < 4) & ~_in(t, ("range_breakout",))),
            "Market was boxed in a {range20_atr:.1f} ATR range."),
    Mistake("C2", "Range whipsaw", "Consolidation", "ex_post",
            "Trade went more than +0.8R in favour and then hit the full stop.",
            lambda t, cf: _s(t, (t["exit_reason"] == "stop") & (t["mfe_r"] > 0.8)),
            "Price swung {mfe_r:.2f}R in favour, then all the way back through the stop."),
    # --------------------------------------------------------------- volatility
    Mistake("V1", "Expecting a move in dead volatility", "Volatility", "ex_ante",
            "Continuation trade with H1 volatility in the bottom 15% of the last 500 bars.",
            lambda t, cf: _s(t, _in(t, CONT) & (t["atr_pct"] < 0.15)),
            "Volatility percentile {atr_pct:.0%}: there was no fuel for follow-through."),
    Mistake("V2", "Entering after a volatility expansion", "Volatility", "ex_ante",
            "Fast ATR > 1.5x slow ATR (expansion already under way).",
            lambda t, cf: _s(t, t["atr_ratio"] > 1.5),
            "Volatility had already expanded {atr_ratio:.2f}x."),
    Mistake("V3", "Stop too tight for volatility", "Volatility", "ex_ante",
            "Initial stop smaller than 0.75 ATR(H1).",
            lambda t, cf: _s(t, t["stop_atr"] < 0.75),
            "Stop was only {stop_atr:.2f} ATR — inside normal noise."),
    Mistake("V4", "Stop unnecessarily wide", "Volatility", "ex_ante",
            "Initial stop larger than 2.5 ATR(H1), shrinking position size and R efficiency.",
            lambda t, cf: _s(t, t["stop_atr"] > 2.5),
            "Stop was {stop_atr:.2f} ATR away."),
    # --------------------------------------------------------------- risk / reward and exits
    Mistake("R1", "Target beyond a known obstacle", "Risk & reward", "ex_ante",
            "2R target lies beyond the nearest opposing level (target needs that level to break).",
            lambda t, cf: _s(t, t["room_in_r"] < 2.0),
            "Target needed {room_in_r:.2f}R of room to exist; the level was in the way."),
    Mistake("R2", "Target too far (should have banked)", "Risk & reward", "ex_post",
            "Reached +1R or more, then finished at a loss.",
            lambda t, cf: _s(t, LOSS(t) & (t["mfe_r"] >= 1.0)),
            "Was +{mfe_r:.2f}R at best and still lost."),
    Mistake("R3", "Target too close (left money on table)", "Risk & reward", "ex_post",
            "Hit the 2R target and price kept going to more than 4R within 24h.",
            lambda t, cf: _s(t, (t["exit_reason"] == "target") & (t.get("post_mfe_r", 0) > 4.0)),
            "Target hit, but the move extended to {post_mfe_r:.1f}R."),
    Mistake("R4", "Stop placement, not idea, was wrong", "Risk & reward", "ex_post",
            "Lost with the original stop, but the same trade with a 1.5x stop (same target) made money.",
            lambda t, cf: _s(t, LOSS(t) & (_cf(cf, "stop_1.5x", t) > 0)),
            "A slightly wider stop would have survived and made money."),
    Mistake("R5", "Wrong direction entirely", "Risk & reward", "ex_post",
            "Lost, and the opposite trade (mirrored stop/target) won at least +1R.",
            lambda t, cf: _s(t, LOSS(t) & (_cf(cf, "opposite", t) >= 1.0)),
            "The read was backwards: the mirrored trade made over 1R."),
    Mistake("R6", "Thesis never played out (time decay)", "Risk & reward", "ex_post",
            "Exited on the time stop with |R| < 0.3.",
            lambda t, cf: _s(t, (t["exit_reason"] == "time") & (t["r"].abs() < 0.3)),
            "Nothing happened for 48h; the trade was dead capital."),
    # --------------------------------------------------------------- news / sessions
    Mistake("N1", "Entry into scheduled news", "News & sessions", "ex_ante",
            "Decision inside, or one hour before, an FOMC / CPI / NFP window.",
            lambda t, cf: _s(t, (t["event"] != "") | (t["event_next"] != "")),
            "Entered around a scheduled release ({event}{event_next})."),
    Mistake("N2", "Illiquid-hours entry", "News & sessions", "ex_ante",
            "Entry during the 21:00-23:00 UTC rollover / thin Asia open.",
            lambda t, cf: _s(t, t["hour"].isin([21, 22])),
            "Entered at {hour:.0f}:00 UTC, the thinnest hour of the day."),
    Mistake("N3", "Friday-afternoon / weekend exposure", "News & sessions", "ex_ante",
            "Entered on Friday after 14:00 UTC (trade likely to be held over the weekend gap).",
            lambda t, cf: _s(t, (t["dow"] == 4) & (t["hour"] >= 14)),
            "Friday afternoon entry."),
    # --------------------------------------------------------------- indicator misinterpretation
    Mistake("K1", "Bollinger touch read as reversal while band-walking", "Indicators", "ex_ante",
            "BB fade while price has closed outside the same band 3+ times in the last 10 bars.",
            lambda t, cf: _s(t, (t["setup"] == "bb_fade") & (((t["direction"] < 0) & (t["bb_outside_up_10"] >= 3)) | ((t["direction"] > 0) & (t["bb_outside_dn_10"] >= 3)))),
            "Price was walking the band — a trend, not an extreme."),
    Mistake("K2", "Bollinger breakout in a range", "Indicators", "ex_ante",
            "Squeeze breakout with ADX < 20.",
            lambda t, cf: _s(t, (t["setup"] == "bb_squeeze_breakout") & (t["adx"] < 20)),
            "Band breakout without any trend strength (ADX {adx:.0f})."),
    Mistake("K3", "Lagging MA cross", "Indicators", "ex_ante",
            "EMA cross after price already moved more than 3 ATR over 12 bars.",
            lambda t, cf: _s(t, (t["setup"] == "ma_cross") & (t["rel_mom12"] > 3)),
            "The cross confirmed a move that was already {rel_mom12:.1f} ATR old."),
    Mistake("K4", "Moving average as support in a flat market", "Indicators", "ex_ante",
            "EMA pullback with |EMA50 slope| < 0.3 ATR per 10 bars.",
            lambda t, cf: _s(t, (t["setup"] == "pullback_ema") & (t["ema50_slope"].abs() < 0.3)),
            "The moving average was flat; it was not acting as trend support."),
    Mistake("K5", "Overbought != sell in a trend", "Indicators", "ex_ante",
            "RSI-extreme or BB fade against an aligned H1/H4/D1 trend.",
            lambda t, cf: _s(t, _in(t, MR) & (t["mtf_align"] == -t["direction"])),
            "RSI/BB said 'extreme' but all three timeframes were trending against the fade."),
    Mistake("K6", "Wick rejection misread", "Candles", "ex_post",
            "Wick-rejection trade stopped out without reaching +0.5R.",
            lambda t, cf: _s(t, (t["setup"] == "wick_rejection") & (t["exit_reason"] == "stop") & (t["mfe_r"] < 0.5)),
            "The wick was not rejection; price came straight back through it."),
    Mistake("K7", "Failed retest", "Retests", "ex_post",
            "Retest trade stopped out without reaching +0.5R.",
            lambda t, cf: _s(t, (t["setup"] == "retest") & (t["exit_reason"] == "stop") & (t["mfe_r"] < 0.5)),
            "The broken level did not flip — the retest failed."),
    Mistake("K8", "Retest too deep", "Retests", "ex_ante",
            "Retest where the signal bar closed less than 0.2 ATR beyond the level after piercing it.",
            lambda t, cf: _s(t, (t["setup"] == "retest") & (((t["close"] - t["ref_level"]) * t["direction"] / t["atr"]) < 0.2)),
            "Price barely held the level on the retest."),
    # --------------------------------------------------------------- execution
    Mistake("X5", "Gap through stop", "Execution", "execution",
            "Exit filled more than 0.3R worse than the stop.",
            lambda t, cf: _s(t, (t["exit_reason"] == "stop") & (t["r"] < -1.3)),
            "Slipped/gapped through the stop to {r:.2f}R."),
    Mistake("X6", "Cost-dominated trade", "Execution", "execution",
            "Costs (spread + slippage) above 0.15R.",
            lambda t, cf: _s(t, t["cost_r"] > 0.15),
            "Costs alone were {cost_r:.2f}R — the stop was too small relative to spread."),
]
CATEGORIES = {m.id: m for m in M}


def flag_trades(t: pd.DataFrame, cf: pd.DataFrame | None = None) -> pd.DataFrame:
    """Boolean matrix trade x category."""
    out = {}
    for m in M:
        try:
            out[m.id] = m.rule(t, cf).astype(bool).values
        except Exception as e:  # a missing column should never kill the run
            out[m.id] = np.zeros(len(t), bool)
            print(f"[taxonomy] {m.id} failed: {e}")
    return pd.DataFrame(out, index=t.index)


def category_table() -> pd.DataFrame:
    return pd.DataFrame([{"id": m.id, "name": m.name, "family": m.family, "phase": m.phase,
                          "definition": m.definition} for m in M])


def category_stats(t: pd.DataFrame, flags: pd.DataFrame, split: str | None = "discovery") -> pd.DataFrame:
    """Is each 'mistake' really associated with worse results? Tested per category.

    For ex-ante categories this is a fair test (flag known before the outcome);
    for ex-post ones it is descriptive (frequency among losers).
    """
    sel = (t["split"] == split) if split else pd.Series(True, index=t.index)
    tt, ff = t[sel], flags[sel]
    rows = []
    for m in M:
        on = ff[m.id]
        r_on, r_off = tt.loc[on, "r"].values, tt.loc[~on, "r"].values
        s_on, s_off = summarise(r_on), summarise(r_off)
        tstat, p = welch(r_on, r_off)
        losers = tt["r"] < 0
        rows.append({
            "id": m.id, "name": m.name, "family": m.family, "phase": m.phase,
            "n_flagged": int(on.sum()), "freq_all": float(on.mean()) if len(on) else np.nan,
            "freq_losers": float(on[losers].mean()) if losers.any() else np.nan,
            "freq_winners": float(on[~losers].mean()) if (~losers).any() else np.nan,
            "avg_r_flagged": s_on["avg_r"], "avg_r_clean": s_off["avg_r"],
            "delta_r": (s_on["avg_r"] - s_off["avg_r"]) if s_on["n"] else np.nan,
            "win_flagged": s_on["win"], "win_clean": s_off["win"], "p_value": p,
        })
    df = pd.DataFrame(rows)
    ex = df["phase"] == "ex_ante"
    df.loc[ex, "q_value"] = benjamini_hochberg(df.loc[ex, "p_value"].values)

    def verdict(r):
        if r["phase"] != "ex_ante":
            return "diagnostic (ex-post)"
        if r["n_flagged"] < 30:
            return "insufficient data"
        if r["q_value"] < 0.05 and r["delta_r"] < 0:
            return "confirmed mistake"
        if r["q_value"] < 0.05 and r["delta_r"] > 0:
            return "CONTRADICTED: flagged trades do better"
        return "folklore (no measurable effect)"
    df["verdict"] = df.apply(verdict, axis=1)
    return df


def explain(trade: pd.Series, flags_row: pd.Series) -> list[dict]:
    out = []
    for m in M:
        if bool(flags_row.get(m.id, False)):
            try:
                text = m.explain.format(**{k: (v if v is not None else np.nan) for k, v in trade.items()})
            except Exception:
                text = m.definition
            out.append({"id": m.id, "name": m.name, "family": m.family, "phase": m.phase, "text": text})
    return out
