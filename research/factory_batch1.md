# Strategy factory, batch 1 (27 Nov 2026)

`research/factory.py`, `research/factory_batch1.json`. Rules fixed and committed (fa45d97) before the first run; design in `research/FACTORY.md`. **Research only:** nothing in the bot changed. hypotheses_tested rises by 20 (the rules sent to the cut), from 1,421 to 1,441 (recorded in research/README.md only).

## Funnel

| Stage | Rules |
|---|---|
| Generated (19 markets x 14,112) | 268,128 |
| At least 30 trades in 2008-19 | 198,546 |
| Passed the build test | 8,587 |
| Screened in rank order: skipped for correlating above 0.5 with a listed rule | 69 |
| Sent to the cut (all beat 500 random-entry shuffles, p = 0.002) | 20 |
| **Passed the cut** (p < 0.05 / 20 = 0.0025 and the other bars) | **0** |

Run time 5.2 minutes on this Mac.

## The cut, 2020 to Nov 2026

| Rule | Build 2008-19 (trades, avg) | Cut (trades, avg) | p | 2020-22 / 2023-26 | Verdict |
|---|---|---|---|---|---|
| GBPUSD: first-hour range break, both, no filter, 3-candle exit | 2476, +0.169R | 1642, +0.034R | 0.099 | +0.059 (719) / +0.014 (923) | fail |
| EURUSD: first-hour range break, short, no filter, 3-candle exit | 1293, +0.192R | 810, +0.095R | 0.0048 | +0.109 (345) / +0.085 (465) | fail |
| GBPUSD: first-hour range break, both, F6, 2R target | 1533, +0.196R | 1062, -0.003R | 0.53 | +0.071 (468) / -0.061 (594) | fail |
| WTI: first-hour range break, both, F2, 2-ATR trail | 730, +0.384R | 757, +0.149R | 0.0094 | +0.102 (350) / +0.189 (407) | fail |
| EURJPY: first-hour range break, short, F2, 3-candle exit | 614, +0.232R | 313, +0.178R | 0.0052 | +0.219 (150) / +0.141 (163) | fail |
| GBPUSD: first-hour range break, short, F5+F6, 3-candle exit | 519, +0.271R | 367, -0.033R | 0.74 | +0.019 (131) / -0.062 (236) | fail |
| GBPUSD: first-hour range break, both, F5+F6, 2-ATR trail | 1000, +0.209R | 676, +0.029R | 0.28 | -0.002 (228) / +0.045 (448) | fail |
| GBPUSD: first-hour range break, both, F2+F6, 3-candle exit | 566, +0.241R | 382, +0.018R | 0.38 | +0.097 (173) / -0.047 (209) | fail |
| EURUSD: first-hour range break, short, F1+F6, 3-candle exit | 299, +0.313R | 200, +0.089R | 0.1 | +0.140 (99) / +0.040 (101) | fail |
| WTI: first-hour range break, short, F2, 3R target | 356, +0.481R | 346, -0.044R | 0.68 | -0.051 (158) / -0.038 (188) | fail |
| GBPUSD: first-hour range break, long, F4, 3-candle exit | 488, +0.246R | 349, +0.100R | 0.034 | +0.153 (199) / +0.029 (150) | fail |
| GBPUSD: first-hour range break, long, no filter, 10-candle exit | 1210, +0.230R | 817, +0.158R | 0.0063 | +0.120 (355) / +0.188 (462) | fail |
| GBPJPY: first-hour range break, both, no filter, 2-ATR trail | 2424, +0.146R | 1573, +0.045R | 0.11 | +0.079 (702) / +0.018 (871) | fail |
| EURUSD: first-hour range break, both, F4, 3-candle exit | 993, +0.162R | 710, -0.008R | 0.59 | -0.006 (422) / -0.010 (288) | fail |
| GBPUSD: first-hour range break, both, F2+F4, 3-candle exit | 474, +0.244R | 329, +0.068R | 0.12 | +0.150 (186) / -0.038 (143) | fail |
| GBPUSD: first-hour range break, both, no filter, 3R target | 1761, +0.189R | 1248, +0.038R | 0.23 | +0.197 (535) / -0.081 (713) | fail |
| EURJPY: first-hour range break, both, no filter, 2-ATR trail | 2492, +0.137R | 1584, +0.026R | 0.22 | +0.051 (705) / +0.007 (879) | fail |
| EURUSD: first-hour range break, short, F1, 2-ATR trail | 649, +0.260R | 401, +0.113R | 0.043 | +0.105 (194) / +0.121 (207) | fail |
| Gold: first-hour range break, short, no filter, 2-ATR trail | 1386, +0.215R | 779, +0.120R | 0.031 | +0.070 (361) / +0.163 (418) | fail |
| GBPUSD: first-hour range break, short, no filter, half 1R, rest 2R | 1207, +0.127R | 801, +0.016R | 0.34 | +0.050 (353) / -0.010 (448) | fail |

Every cut rule's daily returns correlated at 0.08 or less with gold trend, gold inside-day, btc_trend, eth_inside_day and us_ibs.

## What it says

- **Nothing passed.** The strongest results in 2008-19 (t-statistics of 4 to 7) shrank by half or more in 2020-26, and none reached p < 0.0025. This is the usual pattern of a search: the top of the list overstates.
- **One family took the whole list.** All 60 of the strongest build survivors, and all 20 sent to the cut, are the same entry: a break of the London first-hour range, mostly on GBPUSD and EURUSD, plus WTI, EURJPY, GBPJPY and gold. No other entry family came close in 2008-19.
- **That family is still positive, just weaker.** 16 of the 20 made money in 2020-26 after costs, and five came close to the bar: EURUSD short with a 3-candle exit (+0.095R, p 0.0048), EURJPY short with the daily Heikin Ashi filter (+0.178R, p 0.0052), GBPUSD long with a 10-candle exit (+0.158R, p 0.0063), WTI both ways with the daily Heikin Ashi filter and a trail (+0.149R, p 0.0094), and gold short with a trail (+0.120R, p 0.031). A London-open breakout on gold failed in round 5, with different rules.
- **The cut list was not diverse enough to be a fair search.** Twenty versions of one idea are effectively one bet, so the batch tested one family, not twenty ideas.

## Proposed for batch 2 (Bradley's decision)

1. At most 3 rules per entry family on the cut list, so other families get tested.
2. The London first-hour break family as one pre-registered hypothesis, judged on live data only (2020-26 has now been seen for it): track the five near misses above as silent candidates, posting to #candidate-tracking.
3. Costs at the London open: spreads are wider in the first minutes, so the family should be re-run at 1.5 times its costs before any of it is tracked.
