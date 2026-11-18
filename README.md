# xau: gold Heikin Ashi signals to Slack

Alert-only bot. It **never places trades**. A few minutes after each H1 candle closes, GitHub Actions runs `signals.py`. The script checks the Heikin Ashi trend-ride rules on XAU/USD and posts plain-English alerts to Slack:

- **Setup** (buy or sell): the plan (entry, stop, size, take profit 1 and 2, when it's cancelled), why the setup qualifies, and context checks
- **Entry triggered**, **take profit 1** (close half, move the stop to entry), **take profit 2**, **stopped out**, **setup cancelled**
- **Inside-day setup** (the second strategy, after the daily close): two one-cancels-the-other stop orders, then entry, stopped out, close at the daily close, or cancelled
- **Weekly scorecard** on Friday night, posted only if trades closed that week
- **Warning**, sent only if the bot fails 3 runs in a row

When nothing happens, it posts nothing.

## The rules (checked on each H1 candle close)
1. Daily direction agrees: the daily Heikin Ashi colour, plus the daily close compared with the 50 EMA.
2. The last closed **4-hour** Heikin Ashi candle is the same colour, and the last 4-hour close is on the right side of the **Ichimoku cloud** (above it for buys, below for sells). The cloud check was added in research round 4, which tested 20 popular TradingView indicators.
3. The H1 candle is the first Heikin Ashi candle of the new colour with no wick on the wrong side, and its body is bigger than the previous candle's body.
4. There's room before the next daily support or resistance level.

**Trade plan:** a stop-order entry just beyond the signal candle, with the stop beyond the last 5 candles. Take half off at +1R and move the stop to entry, then close the rest at +2R. The setup is cancelled if the colour flips or 12 hours pass before entry.

**Tested 2008–2026 (`research/`):** 720 trades, 60% winners, +0.18R per trade after costs, profit factor 1.44 — reproducible with mode `backtest`, which now replays both history files. The research rounds reported 715 and 1.42, before the history file was last refreshed. Before the Ichimoku cloud check it was 805 trades, 57% winners and +0.12R. The video's original rules lost money over the same period.

## Second setup: inside-day breakout (research round 5)
This runs separately from the trend setups and has its own alerts. When a daily candle (17:00 New York close) sits entirely inside the previous day's range, the bot posts two orders, and the first one to trade cancels the other:
- a buy-stop at the inside day's high, with the stop at its low
- a sell-stop at its low, with the stop at its high

There's no take-profit. The trade closes at the next daily close whatever happens, and the orders are cancelled if neither side trades that day. Lot sizes use **half** the normal risk (`inside_day_risk_mult`). Set `"inside_day": False` in `CONFIG` to turn it off.

**Tested 2008–2026:** 722 trades, 49% winners, +0.10R per trade after costs, profit factor 1.32, positive in all four test periods. It's a thinner edge than the trend setups, but almost uncorrelated with them. Running both at this size raised the Sharpe ratio from 0.95 to 1.09. Round 5 tested 77 more indicators, calendar and other-market filters and 10 well-known strategies, and this was the only one that passed (`research/README.md`).

## Context checks (shown on every setup, information only)
| Check | Passes when |
|---|---|
| Session | London / New York hours (07:00 to 20:00 UK) |
| ADX | H1 trend strength is 20 or higher |
| Volatility | The H1 ATR is neither in the bottom 10% nor the top 5% of the last 500 hours |
| News | No high-impact US event within 30 minutes |

None of these improved results by a meaningful amount in both test periods, so none of them is a filter. Any of them can be switched on in `CONFIG["filters"]`.

Every setup also gets a grade: A when all four checks pass, B for two or three, C for fewer. It is information only, and `backtest.md` shows why — over 2008–2026 grade A averages **+0.12R across 235 trades** while grade B averages **+0.20R across 475**. More checks passing has been slightly *worse*, not better, so do not treat an A as a reason to size up. The reason is arithmetic rather than mysterious: the 4-hour check is a hard filter, so it always passes and the grade is really out of three, with an A needing session, ADX and volatility all to pass — and the backtest says requiring session or ADX *hurts*. Round 6 tested the complements of both and they failed too, so these checks carry little information in either direction.

## Backtest
Open the *Actions* tab and choose *XAU signals*, then *Run workflow*, with mode set to `backtest`. It replays the 10-year history file through the same code the live bot uses. It compares the video's rules with each quality check added, splits the history into a training period and a test period, and writes the results to `backtest.md` with a summary in Slack.

## MT5 Expert Advisor (`mt5/GoldTrendEA.mq5`)
The same rules as an EA for MetaTrader 5, **alerts only by default** (MT5 push plus optional Slack); set `InpAutoTrade = true` to place and manage orders, and test on a demo account first. All 19 strategy parameters match `CONFIG`, so it trades what was backtested. Compile it in MetaEditor (F7) before use.

**Auto-trading.** `InpAutoTrade = false` by default: it only alerts. Set it to `true` and it places the stop order, manages the stop, takes take-profit 1 off and moves the stop to entry, and runs the inside-day pair at `InpInsideDayRisk` of the normal size. The broker holds the stop and take-profit 2, so an exit still happens if MetaTrader is closed.

`InpDemoOnly = true` means that with auto-trading on, the EA **refuses to start** on anything but a demo account, and says why. It fails loudly rather than falling back to alerts, because a silent fallback is easy not to notice. Set `InpDemoOnly = false` only when you actually mean to trade the account in front of you. On start it prints the account type, login, broker, balance, leverage and whether algo trading is permitted — that last one is the usual reason an EA places nothing — and posts a one-off Slack message naming the account and the risk per trade, so there is a record of when execution went live.

**Any MT5 broker.** The EA reads the symbol specification rather than assuming one, so it works the same on Deriv, Weltrade or anything else: it accepts gold under any name (`XAUUSD`, `GOLD`, `GOLD.m`, `XAUUSD.v`), takes the order filling mode from the symbol, sizes from the broker's own tick value and lot step, and picks a pending-order expiry the broker accepts — falling back to good-till-cancelled, which is safe because the EA cancels its own orders after `InpEntryExpiryBars`. On start it prints the full spec it is working from (contract size, tick value, lot limits, stops and freeze levels, current spread, expiry support) so the numbers are visible instead of assumed. If the contract size is not the standard 100 oz per lot, it says so and tells you what to set on the Python side.

Two things it handles that the Python bot gets for free:
- **Gaps.** If the terminal is closed or offline, every missed H1 candle is re-checked in order (up to `InpMaxCatchupBars`), reading the higher timeframes as they stood at the time. A setup found more than two hours late is marked, and the EA says whether its entry was already reached while it was away — it never enters late.
- **The broker's idea of a day.** Everything daily — trend, 50 EMA, daily ATR, the levels and the inside-day test — reads the *broker's* D1 candles, while the research builds its own days in New York time rolling at 17:00 NY. Those agree only if your broker's day rolls there too. Most gold brokers on GMT+2/+3 server time do, but the US and EU change clocks on different dates, so the boundary can slip by an hour for a few weeks each spring and autumn, and some brokers never use that convention. On the first tick the EA works out the broker's actual boundary and warns if it differs, naming the offset. It is a warning, not a block: hourly setups are unaffected, but treat the daily context and the inside-day setup as approximate until you have checked. Turn it off with `InpCheckDailyRoll`.

## Third setup: 4-hour trigger (candidate, silent)
The same trigger as the trend setups, read on the 4-hour Heikin Ashi candle instead of the hourly one, with the daily trend still required. Research round 9 found it the only survivor of four new entry mechanisms: 526 trades over 2008–2026 at +0.14R, positive in all four test periods.

It runs at tier `candidate`, which means it is **journalled and written to the ledger but never alerted**. That is deliberate. Its monthly returns correlate **+0.395** with the trend setups — not a duplicate, since 87% of its signals fire at other times, but both require the daily trend so they can never take opposite sides. Compare the inside-day setup's +0.09, which is what made running two strategies genuinely additive. Its per-trade edge is also below the trend setups' +0.18R, and all of its evidence is in-sample, which round 8 showed is worth little on its own. So it collects live out-of-sample evidence at no risk until the gate has 30 closed trades to judge it on. `"h4_trigger": False` in `CONFIG` turns it off.

`research/round9_entries.py` calls the live `h4_setup` directly, so the backtest and the bot cannot drift apart. Both report 526 trades at +0.1434R.

## Tiers: what gets traded, what only gets watched
Each strategy in `nursery.json` sits in one of three tiers:

| Tier | Alerts | Size | Journalled |
|---|---|---|---|
| `candidate` | none | — | yes |
| `shadow` | yes, marked as paper | none shown | yes |
| `live` | yes | yes | yes |

So a new idea can accumulate **live, out-of-sample evidence at zero risk and zero noise** before it ever touches real size. Both current strategies start `live`, so nothing about today's behaviour changes.

Once a week (with the scorecard, or on demand with mode `gate`) each strategy is judged on its own live trades:
- A **live** strategy whose last 50 trades average less than half the edge it was promoted on is **demoted automatically** — alerts carry on, marked paper and unsized, until it earns its way back. Demotion is automatic because it cuts risk.
- A **candidate or shadow** strategy with 30+ closed trades, a positive average above half its tested edge, and a one-sided bootstrap p<0.05 is **proposed** for promotion. The gate never applies it: raising real size stays your decision, made by editing `nursery.json`.

**Why the asymmetry, and why the bootstrap is honest here.** `research/results*.csv` records **1,063** tested configurations. At a nominal p<0.05 you would expect roughly 53 of those to look good by luck alone, which is why a backtest result on its own earns a candidate slot and nothing more — to clear that search, an idea would need p<0.000047. Live promotion is a different test: the rule was fixed *before* the live data existed, so it is a single pre-registered test with no multiplicity to correct for. That is the whole point of the nursery — it converts a multiple-comparisons problem into one clean out-of-sample test per idea.

## What it remembers (feature ledger)
Every hour the bot checks, it writes one row to `data/ledger.csv`: the features it computed (Heikin Ashi geometry on H1, the daily trend and distance from the 50 EMA in ATRs, the 4-hour colour and Ichimoku position, ADX, ATR and its percentile, room to the nearest daily levels, hour, day, session, inside-day flag) plus what it decided and what state it was in. Closed trades go to `data/outcomes.csv`, keyed by `sig_time` so it joins to the ledger's `t_close`.

The split matters: the ledger row is written when the bar closes, before the outcome is known, and the outcome is attached later. So testing a new idea becomes a query over stored rows rather than a replay of raw candles, and nothing in a row can have been coloured by how the trade turned out.

`source` says where a row came from. `live` is what the bot actually saw at the time. `backfill` is reconstructed from the history file — useful, but keep the two apart when judging anything.

**One column is there purely for research:** `trigger_dir` is the H1 Heikin Ashi trigger on its own, with none of the higher-timeframe filters. Over 2008-2026 it fires on 14.3% of all hours and only 7.2% of those survive to become a setup, so the ledger lets you ask what the filters are actually throwing away.

To build the history in one go, run the workflow with mode `backfill`: it replays both history files (2008-2015 and 2016 onwards) through the live state machine and writes `data/ledger_backfill.csv.gz` — 111,684 hours and 1,442 closed trades, ~5 MB, about 30 seconds. Those 1,442 match the 715 + 726 trades reported by the research rounds, which is a useful check that the replay really does run the live rules. The hourly run appends live rows from then on. Set `"ledger": False` in `CONFIG` to turn the whole thing off; a ledger write never blocks an alert.

## Position size (optional)
Add these repository secrets to show a lot size on every setup:
- `ACCOUNT_SIZE`, for example `5000`
- `ACCOUNT_CCY`: `GBP`, `USD` or `EUR`
- `RISK_PCT`, for example `1`
- `CONTRACT_OZ`, only if your broker is not the standard 100 oz per lot

The calculation assumes 1 lot = 100 oz, which is standard but not universal — micro and cent accounts often are not. Attach the EA and read the contract size it prints, or open the symbol specification in MT5, and set the `CONTRACT_OZ` secret if it differs. A wrong contract size misstates every lot size the bot posts, which is a risk number you would act on.

## Setup
1. Add the repository secrets `SLACK_WEBHOOK_URL` (an Incoming Webhook for #gold-signals) and `TWELVEDATA_API_KEY` (from the free plan).
2. Open *Actions* and run the workflow with mode `test`. A status message should appear in Slack.

### Getting push notifications
Slack sends no push for a webhook message that mentions nobody, because almost everyone's per-channel setting is *mentions and keywords only*. Messages still arrive in the channel; phones stay silent. Two ways to fix it:

- **Per person:** in the channel, open its name → *Notifications* → *All new messages*, and check the mobile section of that dialog separately, since it can differ from desktop. Each member has to do this for their own account.
- **For everyone, once:** the bot mentions `<!channel>` by default. Set the `SLACK_MENTION` secret to change it to `<!here>`, a user group such as `<!subteam^S0123|@traders>`, or an empty string for no mentions at all.

Only the events that need you to **touch your platform** ping everyone: a new setup (place the orders), take-profit 1 (close half, move the stop), a cancellation (delete the pending order), an inside-day entry (delete the other side) and the inside-day close. A fill, a take-profit 2 and a stop-out post without a mention, because the broker has already done the work. The weekly scorecard and the nursery gate never mention anyone. Edit `CONFIG["mention_events"]` to change the split.

Every alert opens with one compact line — direction, entry, stop, lot size, take-profits — because a phone preview shows about that much, and a title like "SELL SETUP: Gold" is not something you can trade from. The detail follows underneath.

A new setup also carries an **open risk** line, so you can see what you are already holding before adding to it, and the `test` status check shows the same thing. It reports *current* risk rather than the risk a trade opened with: once take-profit 1 moves the stop to entry, that position reads `0.00R (stop at entry)`, because the remainder cannot lose. Two positions at full risk read `trend SELL 1.00R · inside-day SELL 0.50R · total 1.50R, about 1.50% of the account`. A candidate strategy never appears, because it is tracked and never traded.

## Notes
- Prices come from Twelve Data's XAU/USD feed, not OANDA's. Candles can differ by a few points, so compare each setup with your MT5 chart.
- GitHub can start scheduled runs several minutes late.
- `state.json` holds the active setup and `journal.json` holds closed trades for the scorecard.
- This is a rule-based tool, not financial advice.
