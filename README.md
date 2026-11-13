# xau: gold Heikin Ashi signals to Slack

Alert-only bot. It **never places trades**. A few minutes after each H1 candle closes, GitHub Actions runs `signals.py`. The script checks the Heikin Ashi trend-ride checklist on XAU/USD and posts to Slack:

- **Signal** (long or short): the checklist results, a stop-order level, a stop idea, and the next daily level
- **Entry level reached**, **stop idea reached**
- **Exit**: the first opposite-colour H1 Heikin Ashi close
- **Daily hold note**: the daily candle closed with no wick in your direction
- **Warning**, sent only if the bot fails 3 runs in a row

When nothing happens, it posts nothing.

## The checklist (H1 candle close)
1. Daily direction agrees: the daily Heikin Ashi colour, plus the daily close compared with the 50 EMA.
2. The candle is the first Heikin Ashi candle of the new colour with no wick on the wrong side (no lower wick for longs, no upper wick for shorts).
3. Its body is bigger than the previous candle's body.
4. In the last 24 H1 candles, price closed through a daily support or resistance level.
5. There is room before the next opposing daily level: at least 0.5 × the daily ATR.

Daily levels come from pivot closes over the last 180 days, the same way you'd mark them on a line chart. Daily candles close at 17:00 New York time, like OANDA's.

Every setting is in `CONFIG` at the top of `signals.py`. Edit it on GitHub and the next run uses the new values.

## Setup
1. **Slack webhook.** Go to api.slack.com/apps and choose *Create New App*, then *From scratch*, then *Incoming Webhooks*. Switch it on, choose *Add New Webhook*, pick **#gold-signals**, and copy the URL.
2. **Twelve Data key.** Sign up for the free plan at twelvedata.com and copy your API key.
3. **Secrets.** In this repo, open *Settings*, then *Secrets and variables*, then *Actions*, then *New repository secret*. Add both of these:
   - `SLACK_WEBHOOK_URL`
   - `TWELVEDATA_API_KEY`
4. **Test.** Open the *Actions* tab and choose *XAU signals*, then *Run workflow*, with mode set to `test`. A status message should appear in #gold-signals.

After that it runs on its own every hour while gold trades.

## Notes
- Prices come from Twelve Data's XAU/USD feed, not OANDA's. Candles can differ by a few points, so check the signal against your MT5 chart.
- GitHub can start scheduled runs several minutes late.
- The bot saves `state.json` after each run so it remembers any active trade idea.
- This is a rule-based tool, not financial advice.
