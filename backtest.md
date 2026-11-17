# Backtest: gold Heikin Ashi trend-ride (4H-confirmed, take-profit exits)

Generated 2026-11-17 15:22 UTC from 113,133 H1 candles (01 Jan 2008 to 13 Nov 2026). Costs: $0.35 per trade.
Training period: before 11 Apr 2021. Test period (rules never tuned on it): from 11 Apr 2021.

**How to read this.** R is the result in multiples of the risk on each trade: +2R means you made twice what you risked. Avg R above 0 after costs means the rules made money over the period. Profit factor (PF) is gross wins ÷ gross losses; above 1.3 is decent. A filter only counts as an improvement if it helps in **both** periods.

## Results

| Rules | Trades | Win | Avg R | Total R | PF | Trades | Win | Avg R | Total R | PF |
|---|---|---|---|---|---|---|---|---|---|---|
| | **Earlier 70%** | | | | | **Latest 30%** | | | | |
| Current rules | 493 | 60% | +0.15 | +75.6 | 1.36 | 227 | 61% | +0.24 | +55.2 | 1.61 |
| Video's original rules | 548 | 34% | -0.02 | -8.8 | 0.94 | 221 | 38% | +0.03 | +7.5 | 1.14 |
| Without the 4H Ichimoku cloud check | 563 | 57% | +0.09 | +52.5 | 1.21 | 250 | 60% | +0.21 | +51.5 | 1.50 |
| + London/NY hours only | 322 | 57% | +0.12 | +37.8 | 1.26 | 156 | 58% | +0.16 | +24.7 | 1.37 |
| + ADX trend strength | 379 | 59% | +0.13 | +48.9 | 1.30 | 178 | 59% | +0.17 | +30.6 | 1.41 |
| + normal volatility | 427 | 58% | +0.12 | +50.6 | 1.27 | 202 | 65% | +0.33 | +67.5 | 1.94 |
| Exit: single target at +1R | 548 | 59% | +0.12 | +67.2 | 1.28 | 249 | 61% | +0.20 | +50.3 | 1.51 |
| Exit: video's opposite-colour exit | 752 | 37% | +0.03 | +21.0 | 1.10 | 351 | 40% | +0.11 | +37.1 | 1.46 |

## Verdicts

- **Video's original rules**: worse in both periods (-0.02 / +0.03 vs +0.15 / +0.24, 221 test trades). Leave it off.
- **Without the 4H Ichimoku cloud check**: worse in both periods (+0.09 / +0.21 vs +0.15 / +0.24, 250 test trades). Leave it off.
- **+ London/NY hours only**: worse in both periods (+0.12 / +0.16 vs +0.15 / +0.24, 156 test trades). Leave it off.
- **+ ADX trend strength**: worse in both periods (+0.13 / +0.17 vs +0.15 / +0.24, 178 test trades). Leave it off.
- **+ normal volatility**: mixed (+0.12 / +0.33 vs +0.15 / +0.24, 202 test trades). No reliable edge.
- **Exit: single target at +1R**: worse in both periods (+0.12 / +0.20 vs +0.15 / +0.24, 249 test trades). Leave it off.
- **Exit: video's opposite-colour exit**: worse in both periods (+0.03 / +0.11 vs +0.15 / +0.24, 351 test trades). Leave it off.

## Baseline in detail (whole period)

- Trades: 720 (plus 426 setups cancelled before entry)
- **Verdict:** a thin edge after costs. Trade it small or paper-trade it while live results build up. 720 trades is a reasonable sample.
- Winners: 60%, average win +0.99R, average loss -1.04R
- Total: +130.8R, profit factor 1.44
- Biggest drop from a peak: 12.2R; longest losing run: 9 trades
- Average time in a trade: 35.8 hours

| Year | Trades | Win | Avg R | Total R |
|---|---|---|---|---|
| 2008 | 36 | 53% | -0.00 | -0.0 |
| 2009 | 42 | 64% | +0.29 | +12.3 |
| 2010 | 41 | 61% | +0.13 | +5.4 |
| 2011 | 56 | 68% | +0.30 | +16.6 |
| 2012 | 38 | 55% | +0.02 | +0.8 |
| 2013 | 31 | 61% | +0.24 | +7.5 |
| 2014 | 30 | 60% | +0.21 | +6.3 |
| 2015 | 38 | 55% | +0.09 | +3.5 |
| 2016 | 37 | 65% | +0.27 | +10.2 |
| 2017 | 34 | 41% | -0.24 | -8.3 |
| 2018 | 33 | 73% | +0.29 | +9.7 |
| 2019 | 33 | 55% | +0.03 | +1.0 |
| 2020 | 34 | 62% | +0.28 | +9.5 |
| 2021 | 35 | 57% | +0.13 | +4.6 |
| 2022 | 44 | 64% | +0.28 | +12.4 |
| 2023 | 31 | 58% | +0.13 | +3.9 |
| 2024 | 43 | 56% | +0.18 | +7.7 |
| 2025 | 50 | 66% | +0.35 | +17.7 |
| 2026 | 34 | 62% | +0.30 | +10.2 |

Grade is how many of the four context checks passed when the setup appeared (A = all four, B = two or three, C = fewer). None of them is a filter, so this table says whether the grade is worth anything.

| Grade | Trades | Win | Avg R | Total R |
|---|---|---|---|---|
| A | 235 | 57% | +0.12 | +28.9 |
| B | 475 | 61% | +0.20 | +96.5 |
| C | 10 | 80% | +0.54 | +5.4 |

| Direction | Trades | Win | Avg R | Total R |
|---|---|---|---|---|
| Sell | 267 | 58% | +0.17 | +44.2 |
| Buy | 453 | 61% | +0.19 | +86.6 |

| Session | Trades | Win | Avg R | Total R |
|---|---|---|---|---|
| Asia / late | 311 | 64% | +0.25 | +77.4 |
| London / NY | 409 | 57% | +0.13 | +53.4 |

## Second setup: inside-day breakout (runs separately)

After a daily candle that sits inside the previous day's range: buy-stop at its high, sell-stop at its low, stop at the other side, close at the next daily close. Research round 5.

| Period | Trades | Win | Avg R | Total R | PF |
|---|---|---|---|---|---|
| Earlier 70% | 532 | 49% | +0.10 | +51.7 | 1.31 |
| Latest 30% | 190 | 51% | +0.12 | +22.3 | 1.38 |
| Whole period | 722 | 49% | +0.10 | +74.1 | 1.32 |

- **Verdict:** a thin edge after costs. Trade it small or paper-trade it while live results build up. 722 trades is a reasonable sample.
- Biggest drop from a peak: 14.8R; longest losing run: 9 trades

| Year | Trades | Win | Avg R | Total R |
|---|---|---|---|---|
| 2008 | 32 | 56% | +0.42 | +13.5 |
| 2009 | 47 | 64% | +0.25 | +11.8 |
| 2010 | 39 | 46% | -0.04 | -1.6 |
| 2011 | 32 | 62% | +0.33 | +10.6 |
| 2012 | 40 | 40% | -0.06 | -2.3 |
| 2013 | 49 | 45% | -0.02 | -0.9 |
| 2014 | 48 | 40% | +0.17 | +8.3 |
| 2015 | 49 | 49% | +0.05 | +2.3 |
| 2016 | 40 | 60% | +0.14 | +5.6 |
| 2017 | 32 | 31% | -0.30 | -9.6 |
| 2018 | 41 | 51% | +0.15 | +6.1 |
| 2019 | 38 | 45% | -0.05 | -1.9 |
| 2020 | 35 | 43% | +0.07 | +2.5 |
| 2021 | 36 | 39% | +0.18 | +6.4 |
| 2022 | 27 | 56% | +0.10 | +2.7 |
| 2023 | 35 | 49% | -0.10 | -3.6 |
| 2024 | 41 | 54% | +0.19 | +8.0 |
| 2025 | 36 | 53% | +0.33 | +11.7 |
| 2026 | 25 | 64% | +0.18 | +4.6 |

## Caveats
- Backtest prices from Dukascopy (10-year file) or Twelve Data; live alerts use Twelve Data. OANDA can differ slightly.
- Entries assume the stop order fills exactly at its level; if a candle hits both entry and stop, the stop is assumed.
- No news blackout in the backtest (no historical calendar).
- Past results do not guarantee future results. Not financial advice.
