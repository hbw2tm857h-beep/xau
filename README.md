# xau: gold Heikin Ashi signals to Slack

Alert-only bot. It **never places trades**. A few minutes after each H1 candle closes, GitHub Actions runs `signals.py`. The script checks the Heikin Ashi trend-ride rules on XAU/USD and posts plain-English alerts to Slack:

- **Setup** (buy or sell): the plan (entry, stop, size, exit, first level ahead, when it's cancelled), why the setup qualifies, and a grade from A to C based on the quality checks
- **Entry triggered**, **stopped out**, **exit signal** (the first opposite-colour H1 Heikin Ashi close), **setup cancelled**, **hold overnight**
- **Weekly scorecard** on Friday night, posted only if trades closed that week
- **Warning**, sent only if the bot fails 3 runs in a row

When nothing happens, it posts nothing.

## The rules (checked on each H1 candle close)
1. Daily direction agrees: the daily Heikin Ashi colour, plus the daily close compared with the 50 EMA.
2. The candle is the first Heikin Ashi candle of the new colour with no wick on the wrong side.
3. Its body is bigger than the previous candle's body.
4. In the last 24 hours, price closed through a daily support or resistance level, and there's room before the next one.

## Quality checks (shown on every setup; they set the grade)
| Check | Passes when |
|---|---|
| Session | London / New York hours (07:00 to 20:00 UK) |
| ADX | H1 trend strength is 20 or higher |
| 4-hour | The last 4-hour Heikin Ashi candle is the same colour as the setup |
| Volatility | The H1 ATR is neither in the bottom 10% nor the top 5% of the last 500 hours |
| News | No high-impact US event within 30 minutes (live alerts only) |

Grade **A** means all 4 of the first four checks pass, **B** means 2 or 3 pass, and **C** means 0 or 1 pass. Any check can become a hard filter in `CONFIG["filters"]`. Only switch one on if the backtest shows it helps in both the training period and the test period.

## Backtest
Open the *Actions* tab and choose *XAU signals*, then *Run workflow*, with mode set to `backtest`. It replays about 2.5 years of H1 data through the same code the live bot uses. It compares the video's rules with each quality check added, splits the history into a training period and a test period, and writes the results to `backtest.md` with a summary in Slack.

## Position size (optional)
Add these repository secrets to show a lot size on every setup:
- `ACCOUNT_SIZE`, for example `5000`
- `ACCOUNT_CCY`: `GBP`, `USD` or `EUR`
- `RISK_PCT`, for example `1`

The calculation assumes 1 lot = 100 oz. Check the contract size in your MT5 symbol specification and change `contract_oz` in `CONFIG` if it differs.

## Setup
1. Add the repository secrets `SLACK_WEBHOOK_URL` (an Incoming Webhook for #gold-signals) and `TWELVEDATA_API_KEY` (from the free plan).
2. Open *Actions* and run the workflow with mode `test`. A status message should appear in Slack.

## Notes
- Prices come from Twelve Data's XAU/USD feed, not OANDA's. Candles can differ by a few points, so compare each setup with your MT5 chart.
- GitHub can start scheduled runs several minutes late.
- `state.json` holds the active setup and `journal.json` holds closed trades for the scorecard.
- This is a rule-based tool, not financial advice.
