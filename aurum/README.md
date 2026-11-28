# Aurum

A research lab for working out why discretionary XAUUSD trades succeed or fail. It is **not** a trading bot. It never connects to a broker, never places orders and never reads live prices.

```
python -m aurum audit                    # prove there is no look-ahead (features + setup signals)
python -m aurum run --budget 150         # full research run + 150 experiments + dashboard
python -m aurum experiment --budget 300  # continue the experiment queue (append-only ledger)
python -m aurum run --trades my.csv      # add your own trade history to the edge profile
python -m aurum template                 # CSV template for your trades
python -m pytest tests                     # simulator / statistics / leakage tests
```

Open `lab_output/dashboard.html` in a browser. It is one self-contained file with Plotly loaded from a CDN.
Needs: Python 3.11+, numpy, pandas, scipy, scikit-learn (`pip install -r aurum/requirements.txt`).
The first run takes about 2 minutes. It builds caches in `aurum/store/cache/`, which git ignores.

---

## Architecture

```
data.py           load + clean H1 (2003-2026) and M15 (2008-2026); build H4/D1 on the 17:00 New York close;
                  FOMC/CPI/NFP event windows; daily macro series shifted one day so they stay causal
features.py       causal indicators: ATR, EMA, RSI, ADX, Bollinger, efficiency ratio, candle anatomy,
                  momentum, rolling-percentile volatility, divergences, sessions, Asia range, round numbers
structure.py      swing pivots that only become known R bars after the pivot; HH/HL/LH/LL structure;
                  S/R levels and touch counts; equal highs/lows (liquidity pools); sweep state
regimes.py        causal daily regimes (trend / volatility / trending-vs-ranging) using expanding percentiles
frame.py          the decision frame: row i = everything knowable at the close of H1 bar i (+H4/D1 context)
setups.py         18 discretionary archetypes x long/short (incl. momentum_burst, burst_pullback), each tied to the TA claim it embodies
simulator.py      replays every trade on M15 bars (H1 fallback for 2003-07); spread + slippage, worse costs
                  around news and rollover, gap fills, stop-first when stop and target share a bar
trades.py         decisions -> trades with a full context snapshot and trade-relative features
taxonomy.py       58 mistake categories (40 ex-ante, 16 ex-post, 2 execution), each with a measurable rule;
                  ex-ante categories are tested statistically, so folklore is labelled as folklore
counterfactual.py 20 alternatives per trade (timing, confirmation, retest, stops, targets, breakeven,
                  chandelier trailing stops, partial exits, opposite, skip). Hindsight view (per trade) is kept apart from the policy view (per setup)
comparison.py     winner vs look-alike loser: nearest-neighbour matching on what the chart showed,
                  then paired tests on hidden context, with a replication check on later data
robustness.py     White's Reality Check + studentised (SPA-style) test + Romano-Wolf step-down over the whole
                  hypothesis family; per-discovery stress: threshold neighbourhood, cost multiples, year
                  consistency, Monte-Carlo drawdown, same-month drift benchmark, regime split
forward.py        freezes surviving hypotheses at the last bar and scores them only on later data
behaviour.py      event studies (average path -24h..+48h around every setup, vs drift) and market-level studies: momentum persistence, up/down asymmetry, exhaustion,
                  long-vs-short decomposition (regime mix vs within-regime), conventional-claim scoreboard
discovery.py      exhaustive condition scan (discovery split only, every cell counted as a trial) and
                  anchored walk-forward gradient-boosting meta-labelling with an embargo
hypothesis.py     hypothesis spec, evaluation, and the 10-field discovery report
experiments.py    the autonomous engine: generate -> test -> gate -> record -> relate -> propose
ledger.py         append-only experiments.jsonl; trial counting (includes the 1,430 legacy research trials)
stats.py          expectancy, PF, drawdown, block bootstrap, Benjamini-Hochberg, deflated Sharpe ratio
validation.py     truncation (look-ahead) audits, walk-forward rule/threshold tests, cost stress
profile.py        personal edge profiling and falsification tests of the self-assessment
dashboard.py      lab_output/dashboard.html
pipeline.py       orchestration; __main__.py is the CLI
```

To extend it, add a detector to `SETUPS` in `setups.py`, a `Mistake` to `taxonomy.M`, a variant to
`counterfactual.py`, or a feature to `features.py`. Then rerun `audit` before trusting the results. The engine
picks up new setups and features on its own through seeding and the scan.

## Data

| Data | Source in repo | Use |
|---|---|---|
| XAUUSD H1 2003-05 → 2026-11 | `data/xauusd_h1*.csv(.gz)` (Dukascopy) | decision frame |
| XAUUSD M15 2008 → 2026-11 | `data/xauusd_m15_YYYY.csv.gz` | trade replay (intrabar order of stop/target) |
| XAUUSD H1 tick volume | `data/volume/xauusd_h1_vol.csv.gz` | `vol_rel` only, treated as a weak proxy (no centralised spot volume exists) |
| FOMC, CPI dates; NFP computed | `data/macro/*.json` | news windows, cost multipliers, N1 category |
| Real yields, broad USD, VIX, GVZ | `data/macro/*.csv` (FRED) | regime / macro context, lagged one day |

Data that would improve the lab, in order of value: (1) **your own trade log** for Phase 6;
(2) tick or M1 data for 2003-07 and for fill modelling around news; (3) a real spread history
(the cost model is an assumption: max($0.20, 0.8 bp) spread plus 2% of an H1 ATR slippage, x3 in news windows);
(4) COMEX GC futures volume and open interest as a real volume source; (5) a full economic calendar with surprise values.

## Validation protocol

* **Splits by decision time:** archive 2003-07 (H1 only, robustness), discovery 2008-17, validation 2018-21, holdout 2022-26.
  Trades that straddle a split boundary are embargoed.
* **Gates:** discovery n≥40, avg R>0.03 and t≥2. Validation n≥20, avg R>0 and t≥1. Only then is the holdout
  scored, **once per hypothesis**. Cards for hypotheses that fail validation never show holdout numbers.
* **Multiple testing:** every scan cell and every ledger test counts. The 1,430 rows logged by earlier `research/`
  rounds count as well, because those rounds already looked at 2008-2026. Deflated Sharpe and BH q-values use that total.
  The holdout is therefore out-of-sample for this lab, but it is not untouched data.
* **No look-ahead:** `python -m aurum audit` rebuilds the frame on data cut at random bars and checks that every
  feature and every setup signal is identical to the full-history value. Current result: 0 mismatches.
* **Costs:** all R figures are net. Gross figures are shown next to them so a cost problem is not mistaken for a bad idea.

## What the first run found (2026-11-27, 72,981 reconstructed trades, 6,692 trials counted)

These are evidence, not advice, and they will move as the engine runs more experiments.

1. **None of the 16 textbook setups has an edge out of sample, even before costs.** Every OOS gross t-stat is below 2.
   After realistic costs every one is at or below about 0 R on the holdout. Most chart setups are coin flips that pay the spread.
2. **The scan found fewer significant cells than chance would.** 35 cells had p<0.05 against 241 expected under the null,
   and none survived FDR. Conditioning simple setups on single features does not uncover a hidden edge.
3. **"Late entry" is not a mistake in gold.** Entries after more than 3 ATR of move in the trade's direction did
   **+0.17 R better** in discovery and **+0.19 R better** in later data. Momentum continues: price after a 4 ATR move over 6h carries on
   by 0.11-0.33 ATR beyond drift over the next 12h. "Trend-following in chop" also did *better* than its reputation, in both periods.
4. **Three mistakes are real and replicate:** stops under 0.75 ATR (mostly because costs eat small stops), fading RSI/BB
   extremes against an aligned H1/H4/D1 trend, and reversals taken before the liquidity pool behind them is swept.
   About 30 other "mistakes" have no measurable effect.
5. **Look-alike winners and losers differ by only a few hundredths of a standard deviation** on every hidden feature.
   At H1 resolution, identical-looking setups mostly diverge on noise. Trend strength (lower ADX, flatter EMA) and less
   24h extension are the only differences that replicated, and they are tiny.
6. **Hindsight is a trap.** "Take the opposite trade" would have rescued 49% of losers, yet as a rule it adds about 0 R.
   As policies, only *waiting for the next bar to confirm* (+0.04 R) and *entering 3 bars later* (+0.03 R) improved setups
   in both periods. That is consistent with finding 3: signals arrive late, and confirmation filters noise.
7. **A walk-forward model sees something, but not enough.** AUC is 0.52-0.54. Its top quintile lifts holdout expectancy from
   −0.06 R to −0.01 R. The signal is real but does not cover costs.
8. **The best surviving hypothesis is weak.** *Long momentum bar during the Asia session* passed discovery (+0.30 R, n=124) and
   validation (+0.22 R, n=57), then fell to +0.05 R on the holdout (n=96, t<1). It also lost money in 2003-07.
   Treat it as unproven.
9. **Gold's down-moves behave differently from up-moves.** Moderate selloffs (1-2 ATR over 6h) tend to stall. Only
   very large selloffs (>4 ATR) continue strongly. This matters for the short-side questions below.

### Personal profile status

There is no personal trade file yet, so the six self-assessment tests run on the mechanical trades as a **market baseline**.
Across all 16 setups, shorts trail longs by 0.04 R. Almost none of that gap (0.001 R) comes from regime mix; it shows up
inside the same regimes, and is consistent with gold's long-run up-drift and the down-move behaviour in finding 9.
A personal short-side edge has to beat this baseline to count as skill. Export your trades to
`aurum/store/my_trades.csv` (`python -m aurum template`) and the profile switches to your data. It then adds a
random-timing benchmark per trade (same day, same side, same stop distance), so timing skill can be told apart from drift.

## Round 2 (same day): exits, momentum, family-wise controls

Added: trailing-stop and partial-exit variants; two momentum setups built to exploit finding 3; H4/daily
"significant" levels (median 1.15 ATR away instead of 0.38); event studies; a two-feature interaction scan;
White's Reality Check over the whole family; stress tests including a same-month drift benchmark;
a forward-test registry; H1 extended to 2026-11-23 from M15. 2,091 hypotheses are now in the Reality Check, and 9,831 trials are counted.

1. **The whole family fails the data-snooping test.** The best of 2,091 hypotheses has t = 3.7. The 95% luck threshold for
   that many tries is 4.2, so the studentised Reality Check p = 0.23, and **no hypothesis survives Romano-Wolf at 5%**.
   Anything "found" by mining these setups should be treated as unproven.
2. **The momentum effect is real but too small to trade on its own.** The momentum setups have small positive gross edge
   (`momentum_burst` OOS gross t = 1.5), but net expectancy is about 0 and every trailing or threshold variant failed discovery.
   Fast moves continue by 0.1-0.3 ATR beyond drift, while the stop is 1-2 ATR plus costs.
3. **Higher-timeframe levels do not stop momentum.** Pushing a continuation trade into a nearby H4/daily level (S4, S5)
   did *better*, in discovery and later data. So did "stop wider than 2.5 ATR" (V4). Replicated real mistakes now number five:
   tight stops (V3), fading an aligned trend (K5), catching a knife against a strong 20-day trend (T4),
   trading against H4 swing structure (T8), and reversing before the liquidity behind you is swept (L3).
4. **Event studies, net of drift.** After 48h, long momentum bars, session breakouts and range-breakout shorts are the setups
   furthest ahead of drift (+0.2 to +0.3 ATR). Exhaustion fades, double tops/bottoms and sweep reversals are furthest behind
   (−0.1 to −0.4 ATR). In gold, reversal patterns are the worst category on every measure.
5. **One provisional finding: the walk-forward model's long picks, held with a 3 ATR trail switched on at +1R.**
   Results: +0.13R in discovery (n = 1,921), +0.10R in validation (n = 1,773), +0.22R in holdout (n = 1,548).
   Within the same month it beats all long trades with the same exit by +0.16R / +0.06R / +0.17R, so the selection is not
   just drift. But:
   * the exit was chosen after seeing a per-exit table that included holdout. **Its holdout is contaminated**, as recorded in
     the ledger and shown on the card. The dashboard now hides holdout from that table;
   * the profit comes from bull regimes (+0.31R; bear +0.03R, neutral +0.06R), and only 8 of 15 years were positive;
   * it does not survive the family-wise Reality Check.
   It is frozen in `store/frozen.json` and will be scored only on data after 2026-11-23. That forward score is the honest test.

## Round 3: the mistake × remedy atlas (`atlas.py`, `remedies.py`)

Every ex-ante mistake (40), every pair, and every triple with ≥40 discovery trades, crossed with **162 remedies**:
5 entry fixes (as taken, wait 1 bar, wait 3 bars, wait for a confirming close, limit back at the signal-bar midpoint) ×
4 stop fixes (planned, 1.5×, 2×, 2 ATR) × 8 exit fixes (1R/2R/3R targets, breakeven at +1R, 12h time exit, 2 ATR trail,
3 ATR trail after +1R, half at 1R plus half trailed), plus skip and take-the-opposite. These are evaluated for all trades,
longs, shorts and every setup × side. That is **2,035,040 cells** and about 11 million re-simulated trades, all counted as trials.

| Question | Discovery | Validation (nothing re-fitted) |
|---|---|---|
| Does a remedy **improve** the trades carrying a mistake? | 82,145 BH survivors | 25,192 replicate (≈4,220 expected by luck); 71% sign agreement |
| Does mistake + remedy become **profitable**? | 130,686 cells at p<0.05 (101,120 expected by luck) | 3,970 replicate (≈2,083 expected); **43% sign agreement, worse than a coin flip** |

What it means:
1. **Remedies are real, but they are defences.** For almost every mistake, the best remedy turns a −0.05 to −0.18R trade
   into roughly breakeven in validation. It does not turn it into a winner.
2. **Remedy ingredients, ranked by how often they help across all single-mistake cells:** waiting for a confirming close
   (helps in 87% of cells, +0.07R), the 3 ATR trail switched on at +1R (79%, +0.05R) and the 2 ATR trail (77%).
   **Waiting three bars hurts** (−0.06R): the signal's information decays fast. Wider stops are mixed.
3. **Profit does not generalise.** Mistake combinations that looked profitable after a remedy in 2008-17 were more likely to
   flip sign in 2018-21 than to repeat.
4. **Holdout check.** The engine re-tested the 40 best replicated cells under its normal gates. 26 failed its discovery bar,
   which is stricter than the atlas's. Of the 12 that reached the holdout, 6 were positive. A typical one is "chasing
   (E1) + trend-following in chop (T3), remedied by confirming close + 2 ATR stop + 1R target": +0.07R, t≈1.7, n≈50.
   Most were flat or negative in 2003-07. They are frozen for forward testing but are weak evidence.
5. **The hindsight fix is almost always "take the opposite trade"** for after-the-fact diagnoses (false breakout, stop hunt,
   wrong direction). It is useless as a rule, because the opposite trade loses just as reliably on average.
6. With about 2 million trials now counted, the Reality Check over the engine's 2,931 hypotheses gives p = 0.32, and
   nothing survives Romano-Wolf.

## Round 4: anatomy of the live bot's losing trades (`bot_anatomy.py`)

`signals.py` is replayed with its own code (trend, 4-hour trend and inside-day strategies: 1,968 trades since 2008,
the same counts the bot publishes). The lab then dissects every trade.

**Findings (2008-2021 only; the holdout was opened once, for the three pre-declared rules):**
1. **Before entry, the bot's losers look like its winners.** None of the lab's 40 context features separates them in
   both periods. The bot's own rules already remove the visible mistakes. The one warning sign that is negative in both
   periods for all three strategies is **timeframes disagreeing** (H1, 4-hour and daily trends not aligned, lab mistake T2):
   trend +0.07R vs +0.19R when aligned, 4-hour trend −0.09R vs +0.16R, inside-day +0.07R vs +0.12R.
2. **The essence of a loss is that it never gets going.** 68% of losers never reach +0.5R, against 4% of winners.
   Progress after 3 hours is strongly informative: a trend trade below +0.25R wins 46% of the time, while one above +1R wins 97%.
3. **But "cut it if it isn't working" is the wrong remedy.** Early exits lowered expectancy in all 18 versions tested
   (t ≈ −2.5 to −3.8 in 2008-17). Slow starters still win often, and exiting locks in about −0.3R.
4. **How losses happen:** 52% move a little and then reverse, 42% never work at all, and only 2% are stop hunts.
5. **Remedies scored once on the 2022-26 holdout:**
   - trail the whole trend trade at 3 ATR after +1R: +0.06 / +0.09 / +0.02R;
   - the same for inside-day: +0.02 / +0.05 / +0.10R (t 2.0);
   - skip conflicted 4-hour setups: +0.01 / +0.12 / −0.04R, with less drawdown.

   All are positive or neutral, and none is strong enough to change live trading without forward evidence.

**What the bot now does (signals.py)**
* `anatomy_notes: True`: every gold setup alert ends with one line saying whether the H1, 4-hour and daily trends agree,
  and what that has meant for that strategy since 2008. The flags are saved with each trade in `journal.json`, so their
  live value is measured. The stdlib implementation matches the lab's definition on 99.9% of 1,925 historical signals.
* `anatomy_progress: False` (opt-in): a "3 hours in" note giving the best excursion so far and the historical win rate at
  that stage, with an explicit "don't cut it early".
* `anatomy_skip_h4_conflict: False` (research candidate): skip 4-hour setups when timeframes disagree. Turn it on only if
  the forward results in the dashboard's "Your bot" tab support it.
* The trading rules are unchanged. These changes only take effect on `main`, because the hourly workflow runs from there.

Each research cycle re-scores all of this on new trades (forward section of the "Your bot" tab).

## Ongoing research (how the lab keeps running)

```
python -m aurum update                    # pull new candles from Dukascopy (complete UTC days -> M15 files)
python -m aurum cycle --budget 300        # one full cycle: update -> experiments -> forward test -> log
```

Each **cycle** does the following:
1. Downloads new XAUUSD candles directly from the Dukascopy feed and rebuilds the caches if the data grew.
2. Tests the **pre-registered agenda** first (`aurum/agenda.json`), then the engine's own queue: mutations, contradiction
   probes, scan cells, and coverage-seeking exploration, so the queue never runs dry.
3. Re-runs the Reality Check over the whole family. Every new hypothesis raises the bar for all the others.
4. Freezes any newly surviving hypothesis and scores all frozen ones on the **forward split**: data after 2026-11-23 that no
   test has ever used. After 30 forward trades each gets a verdict: `forward_confirmed`, `forward_failed` or `forward_inconclusive`.
5. Writes what changed to `aurum/RESEARCH_LOG.md` (newest first) and `store/cycles.jsonl`, and rebuilds the dashboard.

The holdout is now fixed at 2022-01-01 to 2026-11-23, so results stay reproducible. New data only ever lands in `forward`.

**The holdout is sealed.** Every descriptive view — taxonomy verdicts, look-alike replication, event studies, momentum and
asymmetry studies, setup tables, the ML charts — uses discovery + validation only. Holdout numbers appear only on the card of a
hypothesis that passed validation, after it has been scored. Researchers (you, me, the weekly session) design hypotheses from
what the dashboard shows, so this keeps the holdout from leaking into ideas. Two earlier leaks are recorded in the ledger
and shown on the affected cards: the ML exit choice, and the cycle-0 agenda that was built from pooled verdicts.

**Schedulers**
* **Weekly Claude research session** (Sundays 04:23 UTC). It runs a cycle, reads the results as a researcher,
  pre-registers 3-6 new hypotheses in `agenda.json` for the next cycle, writes "Researcher notes" into the log, and pushes to
  this branch. It may design hypotheses only from discovery/validation evidence, never from holdout or forward numbers.
  Manage or stop it under scheduled tasks in Claude Code on the web.
* **GitHub Actions** `.github/workflows/aurum.yml` (Sundays 03:17 UTC, or by hand). This is the mechanical cycle with no
  reasoning step. GitHub only runs scheduled workflows from the default branch, so it activates once merged to `main`.
  The Claude session skips its own cycle when one ran in the last 12 hours.

**Adding your own ideas:** append a spec to `aurum/agenda.json`, for example
`{"setup": "breakout", "direction": -1, "conditions": [{"f": "session", "op": "==", "v": "london"}], "exit": "trail_2atr", "rationale": "...", "author": "me"}`.
It is tested first in the next cycle and pays the same multiple-testing price as everything else.

## Limitations

* Setups are mechanical stand-ins for discretionary reads. The taxonomy explains these trades, not your judgement, until you add your log.
* Swing levels are dense (fractal pivots), so the "near an opposing level" categories flag most trades.
  Weighting levels by significance is an open experiment.
* Volume is Dukascopy tick count, not traded volume.
* Spreads are modelled, not historical.
