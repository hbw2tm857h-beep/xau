"""Round 41: round 40's three volume tests on the years where Yahoo's gold
volume is real (pre-registered 27 Nov 2026, before any trade from September
2020 on was joined to volume).

Round 40 is void. Yahoo's GC=F volume is not exchange volume before 2020: it
runs at a median of about 100 contracts a day in 2008-19 against roughly
200,000 from June 2020, so it is the volume of one thin contract, not the
front month. The jump also tripped round 40's cleaning rule, which marked
every later day invalid, so no trade from 2020 on was joined to volume there.
Round 40's numbers come from the junk years only and are not used.

This round keeps round 40's rules, measures (Q1 RVOL >= 1.0 on trend trades,
Q2 RVOL < 1.0 on inside-day trades, Q3 5-day over prior-60-day volume < 0.8 on
trend trades), cleaning and 20-trade minimum, with two changes fixed now:
  - volume is read from 1 June 2020 (the first day after the series turns
    real, 27 May 2020, that starts a calendar month), so the cleaning rule
    starts from real volume;
  - only trades signalled from 1 September 2020 are used, after 65 valid days
    exist for every measure.
Periods: Sep 2020-24 and 2025-26. Pass: expected sign, two-sided Welch
p < 0.05 / 3 on all trades from Sep 2020, and the same sign in each period
where the group has at least 20 trades. hypotheses_tested rises from 1,418 to
1,421 (round 40's three are counted although void).

About 220 trend trades fall in this window, so only a large effect can pass.
A pass goes to Bradley as a proposal; nothing changes the live alerts. Research
only: signals.py's counter is not touched.
"""
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import round40_real_volume as R40  # noqa: E402

UTC = timezone.utc
START_VOL = datetime(2020, 6, 1, tzinfo=UTC)
START = datetime(2020, 9, 1, tzinfo=UTC)
PERIODS = [("2020-24", START, datetime(2025, 1, 1, tzinfo=UTC)),
           ("2025-26", datetime(2025, 1, 1, tzinfo=UTC), datetime(2030, 1, 1, tzinfo=UTC))]

if __name__ == "__main__":
    R40.main(vol_start=START_VOL, trade_start=START, periods=PERIODS, main_periods=PERIODS,
             out="round41_results.json")
