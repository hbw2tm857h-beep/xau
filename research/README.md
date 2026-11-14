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

## Reproduce
```
python3 research/stage1.py   # video rules with different exits
python3 research/stage2.py   # 840-combination search over three strategy families
python3 research/stage3.py   # exit styles on the chosen signal
python3 research/holdout.py  # final check on the untouched holdout, by year, cost sensitivity
```
