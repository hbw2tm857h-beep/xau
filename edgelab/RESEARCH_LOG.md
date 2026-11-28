# Edge Lab research log

Newest first. Written automatically by `python -m edgelab cycle`.



## Cycle 2026-11-28 00:48 UTC

- +150 hypotheses tested (total 1,950; trials counted 10,281).
- **validated**: SHORT range_breakout when adx < 18.513 AND rel_h4_dist_ema20 in [-0.236, 0.764) [exit: confirm_close] (new)
- **validated**: LONG momentum_bar when rel_mom12 >= 2.676 AND rel_usd_chg20 in [-0.006, 0.008) [exit: stop_1.5x] (new)
- **validated**: SHORT range_breakout when adx < 18.513 AND rel_h4_dist_ema20 in [-0.236, 0.764) (new)
- **weak_holdout**: SHORT range_breakout when adx < 18.513 AND rel_h4_dist_ema20 in [-0.236, 0.764) [exit: target_3r] (new)
- **validated**: LONG momentum_bar when rel_mom12 >= 2.676 AND rel_usd_chg20 in [-0.006, 0.008) [exit: confirm_close] (new)
- **weak_holdout**: SHORT range_breakout when adx < 18.513 AND rel_h4_dist_ema20 in [-0.236, 0.764) [exit: trail_2atr] (new)
- **contradicted_holdout**: SHORT any setup when adx < 18.513 AND rel_h4_dist_ema20 in [-0.236, 0.764) [exit: trail_3atr_after_1r] (new)
- **contradicted_holdout**: SHORT bb_squeeze_breakout when range20_atr in [3.248, 3.837) AND rel_mom24 in [0.889, 2.404) (new)
- **contradicted_holdout**: LONG session_breakout when room_in_r_htf in [0.547, 1.524) AND rel_rsi in [58.713, 66.58) (new)
- **contradicted_holdout**: LONG session_breakout when room_in_r_htf in [0.547, 1.524) AND rel_dist_ema50 in [0.94, 2.652) (new)
- Reality Check (studentised) p = 0.276; best: SHORT range_breakout when er10 >= 0.52 AND rel_mtf_votes >= 1.0 [exit: trail_3atr_after_1r]; Romano-Wolf survivors: 0.
- Forward: LONG momentum_bar when rel_mom12 >= 2.676 AND rel_usd_chg20 in [-0.006, 0.008) [exit: stop_1.5x] -> n=0, avg R nan, accumulating (0/30 trades)
- Forward: LONG momentum_bar when rel_mom12 >= 2.676 AND rel_usd_chg20 in [-0.006, 0.008) [exit: confirm_close] -> n=0, avg R nan, accumulating (0/30 trades)
- Forward: SHORT range_breakout when adx < 18.513 AND rel_h4_dist_ema20 in [-0.236, 0.764) -> n=0, avg R nan, accumulating (0/30 trades)
- Forward: SHORT range_breakout when adx < 18.513 AND rel_h4_dist_ema20 in [-0.236, 0.764) [exit: target_3r] -> n=0, avg R nan, accumulating (0/30 trades)
- Forward: SHORT range_breakout when adx < 18.513 AND rel_h4_dist_ema20 in [-0.236, 0.764) [exit: confirm_close] -> n=0, avg R nan, accumulating (0/30 trades)
- Forward: SHORT range_breakout when adx < 18.513 AND rel_h4_dist_ema20 in [-0.236, 0.764) [exit: trail_2atr] -> n=0, avg R nan, accumulating (0/30 trades)

Next in the queue:
- LONG session_breakout when room_fwd_htf < 0.929 AND room_in_r in [0.143, 0.432) [exit: stop_1.5x]
- SHORT session_breakout when room_fwd_htf < 0.929 AND room_in_r in [0.143, 0.432) [exit: time_exit_12h]
- SHORT session_breakout when room_fwd_htf < 0.929 AND room_in_r in [0.143, 0.432) [exit: retest_limit]
- SHORT session_breakout when room_fwd_htf < 0.929 AND room_in_r in [0.143, 0.432) [exit: confirm_close]
- SHORT session_breakout when room_fwd_htf < 0.929 AND room_in_r in [0.143, 0.432) [exit: trail_2atr]

## Cycle 2026-11-28 00:20 UTC

- First recorded cycle.

Next in the queue:
- LONG any setup when rel_mom12 >= 2.676 AND rel_usd_chg20 in [-0.006, 0.008)
- SHORT momentum_bar when rel_mom12 >= 2.676 AND rel_usd_chg20 in [-0.006, 0.008)
- LONG momentum_bar when rel_mom12 >= 2.676 AND rel_usd_chg20 in [-0.006, 0.008) [exit: target_1r]
- LONG momentum_bar when rel_mom12 >= 2.676 AND rel_usd_chg20 in [-0.006, 0.008) [exit: target_3r]
- LONG momentum_bar when rel_mom12 >= 2.676 AND rel_usd_chg20 in [-0.006, 0.008) [exit: breakeven_1r]
