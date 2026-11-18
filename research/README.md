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

## Round 4: popular TradingView indicators (16 Nov 2026)
**Question:** do the best-known TradingView indicators add anything to the gold rules?

**What was tested** (`tv_indicators.py`, `round4_tradingview.py`, `results_round4_tradingview.csv`): 20 of the most popular **open-source** scripts, ported from their published Pine code with the **author's default settings** and no tuning on gold. They were SuperTrend, UT Bot Alerts, SSL Channel, Squeeze Momentum, WaveTrend, QQE MOD, Chandelier Exit, Range Filter, Hull Suite, HalfTrend, the LuxAlgo Smart Money Concepts structure (internal and swing), MACD, RSI, EMA 200, the Ichimoku cloud, Parabolic SAR, Stoch RSI, DMI and the Donchian midline. Each one was tested 3 ways, one at a time: as an H1 filter, as a 4H filter, and as a replacement for the Heikin Ashi trigger. That makes 60 tests.

Some scripts were left out. Protected and invite-only scripts don't publish their code. VWAP, MFI, OBV and Cipher B's money flow need volume, which spot gold doesn't have. The Nadaraya-Watson Envelope repaints, and Lorentzian Classification is a machine-learning model that would need fitting.

**Pass mark:** the same as round 2, which is better average R by more than 0.02 in both 2016–22 and 2023–24, while keeping at least 60% of the trades. Anything that passed was then checked on 2008–15 and 2025–26. Those periods had been seen before, but none of these indicators was chosen or set using them. To be adopted, a change had to beat the live rules in all four periods.

| Passed stage 1 | 2016–22 | 2023–24 | 2008–15 | 2025–26 | Verdict |
|---|---|---|---|---|---|
| Live rules (reference) | +0.094 | +0.088 | +0.104 | +0.299 | |
| **Ichimoku cloud, 4H** | **+0.136** | **+0.156** | **+0.168** | **+0.326** | **adopted** |
| Chandelier Exit, 4H | +0.117 | +0.208 | +0.129 | +0.343 | passed, not added (see below) |
| Hull Suite, H1 | +0.124 | +0.172 | +0.105 | +0.363 | flat on 2008–15 |
| Stoch RSI K/D, 4H | +0.146 | +0.294 | +0.126 | +0.398 | cuts 36% of trades; total R falls |
| WaveTrend trigger | −0.056 | +0.019 | −0.020 | +0.037 | worse than the live rules |

**Findings**
1. **None of the 20 indicators beat the Heikin Ashi trigger.** As triggers, all 20 did worse than the live rules over 2016–22. The best was the SMC swing structure at +0.085R, against +0.094R, and that came from only 34 trades.
2. **The Ichimoku cloud on 4H is a real improvement.** Over 2008–26 it removes 110 trades that averaged −0.17R. The average goes from +0.12R to +0.18R and total R from +97 to +125. It's better in 15 of 19 years. Dropping the same number of trades at random never matched the gain in 5,000 tries.
3. **Chandelier Exit 4H also passed, but it isn't stacked on top.** It measures the same thing (the 4-hour trend), and adding a second filter that was picked from the same 60 tests is how curve-fitting starts.
4. **Most H1 filters do nothing.** RSI, MACD, EMA 200, DMI and Donchian are within ±0.02R of the live rules. Gold's edge here comes from the timeframes agreeing, not from extra confirmations on the same hourly chart.
5. **Caveat:** 60 tests were run, so a few passes by luck are expected. The cloud passed four separate periods and fits the earlier finding that 4-hour agreement is where the edge comes from, but live results are still the real test.

## Round 5: everything else open-source (16 Nov 2026)
**Question:** is there any other open-source indicator, strategy or market relationship with a genuine edge on gold?

The live rules now include the 4H cloud check, so that's what every idea had to beat: 715 trades, +0.175R per trade and +124.8R over 2008–26. All settings were the authors' defaults, fixed before any result was seen. Because many more ideas were tried this round, the adoption bar was raised:
1. **Stage 1:** better average R by more than 0.02 in both 2016–22 and 2023–24, while keeping at least 60% of the trades.
2. **Stage 2:** also better in 2008–15 and 2025–26.
3. **Stage 3:** over 2008–26, total R must not fall. Dropping the same number of the live trades at random also had to match the gain in fewer than 0.1% of 10,000 tries.

### A–C: 77 more filters and triggers (`round5.py`, `tv_indicators2.py`, `results_round5.csv`)
- **A, 21 more TradingView indicators,** each tested as an H1 filter, a 4H filter and a trigger: Aroon, CCI, Williams %R, Vortex, TRIX, Fisher Transform, Elder Impulse, KAMA, Schaff Trend Cycle, Williams Alligator, Awesome Oscillator, Ultimate Oscillator, OTT, McGinley Dynamic, Coral Trend, Laguerre RSI, Pivot Point SuperTrend, LuxAlgo S/R with Breaks, EMA 9/21 cross, ZLSMA and Kijun-sen. Choppiness and "squeeze released" were tested as H1 and 4H regime filters. Every port was checked for lookahead.
- **B, calendar effects:** skip Mondays, skip Fridays, skip the 28th onwards, skip the US jobs-report Friday, and trade with the published intraday "hat" seasonality.
- **C, other markets:** a USD index built from EUR, GBP, AUD and JPY, tested on its 50-day trend, 20-day momentum and 4H Heikin Ashi colour, plus silver's daily trend and 4H colour.

| Result | |
|---|---|
| Passed stage 1 | 1 of 77: the **Vortex (14) H1 filter** |
| Vortex, all four periods | +0.161 / +0.188 / +0.180 / +0.374, against +0.136 / +0.156 / +0.168 / +0.326 |
| Vortex, stage 3 | **failed.** Random drops matched it 1.1% of the time (the limit was 0.1%), so it's not adopted |
| Best replacement trigger | Laguerre RSI at +0.036R in 2016–22, against +0.136R. All 21 were worse than Heikin Ashi |
| Calendar | none passed. Skipping Mondays helped 2023–24 (+0.235) but not 2016–22 (−0.005) |
| USD index and silver | none passed. All three USD filters made 2023–24 **worse** (by −0.03 to −0.11) |

So 41 popular indicators across rounds 4 and 5 have now been tested. The Ichimoku cloud is still the only one that adds anything. Gold's hourly edge comes from the timeframes agreeing, and more confirmation on top doesn't help.

### D: 10 well-known standalone strategies (`round5_standalone.py`, `results_round5_standalone.csv`)
**Pass mark:** a positive average in all four periods, profit factor above 1.15 and at least 100 trades.

| Strategy | Trades | Win | Avg R | PF | 2008–15 | 2016–22 | 2023–24 | 2025–26 | |
|---|---|---|---|---|---|---|---|---|---|
| Turtle System 1 (20/10) | 215 | 38% | +0.03 | 1.07 | −0.04 | −0.02 | +0.12 | +0.55 | fail |
| Turtle System 2 (55/20) | 86 | 36% | +0.51 | 1.96 | +0.24 | +0.19 | +0.67 | +4.47 | too few trades |
| Connors RSI-2 | 172 | 62% | +0.01 | 1.01 | +0.13 | −0.18 | −0.14 | +0.27 | fail |
| Bollinger reversion (20, 2) | 171 | 65% | −0.19 | 0.82 | −0.03 | −0.22 | +0.10 | −1.25 | fail |
| NR7 breakout | 700 | 49% | +0.09 | 1.23 | +0.20 | −0.01 | −0.09 | +0.13 | fail |
| **Inside-day breakout** | **726** | **49%** | **+0.10** | **1.32** | **+0.12** | **+0.04** | **+0.06** | **+0.27** | **pass** |
| Turtle Soup | 208 | 33% | −0.02 | 0.97 | +0.00 | +0.04 | −0.15 | −0.28 | fail |
| Golden/death cross (50/200) | 25 | 28% | +4.46 | 2.48 | | | | | too few trades |
| London opening range breakout | 4,872 | 37% | −0.06 | 0.91 | −0.06 | −0.09 | −0.09 | +0.08 | fail |
| Eastern-hours long (00–08 UTC) | 4,835 | 49% | −0.01 | 0.96 | −0.01 | −0.01 | +0.01 | +0.02 | fail |

Mean reversion (RSI-2, Bollinger) loses on gold, and so do opening-range and time-of-day trades. The long-term trend followers (Turtle 55/20, 50/200 cross) made money but traded too rarely to judge.

**Inside-day breakout checks** (`round5_insideday_checks.py`):
- **Costs:** it makes +0.06R per trade at $0.80 costs and breaks even at about $1.50.
- **Years:** 13 of 19 were profitable. The worst was 2017 at −9.6R.
- **Direction:** buys and sells both work.
- **Days that break both sides:** 153 of them, already booked as full losses.
- **Similar setups:** an inside day that's also NR7 makes +0.12R, and NR4 makes +0.05R, so the idea isn't a cliff edge.
- **Luck test:** t-stat 2.8. Only 0.34% of bootstrap resamples have an average of zero or less.

**Alongside the trend setups:** monthly results are almost uncorrelated (0.08). Over 2008–26:

| | Total R | Biggest drop | Sharpe (annual) |
|---|---|---|---|
| Trend setups only | +123.5 | 11.7R | 0.95 |
| Both, same size | +195.2 | 23.3R | 1.10 |
| **Both, inside-day at half size (adopted)** | **+159.4** | **17.2R** | **1.09** |

**Adopted:** the inside-day breakout is now a second, separate setup in `signals.py` and in the MT5 EA (version 2.20). It has its own alerts, sizes at half the normal risk, and has its own line in the weekly scorecard. The trend rules are unchanged. The live code reproduces the research trade for trade, apart from the warm-up period. That check caught a bug: US holiday sessions close early, and the first version missed those day closes.

**Caveats:** it's a thin edge (+0.10R). It's sensitive to costs, so check your broker's spread on gold. It needs the broker's daily candles to close at 17:00 New York. On a small account the daily range is often too wide for half-percent risk at 0.01 lots.

## Round 6: six pre-registered ideas, and a look at the split (17 Nov 2026)

`round6.py`, `results_round6.csv`, `round6b_allocation.py`, `results_round6b_allocation.csv`

By this point `results*.csv` records **1,063 tested configurations**. At a nominal p<0.05 about 53 of those would look good by luck alone, so this round deliberately tested *six* ideas rather than hundreds, each with a mechanical reason, and paid the Bonferroni price for six (p<0.0083).

Two came from something the data said. The four context checks are information only, and the grade built from them is **inverted**: grade A averages +0.12R over 235 trades against grade B's +0.20R over 475. That is not mysterious once you look at how the grade is built — `h4` is a hard filter, so it contributes a guaranteed point and the grade is really out of three, with A requiring `session`, `adx` and `atr_band` all to pass. The backtest already says that requiring `session` or `adx` **hurts**. Grade A selects for two conditions known to be mildly harmful. So the obvious question was whether their *complements* help.

| Test | tune 2016-22 | val 2023-24 | kept | p | Verdict |
|---|---|---|---|---|---|
| BASELINE live rules | +0.156 | +0.156 | — | — | 721 trades, +0.181R all-period |
| H1 outside-hours only (20-07 UK) | +0.190 | **-0.020** | 61% | 0.103 | no |
| H2 quiet trend only (ADX < 20) | **-0.027** | +0.187 | 34% | 0.067 | no |
| H3 room-aware target | -0.017 | -0.046 | 104% | 1.000 | no |
| H4 skip after a losing trade | -0.012 | +0.096 | 86% | 0.095 | no |
| H5 stop at the signal candle (swing=1) | -0.115 | -0.251 | 130% | 1.000 | no |
| H6 stop at two candles (swing=2) | +0.004 | -0.093 | 108% | 1.000 | no |

**None passed.** What the round is actually worth:

- **The inverse filters don't work either.** H1 and H2 each look good in three of four periods and fail the fourth, with H2 keeping only a third of the trades. The grade is a poor signal, but its complement is not a good one. The right conclusion is that these checks carry little information in either direction, not that they should be flipped.
- **The 5-bar swing stop is doing real work.** H5 is the most decisive result here: stopping at the signal candle alone collapses the edge from +0.181R to **+0.013R** while *increasing* trades from 721 to 935. H6 (two candles) lands in between at +0.138R. Stop width is not a free parameter, and the current setting is well chosen.
- **Capping the target at a nearby level costs money.** H3 is mildly worse everywhere, so the winners that run straight through a daily level more than pay for the ones that stall at it.
- **Losses don't usefully cluster.** H4's validate period flatters it, the tune period does not.

### Round 6b: is the inside-day setup sized right?
Not another pattern search: one parameter over two already-validated return streams. Monthly correlation between the two strategies is **+0.091**, which independently confirms they are near-uncorrelated.

| Inside-day weight | Total | Max DD | Return/DD | Sharpe |
|---|---|---|---|---|
| 0.00 (trend only) | 130.6 | 12.2 | **10.70** | 0.999 |
| 0.25 | 149.1 | 15.2 | 9.79 | 1.095 |
| **0.50 (live)** | 167.6 | 18.3 | 9.18 | 1.143 |
| 0.75 | 186.1 | 21.3 | 8.75 | **1.154** |
| 1.00 | 204.6 | 24.4 | 8.37 | 1.142 |
| 1.50 | 241.7 | 31.1 | 7.77 | 1.093 |

Sharpe sits on a flat plateau from 0.5 to 1.0 and peaks at 0.75 by **0.011**, which is noise across 224 months — and it is a re-read of the same 18 years the weight was originally chosen on, not a new test. Return-over-drawdown actually prefers trend-only. **No change recommended:** 0.5 is a defensible point on a flat curve, and the honest summary is that the two objectives disagree, so the setting is a preference about drawdown rather than a number to optimise.

### Where that leaves things
All the gold data has been seen, so nothing here can be adopted on backtest evidence. Round 6 produced no candidate, and round 6b produced no change. The remaining honest routes to more edge are (1) forward live evidence, which the `nursery.json` tiers and `gate()` now collect, (2) the feature ledger, which from now on stores every hour the bot evaluates so later questions are answered from recorded features rather than re-derived, and (3) execution quality, which H1 data cannot measure.

## Round 7: does the edge read structure, or the return distribution? (18 Nov 2026)

`round7_synthetic.py`, `results_round7.csv`

A backtest can look good because a strategy genuinely reads market structure, or because its payoff shape happens to suit the return distribution. Rounds 1–6 never separated those. This does.

**The shuffle test.** Take the real 113,133 hourly candles, keep each candle's shape and its exact return, and replay them in random order. Trends, daily levels, session effects and every sequence the rules are supposed to read are destroyed; the return distribution, each bar's own volatility and the cost model are untouched. Then run the live rules.

| | Trades | Avg R |
|---|---|---|
| Real history | 721 | **+0.181** |
| 30 shuffled histories | median 819 | mean **−0.036** (sd 0.038, best +0.079) |

**None of the thirty reached the real result** (p = 0.032), and the real figure sits **5.7 standard deviations** above the shuffled mean. Destroying the order of the candles destroys the edge, and the shuffles land slightly *negative* — which is what a cost-paying strategy should do on a structureless series. This is the strongest evidence in the project that the rules read genuine sequence rather than exploiting the shape of gold's returns.

Note the trade count rises under shuffling (819 vs 721): with the sequence broken, more candles pass the trigger and fewer setups get cancelled by a colour flip. The real market produces *fewer but better* setups.

**The random-walk control, and why it does not work.** The intent was a second null: generate GBM at 75% annualised volatility and run the same rules on a series with nothing to read. It cannot do that job, and the reason is worth recording so nobody repeats it. A GBM cannot be driftless in both measures at once:

- a martingale in **price** (`px *= 1 + e`) carries log drift −σ²/2, which over 113k hours is a ~97% decline. That is a real downtrend, and the rules shorted it for **+0.091R**.
- a martingale in **log price** (`px *= exp(e)`) carries arithmetic drift +σ²/2 by Jensen, an uptrend over the same span, which measures **+0.034R** at zero cost and **+0.026R** with cost.

One artifact for its mirror image. A trend follower reads price levels, so whichever measure you pin, the other drifts and the rules pick it up. The shuffle test has no such problem, because it uses gold's own returns and assumes nothing about drift. **Test A is the null that counts; test B is kept only as a record of why a parametric control is the wrong tool here.**

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
python3 research/round4_tradingview.py # 20 TradingView indicators x 3 uses
python3 research/round5.py             # 21 more indicators, calendar, USD and silver filters
python3 research/round5_standalone.py  # 10 well-known standalone strategies
python3 research/round5_insideday_checks.py # robustness of the one that passed
python3 research/round6.py              # 6 pre-registered ideas, Bonferroni-corrected
python3 research/round6b_allocation.py  # inside-day risk weight sweep
python3 research/round7_synthetic.py   # shuffle test + random-walk control
```
