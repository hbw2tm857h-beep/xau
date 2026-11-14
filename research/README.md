# Strategy research (November 2026)

**Goal:** find a version of the gold Heikin Ashi strategy with a real edge, and a 70% win rate if possible, without curve-fitting.

## Method
- **Data:** about 64,000 Dukascopy XAUUSD H1 candles from 2016 to 2026 (`data/xauusd_h1.csv`, fetched by the *Fetch gold history* workflow). Weekend and flat candles are removed.
- **Costs:** $0.35 is charged on every trade.
- **Fills:** entries are stop orders. If a stop and a target both fall inside one candle, the stop is assumed to have been hit first.
- **Periods:**
  - TUNE, 2016 to 2022: settings were chosen here only.
  - VALIDATE, 2023 to 2024: checked without any re-tuning.
  - HOLDOUT, 2025 to 2026: looked at once, for the final pick.
- **Logging:** every combination tried is in `results.csv` (840 rows) and `results_stage3.csv`.

## Findings
| | Trades | Win | Avg R | PF |
|---|---|---|---|---|
| Video's rules, all 10 years | 482 | 36% | −0.00 | 1.00 |
| Asia-range breakout or fade (best of 336) | 523 | 54% | +0.04 tune, −0.01 validate | — |
| Trend pullback to the 20 EMA (best of 336) | 400 | 37% | +0.05 tune, −0.00 validate | — |
| **Chosen: HA + 4H agreement, half off at +1R, rest at +2R** | **460** | **57%** | **+0.13** | **1.30** |
| Chosen, holdout only (2025 to 2026) | 91 | 63% | +0.30 | 1.81 |

1. **The video's rules have no edge over 10 years.** The +0.06R seen earlier on 2 years of data was noise.
2. **Requiring the 4-hour Heikin Ashi candle to agree** made the signal profitable. It was positive at every nearby setting in both the tune and validate periods.
3. **Fixed take-profits beat the opposite-colour exit** on the same signals: +0.13R against +0.02R per trade.
4. **A 70% win rate is reachable, but only by giving up the edge.** Take-profit at +0.5R gave 70.5% winners and +0.01R per trade, which is break-even after costs. The best expectancy came at about 57% winners.
5. **The result holds as costs rise.** It's +0.08R per trade even at $0.80 costs.
6. **Not every year is positive.** 2017 (−7.5R) and 2019 (−4.6R) lost money. Expect losing stretches of 5 to 10R, and a worst drawdown of about 11.5R.

## Round 2 (same day): looking for more edge
Every idea was tested one at a time against the current rules on 2016–2024 only. An idea was kept only if it improved the average R by more than 0.02 in both the tune and validate periods without cutting trades below 60%. 2025–26 had already been viewed once, so it wasn't reused. Instead, **2008–2015 was downloaded as a new, untouched final test.**

- **36 single changes** (`round2.py`, `results_round2.csv`): stop placement, ATR stops, target and partial sizes, time stops, trailing, trend definitions, body size, room, freshness of the colour flip, 4H wick, daily and H1 ADX, volatility, trading hours, order expiry, breakout requirement and entry buffer. Only the entry buffer passed.
- **Entry buffer sweep and greedy combinations** (`round3.py`, `results_round3.csv`): a buffer of 0.3× H1 ATR looked best (+0.13R tune, +0.24R validate). No combination on top of it passed. Several improved both periods but halved the trade count, which is the usual sign of a lucky filter.

### Final test on 2008–2015, run once (`lockbox.py`)
| Rules | Trades | Win | Avg R | PF | Losing years |
|---|---|---|---|---|---|
| Video's original rules | 397 | 31% | −0.05 | 0.83 | 6 of 8 |
| **Current live rules** | **345** | **58%** | **+0.10** | **1.24** | **2 of 8 (−2.7R, −0.4R)** |
| Candidate (+0.3× ATR buffer) | 305 | 53% | +0.04 | 1.08 | 2 of 8 |

**Conclusions**
- The current rules held up on 8 years of data they had never seen. Combined over 2008–2026 that's 805 trades, 57% winners and +0.12R per trade after costs.
- The ATR-buffer "improvement" didn't survive the final test, so it was fitted to 2016–2024 and has been rejected. **The live bot is unchanged.**
- All data has now been looked at. From here, the honest test is **live forward results**, which the Friday scorecard tracks, and the **same rules on other markets** they were never tuned on.

## Round 3: do the gold rules work on other markets?
The exact live rules were run on 5 other markets they were never tuned on, over 2008–2026 (`cross_market.py`). Costs and entry buffer were fixed beforehand. The pass mark was +0.05R per trade or better, at least 300 trades, and a positive result in both 2008–16 and 2017–26.

| Market | Trades | Win | Avg R | Positive years | Result |
|---|---|---|---|---|---|
| **XAUUSD (reference)** | **839** | **59%** | **+0.16** | **15 / 19** | **pass** |
| XAGUSD (silver) | 788 | 51% | −0.09 | 4 / 19 | fail |
| EURUSD | 886 | 51% | −0.03 | 7 / 19 | fail |
| GBPUSD | 876 | 49% | −0.07 | 7 / 19 | fail |
| USDJPY | 896 | 52% | +0.01 | 9 / 19 | fail |
| AUDUSD | 862 | 50% | −0.04 | 7 / 19 | fail |

**Is gold's edge just the 2008–2026 bull market?** No (`gold_direction.py`):

| Gold trades | Trades | Avg R |
|---|---|---|
| Longs | 504 | +0.14 |
| Shorts | 310 | +0.12 |
| Gold's down years (2013–15, 2018, 2021–22, 2026) | 278 | +0.17 |
| Shorts in down years | 174 | +0.18 |

**Conclusions**
- **The edge is specific to gold.** It doesn't carry over to silver or the major currency pairs, so the bot stays gold-only. Adding the other markets would have added losing trades.
- **Within gold it's robust.** It works for longs and shorts, in up and down years, and in 15 of 19 years. Gold's tendency to trend smoothly once the daily, 4-hour and 1-hour timeframes line up seems to be what the rules capture.
- A pattern that worked on every market would have been stronger evidence. Gold-only means the live scorecard matters even more.

## Reproduce
```
python3 research/stage1.py   # video rules with different exits
python3 research/stage2.py   # 840-combination search over three strategy families
python3 research/stage3.py   # exit styles on the chosen signal
python3 research/holdout.py  # final check on the untouched holdout, by year, cost sensitivity
python3 research/round2.py   # 36 single changes vs current rules (2016-2024)
python3 research/round3.py   # entry buffer sweep + greedy combinations
python3 research/lockbox.py  # one-time final test on 2008-2015
python3 research/cross_market.py   # same rules on silver + 4 FX majors
python3 research/gold_direction.py # longs vs shorts, up vs down years
```
