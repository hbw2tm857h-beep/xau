# The Edge Lab

A research lab for working out why discretionary XAUUSD trades succeed or fail. It is **not** a trading bot. It never connects to a broker, never places orders and never reads live prices.

```
python -m edgelab audit                    # prove there is no look-ahead (features + setup signals)
python -m edgelab run --budget 150         # full research run + 150 experiments + dashboard
python -m edgelab experiment --budget 300  # continue the experiment queue (append-only ledger)
python -m edgelab run --trades my.csv      # add your own trade history to the edge profile
python -m edgelab template                 # CSV template for your trades
python -m pytest tests                     # simulator / statistics / leakage tests
```

Open `lab_output/dashboard.html` in a browser. It is one self-contained file with Plotly loaded from a CDN.
Needs: Python 3.11+, numpy, pandas, scipy, scikit-learn (`pip install -r edgelab/requirements.txt`).
The first run takes about 2 minutes. It builds caches in `edgelab/store/cache/`, which git ignores.

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
setups.py         16 discretionary archetypes x long/short, each tied to the TA claim it embodies
simulator.py      replays every trade on M15 bars (H1 fallback for 2003-07); spread + slippage, worse costs
                  around news and rollover, gap fills, stop-first when stop and target share a bar
trades.py         decisions -> trades with a full context snapshot and trade-relative features
taxonomy.py       56 mistake categories (38 ex-ante, 16 ex-post, 2 execution), each with a measurable rule;
                  ex-ante categories are tested statistically, so folklore is labelled as folklore
counterfactual.py 17 alternatives per trade (timing, confirmation, retest, stops, targets, breakeven,
                  opposite, skip). Hindsight view (per trade) is kept apart from the policy view (per setup)
comparison.py     winner vs look-alike loser: nearest-neighbour matching on what the chart showed,
                  then paired tests on hidden context, with a replication check on later data
behaviour.py      market-level studies: momentum persistence, up/down asymmetry, exhaustion,
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
* **No look-ahead:** `python -m edgelab audit` rebuilds the frame on data cut at random bars and checks that every
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
`edgelab/store/my_trades.csv` (`python -m edgelab template`) and the profile switches to your data. It then adds a
random-timing benchmark per trade (same day, same side, same stop distance), so timing skill can be told apart from drift.

## Limitations

* Setups are mechanical stand-ins for discretionary reads. The taxonomy explains these trades, not your judgement, until you add your log.
* Swing levels are dense (fractal pivots), so the "near an opposing level" categories flag most trades.
  Weighting levels by significance is an open experiment.
* Volume is Dukascopy tick count, not traded volume.
* Spreads are modelled, not historical.
