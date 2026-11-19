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

## Round 8: the multiple-testing haircut (18 Nov 2026)

`round8_multiple_testing.py`, `results_round8.csv`

Round 6 noted that 1,063 recorded configurations means ~53 would look good by luck at a nominal 5% threshold. That was an argument; this measures it, using the Deflated Sharpe Ratio (Bailey & López de Prado, *Journal of Portfolio Management* 40(5)) and the equivalent haircut in Harvey & Liu, *Backtesting* (SSRN 2345489).

The False Strategy Theorem: run N skill-free backtests and the best still posts a respectable Sharpe, purely from the spread of the trials. Its expected value is `sqrt(V[SR]) · [(1-γ)·Z(1-1/N) + γ·Z(1-1/(Ne))]`. That, not zero, is the bar a real strategy must clear.

V[SR] is normally the input nobody has, because failed backtests get deleted. This project logged **1,070** of them, so it is measured rather than assumed. Each trial's tune-period average R is divided by the live per-trade standard deviation, which is fair because every trial shares the same 1R-stop / 2R-target payoff shape.

**Compared on a like basis.** The trials were all scored on the tune period, so the candidate is too: tune-period per-trade Sharpe **0.1464** on 250 trades. (Whole period: 0.1694 per trade, ~1.05 annualised. Comparing that against the spread of 250-trade trials would pit a precise estimate against noisy ones and is wrong.)

| N independent trials | E[max SR] under no skill | as a share of the observed 0.1464 | DSR |
|---|---|---|---|
| no selection | 0.0000 | 0% | 0.989 |
| 10 | 0.2445 | 167% | 0.061 |
| 50 | 0.3535 | 241% | 0.001 |
| 100 | 0.3930 | 268% | 0.000 |
| 1,070 | 0.5085 | 347% | 0.000 |

**The in-sample Sharpe does not survive.** At just ten independent trials, the expected best result under no skill already exceeds what the rules actually achieved on the tune period. At the full trial count, luck alone would be expected to produce three and a half times the observed figure. Restricting V[SR] to variants of the adopted rules (dropping the unrelated `asia` and `pullback` sweeps) makes it harsher still, because rounds 4–5's indicator variants scatter more widely than those tightly clustered sweeps.

**What this does and does not say.** It says the backtest's in-sample Sharpe is worth approximately nothing as evidence, and that any future idea selected on in-sample performance should be assumed worthless until confirmed out of sample. It does not say the strategy has no edge, because two pieces of evidence of an entirely different kind sit outside a selection-bias calculation:

- the **sealed 2008–15 lockbox**, opened once, where the adopted rules held (345 trades, 58% winners, +0.10R) and a competing candidate was rejected
- **round 7's shuffle test**, where destroying the candle order destroyed the edge (0 of 30, 5.7 standard deviations). Selection bias cannot explain why the order of the bars matters.

One caveat cuts the strategy's way and is not resolved: V[SR] is the *observed* spread, which mixes estimation noise with real differences in strategy quality, while the theorem wants the spread under no skill. To the extent some trials were genuinely better or worse, V[SR] is overstated here.

**The practical consequence** is the nursery (`nursery.json`) and the gate, which were already built on exactly this reasoning: a backtest result earns a candidate slot and nothing more, and promotion requires live out-of-sample trades. Round 8 is the number that justifies that policy.

## Round 9: four new entry mechanisms (18 Nov 2026)

`round9_entries.py`, `results_round9.csv`

### What was already ruled out

"Try other entries" had largely been done, and it is worth stating before proposing anything: **672 of the 1,070 recorded trials were non-Heikin-Ashi entries, and both families lost money.**

- `asia`, 336 configs, mean tune avg R **−0.085**: Asia-range breakout at London *and* fade mode, which is a failed-breakout reversal, across range filters, trend filters and stop placements.
- `pullback`, 336 configs, mean tune avg R **−0.063**: daily trend + the right side of EMA50 + dip to EMA20 + Heikin Ashi confirmation.

Round 5 then ran ten well-known standalone systems and nine failed: Turtle 1 and 2, Connors RSI-2, Bollinger reversion, NR7 breakout, Turtle Soup, golden/death cross, London opening-range breakout, Eastern-hours long. Only the inside-day breakout passed.

So **mean reversion, failed breakouts, opening-range, channel breakout and moving-average crosses are tested and dead on this instrument.** Proposing them again would re-run a failed experiment and add to the multiple-testing bill.

### The four ideas and the results

| Test | Trades | Avg R | All four periods positive | p | Verdict |
|---|---|---|---|---|---|
| E1 H1 inside bar | 11,558 | **−0.200** | no | 1.000 | no |
| **E2 4H Heikin Ashi trigger** | **526** | **+0.143** | **yes** | **0.0017** | **PASS** |
| E3 rolling 12h squeeze breakout | 2,636 | −0.010 | no | 1.000 | no |
| E4 Sunday gap fill | 81 | −0.224 | no | 1.000 | no |

**E1 is the informative failure.** The inside-day setup is a volatility contraction on D1 and it works; the identical mechanism on H1 loses 0.2R per trade across 11,558 trades. The mechanism does not survive the timeframe change, which is a useful constraint on how it is understood: the daily inside bar is probably about the *daily* decision cycle, not about compression in general.

**E2 passed**: the project's own trigger, read on the 4-hour candle instead of the hourly one, with the daily trend still required. Positive in all four periods, strongest in the two most recent, 526 trades at +0.143R.

### How much E2 is actually worth

It had to be checked against the obvious objection — that it is the live strategy in slow motion:

| | E2 vs the live trend rules |
|---|---|
| Monthly return correlation | **+0.395** |
| Signals within 4 hours of a live signal | 13% |
| Same calendar day | 21%, and **always the same direction** |

It is not a duplicate: 87% of its signals fire at times the live rules do not. But it is not independent either. Both require the daily trend to agree, so the two can never take opposite sides, and +0.395 is far from the inside-day's +0.09 that made running two strategies worthwhile. Its per-trade edge is also slightly below the live rules' +0.181R.

Two further cautions. Both E2 and the live rules show their strongest results in 2025–26, when gold trended hard; that flatters any trend follower and is a regime, not a skill. And per round 8, the in-sample figure carries little weight on its own with 1,070 trials recorded — the four-period consistency is the only in-sample evidence worth anything.

**Conclusion: E2 earns a nursery candidate slot and nothing more.** It is a real, distinct trade stream with a positive expectation across every period tested, selected under a pre-registered Bonferroni-corrected rule. It is also correlated with something already live, so its portfolio contribution is modest, and all its evidence is in-sample. Tracking it silently on live data is exactly what the candidate tier exists for.

## Round 10: the gold strategies on 21 other markets (19 Nov 2026)

`round10_markets.py`, `results_round10_markets.csv`, `round10_btc_checks.py`, data in `data/markets/`

**Why:** gold alone gives about one trend setup and 0.7 inside-day setups a week. More markets would mean more signals, but only if the edge travels. This is also the cleanest test left in the project. None of the three strategies was ever tuned on any of these markets, so every result is out of sample for the rules. That's a different kind of evidence from the in-sample Sharpe that round 8 discounted.

**Pre-registered:**
- **Strategies:** the live trend rules (with the cloud), the inside-day breakout and the 4-hour trigger, nothing re-tuned.
- **Markets (21):**
  - FX: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD, EURJPY, GBPJPY, EURGBP, AUDJPY
  - Silver, WTI and Brent oil
  - Indices: S&P 500, Nasdaq 100, Dow, DAX, FTSE, Nikkei
  - Bitcoin
- **Data:** Dukascopy H1, 2008 to now. Indices start between 2011 and 2013, with some quarters of 2013 missing; Bitcoin starts in 2017.
- **Costs:** a share of price per market, 1 to 10 basis points (gold is 1.75). Gold's three $0.30 buffers are scaled by each market's typical hourly range (ATR).
- **Pass mark, 63 tests:**
  - at least 150 trades and at least +0.05R per trade
  - positive in every period with 10 or more trades, with at least 3 such periods
  - p < 0.05/63 = 0.0008

### Results
| | trend | inside-day | 4-hour |
|---|---|---|---|
| **Gold (reference)** | +0.192 ✔ | +0.111 (p 0.0011) | +0.149 ✔ |
| 11 FX pairs | best AUDJPY +0.075 (p 0.03) | best USDJPY +0.121, but 2023–24 negative | best NZDUSD +0.036 |
| Silver | −0.028 | +0.063 | +0.018 |
| WTI / Brent | −0.039 / +0.056 | **+0.130** (2025–26 −0.002) / +0.073 | +0.041 / +0.002 |
| S&P / Nasdaq / Dow | +0.007 / +0.033 / −0.023 | +0.005 / +0.016 / −0.050 | +0.023 / **+0.181** (p 0.0012) / +0.012 |
| DAX / FTSE / Nikkei | +0.063 / −0.023 / **+0.126** (p 0.0033) | −0.001 / −0.160 / +0.087 | +0.056 / −0.072 / −0.005 |
| **Bitcoin** | **+0.185 ✔** | **+0.210 ✔** | +0.166 (p 0.012) |

**2 of 63 passed, both on Bitcoin.** Even the gold reference's own inside-day setup misses at this bar (p 0.0011), which shows how strict it is. Near misses that are positive in every period but not significant after correction: Nikkei trend (p 0.0033) and Nasdaq 4-hour (p 0.0012). FX is dead for all three strategies, as round 3 found for the trend rules.

### The Bitcoin checks (`round10_btc_checks.py`)
| | trend | inside-day |
|---|---|---|
| As tested (gold's trading hours, 5 bp) | +0.185 | +0.210 |
| Costs at 10 bp / 20 bp | +0.159 / +0.107 | +0.191 / +0.152 |
| Fills at the open after a gap | +0.191 | |
| 24/7 data, weekend signals included | +0.112 (p 0.014) | +0.062 (p 0.096) |
| **Weekday signals, trades tracked through weekends (realistic)** | **+0.180, 375 trades, p 0.00078** | +0.170, but 2025–26 −0.023, p 0.009 |
| Shuffle test (20 shuffles) | 0/20 reached it, 5.0 sd | 0/20, 2.9 sd |
| Years positive | 9/10 | 10/10 |
| Buys / sells | +0.217 / +0.124 | +0.255 / +0.159 |
| Monthly correlation with gold trend / inside-day | −0.03 / +0.08 | |

- **The weekend matters.** Weekend Bitcoin signals are weak, and the inside-day passed only because the first test dropped weekend candles. A live bot would still be holding trades through the weekend.
- **Realistic test:** take signals only in gold's trading hours, but manage open trades on every candle. The trend rules still pass under that; the inside-day setup doesn't.
- **What remains:** the trend rules on Bitcoin read real sequence (the shuffle destroys the edge), are positive in 9 of 10 years, and are uncorrelated with gold. The data is shorter (2017 on), and 2017–2026 was mostly a bull market, though shorts made money too (+0.124R).

**Adopted as a shadow strategy, `btc_trend`:** Bitcoin trend setups are alerted in Slack, marked as paper with no position size, and judged by the weekly gate on live trades. Promoting it to sized is your decision. In `signals.py` it runs as an extra market: same code, its own saved state, weekday signals only, weekend candles kept, $7.50 entry buffer (gold's $0.30 × the ATR ratio over the last 12 months) and $30 costs (about 5 bp). Run through the live code with the research settings, it reproduces the research exactly (375 trades, +0.208R before costs). Gold's trades are unchanged.

Not done: the MT5 EA still trades gold only.

## Round 11: published anomalies from SSRN and the literature (19 Nov 2026)

`round11_literature.py`, `results_round11_literature.csv`, `round11_noise_checks.py`

**Sources:** SSRN, journals and quant-research sites (Quantpedia, Concretum, QuantifiedStrategies, university repositories). Reddit could not be read: it blocks this tool's crawler and returns 403 to direct requests, and getting around that would break its access terms. Every idea found was checked against the 1,137 configurations already tested.

**Not tested, with reasons:**
- **Gold in September and November (Baur 2013):** monthly seasonality that failed the original study's own data-snooping test (Quantpedia, SSRN 3202658).
- **Monthly gold moving-average and momentum timing:** no new signals, and it overlaps the trend rules.
- **Pre-FOMC drift (Lucca & Moench):** shown for stocks, with no solid evidence for gold.
- **London-fix price pressure (Caminschi & Heaney):** needs minute data, and the fix method changed in 2015.
- **Every Reddit and TradingView "gold strategy" the searches surfaced:** no testable rules or track record.

**Nine pre-registered tests** (rules as published, adapted to hourly candles; results in basis points after costs; p < 0.05/9 = 0.0056):

| Test | Source | Per week | Net bp | 2008–15 | 2016–22 | 2023–24 | 2025–26 | Years + | p | |
|---|---|---|---|---|---|---|---|---|---|---|
| L1 Gold intraday momentum | Gao, Han, Li & Zhou (JFE 2018) | 3.9 | −2.2 | −2.5 | −2.3 | −0.9 | −2.0 | 1/19 | 1 | no |
| L2 Bitcoin intraday momentum | Shen, Urquhart & Wang | 6.0 | −4.9 | | −5.6 | −4.6 | −3.7 | 1/10 | 1 | no |
| L3 Bitcoin 21–23 UTC long | Padyšák & Vojtko | 6.3 | +2.2 | | +2.6 | +4.1 | **−1.0** | 7/10 | 0.098 | no, faded after publication |
| L4 Bitcoin Monday Asia open | Concretum (2025) | 1.0 | +37.7 | | +40.8 | +41.1 | +25.2 | 8/10 | 0.019 | near miss |
| L5 Gold long between the London fixes | Bell (SSRN 6077836) | 5.0 | +3.3 | +2.5 | +2.4 | +6.9 | +5.9 | 12/19 | 0.007 | near miss |
| L6 Noise-area momentum, gold | Zarattini, Aziz & Barbon (SSRN 4824172) | 10.1 | −2.1 | −3.2 | −1.7 | −0.6 | +0.3 | 4/19 | 1 | no |
| L7 Noise-area momentum, Bitcoin | same | 11.9 | −1.0 | | −1.4 | +0.7 | −1.8 | 5/10 | 0.66 | no |
| **L8 Noise-area momentum, Nasdaq 100** | **same** | **3.0** | **+5.7** | **+5.8** | **+5.4** | **+5.2** | **+7.5** | **14/15** | **0.000008** | **PASS** |
| L9 Bitcoin at a 20-day high or low | Padyšák & Vojtko (SSRN 4081000) | 1.6 | +26.4 | | +36.7 | +27.3 | −3.1 | 7/10 | 0.032 | no |

**What the round says:**
- **Gold and Bitcoin show no edge in any of these intraday mechanisms.** Intraday momentum and the noise-area breakout both lose on gold and Bitcoin, though both are documented on stock indices. Nothing here argues against the existing gold rules: it says gold's edge is multi-timeframe trend, not intraday flow.
- **Published edges fade.** The Bitcoin 21–23 UTC effect is negative in 2025–26, the main period after its 2022 publication.
- **The pass replicates the paper's own claim.** The noise-area method was published on US index ETFs, and on the Nasdaq it holds on hourly candles in every period.

**Nasdaq noise-area stress tests (`round11_noise_checks.py`):**
- **Costs:** +4.7 bp at 2 bp costs and +3.7 bp at 3 bp, still positive in every period.
- **Direction:** buys +7.2 bp (15 of 15 years positive), sells +4.1 bp.
- **Shuffle test:** 0 of 20 shuffles reached it, about 9 standard deviations below the real result.
- **Risk:** daily Sharpe 1.59 a year, worst drop 650 bp.
- **S&P 500 (the paper's original market):** +2.6 bp, positive every period, p 0.0075.
- **Dow:** fails (−0.4 bp).

**Re-test on live-matchable candles (`round11_noise_30.py`).** A live feed (QQQ on Twelve Data) gives hourly candles from the 09:30 open, not on the hour, so the rules were re-run on 30-minute Dukascopy data rebuilt that way:

| | Net per trade | 2011–15 | 2016–22 | 2023–24 | 2025–26 | Years + | p |
|---|---|---|---|---|---|---|---|
| 09:30 candles, 1 bp | +4.4 bp | +1.4 | +5.4 | +6.6 | +4.2 | 12/15 | 0.00041 |
| 09:30 candles, 3 bp | +2.4 bp | −0.6 | +3.4 | +4.6 | +2.2 | 10/15 | 0.035 |

It still passes at realistic costs (0.5–1 bp), with buys at +5.8 bp and sells at +2.7 bp, but it's thinner and more sensitive to costs than on the on-the-hour candles. The bot's `noise_trades` reproduces these 2,242 trades exactly (`round11_noise_30.py check`): +0.074R per trade with 1R = the noise band at entry (median 41 bp), 44% winners.

**Now in the bot as a silent candidate (`ndx_noise`).** Each run fetches QQQ's hourly candles, replays the rules on complete sessions and journals new closed trades. It never alerts. That builds the live record the gate judges at no risk, and because the replay is deterministic, late runs don't matter. Before it could ever alert, it would need:
1. **On-time runs:** an external hourly trigger, since GitHub's schedule runs hours late.
2. **Alert code:** intraday entry and exit alerts, which aren't written yet.
3. **Your sizing decision:** it's an index trade alongside gold.

**Original status (before the re-test): research only, not in the bot.** It's a genuine candidate, but three things stand between it and alerts:
1. **Timing.** It acts within the hour during the US cash session. GitHub's scheduler has been running the bot hours late, and a late alert is worthless for an intraday trade. It needs the external hourly trigger first.
2. **Data.** The research used Dukascopy's Nasdaq 100 CFD with candles on the hour. A live feed (Twelve Data's NDX, or QQQ, whose candles start at :30) has to be matched to that, or the rules re-checked on it.
3. **Portfolio.** Gold, Bitcoin and an index trade are different risks. How it should be sized next to the gold setups is your decision.

## Round 12: documented edges beyond gold (19 Nov 2026)

`round12_beyond_gold.py`, `results_round12_beyond_gold.csv`, `round12_ibs_checks.py`

**Why:** the Slack system should cover more than gold. Rounds 3 and 10 showed the gold rules don't travel, so this round started from edges documented *on each market*, in the literature or in the Reddit catalogue (`reddit_catalogue.md`), and tested them on the hourly data already in `data/`. All nine rules, the costs, CFD financing for index positions held overnight, and the pass mark were committed (5b800b2) before anything ran. Pass: 150+ observations, positive in every period with 10+, one-sided p < 0.05/9 = 0.0056.

| Test | Source | n | Net bp | 2008–15 | 2016–22 | 2023–24 | 2025–26 | Years + | p | |
|---|---|---|---|---|---|---|---|---|---|---|
| M1 Time-series momentum, 22 markets (monthly, vol-scaled) | Moskowitz, Ooi & Pedersen 2012 | 214 | +9.3 | +6.8 | +6.6 | +7.1 | +30.2 | 10/18 | 0.17 | no |
| M2 FX: home currency weakens 08–12 local | Breedon & Ranaldo 2013 | 4,901 | −0.8 | −0.2 | −1.3 | −1.0 | −1.4 | 4/19 | 1 | no |
| M3 FX: dollar weakens 08–12 New York | same | 4,900 | −1.1 | −1.2 | −0.8 | −1.8 | −0.6 | 4/19 | 0.99 | no |
| M4 FX month-end hedge flows | Melvin & Prins 2015 | 158 | −2.3 | +1.2 | −4.4 | −3.8 | +2.8 | 5/14 | 0.89 | no |
| M5 Turn of the month, 6 indices | Lakonishok & Smidt; McConnell & Xu | 172 | +10.8 | +23.4 | +7.6 | −28.2 | +41.5 | 7/15 | 0.24 | no |
| M6 US overnight drift (after financing) | Cliff, Cooper & Gulen; Reddit #6 | 3,236 | +0.3 | +1.2 | +0.1 | −0.3 | +0.7 | 11/14 | 0.41 | no |
| M7 European-open drift, US indices | Boyarchenko, Larsen & Whelan 2023 | 3,346 | +0.1 | +1.1 | −0.1 | −1.0 | +0.8 | 7/14 | 0.43 | no |
| **M8 IBS band reversion, 6 indices** | **Reddit #1; Pagonidis 2013** | **1,060** | **+36.6** | **+46.7** | **+32.1** | **+31.4** | **+40.2** | **13/15** | **2.6e-07** | **PASS** |
| M9 USDJPY into the Tokyo fix | Ito & Yamada 2017 | 1,359 | −0.3 | +0.1 | −0.1 | −0.8 | −1.9 | 8/19 | 0.71 | no |

(Index data starts in 2011–13, so "2008–15" means 2011–15 for M5–M8.)

**What failed and why it matters:** the FX time-of-day effects are now slightly *negative* after costs, and so is the month-end hedge-flow trade. US overnight drift is real before financing but a long CFD position pays roughly 2 bp a night, which takes all of it. Time-series momentum is positive in every period but far too noisy at monthly frequency to clear the bar.

**IBS stress tests (`round12_ibs_checks.py`):**
- **Random entries** with the same holding periods on the same indices make +10.6 bp, which is the indices' upward drift. **None of 300 random runs reached +36.6 bp** (z = 3.8). The edge is the timing, not just being long.
- **Execution:** entering at the next session's open instead of the signal close gives +34.9 bp. Double costs give +35.3 bp. Without financing it would be +42.9 bp.
- **Clustering:** trades on different indices often fire in the same sell-off. On weekly averages it's still t = 5.1.
- **Where it works:** the three US indices carry it: S&P 500 +55 bp (p 5e-05), Nasdaq +70 bp (p 2e-05), Dow +46 bp (p 0.0003). DAX, FTSE and Nikkei are positive (+14 to +22 bp) but not significant on their own.
- **No stop, so the tail is real:** worst trades were DAX −31% (Feb 2020, held 19 sessions), FTSE −22% and Nikkei −17% (Mar 2020). Median hold 3 sessions. About 70 trades a year across six indices.
- **Correlation, monthly:** −0.03 with the gold trend setups, −0.05 with inside-day, −0.07 with `ndx_noise`. A genuinely separate stream.

**Verdict:** a nursery candidate on the three US indices, where it passes on each one alone. It stays journal-only until live trades back it. Before it could ever carry size it needs a decision on the tail: the rule as published has no stop, and the 2020 trades show what that costs.

## Round 13: does the IBS edge travel? (19 Nov 2026)

`round13_more_markets.py`, `results_round13_more_markets.csv`. Seven tests, committed before running, bar p < 0.05/7 = 0.0071.

| Test | n | Net bp | 2008–15 | 2016–22 | 2023–24 | 2025–26 | p | |
|---|---|---|---|---|---|---|---|---|
| N1 IBS band, 11 FX pairs, both sides | 4,450 | −0.8 | −4.0 | −1.3 | −3.2 | +16.5 | 0.64 | no |
| N2 IBS band, gold/silver/WTI/Brent, both sides | 1,457 | −23.2 | −34.6 | −32.9 | +37.7 | −26.2 | 0.96 | no |
| N3 IBS band, Bitcoin, long only | 118 | +120.8 | | +156.4 | +80.7 | +50.8 | 0.053 | too few trades |
| N4 Nasdaq intraday momentum (Gao et al. 2018) | 3,659 | −0.9 | +0.5 | −1.1 | −2.0 | −1.3 | 0.94 | no |
| N5 Bitcoin weekly momentum (Liu & Tsyvinski 2021) | 489 | +35.6 | | +53.1 | +4.7 | +15.3 | 0.21 | no |
| N6 Lower-low/high reversal, US indices (Reddit #3) | 1,704 | +3.3 | +0.6 | +6.2 | +3.2 | −2.8 | 0.051 | no |
| N7 Daily gap fill, US indices (Reddit #12) | 263 | +24.9 | +45.1 | +6.7 | +51.1 | +38.3 | 0.041 | no |

IBS reversion is not a general mean-reversion edge: it is flat on FX and loses on commodities, gold included. Bitcoin is promising but has only 118 trades.

## Round 14: relative value and cross-sectional (19 Nov 2026)

`round14_relative_value.py`, `results_round14_relative_value.csv`. Six tests, bar p < 0.05/6 = 0.0083.

| Test | n | Net bp | p | |
|---|---|---|---|---|
| P1 FX cross-sectional momentum (Menkhoff et al. 2012) | 225 | −16.3 | 0.97 | no |
| P2 Pairs: Brent vs WTI (z = 2, 20 days) | 106 | +12.9 | 0.20 | no |
| P3 Pairs: AUDUSD vs NZDUSD | 169 | −3.9 | 0.75 | no |
| P4 Pairs: Nasdaq 100 vs Dow | 116 | −16.4 | 0.86 | no |
| P5 Pairs: gold vs silver | 168 | −32.8 | 0.91 | no |
| P6 Weekly reversal across six indices | 419 | +4.8 | 0.22 | no |

No relative-value edge on these markets at textbook settings.

## Round 15: IBS on ten indices it had never seen (19 Nov 2026)

`round15_ibs_new_indices.py`, `results_round15_ibs_new_indices.csv`. Ten more indices were downloaded from Dukascopy for this test only (`data/markets/*idx*`). CAC 40, SMI and South Africa 40 fail in the downloader. One confirmatory test of the unchanged round 12 rule, bar p < 0.05.

**It failed.** Pooled: 1,495 trades, +1.75 bp, p 0.41, and 110 of 300 random-entry runs did as well.

| Index | From | n | Net bp | p |
|---|---|---|---|---|
| Russell 2000 | 2018 | 109 | +43.0 | 0.096 |
| Euro Stoxx 50 | 2014 | 175 | +30.8 | 0.079 |
| FTSE MIB | 2016 | 119 | +8.5 | 0.41 |
| Hang Seng | 2013 | 247 | +5.7 | 0.36 |
| WIG 20 | 2018 | 109 | +0.0 | 0.50 |
| ASX 200 | 2014 | 189 | −3.5 | 0.57 |
| AEX | 2018 | 111 | −8.3 | 0.61 |
| IBEX 35 | 2014 | 159 | −9.0 | 0.65 |
| Singapore | 2018 | 146 | −24.1 | 0.83 |
| China A50 | 2017 | 131 | −25.6 | 0.87 |

**What it means:** the IBS edge is not a property of stock indices in general. It is a US effect. All four US indices tested are positive, by +43 to +70 bp: S&P 500, Nasdaq 100 and Dow in round 12, each significant on its own, plus Russell 2000 here, the only new US index. Outside the US it is mostly flat or negative, and round 12's DAX, FTSE and Nikkei were not significant either. That fits the explanation usually given for it, persistent buying of US index dips. **So the candidate covers the US indices only**, and a non-US version is ruled out.

## Round 16: the gold strategies on 16 more markets (19 Nov 2026)

`round16_commodities_crypto.py`, `results_round16_commodities_crypto.csv`, `round16_eth_checks.py`, `round16_eth_live_check.py`

Round 10's code, costs method and pass mark, unchanged, on markets Dukascopy offers that round 10 didn't use: copper, platinum, palladium, natural gas, cocoa, coffee, sugar, cotton, soybeans, orange juice, diesel, Ether, Litecoin, Bitcoin Cash, Stellar and Cardano. 48 tests, bar p < 0.05/48 = 0.00104, committed (9fddd8f) before the data was downloaded. Most softs and the altcoins start in 2017–2021, and copper and natural gas are missing 2013 (Dukascopy fails on that year).

**1 of 48 passed: the inside-day breakout on Ether**, 376 trades, +0.223R, PF 1.83, p 5.5e-05. Near misses that don't clear the bar: orange-juice inside-day (+0.143R, p 0.0038), coffee trend (+0.136R, p 0.056) and coffee inside-day (p 0.063). Everything else is flat or negative, including every metal and all four other cryptos' trend setups.

**Ether checks** (the realistic test was fixed in advance: 24/7 data, signals only from weekday inside days, trades tracked through weekends; it must stay positive in every period at p < 0.05):

| | n | avg R | 2016–22 | 2023–24 | 2025–26 | p |
|---|---|---|---|---|---|---|
| As tested (gold's hours, 8 bp) | 376 | +0.223 | +0.315 | +0.188 | +0.023 | 5.5e-05 |
| Costs 16 bp / 32 bp | 376 | +0.199 / +0.151 | | | −0.002 / −0.052 | 0.0003 / 0.004 |
| 24/7, all signals | 543 | +0.193 | +0.220 | +0.167 | +0.157 | 2e-05 |
| **24/7, weekday signals (realistic)** | **327** | **+0.226** | **+0.241** | **+0.304** | **+0.102** | **0.0001** |

- Buys +0.229R, sells +0.217R. Positive in 8 of 10 years.
- **Shuffle test:** 0 of 20 shuffles reached it (mean −0.007R).
- **Monthly correlation:** +0.45 with Bitcoin's inside-day setup (not running), −0.01 with Bitcoin's trend setups, +0.10 with gold's trend setups, +0.00 with gold's inside-day.
- **Live code:** `round16_eth_live_check.py` replays all of Ether through `ib_step` with the live config. At zero cost 309 of the research's 327 trades match exactly and the averages agree (+0.252R live, +0.250R research). The rest are the warm-up period, and days that hit both sides, where the live code uses the hourly order instead of the research's open-price rule.

Bitcoin's inside-day setup failed this same realistic test in round 10. Ether's passes it, so **Ether's inside-day setup is now a silent nursery candidate (`eth_inside_day`)**.

## Round 17: the gold strategies on 30 more markets (19 Nov 2026)

`round17_more_fx_indices.py`, `results_round17_more_fx_indices.csv`

Round 10's code and pass mark on the ten indices downloaded for round 15 and twenty FX pairs round 10 didn't cover: USDMXN, USDZAR, USDSEK, USDNOK, USDPLN, USDHUF, USDCNH, USDSGD, USDCZK, AUDNZD, CADJPY, CHFJPY, NZDJPY, EURCHF, EURCAD, EURAUD, GBPAUD, GBPCAD, GBPCHF and AUDCAD. USDTRY was excluded in advance because of financing. 90 tests, bar p < 0.05/90 = 0.00056, committed (514da22) before the FX data was downloaded. Several pairs are missing 2013, which Dukascopy fails to serve.

**0 of 90 passed.** The closest:

| Market | Strategy | n | avg R | p |
|---|---|---|---|---|
| FTSE MIB | h4 | 170 | +0.216 | 0.0046 |
| CADJPY | insideday | 636 | +0.088 | 0.024 |
| Hang Seng | trend | 329 | +0.092 | 0.062 |
| IBEX 35 | h4 | 265 | +0.091 | 0.084 |
| Hang Seng | h4 | 252 | +0.086 | 0.1 |

That completes the sweep. Across rounds 3, 10, 16 and 17 the gold strategies have now been run on 67 other markets, and two survived: the trend rules on Bitcoin and the inside-day breakout on Ether. FX, in any form, never has.

## Round 18: does volume help? (19 Nov 2026)

`round18_volume.py`, `results_round18_volume.csv`, volume in `data/volume/`

**Why:** Bradley asked for a live volume-based probability. **The data problem first:** spot gold, FX and index CFDs have no exchange volume. The free sources for real US ETF volume either block scripts behind a browser check (Stooq) or report the broker's own small flow rather than the exchange's (Dukascopy's SPY shows ~2,000 units a day against ~60 million real shares). So the volume here is Dukascopy's own hourly volume, a proxy for activity. Five tests were committed (b630686) before it was downloaded. Each asks whether a volume condition picks out better trades from a strategy already in the bot. Bar p < 0.05/5 = 0.01.

| Test | Favoured | n | avg | Other | n | avg | p | |
|---|---|---|---|---|---|---|---|---|
| V1 US IBS, capitulation volume (RVOL ≥ 1.5) | high volume | 145 | +43 bp | normal | 447 | +61 bp | 0.77 | no, worse |
| V2 Gold trend, trigger candle RVOL ≥ 1.0 | high volume | 339 | +0.156R | low | 382 | +0.223R | 0.80 | no, worse |
| V3 Gold trend, VPIN above its 500-hour median | high VPIN | 378 | +0.132R | low | 343 | +0.257R | 0.94 | no, worse |
| V4 Gold inside-day, quiet inside day (RVOL < 1) | quiet | 426 | +0.088R | busy | 301 | +0.146R | 0.79 | no, worse |
| V5 Ether inside-day, quiet inside day (RVOL < 1) | quiet | 207 | +0.288R | busy | 120 | +0.117R | 0.073 | no |

**What it says:**
- **Volume adds nothing the strategies can use.** Four of the five favoured groups did *worse*. The classic ideas, capitulation volume, volume confirmation and informed-flow VPIN, all point the wrong way on these strategies, though none of the reversals is significant either.
- **VPIN is the "volume-based probability" in the literature, and it is not a direction signal.** Here, setups taken when it was high averaged half the R of the rest. That fits its published use as a warning of volatility and toxic flow, not as an entry signal.
- **The one hint, Ether's quiet inside days, is not enough.** It is better in all three periods, but p 0.073 misses the bar, and it would be the 1,314th configuration tested. It is not adopted. The bot already journals every Ether trade, so live trades can show whether it is real at no cost.
- A pass on proxy volume would have needed checking against real exchange volume (futures or ETF tape) before use. None passed, so that question doesn't arise.

## Round 19: the five alerted strategies as one portfolio (19 Nov 2026)

`round19_portfolio.py`. Not a rule search: nothing changes and nothing is added to the test count. It measures what the strategies are worth together. Every trade comes from the live code replaying history, in R, booked by exit month, over the 104 months all five can trade (Mar 2018 – Oct 2026), assuming 1R = 1% of the account.

| Stream | R a month | Vol | Sharpe | Total | Worst drop |
|---|---|---|---|---|---|
| Gold trend | +0.72 | 2.15 | 1.16 | +75R | 7.5R |
| Gold inside-day | +0.30 | 1.54 | 0.68 | +31R | 6.7R |
| Bitcoin trend | +0.42 | 1.74 | 0.83 | +43R | 9.7R |
| Ether inside-day | +0.71 | 2.00 | 1.22 | +74R | 5.7R |
| US IBS | +1.21 | 5.13 | 0.82 | +126R | 23.1R |

**Correlations are all low:** the highest monthly correlation is +0.22 (US IBS with gold trend); most pairs are between −0.09 and +0.17.

| Portfolio | R a month | Vol | Sharpe | Worst drop |
|---|---|---|---|---|
| Gold only (today's live set: trend 1%, inside-day 0.5%) | +0.87 | 2.36 | 1.28 | 7.6R |
| All five at 1% each | +3.36 | 7.21 | 1.62 | 24.8R |
| **All five, risk parity (inverse volatility)** | **+2.86** | **5.47** | **1.81** | **22.6R** |
| All five, mean-variance (fitted in-sample) | +3.03 | 5.59 | 1.88 | 20.7R |
| √(Σ Sharpe²), if fully uncorrelated | | | 2.16 | |

Fitted on the first half and judged on the second (52 months): gold only 1.41, equal 1% 1.76, **risk parity 1.80**, mean-variance 1.65. The mean-variance weights don't survive out of sample; risk parity, which uses no return information, does.

**What it says:**
- **Breadth is the lever.** Adding the three new streams lifts the portfolio Sharpe from 1.28 to about 1.8 with no change to any rule. At the same volatility as gold alone, that's roughly 40% more return.
- **Size US IBS at about 0.4% per R, not 1%.** Its R (the 25-day average range) is small next to a no-stop crash, so it carries most of the portfolio's volatility and drawdown. Risk parity weights per R: gold trend 0.98, gold inside-day 1.36, Bitcoin trend 1.20, Ether inside-day 1.05, US IBS 0.41.
- **The drawdown rises with the size.** All five at risk parity have a 22.6R worst drop against gold's 7.6R, mostly from US IBS in crash months. Scaled to gold's volatility the worst drop is about 9.7R. Size the whole book to the drawdown you can sit through, not the Sharpe.
- **Caveats:** in-sample history only. The three new streams have no live record yet (shadow tier). US IBS excludes financing (roughly −6 bp a trade) and has no stop. Bitcoin's live config takes a few more signals than its research version.

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
python3 research/round8_multiple_testing.py # deflated Sharpe / multiple-testing haircut
python3 research/round9_entries.py      # four new entry mechanisms
python3 research/round10_markets.py     # the three strategies on 21 other markets
python3 research/round10_btc_checks.py  # Bitcoin: costs, weekends, shuffle test
python3 research/round11_literature.py  # nine published anomalies (SSRN etc.)
python3 research/round11_noise_checks.py # stress tests on the Nasdaq noise-area pass
python3 research/round12_beyond_gold.py   # nine documented edges on other markets
python3 research/round12_ibs_checks.py    # stress tests on the IBS index pass
python3 research/round13_more_markets.py  # IBS on FX/commodities/Bitcoin + four more
python3 research/round14_relative_value.py # pairs and cross-sectional tests
python3 research/round15_ibs_new_indices.py # IBS on ten unseen indices
python3 research/round16_commodities_crypto.py # gold strategies on 16 more markets
python3 research/round16_eth_checks.py      # stress tests on the Ether inside-day pass
python3 research/round16_eth_live_check.py  # live code vs research on Ether
python3 research/round17_more_fx_indices.py # gold strategies on 30 more markets
python3 research/round18_volume.py         # five volume tests (Dukascopy volume)
python3 research/similar_setups.py         # build data/similar_setups.json (alert history line)
python3 research/round19_portfolio.py      # the five strategies as one portfolio
python3 research/round12_ibs_live_check.py  # live code vs research on US IBS
```
