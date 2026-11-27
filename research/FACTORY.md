# Strategy factory: design for approval (27 Nov 2026)

**Status: design only. Nothing is built until Bradley approves it.**

## What it is for

Forty research rounds tested ideas one at a time, and almost all failed. The rules on gold already capture most of what its candles offer, and every year of gold history has now been used several times. The factory changes the approach. A machine builds thousands of rule combinations on old data, cuts them hard on newer data, and sends the few survivors to silent live tracking, where the bot's existing nursery decides what is real. Live data is the one test that never runs out.

What it can and can't do:
- It **will** produce candidates. Expect most batches to produce 0 to 3 survivors, and most of those to fail in live tracking.
- It **won't** produce an instant better strategy. Every candidate needs about 30 live trades before it can be promoted, which takes months.
- What it builds over time is a **portfolio**: several separate, weak trade streams that together beat any one of them. That gain comes from combining streams, not from luck.

## The pipeline

1. **Generate.** Rules are put together from a fixed set of building blocks (below), on each approved market.
2. **Build test, 2008-2019.** Each rule is run with costs on 2008-19 only. Most are thrown out here.
3. **Cut, 2020-Nov 2026.** The best 20 rules from the build test, and only those, are run once on 2020-26. They have never been tuned on these years.
4. **Silent tracking.** Rules that pass the cut join `nursery.json` as `candidate`. They are journalled, and their cards go to the staff-only #candidate-tracking channel. Members never see them.
5. **Promotion.** The existing gate takes over. After 30 closed live trades it reports whether a candidate is ready for shadow (paper alerts, no size), and every promotion is Bradley's decision. Candidates that average below zero after 30 live trades are retired.

## Building blocks

Every rule is one entry, up to two filters and one exit, traded in one direction or both. The parameters come from small fixed grids, decided now, so the machine can't fine-tune them.

**Entries (hourly or daily candles):**
- break of the highest high or lowest low of the last N candles (N = 10, 20, 55)
- pullback: price touches the N-candle EMA in a trend (N = 20, 50)
- inside candle broken in either direction (daily, 4-hour)
- close at an extreme of the candle's range (IBS under 0.2 or over 0.8), traded back toward the middle
- N closes in a row in one direction, faded or followed (N = 3, 4, 5)
- range squeeze: ATR at its lowest in 20 candles, then a break
- break of the first hour's range of the market's main session

**Filters:**
- higher-timeframe trend: daily close above or below the 50-day EMA; daily Heikin Ashi colour; sign of the 12-month return
- volatility: ATR percentile above or below 50 over the last year
- room: distance to the last daily high or low at least 1 ATR

**Exits:**
- fixed target at 1R, 2R or 3R, with the stop at the entry's natural invalidation (other side of the range or candle)
- half off at 1R, rest at 2R, stop to entry (the live gold exit)
- close after N candles (N = 3, 10, or the day's close)
- trailing stop at 2 ATR

**Ruled out:** time-of-day and day-of-week fishing, machine-learning black boxes, more than two filters, martingale, grids, averaging down, and anything that needs data the bot doesn't receive live.

That is about 4,000 rules per market. On gold plus the approved markets, a batch is roughly 40,000 to 80,000 rules.

## Markets

Gold plus up to 20 liquid markets that already have hourly data from 2008 (2011 for indices) and a cost from rounds 10, 16 and 17. Proposed: silver, oil (WTI, Brent), copper, S&P 500, Nasdaq 100, Dow, DAX, FTSE, Nikkei, EURUSD, GBPUSD, USDJPY, AUDUSD, GBPJPY, EURJPY, Bitcoin, Ether. Each is charged its own cost. Every result is in R after costs. Bitcoin and Ether data starts in 2017, so their build test covers only 2017-19 and they need the 100-trade daily minimum to qualify; they may simply not have enough history.

## Bars, fixed now

**Build test (2008-2019), all of these:**
- at least 200 trades (100 for daily rules)
- average at least +0.05R after costs, and still positive at double costs
- positive in each of 2008-11, 2012-15 and 2016-19
- a plateau, not a peak: the rules one grid step away on each parameter are also positive on average
- beats random entries: the same exits on random entry times (500 shuffles) do worse at p < 0.05

Survivors are ranked by t-statistic. The top 20 per batch go to the cut. If fewer pass, fewer go.

**Cut (2020-Nov 2026), all of these:**
- average at least +0.05R after costs
- one-sided p < 0.05 / 20 = 0.0025 (or 0.05 divided by however many went to the cut)
- positive in both 2020-22 and 2023-26, counting only a period with at least 20 trades
- its daily returns correlate at less than 0.3 with each live and shadow strategy, so it adds something new

**Live (the existing gate):** 30 closed trades, a bootstrap p-value under the gate's bar, and Bradley's decision.

## Counting tests honestly

The build test runs on 2008-19, and the cut runs on separate data, so the bar at the cut only has to cover the rules sent to it: at most 20 per batch. Each batch adds the number it sends to the cut to `hypotheses_tested`. The tens of thousands of rules thrown out in the build test are recorded in the batch report but not added to the counter. The live gate divides its bar by that counter, so adding them would make promotion impossible for every strategy, existing ones included. The build test's own bar (plateau, random entries, three periods, double costs) is what guards against those thousands.

2020-26 has already been seen by earlier rounds, but only for specific rules. None of the factory's rules has been tuned on it, so it serves as their cut. Live tracking is the test nobody has seen.

## What gets built, in order

1. **Generator and test harness** (research only, one PR). It builds the rules, runs the build test and the cut, and writes a batch report. No change to the bot.
2. **Rule runner in `signals.py`** (one PR, end-to-end checked). A single generic function runs any factory rule from a JSON description, so survivors can be tracked live without hand-coding each. It is checked with a replay of the live hours before it merges.
3. **First batch** into the candidate tier, posting only to #candidate-tracking.

At most 10 factory candidates are tracked at once, so the staff channel stays readable.

## For Bradley to decide

1. Approve this design, or change it.
2. Are the proposed markets right? Add or remove any.
3. Is the cap of 10 factory candidates at once right?
4. Should factory candidates post to #candidate-tracking, or be journalled only?
