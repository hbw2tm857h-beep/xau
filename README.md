# xau: LumnFx trading signals to Discord

> **Research lab:** [`aurum/`](aurum/README.md) is a separate research platform that reverse-engineers why XAUUSD trades succeed or fail (mistake taxonomy, counterfactuals, experiment engine, dashboard in `lab_output/dashboard.html`). It never trades.

Alert-only bot. It **never places trades**. A few minutes after each H1 candle closes, GitHub Actions runs `signals.py`. The script checks the Heikin Ashi trend-ride rules on XAU/USD and posts plain-English alerts to the LumnFx Discord server:

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
The same rules as an EA for MetaTrader 5, **alerts only by default** (MT5 push plus optional Slack); set `InpAutoTrade = true` to place and manage orders, and test on a demo account first. All 19 strategy parameters match `CONFIG`, so it trades what was backtested. Compile it in MetaEditor (F7) before use. Version 2.34 compiles with 0 errors and 0 warnings (`mt5/compile.log`, MetaEditor 5 under the MetaQuotes Wine build on macOS). From the command line, run this from the MT5 install folder, with the paths relative to it: `MetaEditor64.exe /portable /compile:MQL5\Experts\<folder>\GoldTrendEA.mq5 /log:MQL5\Experts\<folder>\compile.log`. Absolute paths containing spaces (`C:\Program Files\...`) silently produce no log under Wine.

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

## Other markets: Bitcoin trend setups (shadow)
Research round 10 ran all three strategies, unchanged, on 21 other markets: 11 FX pairs, silver, two oils, six stock indices and Bitcoin. Only one result survived the realistic tests: **the trend rules on Bitcoin**. Taking signals only on weekdays and tracking trades through the weekend, that's 375 trades over 2017–2026 at +0.18R after costs, positive in 9 of 10 years and uncorrelated with gold. FX, oil, the indices and silver all failed (`research/README.md`).

So each run also fetches BTC/USD and runs the same trend code on it, with its own saved state (`state.json` under `markets.btc`). Bitcoin setups start in the **shadow** tier: they're alerted in Slack as paper trades with no size. If they earn it on live trades, the weekly gate proposes promotion, and you decide. They add roughly **0.75 setups a week**. The settings are under `CONFIG["markets"]["btc"]`: weekday signals only, $7.50 entry buffer, $30 costs. Delete that entry to switch it off. The MT5 EA is still gold-only.

## Nasdaq noise-area momentum (candidate, silent)
Research round 11 found one published edge that survives this project's tests: Zarattini, Aziz & Barbon's intraday "noise area" momentum on the Nasdaq 100. Over 2011–2026, on the 09:30 cash-session candles a live feed provides, that's about 3 trades a week at +4.4 bp each after costs (p = 0.0004). Each run fetches QQQ's hourly candles and journals the trades the rules would have made, as `ndx_noise` at tier `candidate`. It never alerts: the trades have to be acted on within the hour, and the scheduler runs late. The weekly gate judges it on these live trades. Set `CONFIG["noise"]["enabled"]` to `False` to turn it off.


## Near-miss candidates (silent)
Five research ideas that came close but missed the pass mark now run forward on live prices, as candidates: journalled, shown only in #candidate-tracking, judged by the weekly gate on live trades. They use candles each run already fetches, except `gold_m15`, which costs one extra Twelve Data call a run (its daily and 4-hour context come from the hourly candles).

| Strategy | Rule | Research | Per week |
|---|---|---|---|
| `btc_skipped` | Bitcoin trend setups skipped because a trade is already open (round 32) | +0.12R, p 0.064 | 0.4 |
| `btc_monday` | Long Bitcoin from Sunday 19:00 New York for 24h (round 11, Concretum) | +0.08R | 1.0 |
| `gold_fixes` | Long gold from the 15:00 London candle to the 10:00 close next morning (round 11, Bell) | +0.03R | 5.0 |
| `us_gap_fill` | Buy a gap down below a recent breakout on SPY, QQQ, DIA (round 13) | +0.31R, 94% winners | 0.34 |
| `gold_m15` | Gold's trend rules on 15-minute candles, only when the 1-hour Heikin Ashi agrees (round 33) | +0.07R, p 0.0032, lost in 2023-24 | 1.7 |

For the time-based rules, 1R is the 25-day average daily range. Round 13's Bitcoin IBS dip was left out: measured in R, with no stop, it averages −0.10R. Set `CONFIG["near_misses"] = False` to switch them all off.
## US index IBS reversion (shadow)
Research rounds 12–15 looked beyond gold: 23 pre-registered tests of documented edges on FX, commodities, stock indices and Bitcoin. One survived: **IBS band reversion on US stock indices**. Buy the cash close when the index has fallen more than 2.5 average daily ranges below its 10-day high *and* closed in the bottom 30% of the day's range. Sell at the first close above the previous day's high. Over 2011–2026 on the S&P 500, Nasdaq 100, Dow and Russell 2000 that's 616 trades, 72% winners, about +62 bp per trade before financing, uncorrelated with the gold strategies (monthly −0.03 to −0.07). It failed on ten non-US indices, so it is a US effect (`research/README.md`, rounds 12 and 15).

It runs as `us_ibs` at tier `shadow`: each hourly run fetches the daily candles of one of SPY, QQQ, DIA or IWM in turn, replays the rule, journals closed trades and posts paper alerts, a **BUY** when a dip qualifies and a **CLOSE** when the exit comes, never with a size. Each ETF is checked every four runs, so an alert can arrive up to about four hours after the 16:00 New York close it describes; index CFDs trade after hours, and in the research, entering at the next open instead of the close cost almost nothing (+34.9 bp against +36.6 bp). **The rule has no stop**, and the worst index trade in the 2020 crash lost 31%, so before it could carry size it needs a decision on that tail. 1R is the 25-day average daily range, so its R figures are not comparable with the gold setups'. Set `CONFIG["ibs"]["enabled"]` to `False` to turn it off.

## Ether inside-day (shadow)
Research round 16 ran the three gold strategies, unchanged, on 16 more markets: 11 commodities and 5 cryptocurrencies. One passed: **the inside-day breakout on Ether**. It held on 24/7 data with signals only from weekday inside days: 327 trades over 2017–2026 at +0.23R after costs, positive in every period, p = 0.0001, and none of 20 shuffled histories came close. It's uncorrelated with the gold setups (monthly +0.10 and 0.00).

Each run fetches ETH/USD hourly candles and runs the live inside-day code on them as `eth_inside_day` at tier `shadow`: the same inside-day alerts as gold, marked as paper with no size. Trend and 4-hour setups are off for Ether (`"trend": False`). The settings are under `CONFIG["markets"]["eth"]`; delete that entry to switch it off.

## History line on every new setup
Each new-setup alert (trend, inside-day, Bitcoin, Ether, US index dips) carries one line on how setups like it did in the past, for example:

> :abacus: _History: setups like this (BUY, grade B) won 63% of 298 times, avg +0.23R; all gold trend setups: 60% of 720 won, avg +0.18R. No real difference from the rest._

The numbers come from `data/similar_setups.json`, built by `research/similar_setups.py`, which replays the history files through the live code (prices scaled for Bitcoin and Ether, whose dollar settings are set for today's price). The groups are fixed and coarse: direction and grade for trend setups, tight or wide inside day (its range against the last 14 days' average, split at the median), deep or moderate dip for the US index trades. The line says whether a group's average differs from the rest (Welch t-test, p<0.05) and reminds you that a difference found by looking at the same history is a hint, not a rule. Most groups show no real difference, which is the honest answer: rounds 4–6 and 18 found that context and volume barely separate winners from losers. Re-run the script after refreshing the history files.

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
- **Pre-approved (21 Nov 2026):** Bitcoin trend, Ether inside-day and US index IBS (`CONFIG["auto_promote"]`) move to `live` by themselves once they pass that same test in full. They stay at a quarter of their risk-parity size, so their alerts look exactly as they do now ("Risk 0.30% of your account", no lot size; the lot calculator is built for gold contracts). The gold strategies are not on the list and are unaffected. A promoted strategy is demoted by itself, like any live one, if its last 50 trades fall under half its tested edge. Remove a name from `auto_promote` to take it back off the list.

**Why the asymmetry, and why the bootstrap is honest here.** `research/results*.csv` records **1,063** tested configurations (1,308 by round 17). At a nominal p<0.05 you would expect roughly 53 of those to look good by luck alone, which is why a backtest result on its own earns a candidate slot and nothing more — to clear that search, an idea would need p<0.000047. Live promotion is a different test: the rule was fixed *before* the live data existed, so it is a single pre-registered test with no multiplicity to correct for. That is the whole point of the nursery — it converts a multiple-comparisons problem into one clean out-of-sample test per idea.

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
1. Add the repository secrets `TWELVEDATA_API_KEY` (from the free plan) and the Discord webhooks listed under *Discord (LumnFx)* below.
2. Open *Actions* and run the workflow with mode `test`. A status message should appear in #bot-status.

Since 20 Nov 2026 the workflow posts to Discord only. The Slack code paths are still in `signals.py` (a message with no Slack webhook is printed to the log and skipped), so Slack can come back by adding the secrets to the workflow's `env` again.

### One channel per strategy (Slack, not in use)
Each strategy posts to its own channel through its own incoming webhook. A route with no webhook falls back to `SLACK_WEBHOOK_URL`, so channels can be added one at a time:

| Channel | Strategy | Secret |
|---|---|---|
| #signals-bitcoin | Bitcoin trend setups | `SLACK_WEBHOOK_BTC` |
| #signals-ether | Ether inside-day setups | `SLACK_WEBHOOK_ETH` |
| #signals-us-indices | US index IBS dips | `SLACK_WEBHOOK_US_IBS` |
| #gold-signals | gold trend and inside-day setups (and the 4-hour trigger, if promoted), plus the scorecard, nursery gate, status checks, backtests and failure warnings | `SLACK_WEBHOOK_URL` (`SLACK_WEBHOOK_TREND`, `SLACK_WEBHOOK_INSIDE_DAY` and `SLACK_WEBHOOK_REPORTS` are left unset, so they fall back to it) |

To add one: in your Slack app's *Incoming Webhooks* page, click *Add New Webhook to Workspace*, pick the channel and copy the URL. Then add it as a repository secret under the name above (*Settings → Secrets and variables → Actions*). The routes live in `CONFIG["slack_routes"]`.

### Discord (LumnFx)
Every alert goes to the LumnFx Discord server, converted to Discord's formatting (bold, `@everyone`, links, emoji). Routes are in `CONFIG["discord_routes"]`; a route without its secret is simply not posted to Discord.

| Discord channel | Gets | Secret |
|---|---|---|
| #gold | gold trend and breakout alerts | `DISCORD_WEBHOOK_GOLD` |
| #bitcoin | BTC/USD trend alerts | `DISCORD_WEBHOOK_BTC` |
| #ether | ETH/USD breakout alerts | `DISCORD_WEBHOOK_ETH` |
| #us-indices | US index rebound alerts | `DISCORD_WEBHOOK_US_IBS` |
| #bot-status (staff only) | scorecard, gate, status checks, warnings | `DISCORD_WEBHOOK_REPORTS` |

A failed Discord post never blocks the others; it is recorded, and the verify step reports it.

### Timing and the delivery check
- **Hourly runs** are started by the *Metronome* workflow (`.github/workflows/metronome.yml`) at :06 every hour, every day. It runs on GitHub alone: no outside scheduler, no extra token, no Claude session, so it keeps going when Claude usage runs out. One metronome job stays awake for about 5h40m, dispatches the signal check at :06, checks at :25 that a run started that hour (and starts one and warns in #bot-status if not), then dispatches the next metronome before the 6-hour job limit. Its own schedule (every 4 hours) restarts the chain if it ever breaks. GitHub's schedule on the signals workflow (`7 * * * *`) is the last backup. To stop the metronome, disable the workflow in the *Actions* tab. This relies on the repository being public: a private repository's free Actions minutes would not cover a job that is awake all day. Each run first pulls the latest state, so a run queued behind another can't repeat its alerts.
- **Economic calendar** (`calendar_post.py`, `.github/workflows/calendar.yml`): on Sunday at 20:15 UTC it posts the week's high-impact US releases to #economic-calendar, and on weekday mornings at 06:30 UTC it posts the day's releases when any are due. The data is Forex Factory's public weekly feed. It needs the `DISCORD_WEBHOOK_CALENDAR` secret; a failed post warns in #bot-status. It doesn't touch the signals.
- **Track record** (`track_record.py`): after every hourly run it rebuilds the #track-record post from `journal.json`, listing every trade members were alerted to (live and shadow strategies) that has closed since 14 November 2026, newest first, with the total in R. Silent candidates are left out. It edits the existing post in place and only when something changed. It needs the `DISCORD_WEBHOOK_TRACK` secret (the #track-record webhook, which created that post); without it the step does nothing.
- **US index dips** are checked for all four ETFs in the first run after 16:05 New York, so a BUY or CLOSE posts within minutes of the close. That run waits a minute before the extra calls, to stay within Twelve Data's free 8 calls a minute.
- **Late setups are not posted.** If a run is late and finds a new setup more than an hour after its candle closed, the setup is not posted (the entry may already have run), and nor are its later fills, take-profits or stops. One :fast_forward: line in the reports channel says what was skipped; the trade is still journalled. Alerts about a trade you were told about still post, marked late with the time of the setup, the time of the post and how late it is, because you may be in it. `CONFIG["max_setup_age_hours"]` sets the limit.
- **Verify step:** about 75 seconds after each hourly run, the workflow runs `signals.py` in `verify` mode. It checks that the run started within 15 minutes of the hour, processed the candle that just closed for gold, Bitcoin and Ether, checked the US ETFs after their close, delivered every post, and flagged nothing as late. When all is well it posts nothing. Otherwise it posts a :rotating_light: warning to the reports channel listing what went wrong.

### Getting push notifications
Slack sends no push for a webhook message that mentions nobody, because almost everyone's per-channel setting is *mentions and keywords only*. Messages still arrive in the channel; phones stay silent. Two ways to fix it:

- **Per person:** in the channel, open its name → *Notifications* → *All new messages*, and check the mobile section of that dialog separately, since it can differ from desktop. Each member has to do this for their own account.
- **For everyone, once:** the bot mentions `<!channel>` by default. Set the `SLACK_MENTION` secret to change it to `<!here>`, a user group such as `<!subteam^S0123|@traders>`, or an empty string for no mentions at all.

Heads-ups and the events that need you to act ping everyone: a confirmed entry, take-profit 1 (close half, move the stop) and the inside-day close. Expiries, take-profit 2 and stop-outs post without a mention. The weekly scorecard and the nursery gate never mention anyone. Edit `CONFIG["mention_events"]` to change the split.

Each trade gets a **heads-up** when the setup forms, mentioning everyone, with the stop order to place: its price, the stop and the take-profits. The **confirmed** alert goes out when the order fills (`CONFIG["confirmed_only"]`), on one line a phone preview can show. If the order expires unfilled, a quiet note says to delete it. A heads-up that would arrive more than `max_setup_age_hours` late is skipped, and so is a fill that late (with its follow-ups), because the price has moved on. For example:

```
@everyone Heads up: Gold may SELL · Place a sell-stop at 3,963.62 · Stop 4,002.41 · TP1 3,924.84 · TP2 3,886.06
The order lasts 12h. We'll post when it fills, or tell you to delete it if it doesn't.
@everyone SELL Gold · Filled · Entry 3,963.62 · Stop 4,002.41 · TP1 3,924.84 · TP2 3,886.06
@everyone Gold SELL · TP1 hit 3,924.84
Close 50% and move your stop to entry (3,963.62). The rest runs to TP2 3,886.06.
Gold SELL · TP2 hit 3,886.06 · Closed +1.49R
```

A new setup also carries an **open risk** line, so you can see what you are already holding before adding to it, and the `test` status check shows the same thing. It reports *current* risk rather than the risk a trade opened with: once take-profit 1 moves the stop to entry, that position reads `no risk left (stop at entry)`, because the remainder cannot lose. With two positions open it reads `Also open on Gold: trend SELL, 1.00R at risk · inside-day SELL, 0.50R at risk · 1.50R at risk in total`. The setup being announced is left out of its own line. A candidate strategy never appears, because it is tracked and never traded.

## Notes
- Prices come from Twelve Data's XAU/USD feed, not OANDA's. Candles can differ by a few points, so compare each setup with your MT5 chart.
- GitHub can start scheduled runs several minutes late.
- `state.json` holds the active setup and `journal.json` holds closed trades for the scorecard.
- This is a rule-based tool, not financial advice.
