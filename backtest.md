# Backtest: gold Heikin Ashi trend-ride

Generated 2026-11-14 18:03 UTC from 12,053 H1 candles (22 Nov 2024 to 13 Nov 2026). Costs: $0.35 per trade.
Training period: before 08 May 2026. Test period (rules never tuned on it): from 08 May 2026.

**How to read this.** R is the result in multiples of the risk on each trade: +2R means you made twice what you risked. Avg R above 0 after costs means the rules made money over the period. Profit factor (PF) is gross wins ÷ gross losses; above 1.3 is decent. A filter only counts as an improvement if it helps in **both** periods.

## Results

| Rules | Trades | Win | Avg R | Total R | PF | Trades | Win | Avg R | Total R | PF |
|---|---|---|---|---|---|---|---|---|---|---|
| | **Training** | | | | | **Test** | | | | |
| Video rules (baseline) | 45 | 38% | +0.03 | +1.3 | 1.13 | 34 | 41% | +0.11 | +3.8 | 1.48 |
| + London/NY hours only | 27 | 48% | +0.11 | +2.9 | 1.70 | 18 | 28% | -0.05 | -0.9 | 0.81 |
| + ADX trend strength | 35 | 34% | -0.01 | -0.4 | 0.95 | 24 | 29% | -0.13 | -3.1 | 0.53 |
| + 4-hour agrees | 35 | 40% | +0.09 | +3.1 | 1.44 | 20 | 45% | +0.17 | +3.4 | 1.97 |
| + normal volatility | 37 | 35% | +0.04 | +1.7 | 1.20 | 27 | 41% | +0.13 | +3.4 | 1.57 |
| + stop not too wide | 37 | 38% | -0.05 | -1.7 | 0.81 | 29 | 38% | +0.09 | +2.7 | 1.39 |
| + all quality checks | 15 | 47% | +0.12 | +1.7 | 1.77 | 8 | 12% | -0.12 | -1.0 | 0.53 |
| Baseline + breakeven at 1R | 45 | 33% | +0.02 | +0.9 | 1.09 | 34 | 41% | +0.11 | +3.8 | 1.48 |

## Verdicts

- **+ London/NY hours only**: mixed (+0.11 / -0.05 vs +0.03 / +0.11, 18 test trades). No reliable edge.
- **+ ADX trend strength**: worse in both periods (-0.01 / -0.13 vs +0.03 / +0.11, 24 test trades). Leave it off.
- **+ 4-hour agrees**: slightly better in both periods (+0.09 / +0.17 vs +0.03 / +0.11, 20 test trades), but too small or too few trades to rule out luck. Keep watching.
- **+ normal volatility**: slightly better in both periods (+0.04 / +0.13 vs +0.03 / +0.11, 27 test trades), but too small or too few trades to rule out luck. Keep watching.
- **+ stop not too wide**: worse in both periods (-0.05 / +0.09 vs +0.03 / +0.11, 29 test trades). Leave it off.
- **+ all quality checks**: mixed (+0.12 / -0.12 vs +0.03 / +0.11, 8 test trades). No reliable edge.
- **Baseline + breakeven at 1R**: mixed (+0.02 / +0.11 vs +0.03 / +0.11, 34 test trades). No reliable edge.

## Baseline in detail (whole period)

- Trades: 79 (plus 37 setups cancelled before entry)
- **Verdict:** a thin edge after costs. Trade it small or paper-trade it while live results build up. Only 79 trades, so this is an early read, not proof.
- Winners: 39%, average win +0.74R, average loss -0.37R
- Total: +5.1R, profit factor 1.29
- Biggest drop from a peak: 3.2R; longest losing run: 6 trades
- Average time in a trade: 5.9 hours

| Grade | Trades | Win | Avg R | Total R |
|---|---|---|---|---|
| A | 23 | 35% | +0.03 | +0.8 |
| B | 45 | 40% | +0.04 | +1.6 |
| C | 11 | 45% | +0.24 | +2.7 |

| Direction | Trades | Win | Avg R | Total R |
|---|---|---|---|---|
| Sell | 35 | 40% | +0.08 | +2.7 |
| Buy | 44 | 39% | +0.05 | +2.3 |

| Session | Trades | Win | Avg R | Total R |
|---|---|---|---|---|
| Asia / late | 34 | 38% | +0.09 | +3.1 |
| London / NY | 45 | 40% | +0.04 | +2.0 |

## Caveats
- Twelve Data prices, not OANDA's; wicks can differ slightly.
- Entries assume the stop order fills exactly at its level; if a candle hits both entry and stop, the stop is assumed.
- No news blackout in the backtest (no historical calendar).
- Past results do not guarantee future results. Not financial advice.
