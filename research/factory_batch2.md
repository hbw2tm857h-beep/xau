# Strategy factory, batch 2 (27 Nov 2026)

`research/factory_batch2.py`, `factory_batch2.json`, `factory_batch2_costs.json`. Rules committed (6204f13) before the run. **Research only:** nothing in the bot changed. hypotheses_tested rises by 18 (part B's cut list), from 1,441 to 1,459 (recorded in research/README.md only).

## Part A: batch 1's near misses at 1.5 times costs

| Rule | Cost (bp) | 2008-19 | 2020-26 | 2020-22 / 2023-26 | Verdict |
|---|---|---|---|---|---|
| EURUSD: first-hour range break, short, no filter, 3-candle exit | 1.50 | +0.164R (1293) | +0.061R (810) | +0.079 (345) / +0.048 (465) | holds |
| EURJPY: first-hour range break, short, F2, 3-candle exit | 2.25 | +0.197R (614) | +0.137R (313) | +0.178 (150) / +0.099 (163) | holds |
| GBPUSD: first-hour range break, long, no filter, 10-candle exit | 1.80 | +0.197R (1210) | +0.123R (817) | +0.091 (355) / +0.147 (462) | holds |
| WTI: first-hour range break, both, F2, 2-ATR trail | 7.50 | +0.322R (730) | +0.110R (757) | +0.067 (350) / +0.148 (407) | holds |
| Gold: first-hour range break, short, no filter, 2-ATR trail | 2.62 | +0.175R (1386) | +0.086R (779) | +0.037 (361) / +0.129 (418) | holds |

**All five hold.** At one and a half times the costs, each still averages at least +0.05R in 2020-26 and is positive in both halves. Per the rules they are proposed as silent candidates, judged by the live gate alone. 2020-26 has been seen for them, so no new p-value is claimed.

## Part B: the cut with at most 3 rules per entry family, London first-hour family left out

8,587 rules passed the build test, as in batch 1. 18 went to the cut (the families ran out of rules that beat random entries and did not duplicate listed ones); bar p < 0.05 / 18 = 0.0028.

| Rule | Build 2008-19 (trades, avg) | Cut (trades, avg) | p | 2020-22 / 2023-26 | Verdict |
|---|---|---|---|---|---|
| Nasdaq 100: H1 55-candle breakout, long, F3, 2-ATR trail | 502, +0.399R | 568, +0.262R | 0.0021 | +0.171 (239) / +0.329 (329) | pass |
| Nikkei 225: H4 inside-candle break, long, F3, 3-candle exit | 536, +0.318R | 587, +0.025R | 0.36 | +0.047 (215) / +0.012 (372) | fail |
| Brent: D1 55-candle breakout, both, no filter, 1R target | 103, +0.337R | 84, +0.125R | 0.12 | +0.201 (46) / +0.033 (38) | fail |
| Bitcoin: H1 pullback to the 20 EMA, both, F1+F5, 2-ATR trail | 236, +0.783R | 809, +0.187R | 0.013 | +0.371 (373) / +0.029 (436) | fail |
| Nasdaq 100: H1 4 closes in a row, fade, long, F6, 3R target | 503, +0.292R | 638, +0.019R | 0.39 | +0.041 (278) / +0.001 (360) | fail |
| Nikkei 225: H1 20-candle breakout, long, F6, 2R target | 487, +0.234R | 654, -0.010R | 0.57 | +0.035 (287) / -0.046 (367) | fail |
| Brent: D1 inside-candle break, long, no filter, next daily close | 116, +0.298R | 109, -0.009R | 0.55 | +0.133 (47) / -0.117 (62) | fail |
| WTI: D1 inside-candle break, both, no filter, next daily close | 216, +0.226R | 195, +0.043R | 0.21 | +0.078 (80) / +0.019 (115) | fail |
| FTSE 100: D1 3 closes in a row, follow, both, F2, 1R target | 188, +0.216R | 185, -0.022R | 0.62 | -0.056 (81) / +0.005 (104) | fail |
| Nasdaq 100: H1 3 closes in a row, follow, long, F6, 10-candle exit | 841, +0.192R | 1192, +0.013R | 0.4 | -0.046 (548) / +0.064 (644) | fail |
| Nikkei 225: H1 squeeze breakout, long, F3, next daily close | 490, +0.279R | 671, +0.155R | 0.028 | +0.161 (233) / +0.153 (438) | fail |
| Nikkei 225: H1 squeeze breakout, both, F4+F6, next daily close | 355, +0.344R | 700, -0.032R | 0.67 | -0.109 (286) / +0.021 (414) | fail |
| S&P 500: H1 pullback to the 20 EMA, long, F4, 10-candle exit | 805, +0.200R | 1059, +0.055R | 0.18 | +0.039 (487) / +0.069 (572) | fail |
| EURUSD: D1 IBS extreme, short, F1+F4, next daily close | 108, +0.153R | 66, +0.044R | 0.27 | +0.035 (41) / +0.060 (25) | fail |
| S&P 500: H1 pullback to the 20 EMA, long, F4+F6, 2-ATR trail | 347, +0.341R | 462, +0.072R | 0.22 | +0.116 (234) / +0.026 (228) | fail |
| Dow: H1 squeeze breakout, both, F2, 10-candle exit | 476, +0.304R | 847, +0.025R | 0.38 | +0.195 (336) / -0.087 (511) | fail |
| S&P 500: D1 IBS extreme, long, F4, 10-candle exit | 111, +0.427R | 108, +0.185R | 0.13 | -0.072 (56) / +0.461 (52) | fail |
| Nasdaq 100: D1 IBS extreme, long, F6, next daily close | 217, +0.143R | 280, +0.038R | 0.2 | -0.036 (135) / +0.106 (145) | fail |

**1 of 18 passed:** Nasdaq 100, a close above the highest high of the last 55 hourly candles, buys only, when the 12-month return is up, with a 2-ATR trailing stop. +0.262R a trade on 568 trades in 2020-26, positive in both halves, correlation 0.03 with every live and shadow strategy.

**A check run after the result, not part of the bar:** Nasdaq rose strongly in 2020-26, and a long-only rule gains from that alone. Random buy entries on Nasdaq in 2020-26 with the same risks and the same trailing exit averaged +0.107R (300 shuffles), and the rule beat them 94% of the time. Random buys taken only when the 12-month return was up averaged +0.097R, and the rule beat them 98.7% of the time (p 0.013). So the rule does better than drift, but about 40% of its average is the market's rise, and the evidence beyond drift is p 0.013, not 0.0021. It qualifies as a silent candidate under the approved design; the live record decides.

## Next

Six candidates (the Nasdaq breakout and the five London first-hour rules) for silent tracking, under the cap of 10. They need the generic rule runner in `signals.py` (step 2 of the design) and a live data feed for each market.
