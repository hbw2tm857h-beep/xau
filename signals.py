#!/usr/bin/env python3
"""
XAU Heikin Ashi trend-ride signals -> Slack, with backtest and scorecard.

ALERT-ONLY. Never places trades.

Strategy (from "How to Trade Gold - Ride Massive Trends", The Moving Average):
  1. Daily chart = direction + support/resistance taken from daily closes.
  2. H1 Heikin Ashi = entries. Long: first bullish HA candle after the colour
     change with NO lower wick and a bigger body than the previous candle.
     Short: the mirror (bearish, no upper wick).
  3. Price must have broken a daily level and not be boxed in mid-range.
  4. Stop-order entry just beyond the signal candle.
  5. Exit only when an opposite-colour HA candle closes.
  6. A no-wick daily candle in your direction supports holding overnight.
Additions to make it automatable (editable in CONFIG): initial stop beyond
the recent swing, "daily trend" = daily HA colour + close vs 50 EMA, daily
levels from pivot closes.

Checks (4H agreement is required; the rest are shown as context and can be
switched to hard filters in CONFIG["filters"] if the backtest supports it):
  session  - London / New York hours
  adx      - trend strength on H1
  h4       - 4-hour Heikin Ashi colour agrees
  h4_cloud - last closed 4-hour candle closed beyond the Ichimoku cloud in the
             trade's direction (research round 4: TradingView indicators)
  atr_band - volatility neither dead nor extreme
  news     - live only: no high-impact US event close by

Modes (env MODE):
  run        hourly check (default)
  test       post a status message
  scorecard  weekly results of live signals (posts only if trades closed)
  backtest   replay ~2.5 years of H1 data, write backtest.md, post summary

Environment: TWELVEDATA_API_KEY, SLACK_WEBHOOK_URL, optional ACCOUNT_SIZE,
ACCOUNT_CCY (USD/GBP/EUR, default USD), RISK_PCT (default 1).
Standard library only.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# --------------------------------------------------------------------------
# CONFIG - edit on GitHub to tune; the next run uses the new values
# --------------------------------------------------------------------------
CONFIG = {
    "symbol": "XAU/USD",
    "h1_bars": 5000,              # live: one API call (~10 months of H1)
    "backtest_pages": 3,          # backtest fallback: 3 x 5000 Twelve Data H1 bars
    "history_csv": "data/xauusd_h1.csv",  # backtest uses this 10-year file if present
    # the ledger backfill also reads these, so it can cover 2008-2026
    "history_extra_csv": ["data/xauusd_h1_2008_2015.csv"],

    # Feature ledger: every evaluated hour is written down so a new idea can be
    # tested against what the bot saw, instead of re-derived from raw candles
    "ledger": True,
    "ledger_csv": "data/ledger.csv",
    "outcomes_csv": "data/outcomes.csv",
    "ledger_backfill_csv": "data/ledger_backfill.csv.gz",

    # Daily direction
    "daily_trend_mode": "ha_and_ema",   # "ha", "ha_and_ema" or "off"
    "daily_ema": 50,

    # Daily support/resistance from pivot closes (line-chart style)
    "sr_lookback_days": 180,
    "sr_pivot_strength": 3,
    "sr_merge_atr": 0.5,
    "sr_max_levels": 12,

    # Entry checklist. The video required a daily-level breakout; the 10-year
    # research (research/README.md) found the edge without it, with 4H agreement.
    "require_breakout": False,
    "breakout_bars": 24,
    "require_room": True,
    "min_room_atr": 0.5,          # x daily ATR to the next opposing level
    "first_no_wick_only": True,
    "max_bars_since_flip": 12,
    "min_body_growth": 1.0,
    "wick_tolerance": 0.0,        # $ allowed as "no wick"

    # Levels
    "entry_buffer": 0.30,         # $ beyond the signal candle
    "stop_swing_bars": 5,
    "stop_buffer_atr": 0.2,       # x H1 ATR
    "atr_period": 14,

    # Checks. True = required (filter), False = shown for information only.
    # 4-hour agreement is required: it is what turned the strategy positive.
    "filters": {"session": False, "adx": False, "h4": True, "h4_cloud": True, "atr_band": False,
                "news": False, "stop_width": False},
    "session_start_uk": 7,        # London open
    "session_end_uk": 20,         # end of the busy New York hours
    "adx_period": 14,
    "adx_min": 20,
    "atr_pct_window": 500,        # H1 bars used to rank volatility
    "atr_pct_low": 10,            # below = dead market
    "atr_pct_high": 95,           # above = extreme / news chaos
    "max_stop_atr": 3.0,          # stop wider than this x H1 ATR = too wide
    "news_window_min": 30,

    # Trade management (tested best over 2016-2026: half off at +1R, stop to
    # entry, rest at +2R). exit_mode "ha" = the video's opposite-colour exit.
    "exit_mode": "targets",
    "partial_r": 1.0,
    "partial_frac": 0.5,
    "target_r": 2.0,
    "entry_expiry_bars": 12,      # stop order cancelled if not filled in 12 hours
    "breakeven_at_r": None,       # only used with exit_mode "ha"
    "alert_entry_hit": True,
    "alert_daily_hold": True,     # only used with exit_mode "ha"
    "track_record": "Tested 2008-2026: 715 trades, 60% winners, +0.18R per trade after costs",

    # Second, independent setup (research round 5): inside-day breakout. When a
    # daily candle's range sits inside the previous day's, place a buy-stop at
    # its high and a sell-stop at its low (one cancels the other), stop at the
    # other side, and close at the next daily close. Runs alongside the trend
    # setups with its own alerts and its own line in the scorecard.
    "inside_day": True,
    "inside_day_risk_mult": 0.5,  # size at half the normal risk: the two together had the best return per drawdown
    "inside_day_track_record": "Tested 2008-2026: 726 trades, 49% winners, +0.10R per trade after costs",

    # Position size (only if ACCOUNT_SIZE secret is set)
    "contract_oz": 100,           # oz per 1.00 lot; override with the CONTRACT_OZ
                                  # secret if your broker differs (the EA prints
                                  # the real figure from the symbol spec on start)
    "default_risk_pct": 1.0,

    # Backtest
    "cost_per_trade": 0.35,       # $ spread + slippage per trade
    "oos_fraction": 0.30,         # last 30% of time = out-of-sample
    "verdict_min_gain_r": 0.10,   # a filter must add this much avg R in both periods
    "verdict_min_trades": 30,     # ...with at least this many test trades

    # Third setup, research round 9 E2: the same trigger read on the 4-hour
    # Heikin Ashi candle instead of the hourly one, daily trend still required.
    # 526 trades 2008-2026 at +0.143R, positive in all four periods, but +0.395
    # correlated with the trend setup, so it starts as a nursery candidate:
    # journalled and in the ledger, never alerted. See research/README.md.
    "h4_trigger": True,
    "h4_entry_buffer": 0.30,
    "h4_stop_buffer": 0.30,
    "h4_swing_bars": 5,            # 4-hour candles behind the stop
    "h4_max_bars_since_flip": 6,   # 4-hour candles
    "h4_expiry_bars": 12,          # H1 bars the stop order stays live
    "h4_partial_r": 1.0,
    "h4_partial_frac": 0.5,
    "h4_target_r": 2.0,

    # Nursery (layer 2): which strategies are traded, which are only watched,
    # and what it takes to move between tiers. See nursery.json.
    "nursery_file": "nursery.json",
    "gate_promote_min_trades": 30,   # live closed trades before promotion is considered
    "gate_demote_min_trades": 30,    # ...and before a live strategy can be demoted
    "gate_trailing": 50,             # recent live trades used to judge a live strategy
    "gate_tolerance": 0.5,           # live avg R must stay above this x the tested edge
    "gate_alpha": 0.05,              # one-sided bootstrap on live trades
    "gate_bootstrap": 2000,
    # Recorded test rows in research/results*.csv. Used only to report how
    # strict a backtest search would have to be; see gate().
    "hypotheses_tested": 1074,

    # Slack pushes nothing for a webhook message that mentions nobody: most
    # people's per-channel setting is "mentions and keywords only". Set the
    # SLACK_MENTION secret overrides this with "<!here>", a user group such as
    # "<!subteam^S0123|@traders>", or "" for no mention at all. It is prefixed
    # to the trading alerts - setups, entries, take-profits, stops - and to a
    # manual test run, which exists to prove delivery, but never to the weekly
    # scorecard or the nursery gate, so the routine posts stay quiet.
    "slack_mention": "<!channel>",

    "fail_alert_after": 3,
    # GitHub's scheduler often runs hours late or skips runs, so every missed
    # hour is replayed (up to 2 days) and alerts more than 2 hours old say so.
    "max_catchup_bars": 48,
    "late_alert_hours": 2,
}

NY = ZoneInfo("America/New_York")
UK = ZoneInfo("Europe/London")
UTC = timezone.utc
EPS = 1e-9
H1 = timedelta(hours=1)
EXTRAS = ["session", "adx", "h4", "atr_band"]


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def _get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "xau-signals"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def td_time_series(api_key, symbol, n, end_date=None):
    params = {"symbol": symbol, "interval": "1h", "outputsize": n,
              "timezone": "UTC", "order": "ASC", "apikey": api_key}
    if end_date:
        params["end_date"] = end_date.strftime("%Y-%m-%d %H:%M:%S")
    data = _get_json("https://api.twelvedata.com/time_series?" + urllib.parse.urlencode(params))
    if data.get("status") != "ok":
        raise RuntimeError(f"Twelve Data error: {data.get('code')} {data.get('message')}")
    bars = []
    for v in data["values"]:
        t = datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        bars.append({"t": t, "o": float(v["open"]), "h": float(v["high"]),
                     "l": float(v["low"]), "c": float(v["close"])})
    bars.sort(key=lambda b: b["t"])
    return bars


def fetch_h1(api_key, symbol, n):
    return td_time_series(api_key, symbol, n)


def fetch_h1_history(api_key, symbol, pages):
    allbars, end = {}, None
    for p in range(pages):
        if p:
            time.sleep(9)  # free plan: 8 requests per minute
        try:
            bars = td_time_series(api_key, symbol, 5000, end)
        except RuntimeError as e:
            if p == 0:
                raise
            print(f"History page {p + 1} stopped: {e}", file=sys.stderr)
            break
        if not bars:
            break
        for b in bars:
            allbars[b["t"]] = b
        end = bars[0]["t"] - H1
    return [allbars[k] for k in sorted(allbars)]


def load_history(cfg):
    """Every history file named in CONFIG, merged and de-duplicated by bar
    time, so the backtest and the ledger backfill both see 2008-2026."""
    merged = {}
    for p in [cfg["history_csv"]] + list(cfg.get("history_extra_csv") or []):
        if os.path.exists(p):
            for b in load_history_csv(p):
                merged[b["t"]] = b
    if not merged:
        raise RuntimeError(f"{cfg['history_csv']} not found: "
                           "run the 'Fetch gold history' workflow first")
    return [merged[k] for k in sorted(merged)]


def load_history_csv(path):
    """10-year H1 file written by the 'Fetch gold history' workflow."""
    import csv
    bars = []
    with open(path) as f:
        for r in csv.DictReader(f):
            t = datetime.strptime(r["time_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            if h - l <= 0 and o == c:
                continue
            bars.append({"t": t, "o": o, "h": h, "l": l, "c": c})
    return bars


def fetch_usd_rate(api_key, ccy):
    """USD per 1 unit of ccy."""
    if ccy == "USD":
        return 1.0
    data = _get_json("https://api.twelvedata.com/exchange_rate?" +
                     urllib.parse.urlencode({"symbol": f"{ccy}/USD", "apikey": api_key}))
    return float(data["rate"])


def fetch_news():
    """High-impact USD events this week as [(utc datetime, title)], or None."""
    try:
        data = _get_json("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=15)
    except Exception as e:  # noqa: BLE001 - news is optional
        print(f"News feed unavailable: {e}", file=sys.stderr)
        return None
    out = []
    for ev in data:
        if ev.get("country") == "USD" and ev.get("impact") == "High":
            try:
                t = datetime.fromisoformat(ev["date"]).astimezone(UTC)
            except (KeyError, ValueError):
                continue
            out.append((t, ev.get("title", "US event")))
    return out


def market_open(t):
    """Gold trades Sun 18:00 to Fri 17:00 New York time. Some free feeds still
    print flat candles over the weekend; those would distort Heikin Ashi."""
    ny = t.astimezone(NY)
    wd, h = ny.weekday(), ny.hour  # Mon=0 ... Sun=6
    if wd == 5 or (wd == 4 and h >= 17) or (wd == 6 and h < 18):
        return False
    return True


def closed_h1(bars, now):
    """Drop the still-forming candle and any weekend candles."""
    return [b for b in bars if b["t"] + H1 <= now and market_open(b["t"])]


# --------------------------------------------------------------------------
# Candle grouping (OANDA-style: days and H4 blocks roll at 17:00 New York)
# --------------------------------------------------------------------------
def trading_day(t):
    return (t.astimezone(NY) + timedelta(hours=7)).date()


def day_end(k):
    return datetime(k.year, k.month, k.day, 17, tzinfo=NY).astimezone(UTC)


def h4_key(t):
    s = t.astimezone(NY) + timedelta(hours=7)
    return (s.date(), s.hour // 4)


def h4_end(key):
    d, blk = key
    naive = datetime(d.year, d.month, d.day) + timedelta(hours=blk * 4 - 7 + 4)
    return naive.replace(tzinfo=NY).astimezone(UTC)


def aggregate(h1, keyfn, endfn):
    out, cur = [], None
    for b in h1:
        k = keyfn(b["t"])
        if cur is None or cur["k"] != k:
            cur = {"k": k, "end": endfn(k), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]}
            out.append(cur)
        else:
            cur["h"] = max(cur["h"], b["h"])
            cur["l"] = min(cur["l"], b["l"])
            cur["c"] = b["c"]
    return out


# --------------------------------------------------------------------------
# Indicators
# --------------------------------------------------------------------------
def ichimoku_cloud_dir(bars):
    """+1 close above the Ichimoku cloud, -1 below, 0 inside (9/26/52, cloud
    shifted 26 bars forward, as on TradingView). Uses closed bars only."""
    n = len(bars)
    out = [0] * n

    def mid(i, p):
        if i < p - 1:
            return None
        seg = bars[i - p + 1:i + 1]
        return (max(b["h"] for b in seg) + min(b["l"] for b in seg)) / 2

    span_a, span_b = [None] * n, [None] * n
    for i in range(n):
        t, k = mid(i, 9), mid(i, 26)
        span_a[i] = (t + k) / 2 if t is not None and k is not None else None
        span_b[i] = mid(i, 52)
    for i in range(25, n):
        a, b = span_a[i - 25], span_b[i - 25]
        if a is None or b is None:
            continue
        c = bars[i]["c"]
        out[i] = 1 if c > max(a, b) else -1 if c < min(a, b) else 0
    return out


def heikin_ashi(bars):
    ha = []
    for i, b in enumerate(bars):
        c = (b["o"] + b["h"] + b["l"] + b["c"]) / 4.0
        o = (b["o"] + b["c"]) / 2.0 if i == 0 else (ha[-1]["o"] + ha[-1]["c"]) / 2.0
        ha.append({"o": o, "c": c, "h": max(b["h"], o, c), "l": min(b["l"], o, c)})
    return ha


def ema_last(values, period):
    if len(values) < period:
        return None
    e = sum(values[:period]) / period
    k = 2.0 / (period + 1)
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def true_ranges(bars):
    tr = [bars[0]["h"] - bars[0]["l"]] if bars else []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    return tr


def atr_series(bars, p):
    tr = true_ranges(bars)
    out, s = [None] * len(bars), 0.0
    for i, v in enumerate(tr):
        s += v
        if i >= p:
            s -= tr[i - p]
        if i >= p:
            out[i] = s / p
    return out


def atr_last(bars, p):
    if len(bars) <= p:
        return None
    return sum(true_ranges(bars)[-p:]) / p


def adx_series(bars, p):
    n = len(bars)
    out = [None] * n
    if n < 2 * p + 2:
        return out
    tr, pdm, mdm = [0.0] * n, [0.0] * n, [0.0] * n
    for i in range(1, n):
        up = bars[i]["h"] - bars[i - 1]["h"]
        dn = bars[i - 1]["l"] - bars[i]["l"]
        pdm[i] = up if up > dn and up > 0 else 0.0
        mdm[i] = dn if dn > up and dn > 0 else 0.0
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    a, pp, mm = sum(tr[1:p + 1]), sum(pdm[1:p + 1]), sum(mdm[1:p + 1])
    dxs, adx = [], None
    for i in range(p, n):
        if i > p:
            a = a - a / p + tr[i]
            pp = pp - pp / p + pdm[i]
            mm = mm - mm / p + mdm[i]
        pdi = 100 * pp / a if a else 0.0
        mdi = 100 * mm / a if a else 0.0
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0
        dxs.append(dx)
        if len(dxs) == p:
            adx = sum(dxs) / p
        elif len(dxs) > p:
            adx = (adx * (p - 1) + dx) / p
        if adx is not None:
            out[i] = adx
    return out


def bull(x):
    return x["c"] > x["o"]


def bear(x):
    return x["c"] < x["o"]


def no_lower_wick(x, tol):
    return min(x["o"], x["c"]) - x["l"] <= tol + EPS


def no_upper_wick(x, tol):
    return x["h"] - max(x["o"], x["c"]) <= tol + EPS


# --------------------------------------------------------------------------
# Daily context
# --------------------------------------------------------------------------
def daily_trend(daily, cfg):
    mode = cfg["daily_trend_mode"]
    if mode == "off" or not daily:
        return 0
    last = heikin_ashi(daily)[-1]
    ha_dir = 1 if bull(last) else (-1 if bear(last) else 0)
    if mode == "ha":
        return ha_dir
    e = ema_last([d["c"] for d in daily], cfg["daily_ema"])
    c = daily[-1]["c"]
    if e is None:
        return 0
    if ha_dir == 1 and c > e:
        return 1
    if ha_dir == -1 and c < e:
        return -1
    return 0


def build_levels(daily, price, cfg):
    closes = [d["c"] for d in daily[-cfg["sr_lookback_days"]:]]
    k = cfg["sr_pivot_strength"]
    a = atr_last(daily, cfg["atr_period"])
    if a is None or len(closes) < 2 * k + 5:
        return []
    cand = []
    for i in range(k, len(closes) - k):
        win = closes[i - k:i] + closes[i + 1:i + k + 1]
        if all(closes[i] > x for x in win) or all(closes[i] < x for x in win):
            cand.append(closes[i])
    if not cand:
        return []
    cand.sort()
    merged, cluster = [], [cand[0]]
    for x in cand[1:]:
        if x - cluster[-1] <= cfg["sr_merge_atr"] * a:
            cluster.append(x)
        else:
            merged.append(sum(cluster) / len(cluster))
            cluster = [x]
    merged.append(sum(cluster) / len(cluster))
    merged.sort(key=lambda L: abs(L - price))
    return sorted(merged[:cfg["sr_max_levels"]])


def nearest_above(levels, p):
    return next((L for L in levels if L > p), None)


def nearest_below(levels, p):
    return next((L for L in reversed(levels) if L < p), None)


# --------------------------------------------------------------------------
# Features: everything the rules need, computed once, no look-ahead
# --------------------------------------------------------------------------
class Features:
    def __init__(self, h1, cfg):
        self.h1, self.cfg = h1, cfg
        n = len(h1)
        self.ha = heikin_ashi(h1)
        self.hatr = atr_series(h1, cfg["atr_period"])
        self.adx = adx_series(h1, cfg["adx_period"])
        self.daily = aggregate(h1, trading_day, day_end)
        self.h4 = aggregate(h1, h4_key, h4_end)
        self.h4_ha = heikin_ashi(self.h4)
        self.h4_cloud = ichimoku_cloud_dir(self.h4)
        self.d_idx, self.h4_idx = [-1] * n, [-1] * n
        dj = hj = -1
        for i, b in enumerate(h1):
            close = b["t"] + H1
            while dj + 1 < len(self.daily) and self.daily[dj + 1]["end"] <= close:
                dj += 1
            while hj + 1 < len(self.h4) and self.h4[hj + 1]["end"] <= close:
                hj += 1
            self.d_idx[i], self.h4_idx[i] = dj, hj
        w = cfg["atr_pct_window"]
        self.atr_pct = [None] * n
        for i in range(n):
            x = self.hatr[i]
            if x is None:
                continue
            win = [v for v in self.hatr[max(0, i - w + 1):i + 1] if v is not None]
            if len(win) >= 50:
                self.atr_pct[i] = 100.0 * sum(1 for v in win if v <= x) / len(win)
        self._dctx = {}

    def close_time(self, i):
        return self.h1[i]["t"] + H1

    def daily_ctx(self, i):
        k = self.d_idx[i]
        if k < 0:
            return None
        if k not in self._dctx:
            sub = self.daily[:k + 1]
            self._dctx[k] = {
                "k": k,
                "trend": daily_trend(sub, self.cfg),
                "levels": build_levels(sub, sub[-1]["c"], self.cfg),
                "datr": atr_last(sub, self.cfg["atr_period"]),
                "ha": heikin_ashi(sub)[-1],
                "ema": ema_last([b["c"] for b in sub], self.cfg["daily_ema"]),
            }
        return self._dctx[k]

    def warm(self, i):
        """Enough history for every rule at bar i."""
        return (self.d_idx[i] >= max(60, self.cfg["daily_ema"] + 5) and self.adx[i] is not None
                and self.atr_pct[i] is not None and self.h4_idx[i] >= 1 and i >= 30)


# --------------------------------------------------------------------------
# Setup evaluation
# --------------------------------------------------------------------------
def news_near(news, t, window_min):
    """Closest high-impact event within the window, or None."""
    if not news:
        return None
    best = None
    for et, title in news:
        mins = (et - t).total_seconds() / 60
        if -window_min <= mins <= window_min * 2 and (best is None or abs(mins) < abs(best[2])):
            best = (et, title, mins)
    return best


def evaluate(F, i, d, cfg, news=None):
    """Return a setup dict if closed H1 bar i passes the checklist for direction d."""
    tol = cfg["wick_tolerance"]
    ha, h1 = F.ha, F.h1
    x = ha[i]
    if d == 1 and not (bull(x) and no_lower_wick(x, tol)):
        return None
    if d == -1 and not (bear(x) and no_upper_wick(x, tol)):
        return None

    flip, earlier, since = False, False, 0
    for j in range(i - 1, max(-1, i - 1 - cfg["max_bars_since_flip"]), -1):
        y = ha[j]
        if (d == 1 and bear(y)) or (d == -1 and bull(y)):
            flip, since = True, i - j
            break
        if (d == 1 and bull(y) and no_lower_wick(y, tol)) or (d == -1 and bear(y) and no_upper_wick(y, tol)):
            earlier = True
    if not flip or (cfg["first_no_wick_only"] and earlier):
        return None

    b1 = abs(x["c"] - x["o"])
    b2 = abs(ha[i - 1]["c"] - ha[i - 1]["o"])
    if b1 < b2 * cfg["min_body_growth"]:
        return None

    dc = F.daily_ctx(i)
    if dc is None:
        return None
    if cfg["daily_trend_mode"] != "off" and dc["trend"] != d:
        return None

    close1 = h1[i]["c"]
    prev = [b["c"] for b in h1[max(0, i - cfg["breakout_bars"]):i]]
    broken = None
    if prev:
        lo, hi = min(prev), max(prev)
        for L in dc["levels"]:
            if d == 1 and lo < L < close1:
                broken = L if broken is None else max(broken, L)
            if d == -1 and close1 < L < hi:
                broken = L if broken is None else min(broken, L)
    if cfg["require_breakout"] and broken is None:
        return None

    nxt = nearest_above(dc["levels"], close1) if d == 1 else nearest_below(dc["levels"], close1)
    room = abs(nxt - close1) if nxt is not None else None
    if cfg["require_room"] and nxt is not None and dc["datr"] and room < cfg["min_room_atr"] * dc["datr"]:
        return None

    # levels
    b = h1[i]
    swing = h1[max(0, i - cfg["stop_swing_bars"] + 1):i + 1]
    hatr = F.hatr[i] or 0
    if d == 1:
        entry = b["h"] + cfg["entry_buffer"]
        stop = min(s["l"] for s in swing) - cfg["stop_buffer_atr"] * hatr
    else:
        entry = b["l"] - cfg["entry_buffer"]
        stop = max(s["h"] for s in swing) + cfg["stop_buffer_atr"] * hatr
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    target = nearest_above(dc["levels"], entry) if d == 1 else nearest_below(dc["levels"], entry)

    # quality checks
    t_close = F.close_time(i)
    checks = {}
    hr = t_close.astimezone(UK).hour
    s_ok = cfg["session_start_uk"] <= hr < cfg["session_end_uk"]
    checks["session"] = (s_ok, "London / New York hours" if s_ok else "Outside London / New York hours (quiet Asia session)")
    a = F.adx[i]
    a_ok = a is not None and a >= cfg["adx_min"]
    checks["adx"] = (a_ok, f"Trend strength ADX {a:.0f}: {'trending' if a_ok else 'weak / ranging'}" if a is not None else "ADX not available")
    hk = F.h4_idx[i]
    h4c = F.h4_ha[hk] if hk >= 0 else None
    h4_ok = h4c is not None and (bull(h4c) if d == 1 else bear(h4c))
    col = "green" if h4c is not None and bull(h4c) else "red"
    checks["h4"] = (h4_ok, f"4-hour candles {'agree' if h4_ok else 'disagree'} ({col})")
    cl = F.h4_cloud[hk] if hk >= 0 else 0
    cl_ok = cl == d
    where = "above" if cl == 1 else "below" if cl == -1 else "inside"
    checks["h4_cloud"] = (cl_ok, f"4-hour price is {where} the Ichimoku cloud")
    pct = F.atr_pct[i]
    if pct is None:
        checks["atr_band"] = (False, "Volatility unknown")
    elif pct < cfg["atr_pct_low"]:
        checks["atr_band"] = (False, "Very quiet market (low volatility)")
    elif pct > cfg["atr_pct_high"]:
        checks["atr_band"] = (False, "Unusually volatile market")
    else:
        checks["atr_band"] = (True, "Normal volatility")
    sw_ok = hatr == 0 or risk <= cfg["max_stop_atr"] * hatr
    checks["stop_width"] = (sw_ok, "Stop size normal" if sw_ok else f"Wide stop ({risk / hatr:.1f}x hourly ATR)")
    if news is not None:
        nn = news_near(news, t_close, cfg["news_window_min"])
        if nn:
            et, title, mins = nn
            when = f"in {mins:.0f} min" if mins >= 0 else f"{-mins:.0f} min ago"
            checks["news"] = (False, f"US {title} at {et.astimezone(UK):%H:%M} UK ({when}): spreads may jump")
        else:
            checks["news"] = (True, f"No major US news within {cfg['news_window_min']} min")

    for name, required in cfg["filters"].items():
        if required and name in checks and not checks[name][0]:
            return None

    score = sum(1 for n in EXTRAS if checks[n][0])
    grade = "A" if score == 4 else ("B" if score >= 2 else "C")

    return {
        "dir": d, "i": i, "t_close": t_close, "close": close1,
        "entry": entry, "stop": stop, "risk": risk, "target": target,
        "broken": broken, "next": nxt, "room": room, "since": since,
        "body_ratio": b1 / b2 if b2 > 0 else 0.0, "checks": checks,
        "score": score, "grade": grade, "trend": dc["trend"],
    }


# --------------------------------------------------------------------------
# State machine (shared by live and backtest)
# --------------------------------------------------------------------------
def _close_r(idea, price, cost):
    """R for the whole position if the remainder closes at `price`."""
    d, risk = idea["dir"], idea["risk"]
    done = idea.get("done", 0.0)
    return idea.get("booked", 0.0) + (1 - done) * (price - idea["entry"]) * d / risk - cost / risk


def step(F, i, st, cfg, news=None):
    """Advance one closed H1 bar. Returns a list of event dicts.

    Mirrors research/lab.py exactly: on the fill bar only the stop is checked;
    afterwards stop first, then the partial, then the final target (or the
    opposite-colour HA exit in "ha" mode).
    """
    ev = []
    b, x = F.h1[i], F.ha[i]
    t_close = F.close_time(i)
    idea = st.get("idea")
    cost = cfg["cost_per_trade"]
    targets = cfg["exit_mode"] == "targets"
    closed = False

    def hit(level, d, side):  # side "favour" = price moved our way to level
        if side == "favour":
            return b["h"] >= level if d == 1 else b["l"] <= level
        return b["l"] <= level if d == 1 else b["h"] >= level

    if idea:
        d = idea["dir"]
        if not idea["triggered"]:
            idea["age"] = idea.get("age", 0) + 1
            if hit(idea["entry"], d, "favour"):
                idea["triggered"] = True
                idea["entry_time"] = t_close.isoformat()
                ev.append({"type": "entry", "idea": dict(idea), "t": t_close})
                if hit(idea["stop"], d, "against"):
                    ev.append({"type": "stop", "idea": dict(idea), "t": t_close,
                               "r": _close_r(idea, idea["stop"], cost), "price": idea["stop"]})
                    st["idea"] = idea = None
            elif (d == 1 and bear(x)) or (d == -1 and bull(x)):
                ev.append({"type": "cancel", "idea": dict(idea), "t": t_close, "why": "flip"})
                st["idea"] = idea = None
            elif idea["age"] >= cfg["entry_expiry_bars"]:
                ev.append({"type": "cancel", "idea": dict(idea), "t": t_close, "why": "expired"})
                st["idea"] = idea = None
        else:
            if hit(idea["stop"], d, "against"):
                ev.append({"type": "stop", "idea": dict(idea), "t": t_close,
                           "r": _close_r(idea, idea["stop"], cost), "price": idea["stop"]})
                st["idea"] = idea = None
                closed = True
            elif targets:
                if cfg["partial_r"] and not idea.get("done") and hit(idea["partial"], d, "favour"):
                    idea["done"] = cfg["partial_frac"]
                    idea["booked"] = cfg["partial_frac"] * cfg["partial_r"]
                    idea["stop"] = idea["entry"]
                    ev.append({"type": "partial", "idea": dict(idea), "t": t_close})
                if hit(idea["target"], d, "favour"):
                    ev.append({"type": "target", "idea": dict(idea), "t": t_close,
                               "r": _close_r(idea, idea["target"], cost), "price": idea["target"]})
                    st["idea"] = idea = None
                    closed = True
            else:
                if cfg["breakeven_at_r"] and not idea.get("be"):
                    lvl = idea["entry"] + d * cfg["breakeven_at_r"] * idea["risk"]
                    if hit(lvl, d, "favour"):
                        idea["stop"], idea["be"] = idea["entry"], True
                        ev.append({"type": "breakeven", "idea": dict(idea), "t": t_close})
                if (d == 1 and bear(x)) or (d == -1 and bull(x)):
                    ev.append({"type": "exit", "idea": dict(idea), "t": t_close,
                               "r": _close_r(idea, b["c"], cost), "price": b["c"]})
                    st["idea"] = idea = None
                    closed = True

    # new signal: only when flat (a pending order may be replaced)
    if not closed and not (idea and idea["triggered"]):
        for d in (1, -1):
            s = evaluate(F, i, d, cfg, news)
            if s:
                replaced = dict(idea) if idea else None
                risk = s["risk"]
                st["idea"] = idea = {
                    "dir": d, "entry": round(s["entry"], 2), "stop": round(s["stop"], 2),
                    "risk": round(risk, 4), "triggered": False, "age": 0,
                    "partial": round(s["entry"] + d * cfg["partial_r"] * risk, 2) if cfg["partial_r"] else None,
                    "target": round(s["entry"] + d * cfg["target_r"] * risk, 2) if cfg["target_r"] else None,
                    "sig_time": s["t_close"].isoformat(),
                    "session": s["checks"]["session"][0], "grade": s["grade"],
                }
                ev.append({"type": "signal", "setup": s, "idea": dict(idea), "t": t_close,
                           "replaced": replaced})
                break
    return ev


def daily_hold(F, k, idea, cfg):
    if cfg["exit_mode"] != "ha":
        return None
    if not (cfg["alert_daily_hold"] and idea and idea.get("triggered") and k >= 0):
        return None
    x = heikin_ashi(F.daily[:k + 1])[-1]
    tol = cfg["wick_tolerance"]
    if (idea["dir"] == 1 and bull(x) and no_lower_wick(x, tol)) or \
       (idea["dir"] == -1 and bear(x) and no_upper_wick(x, tol)):
        return {"type": "hold", "idea": dict(idea)}
    return None


# --------------------------------------------------------------------------
# Second setup: inside-day breakout (research/round5_standalone.py)
# --------------------------------------------------------------------------
def is_inside_day(daily, k):
    return k >= 1 and daily[k]["h"] < daily[k - 1]["h"] and daily[k]["l"] > daily[k - 1]["l"]


def ib_step(F, i, st, cfg):
    """Advance the inside-day setup by one closed H1 bar (kept in st["ib"]).

    Matches the research rules: the order is live for the next daily candle
    only; the first side traded fills (at the open if price gaps through); the
    stop is the other side; if one H1 candle touches both sides the stop is
    assumed; whatever is open is closed at that day's close.
    """
    ev = []
    if not cfg.get("inside_day"):
        return ev
    b, t_close, cost = F.h1[i], F.close_time(i), cfg["cost_per_trade"]
    k = F.d_idx[i]
    new_day = i > 0 and k >= 0 and k != F.d_idx[i - 1]
    if new_day and F.daily[k]["end"] <= b["t"]:
        # the day ended in a gap before this candle (early holiday close): settle it at its last price first
        ev += _ib_day_close(F, k, st, F.h1[i - 1]["c"], t_close, cost)
    ib = st.get("ib")
    if ib and not ib["triggered"]:
        up, dn = b["h"] >= ib["hi"], b["l"] <= ib["lo"]
        if up or dn:
            d = (1 if up else -1) if up != dn else (1 if b["o"] >= (ib["hi"] + ib["lo"]) / 2 else -1)
            entry = max(b["o"], ib["hi"]) if d == 1 else min(b["o"], ib["lo"])
            stop = ib["lo"] if d == 1 else ib["hi"]
            ib.update(triggered=True, dir=d, entry=round(entry, 2), stop=stop,
                      risk=round(abs(entry - stop), 4), entry_time=t_close.isoformat())
            ev.append({"type": "ib_entry", "idea": dict(ib), "t": t_close})
            if up and dn:
                ev.append({"type": "ib_stop", "idea": dict(ib), "t": t_close,
                           "r": _close_r(ib, stop, cost), "price": stop})
                st["ib"] = ib = None
    elif ib:
        d = ib["dir"]
        if (b["l"] <= ib["stop"]) if d == 1 else (b["h"] >= ib["stop"]):
            ev.append({"type": "ib_stop", "idea": dict(ib), "t": t_close,
                       "r": _close_r(ib, ib["stop"], cost), "price": ib["stop"]})
            st["ib"] = ib = None

    if new_day and F.daily[k]["end"] > b["t"]:
        ev += _ib_day_close(F, k, st, b["c"], t_close, cost)  # this candle closed the day
    return ev


def _ib_day_close(F, k, st, price, t, cost):
    """Daily candle k has closed: settle the open inside-day trade or cancel the
    unfilled orders, then look for a new inside day."""
    ev = []
    ib = st.get("ib")
    day_end_iso = F.daily[k]["end"].isoformat()
    if ib and ib["setup_day_end"] != day_end_iso:
        if ib["triggered"]:
            ev.append({"type": "ib_close", "idea": dict(ib), "t": t,
                       "r": _close_r(ib, price, cost), "price": price})
        else:
            ev.append({"type": "ib_cancel", "idea": dict(ib), "t": t})
        st["ib"] = None
    if is_inside_day(F.daily, k):
        cur, prev = F.daily[k], F.daily[k - 1]
        st["ib"] = {"strategy": "inside_day", "hi": round(cur["h"], 2), "lo": round(cur["l"], 2),
                    "prev_hi": round(prev["h"], 2), "prev_lo": round(prev["l"], 2),
                    "triggered": False, "setup_day_end": day_end_iso, "sig_time": F.daily[k]["end"].isoformat()}
        ev.append({"type": "ib_signal", "idea": dict(st["ib"]), "t": t})
    return ev


# --------------------------------------------------------------------------
# Feature ledger
#
# Every hour the bot evaluates is written down: the features it computed, what
# it decided, and nothing about what happened next. Outcomes go to a separate
# file keyed by the signal time, so the join is always after the fact. That
# makes a new idea a query over stored rows instead of a fresh replay of raw
# candles, and the rows were written before the outcome was known.
#
# "source" says live or backfill. A backfilled row is reconstructed from the
# history file; a live row is what the bot actually saw at the time. Keep them
# apart when judging anything.
# --------------------------------------------------------------------------
LEDGER_COLS = [
    "t_close", "source", "state_before",
    "open", "high", "low", "close",
    "ha_dir", "ha_body", "body_ratio", "lower_wick", "upper_wick", "bars_since_flip",
    "trigger_dir", "d_trend", "d_ha_dir", "d_close_vs_ema_atr",
    "h4_ha_dir", "h4_cloud", "atr_h1", "atr_pct", "adx", "datr",
    "nearest_above", "nearest_below", "room_above_atr", "room_below_atr",
    "hour_uk", "dow", "in_session", "daily_close", "inside_day",
    "setup_dir", "grade", "score", "entry", "stop", "risk", "target", "events",
]

OUTCOME_COLS = ["sig_time", "entry_time", "exit_time", "dir", "grade", "strategy",
                "entry", "exit", "r", "how"]


def _r(v, n=4):
    return "" if v is None else round(v, n)


def trigger_geometry(F, i, cfg):
    """The H1 Heikin Ashi trigger on its own: colour, no wick against the move,
    first one since the flip, body growth. None of the higher-timeframe
    filters. 1, -1 or 0. This is the "something nearly happened" marker, so
    research can count how often the trigger fires against how often the
    filters let it through."""
    tol = cfg["wick_tolerance"]
    ha = F.ha
    if i < 1:
        return 0
    for d in (1, -1):
        x = ha[i]
        if d == 1 and not (bull(x) and no_lower_wick(x, tol)):
            continue
        if d == -1 and not (bear(x) and no_upper_wick(x, tol)):
            continue
        flip, earlier = False, False
        for j in range(i - 1, max(-1, i - 1 - cfg["max_bars_since_flip"]), -1):
            y = ha[j]
            if (d == 1 and bear(y)) or (d == -1 and bull(y)):
                flip = True
                break
            if (d == 1 and bull(y) and no_lower_wick(y, tol)) or (d == -1 and bear(y) and no_upper_wick(y, tol)):
                earlier = True
        if not flip or (cfg["first_no_wick_only"] and earlier):
            continue
        b1 = abs(x["c"] - x["o"])
        b2 = abs(ha[i - 1]["c"] - ha[i - 1]["o"])
        if b1 < b2 * cfg["min_body_growth"]:
            continue
        return d
    return 0


def bars_since_flip(F, i):
    """Bars since the H1 Heikin Ashi colour last differed from this bar's."""
    up = bull(F.ha[i])
    for j in range(i - 1, -1, -1):
        if bull(F.ha[j]) != up:
            return i - j
    return 0


def state_label(st):
    idea = st.get("idea")
    if not idea:
        return "flat"
    return "in_trade" if idea.get("triggered") else "pending"


def ledger_row(F, i, cfg, events=(), state_before="flat", source="live"):
    b, x = F.h1[i], F.ha[i]
    dc = F.daily_ctx(i)
    hk = F.h4_idx[i]
    k = F.d_idx[i]
    h4c = F.h4_ha[hk] if hk >= 0 else None
    close = b["c"]
    levels = dc["levels"] if dc else []
    datr = dc["datr"] if dc else None
    above, below = nearest_above(levels, close), nearest_below(levels, close)
    t_close = F.close_time(i)
    uk = t_close.astimezone(UK)
    body = abs(x["c"] - x["o"])
    prev_body = abs(F.ha[i - 1]["c"] - F.ha[i - 1]["o"]) if i >= 1 else 0.0
    day_rolled = k >= 0 and (i == 0 or F.d_idx[i - 1] != k)
    sig = next((e for e in events if e["type"] == "signal"), None)
    s = sig["setup"] if sig else None
    row = {
        "t_close": t_close.isoformat(),
        "source": source,
        "state_before": state_before,
        "open": _r(b["o"], 2), "high": _r(b["h"], 2), "low": _r(b["l"], 2), "close": _r(close, 2),
        "ha_dir": 1 if bull(x) else (-1 if bear(x) else 0),
        "ha_body": _r(body, 3),
        "body_ratio": _r(body / prev_body, 3) if prev_body > 0 else "",
        "lower_wick": _r(min(x["o"], x["c"]) - x["l"], 3),
        "upper_wick": _r(x["h"] - max(x["o"], x["c"]), 3),
        "bars_since_flip": bars_since_flip(F, i),
        "trigger_dir": trigger_geometry(F, i, cfg),
        "d_trend": dc["trend"] if dc else "",
        "d_ha_dir": (1 if bull(dc["ha"]) else (-1 if bear(dc["ha"]) else 0)) if dc else "",
        "d_close_vs_ema_atr": "",
        "h4_ha_dir": (1 if bull(h4c) else (-1 if bear(h4c) else 0)) if h4c is not None else "",
        "h4_cloud": F.h4_cloud[hk] if hk >= 0 else "",
        "atr_h1": _r(F.hatr[i], 3), "atr_pct": _r(F.atr_pct[i], 1),
        "adx": _r(F.adx[i], 2), "datr": _r(datr, 3),
        "nearest_above": _r(above, 2), "nearest_below": _r(below, 2),
        "room_above_atr": "", "room_below_atr": "",
        "hour_uk": uk.hour, "dow": t_close.weekday(),
        "in_session": 1 if cfg["session_start_uk"] <= uk.hour < cfg["session_end_uk"] else 0,
        "daily_close": _r(F.daily[k]["c"], 2) if k >= 0 else "",
        "inside_day": (1 if is_inside_day(F.daily, k) else 0) if day_rolled else "",
        "setup_dir": s["dir"] if s else 0,
        "grade": s["grade"] if s else "",
        "score": s["score"] if s else "",
        "entry": _r(s["entry"], 2) if s else "",
        "stop": _r(s["stop"], 2) if s else "",
        "risk": _r(s["risk"], 3) if s else "",
        "target": _r(s["target"], 2) if s else "",
        "events": ";".join(e["type"] for e in events),
    }
    if dc and dc.get("ema") and datr and k >= 0:
        row["d_close_vs_ema_atr"] = _r((F.daily[k]["c"] - dc["ema"]) / datr, 3)
    if datr:
        if above is not None:
            row["room_above_atr"] = _r((above - close) / datr, 3)
        if below is not None:
            row["room_below_atr"] = _r((close - below) / datr, 3)
    return row


def _csv_last(path, col):
    """Last value of a column in a csv file, or None."""
    import csv
    if not os.path.exists(path):
        return None
    last = None
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            last = row.get(col)
    return last


def ledger_append(path, rows):
    """Append rows, skipping bars already written. Header on the first write."""
    import csv
    if not rows:
        return 0
    last = _csv_last(path, "t_close")
    rows = [r for r in rows if last is None or r["t_close"] > last]
    if not rows:
        return 0
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLS, extrasaction="ignore", lineterminator="\n")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


def outcomes_append(path, entries):
    """Closed trades as an append-only csv, keyed by sig_time so it joins to
    the ledger's t_close."""
    import csv
    if not entries:
        return 0
    seen = set()
    if os.path.exists(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                seen.add((row.get("sig_time"), row.get("exit_time"), row.get("how")))
    rows = [e for e in entries
            if (e.get("sig_time"), e.get("exit_time"), e.get("how")) not in seen]
    if not rows:
        return 0
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTCOME_COLS, extrasaction="ignore", lineterminator="\n")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


def ledger_backfill(cfg, h1, path):
    """Replay the history file through the live state machine and write a
    ledger row for every warm hour. Rows are marked source=backfill."""
    import csv
    import gzip
    import io
    F = Features(h1, cfg)
    st, journal, n = {}, [], 0
    start = next((i for i in range(len(F.h1)) if F.warm(i)), None)
    if start is None:
        raise RuntimeError("Not enough history to backfill the ledger")
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    # mtime=0 so re-running on the same data gives a byte-identical file
    # instead of a fresh multi-megabyte blob in git every time
    if path.endswith(".gz"):
        f = io.TextIOWrapper(gzip.GzipFile(path, "wb", compresslevel=9, mtime=0), newline="")
    else:
        f = open(path, "w", newline="")
    with f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for i in range(start, len(F.h1)):
            if not F.warm(i):
                continue
            before = state_label(st)
            evs = step(F, i, st, cfg, None) + ib_step(F, i, st, cfg)
            for e in evs:
                if e["type"] in ("exit", "stop", "target", "ib_stop", "ib_close"):
                    journal_add(journal, e)
            w.writerow(ledger_row(F, i, cfg, evs, before, "backfill"))
            n += 1
    return n, journal


# --------------------------------------------------------------------------
# Third setup: the trigger read on the 4-hour candle (round 9 E2)
#
# Identical mechanism to the hourly trend setup, one timeframe up: the first
# 4-hour Heikin Ashi candle of a new colour, no wick against the move, body at
# least as big as the one before, with the daily trend agreeing. Entry and
# management still happen on H1 bars, because that is where fills resolve.
#
# research/round9_entries.py calls these same functions, so the backtest and
# the live bot cannot drift apart.
# --------------------------------------------------------------------------
def h4_setup(F, i, k, d, cfg):
    """A setup on the closed 4-hour candle k, acted on at H1 bar i, or None."""
    ha4, h4 = F.h4_ha, F.h4
    if k < 1 or k >= len(ha4):
        return None
    tol = cfg["wick_tolerance"]
    x = ha4[k]
    if d == 1 and not (bull(x) and no_lower_wick(x, tol)):
        return None
    if d == -1 and not (bear(x) and no_upper_wick(x, tol)):
        return None

    # the first candle of the new colour: an opposite candle must come before
    # any earlier no-wick candle of our own colour
    flip = False
    for j in range(k - 1, max(-1, k - 1 - cfg["h4_max_bars_since_flip"]), -1):
        y = ha4[j]
        if (d == 1 and bear(y)) or (d == -1 and bull(y)):
            flip = True
            break
        nw = (bull(y) and no_lower_wick(y, tol)) if d == 1 else (bear(y) and no_upper_wick(y, tol))
        if nw:
            flip = False
            break
    if not flip:
        return None

    if abs(x["c"] - x["o"]) < abs(ha4[k - 1]["c"] - ha4[k - 1]["o"]):
        return None

    dc = F.daily_ctx(i)
    if dc is None or dc["trend"] != d:
        return None

    sw = h4[max(0, k - cfg["h4_swing_bars"] + 1):k + 1]
    buf, sbuf = cfg["h4_entry_buffer"], cfg["h4_stop_buffer"]
    if d == 1:
        entry = h4[k]["h"] + buf
        stop = min(z["l"] for z in sw) - sbuf
    else:
        entry = h4[k]["l"] - buf
        stop = max(z["h"] for z in sw) + sbuf
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    return {"dir": d, "k": k, "entry": entry, "stop": stop, "risk": risk,
            "t_close": F.close_time(i)}


def h4_step(F, i, st, cfg):
    """Advance the 4-hour setup by one closed H1 bar. State lives in st["h4"].

    Mirrors step(): on the fill bar only the stop is checked; afterwards the
    stop first, then the partial, then the target.
    """
    if not cfg.get("h4_trigger"):
        return []
    ev = []
    b = F.h1[i]
    t_close = F.close_time(i)
    idea = st.get("h4")
    cost = cfg["cost_per_trade"]
    closed = False

    def hit(level, d, side):
        if side == "favour":
            return b["h"] >= level if d == 1 else b["l"] <= level
        return b["l"] <= level if d == 1 else b["h"] >= level

    if idea:
        d = idea["dir"]
        if not idea["triggered"]:
            idea["age"] = idea.get("age", 0) + 1
            if hit(idea["entry"], d, "favour"):
                idea["triggered"] = True
                idea["entry_time"] = t_close.isoformat()
                ev.append({"type": "h4_entry", "idea": dict(idea), "t": t_close})
                if hit(idea["stop"], d, "against"):
                    ev.append({"type": "h4_stop", "idea": dict(idea), "t": t_close,
                               "r": _close_r(idea, idea["stop"], cost), "price": idea["stop"]})
                    st["h4"] = idea = None
                    closed = True
            elif idea["age"] >= cfg["h4_expiry_bars"]:
                ev.append({"type": "h4_cancel", "idea": dict(idea), "t": t_close,
                           "why": "expired"})
                st["h4"] = idea = None
                closed = True
        else:
            if hit(idea["stop"], d, "against"):
                ev.append({"type": "h4_stop", "idea": dict(idea), "t": t_close,
                           "r": _close_r(idea, idea["stop"], cost), "price": idea["stop"]})
                st["h4"] = idea = None
                closed = True
            else:
                if idea.get("partial") and not idea.get("done") and hit(idea["partial"], d, "favour"):
                    idea["done"] = cfg["h4_partial_frac"]
                    idea["booked"] = idea["done"] * cfg["h4_partial_r"]
                    idea["stop"] = idea["entry"]
                    ev.append({"type": "h4_partial", "idea": dict(idea), "t": t_close})
                if idea.get("target") and hit(idea["target"], d, "favour"):
                    ev.append({"type": "h4_target", "idea": dict(idea), "t": t_close,
                               "r": _close_r(idea, idea["target"], cost), "price": idea["target"]})
                    st["h4"] = idea = None
                    closed = True

    # one evaluation per closed 4-hour candle, acted on only when flat
    k = F.h4_idx[i]
    new_k = k >= 1 and st.get("h4_last_k") != k
    if new_k:
        st["h4_last_k"] = k
    if not closed and not st.get("h4") and new_k:
        for d in (1, -1):
            s = h4_setup(F, i, k, d, cfg)
            if not s:
                continue
            risk = s["risk"]
            st["h4"] = {
                "dir": d, "entry": round(s["entry"], 2), "stop": round(s["stop"], 2),
                "risk": round(risk, 4), "triggered": False, "age": 0,
                "partial": round(s["entry"] + d * cfg["h4_partial_r"] * risk, 2),
                "target": round(s["entry"] + d * cfg["h4_target_r"] * risk, 2),
                "sig_time": s["t_close"].isoformat(), "strategy": "h4_trend",
                "grade": None, "session": None,
            }
            ev.append({"type": "h4_signal", "idea": dict(st["h4"]), "t": t_close, "setup": s})
            break
    return ev


# --------------------------------------------------------------------------
# Plain-English Slack messages
# --------------------------------------------------------------------------
def px(v):
    return f"{v:,.2f}"


def side_word(d):
    return "BUY" if d == 1 else "SELL"


def uk_hm(t):
    return t.astimezone(UK).strftime("%H:%M")


def uk_day(t):
    return t.astimezone(UK).strftime("%a %d %b %H:%M")


def lot_size(risk_pts, sizing, cfg):
    """Return (lots, risk_amount_ccy) or None."""
    if not sizing:
        return None
    usd_per_ccy = sizing["usd_rate"]
    risk_ccy = sizing["account"] * sizing["risk_pct"] / 100.0
    risk_usd = risk_ccy * usd_per_ccy
    per_lot = risk_pts * cfg["contract_oz"]
    if per_lot <= 0:
        return None
    lots = int(risk_usd / per_lot * 100) / 100.0
    return lots, risk_ccy


def ccy_sym(c):
    return {"GBP": "£", "USD": "$", "EUR": "€"}.get(c, c + " ")


def fmt_signal(e, cfg, sizing):
    s, idea = e["setup"], e["idea"]
    d = s["dir"]
    green, red = ("green", "red") if d == 1 else ("red", "green")
    icon = ":large_green_circle:" if d == 1 else ":red_circle:"
    wick = "lower" if d == 1 else "upper"
    above = "above" if d == 1 else "below"
    targets = cfg["exit_mode"] == "targets"
    lines = [
        f"{icon} *{side_word(d)} SETUP: Gold (XAUUSD)* | 1H candle closed {uk_hm(s['t_close'])} UK",
        f"_The 1-hour Heikin Ashi candle turned {green} with no {wick} wick, in line with the daily trend "
        "and the 4-hour candles: the strategy's entry trigger._",
    ]
    if e.get("replaced"):
        lines.append(f"_Replaces the earlier {side_word(e['replaced']['dir']).lower()} setup that had not triggered._")
    lines += [
        "",
        "*The plan*",
        f"• *Entry:* only if price trades {above} *{px(s['entry'])}* ({'buy' if d == 1 else 'sell'}-stop order)",
        f"• *Stop:* *{px(s['stop'])}* ({s['risk']:.2f} from entry = 1R)",
    ]
    ls = lot_size(s["risk"], sizing, cfg)
    if ls:
        lots, amt = ls
        sym = ccy_sym(sizing["ccy"])
        if lots >= 0.01:
            lines.append(f"• *Size:* {lots:.2f} lots risks about {sym}{amt:,.0f} ({sizing['risk_pct']:g}% of account)")
        else:
            lines.append(f"• *Size:* stop is too wide for {sizing['risk_pct']:g}% risk at the 0.01 lot minimum")
    if targets:
        if idea.get("partial") is not None:
            pct = int(cfg["partial_frac"] * 100)
            lines.append(f"• *Take profit 1:* close {pct}% at *{px(idea['partial'])}* (+{cfg['partial_r']:g}R), "
                         "then move the stop to entry")
        lines.append(f"• *Take profit 2:* close the rest at *{px(idea['target'])}* (+{cfg['target_r']:g}R)")
    else:
        lines.append(f"• *Exit:* when a *{red}* 1-hour Heikin Ashi candle closes")
    lines.append(f"• *Cancelled if:* a {red} candle closes, or {cfg['entry_expiry_bars']} hours pass, "
                 f"before price reaches {px(s['entry'])}")
    lines += ["", "*Why it qualifies*",
              f":white_check_mark: Daily trend is {'up' if d == 1 else 'down'}",
              f":white_check_mark: {s['checks']['h4'][1]}",
              f":white_check_mark: {s['checks']['h4_cloud'][1]}",
              f":white_check_mark: Candle {s['since']} of the new colour, body {s['body_ratio']:.1f}x the previous one"]
    if s["broken"] is not None:
        lines.append(f":white_check_mark: Broke {'above' if d == 1 else 'below'} the daily level {px(s['broken'])}")
    if s["next"] is not None:
        lines.append(f":white_check_mark: Room to the next daily level {px(s['next'])} ({s['room']:.0f} pts away)")
    info = []
    for n in ("session", "adx", "atr_band", "stop_width", "news"):
        if n in s["checks"]:
            ok, txt = s["checks"][n]
            if n == "stop_width" and ok:
                continue
            mark = ":white_check_mark:" if ok else ":warning:"
            info.append(f"{mark} {txt}")
    if info:
        lines += ["", "*Context*"] + info
    lines += ["", f"_{cfg['track_record']}. Prices from Twelve Data: compare with your MT5 chart. "
                  "Rule-based alert, not financial advice._"]
    return "\n".join(lines)


def fmt_ib_event(e, cfg, sizing):
    t, ib = e["type"], e["idea"]
    if t == "ib_signal":
        risk = ib["hi"] - ib["lo"]
        lines = [
            f":package: *INSIDE-DAY SETUP: Gold (XAUUSD)* | daily candle closed {uk_day(e['t'])} UK",
            f"_Today's range ({px(ib['lo'])} to {px(ib['hi'])}) stayed inside yesterday's "
            f"({px(ib['prev_lo'])} to {px(ib['prev_hi'])}). This second strategy trades the breakout during the "
            "next daily candle. It runs separately from the trend setups._",
            "",
            "*The plan* (two orders, one cancels the other)",
            f"• *Buy-stop:* *{px(ib['hi'])}*, stop *{px(ib['lo'])}*",
            f"• *Sell-stop:* *{px(ib['lo'])}*, stop *{px(ib['hi'])}*",
            f"• *Risk:* {risk:.2f} per side = 1R",
        ]
        half = dict(sizing, risk_pct=sizing["risk_pct"] * cfg.get("inside_day_risk_mult", 1.0)) if sizing else None
        ls = lot_size(risk, half, cfg)
        if ls:
            lots, amt = ls
            sym = ccy_sym(sizing["ccy"])
            lines.append(f"• *Size:* {lots:.2f} lots risks about {sym}{amt:,.0f} ({half['risk_pct']:g}% of account, "
                         "smaller than the trend setups)"
                         if lots >= 0.01 else
                         f"• *Size:* range too wide for {half['risk_pct']:g}% risk at the 0.01 lot minimum")
        lines += [
            "• *No take-profit:* close the trade at the next daily close (17:00 New York) whatever happens",
            "• *Cancelled if:* neither side trades before that close",
            "",
            f"_{cfg['inside_day_track_record']}. Rule-based alert, not financial advice._",
        ]
        return "\n".join(lines)
    if t == "ib_cancel":
        return (f":heavy_minus_sign: *Inside-day setup cancelled: Gold*. Price stayed between {px(ib['lo'])} and "
                f"{px(ib['hi'])} for the whole day. Delete both orders. No trade.")
    sw = side_word(ib["dir"])
    if t == "ib_entry":
        other = "sell" if ib["dir"] == 1 else "buy"
        return (f":dart: *Inside-day entry: Gold {sw}* at {px(ib['entry'])} (candle closing {uk_hm(e['t'])} UK). "
                f"Delete the {other}-stop. Stop {px(ib['stop'])}; close at the daily close (17:00 New York).")
    if t == "ib_stop":
        return f":octagonal_sign: *Inside-day stopped out: Gold {sw}* at {px(e['price'])}. Result *{e['r']:+.2f}R* after costs."
    if t == "ib_close":
        return (f":checkered_flag: *Inside-day trade: close the Gold {sw} now* (daily close, {px(e['price'])}). "
                f"Result from entry {px(ib['entry'])}: *{e['r']:+.2f}R* after costs.")
    return None


def fmt_h4_event(e, cfg, sizing):
    """Messages for the 4-hour trigger strategy.

    Only the setup needs its own wording: h4_setup returns the levels, not the
    context checks that fmt_signal reads, so routing h4_signal there would
    raise. The entry, partial, target, stop and cancel messages reuse the trend
    wording, which touches only the idea's own fields.
    """
    t = e["type"]
    tag = ":clock4: _4-hour trigger: a separate strategy from the hourly setups._\n"
    if t != "h4_signal":
        msg = fmt_event(dict(e, type=t[3:]), cfg, sizing)
        return None if msg is None else tag + msg
    idea = e["idea"]
    d = idea["dir"]
    risk = idea["risk"]
    lots = lot_size(risk, sizing, cfg) if sizing else None
    size = (f"\n• *Size:* {lots[0]:.2f} lots ({ccy_sym(sizing['ccy'])}{lots[1]:,.0f} at risk)"
            if lots else "")
    icon = ":large_green_circle:" if d == 1 else ":red_circle:"
    pct = int(cfg["h4_partial_frac"] * 100)
    return (tag + f"{icon} *{side_word(d)} SETUP: Gold (4-hour trigger)*\n"
            f"• *Entry:* {'buy' if d == 1 else 'sell'}-stop at *{px(idea['entry'])}*\n"
            f"• *Stop:* *{px(idea['stop'])}* ({risk:.2f} = 1R)" + size + "\n"
            f"• *Take profit 1:* close {pct}% at *{px(idea['partial'])}* "
            f"(+{cfg['h4_partial_r']:g}R), stop to entry\n"
            f"• *Take profit 2:* *{px(idea['target'])}* (+{cfg['h4_target_r']:g}R)\n"
            f"• *Cancelled if:* price hasn't reached the entry within "
            f"{cfg['h4_expiry_bars']} hours\n"
            "_Research round 9: 526 trades 2008-2026, +0.14R per trade after costs. "
            "Rule-based alert, not financial advice._")


def fmt_event(e, cfg, sizing):
    t = e["type"]
    if t.startswith("ib_"):
        return fmt_ib_event(e, cfg, sizing)
    if t.startswith("h4_"):
        return fmt_h4_event(e, cfg, sizing)
    if t == "signal":
        return fmt_signal(e, cfg, sizing)
    idea = e["idea"]
    d = idea["dir"]
    sw = side_word(d)
    red = "red" if d == 1 else "green"
    if t == "entry":
        if cfg["exit_mode"] == "targets":
            plan = (f"Stop {px(idea['stop'])} | take profit 1 {px(idea['partial'])} | "
                    f"take profit 2 {px(idea['target'])}")
        else:
            plan = f"Stop {px(idea['stop'])}. Exit on the first *{red}* 1-hour Heikin Ashi close."
        return f":dart: *Entry triggered: Gold {sw}* at {px(idea['entry'])} (candle closing {uk_hm(e['t'])} UK).\n{plan}"
    if t == "partial":
        pct = int(cfg["partial_frac"] * 100)
        return (f":moneybag: *Take profit 1 hit: Gold {sw}* at {px(idea['partial'])}. Close {pct}% (+{cfg['partial_r']:g}R "
                f"on that part) and move the stop to entry {px(idea['entry'])}. The rest is now risk-free and targets "
                f"{px(idea['target'])}.")
    if t == "target":
        return (f":trophy: *Take profit 2 hit: Gold {sw}* at {px(e['price'])}. Trade closed: *{e['r']:+.2f}R* "
                "after costs.")
    if t == "stop":
        if idea.get("done"):
            return (f":shield: *Gold {sw} closed at entry* {px(e['price'])} after take profit 1. "
                    f"Trade result *{e['r']:+.2f}R* after costs.")
        return (f":octagonal_sign: *Stopped out: Gold {sw}* at {px(e['price'])}. "
                f"Result *{e['r']:+.2f}R* after costs.")
    if t == "exit":
        pts = (e["price"] - idea["entry"]) * d
        return (f":checkered_flag: *Exit signal: close the Gold {sw}*. A {red} 1-hour Heikin Ashi candle closed at "
                f"{px(e['price'])} ({uk_hm(e['t'])} UK).\n"
                f"Result from entry {px(idea['entry'])}: *{pts:+.2f} pts ({e['r']:+.2f}R)*")
    if t == "cancel":
        why = (f"the candles turned {red}" if e.get("why") == "flip"
               else f"{cfg['entry_expiry_bars']} hours passed")
        return (f":heavy_minus_sign: *Setup cancelled: Gold {sw}*. {why[0].upper() + why[1:]} before price reached "
                f"{px(idea['entry'])}. No trade.")
    if t == "breakeven":
        return f":shield: *Gold {sw} is +{cfg['breakeven_at_r']:g}R*: strategy moves the stop to entry {px(idea['entry'])}."
    if t == "hold":
        col = "green" if d == 1 else "red"
        wick = "lower" if d == 1 else "upper"
        return (f":calendar: *Hold overnight: Gold {sw}*. Today's daily candle closed {col} with no {wick} wick, "
                "which the strategy reads as strength.")
    return None


# --------------------------------------------------------------------------
# Journal + scorecard
# --------------------------------------------------------------------------
def journal_add(journal, e):
    idea = e["idea"]
    journal.append({
        "sig_time": idea["sig_time"], "entry_time": idea.get("entry_time"),
        "exit_time": e["t"].isoformat(), "dir": idea["dir"], "grade": idea.get("grade"),
        "entry": idea["entry"], "exit": round(e["price"], 2), "r": round(e["r"], 3),
        "how": e["type"], "strategy": idea.get("strategy", "trend"),
    })


def stats(rs):
    n = len(rs)
    if not n:
        return {"n": 0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    eq = peak = dd = 0.0
    streak = worst = 0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        streak = streak + 1 if r <= 0 else 0
        worst = max(worst, streak)
    gl = -sum(losses)
    return {"n": n, "win": 100.0 * len(wins) / n, "avg": sum(rs) / n, "total": sum(rs),
            "pf": (sum(wins) / gl) if gl > 0 else float("inf"), "dd": dd, "streak": worst,
            "avg_win": sum(wins) / len(wins) if wins else 0.0,
            "avg_loss": sum(losses) / len(losses) if losses else 0.0}


def scorecard(journal, now, nursery=None):
    week = [j for j in journal if datetime.fromisoformat(j["exit_time"]) >= now - timedelta(days=7)]
    if not week:
        return None
    w = stats([j["r"] for j in week])
    a = stats([j["r"] for j in journal])
    best = max(week, key=lambda j: j["r"])
    worst = min(week, key=lambda j: j["r"])
    by = []
    strategies = (nursery or {}).get("strategies", {})
    for key in sorted(strategies):
        d = strategies[key]
        js = [j for j in journal if j.get("strategy", "trend") == key]
        if not js:
            continue
        s = stats([j["r"] for j in js])
        wk = [j["r"] for j in week if j.get("strategy", "trend") == key]
        bench = f"{d.get('expected_win', 0):.0f}% winners, {d.get('expected_avg_r', 0):+.2f}R"
        tier = d.get("tier", "live")
        by.append(f"• {d.get('label', key)}{'' if tier == 'live' else f' [{tier}]'}: this week "
                  f"{len(wk)} trade{'s' if len(wk) != 1 else ''}, {sum(wk):+.1f}R | "
                  f"all time {s['n']} trades, {s['win']:.0f}% winners, avg {s['avg']:+.2f}R "
                  f"_(backtest: {bench})_")
    return (":bar_chart: *Gold signals: weekly scorecard*\n"
            f"This week: *{w['n']} trade{'s' if w['n'] != 1 else ''}*, {w['win']:.0f}% winners, "
            f"total *{w['total']:+.1f}R* (avg {w['avg']:+.2f}R per trade)\n"
            f"Best {best['r']:+.2f}R ({side_word(best['dir'])}) | worst {worst['r']:+.2f}R ({side_word(worst['dir'])})\n"
            f"All time: {a['n']} trades, {a['win']:.0f}% winners, {a['total']:+.1f}R, "
            f"biggest drop {a['dd']:.1f}R\n"
            + "\n".join(by) + ("\n" if by else "")
            + "_Backtest benchmarks are 2008-2026 after costs. R = multiples of the risk on each trade; "
            "results assume every signal was taken at the alert levels._")


# --------------------------------------------------------------------------
# Nursery and gate
#
# A strategy sits in one of three tiers:
#   candidate  tracked silently - journalled and in the ledger, no alerts
#   shadow     alerted, marked as paper, with no position size
#   live       alerted and sized
#
# The gate judges each strategy on its own live trades once a week. It applies
# demotions by itself, because they cut risk, and only ever *proposes*
# promotions, because they add it: raising real size stays a human decision.
# --------------------------------------------------------------------------
TIERS = ("candidate", "shadow", "live")


def default_nursery(cfg):
    return {
        "hypotheses_tested": cfg["hypotheses_tested"],
        "strategies": {
            "trend": {
                "tier": "live", "label": "Trend setups",
                "expected_avg_r": 0.18, "expected_win": 60, "expected_n": 720,
                "note": "Rounds 1-4: Heikin Ashi trend-ride, 4H agreement + Ichimoku cloud",
                "history": [],
            },
            "h4_trend": {
                "tier": "candidate", "label": "4-hour trigger",
                "expected_avg_r": 0.143, "expected_win": 0, "expected_n": 526,
                "note": "Round 9 E2: the trigger on the 4-hour candle. Candidate: "
                        "journalled and in the ledger, never alerted. +0.395 "
                        "correlated with the trend setup, so promotion needs live "
                        "evidence, not the backtest.",
                "history": [],
            },
            "inside_day": {
                "tier": "live", "label": "Inside-day setups",
                "expected_avg_r": 0.10, "expected_win": 49, "expected_n": 722,
                "note": "Round 5: inside-day breakout at half risk",
                "history": [],
            },
        },
    }


def load_nursery(cfg):
    """The registry, falling back to the defaults so a missing or partial file
    cannot change what the bot trades."""
    base = default_nursery(cfg)
    n = load_json(cfg["nursery_file"], None)
    if not isinstance(n, dict) or not isinstance(n.get("strategies"), dict):
        return base
    n.setdefault("hypotheses_tested", base["hypotheses_tested"])
    for name, d in base["strategies"].items():
        cur = n["strategies"].setdefault(name, d)
        for k, v in d.items():
            cur.setdefault(k, v)
        if cur.get("tier") not in TIERS:
            cur["tier"] = d["tier"]
    return n


def tier_of(nursery, strategy):
    s = nursery["strategies"].get(strategy or "trend")
    t = (s or {}).get("tier", "live")
    return t if t in TIERS else "live"


def bootstrap_p(rs, b=2000, seed=7):
    """One-sided bootstrap estimate of P(true average R <= 0), by resampling
    the trades. None when there are too few to say anything."""
    import random
    if len(rs) < 5:
        return None
    rnd, n, hits = random.Random(seed), len(rs), 0
    for _ in range(b):
        if sum(rnd.choice(rs) for _ in range(n)) / n <= 0:
            hits += 1
    return hits / b


def gate(nursery, journal, cfg, now):
    """Judge every strategy on its live trades. Mutates the registry for
    demotions only; returns the Slack message."""
    lines = []
    tested = max(1, int(nursery.get("hypotheses_tested", 1)))
    alpha_search = cfg["gate_alpha"] / tested
    for name, s in sorted(nursery["strategies"].items()):
        tier = tier_of(nursery, name)
        label = s.get("label", name)
        exp = s.get("expected_avg_r")
        rs = [j["r"] for j in journal if j.get("strategy", "trend") == name]
        if not rs:
            lines.append(f"• *{label}* ({tier}): no closed live trades yet; tested {exp:+.2f}R.")
            continue
        a = stats(rs)
        trail = rs[-cfg["gate_trailing"]:]
        t = stats(trail)
        floor = (exp or 0.0) * cfg["gate_tolerance"]
        head = (f"• *{label}* ({tier}): {a['n']} live trade{'s' if a['n'] != 1 else ''}, "
                f"avg {a['avg']:+.2f}R | last {t['n']} avg {t['avg']:+.2f}R | tested {exp:+.2f}R")
        if tier == "live":
            if t["n"] >= cfg["gate_demote_min_trades"] and t["avg"] < floor:
                s["tier"] = "shadow"
                s.setdefault("history", []).append({
                    "when": now.isoformat(), "from": "live", "to": "shadow",
                    "why": f"last {t['n']} trades avg {t['avg']:+.3f}R, below {floor:+.3f}R"})
                lines.append(head + f"\n   :arrow_down: *Demoted to shadow.* The last {t['n']} trades average "
                             f"{t['avg']:+.2f}R, under half the {exp:+.2f}R it was promoted on. Alerts carry on, "
                             "marked paper and without a size, until it earns its way back.")
            else:
                lines.append(head + " — holding.")
            continue
        p = bootstrap_p(trail, cfg["gate_bootstrap"])
        enough = a["n"] >= cfg["gate_promote_min_trades"]
        if enough and a["avg"] > 0 and a["avg"] >= floor and p is not None and p < cfg["gate_alpha"]:
            nxt = "live" if tier == "shadow" else "shadow"
            lines.append(head + f"\n   :arrow_up: *Ready to promote to {nxt}* (bootstrap p={p:.3f} < "
                         f"{cfg['gate_alpha']}). This one is yours to make: set \"tier\": \"{nxt}\" for "
                         f"`{name}` in `{cfg['nursery_file']}`.")
        else:
            if not enough:
                why = f"{cfg['gate_promote_min_trades'] - a['n']} more closed trades needed"
            elif a["avg"] <= 0:
                why = "live average is not positive"
            elif a["avg"] < floor:
                why = f"live average is under half the tested {exp:+.2f}R"
            else:
                why = f"bootstrap p={p:.3f}, not under {cfg['gate_alpha']}" if p is not None else "too few trades to test"
            lines.append(head + f" — not yet: {why}.")
    return (":seedling: *Nursery gate*\n" + "\n".join(lines)
            + f"\n_Promotion is judged on live trades only, with a one-sided bootstrap at p<{cfg['gate_alpha']}: "
              "the rule was fixed before that data existed, so there is no multiple-testing penalty to pay. "
              f"Choosing a rule out of the {tested:,} recorded backtest searches is the part that does need the "
              f"correction, at p<{alpha_search:.6f} — which is why a candidate has to earn live evidence here "
              "instead of arriving on a backtest alone. Demotions apply themselves; promotions never do._")


# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------
BASELINE = "Current rules"


def simulate(F, cfg):
    st, trades, cancels = {}, [], 0
    start = next((i for i in range(len(F.h1)) if F.warm(i)), None)
    if start is None:
        raise RuntimeError("Not enough history to backtest")
    for i in range(start, len(F.h1)):
        for e in step(F, i, st, cfg):
            if e["type"] in ("exit", "stop", "target"):
                idea = e["idea"]
                trades.append({"t": datetime.fromisoformat(idea["sig_time"]), "dir": idea["dir"],
                               "grade": idea["grade"], "session": idea["session"], "r": e["r"],
                               "hours": (e["t"] - datetime.fromisoformat(idea["entry_time"])).total_seconds() / 3600})
            elif e["type"] == "cancel":
                cancels += 1
    return trades, cancels, F.close_time(start)


def simulate_ib(F, cfg):
    """Replay the inside-day setup with the live code (ib_step)."""
    st, trades = {}, []
    start = next((i for i in range(len(F.h1)) if F.warm(i)), None)
    if start is None:
        return trades
    for i in range(start, len(F.h1)):
        for e in ib_step(F, i, st, dict(cfg, inside_day=True)):
            if e["type"] in ("ib_stop", "ib_close"):
                trades.append({"t": datetime.fromisoformat(e["idea"]["sig_time"]), "dir": e["idea"]["dir"],
                               "r": e["r"], "how": e["type"]})
    return trades


def variants(cfg):
    def v(**kw):
        c = json.loads(json.dumps(cfg, default=str))
        c["breakeven_at_r"] = cfg["breakeven_at_r"]
        for k, val in kw.items():
            if k == "filters":
                c["filters"].update(val)
            else:
                c[k] = val
        return c
    return [
        (BASELINE, v()),
        ("Video's original rules", v(filters={"h4": False}, require_breakout=True, exit_mode="ha")),
        ("Without the 4H Ichimoku cloud check", v(filters={"h4_cloud": False})),
        ("+ London/NY hours only", v(filters={"session": True})),
        ("+ ADX trend strength", v(filters={"adx": True})),
        ("+ normal volatility", v(filters={"atr_band": True})),
        ("Exit: single target at +1R", v(partial_r=None, target_r=1.0)),
        ("Exit: video's opposite-colour exit", v(exit_mode="ha")),
    ]


def fmt_stats_row(name, s_is, s_oos):
    def cell(s):
        if s["n"] == 0:
            return "0 | - | - | - | -"
        pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
        return f"{s['n']} | {s['win']:.0f}% | {s['avg']:+.2f} | {s['total']:+.1f} | {pf}"
    return f"| {name} | {cell(s_is)} | {cell(s_oos)} |"


def edge_note(s):
    """Plain-English verdict on whether the baseline has an edge."""
    if not s.get("n"):
        return "No trades."
    if s["n"] < 100:
        size = f"Only {s['n']} trades, so this is an early read, not proof."
    else:
        size = f"{s['n']} trades is a reasonable sample."
    if s["avg"] >= 0.2 and s["pf"] >= 1.5:
        verdict = "*Verdict:* a real edge so far."
    elif s["avg"] >= 0.05:
        verdict = "*Verdict:* a thin edge after costs. Trade it small or paper-trade it while live results build up."
    elif s["avg"] > -0.05:
        verdict = "*Verdict:* roughly break-even after costs. No proven edge yet."
    else:
        verdict = "*Verdict:* losing after costs. Don't trade it as is."
    return f"{verdict} {size}"


def backtest_report(F, cfg, h1, repo):
    first, last = h1[0]["t"], h1[-1]["t"] + H1
    rows, results = [], {}
    split = None
    for name, c in variants(cfg):
        trades, cancels, t0 = simulate(F, c)
        if split is None:
            split = t0 + (last - t0) * (1 - cfg["oos_fraction"])
        ins = [t["r"] for t in trades if t["t"] < split]
        oos = [t["r"] for t in trades if t["t"] >= split]
        results[name] = (trades, cancels, stats(ins), stats(oos), stats([t["r"] for t in trades]))
        rows.append(fmt_stats_row(name, results[name][2], results[name][3]))

    base_trades, base_cancels, b_is, b_oos, b_all = results[BASELINE]

    def breakdown(key, label_fn, trades):
        out = []
        for val in sorted({key(t) for t in trades}, key=str):
            s = stats([t["r"] for t in trades if key(t) == val])
            out.append(f"| {label_fn(val)} | {s['n']} | {s['win']:.0f}% | {s['avg']:+.2f} | {s['total']:+.1f} |")
        return out

    verdicts = []
    for name, (_, _, s_is, s_oos, _) in results.items():
        if name == BASELINE:
            continue
        if s_is["n"] == 0 or s_oos["n"] == 0:
            verdicts.append(f"- *{name}*: too few trades to judge.")
            continue
        gap = cfg["verdict_min_gain_r"]
        d_is = s_is["avg"] - b_is.get("avg", 0)
        d_oos = s_oos["avg"] - b_oos.get("avg", 0)
        nums = (f"({s_is['avg']:+.2f} / {s_oos['avg']:+.2f} vs {b_is.get('avg', 0):+.2f} / "
                f"{b_oos.get('avg', 0):+.2f}, {s_oos['n']} test trades)")
        if d_is >= gap and d_oos >= gap and s_oos["n"] >= cfg["verdict_min_trades"]:
            verdicts.append(f"- *{name}*: clearly better in both periods {nums}. Worth switching on.")
        elif d_is > 0 and d_oos > 0:
            verdicts.append(f"- *{name}*: slightly better in both periods {nums}, but too small or too few trades "
                            "to rule out luck. Keep watching.")
        elif d_is < 0 and d_oos < 0:
            verdicts.append(f"- *{name}*: worse in both periods {nums}. Leave it off.")
        else:
            verdicts.append(f"- *{name}*: mixed {nums}. No reliable edge.")

    md = [
        "# Backtest: gold Heikin Ashi trend-ride (4H-confirmed, take-profit exits)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC from {len(h1):,} H1 candles "
        f"({first:%d %b %Y} to {last:%d %b %Y}). Costs: ${cfg['cost_per_trade']:.2f} per trade.",
        f"Training period: before {split:%d %b %Y}. Test period (rules never tuned on it): from {split:%d %b %Y}.",
        "",
        "**How to read this.** R is the result in multiples of the risk on each trade: +2R means you made twice what you risked. "
        "Avg R above 0 after costs means the rules made money over the period. Profit factor (PF) is gross wins ÷ gross losses; above 1.3 is decent. "
        "A filter only counts as an improvement if it helps in **both** periods.",
        "",
        "## Results",
        "",
        "| Rules | Trades | Win | Avg R | Total R | PF | Trades | Win | Avg R | Total R | PF |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
        "| | **Earlier 70%** | | | | | **Latest 30%** | | | | |",
    ] + rows + [
        "",
        "## Verdicts",
        "",
    ] + [v.replace("*", "**") for v in verdicts] + [
        "",
        "## Baseline in detail (whole period)",
        "",
        f"- Trades: {b_all.get('n', 0)} (plus {base_cancels} setups cancelled before entry)",
        f"- {edge_note(b_all).replace('*', '**')}",
    ]
    if b_all.get("n"):
        md += [
            f"- Winners: {b_all['win']:.0f}%, average win {b_all['avg_win']:+.2f}R, average loss {b_all['avg_loss']:+.2f}R",
            f"- Total: {b_all['total']:+.1f}R, profit factor {b_all['pf']:.2f}",
            f"- Biggest drop from a peak: {b_all['dd']:.1f}R; longest losing run: {b_all['streak']} trades",
            f"- Average time in a trade: {sum(t['hours'] for t in base_trades) / len(base_trades):.1f} hours",
            "",
            "| Year | Trades | Win | Avg R | Total R |", "|---|---|---|---|---|",
        ] + breakdown(lambda t: t["t"].year, lambda v: str(v), base_trades) + [
            "",
            "Grade is how many of the four context checks passed when the setup appeared "
            "(A = all four, B = two or three, C = fewer). None of them is a filter, so this "
            "table says whether the grade is worth anything.",
            "",
            "| Grade | Trades | Win | Avg R | Total R |", "|---|---|---|---|---|",
        ] + breakdown(lambda t: t["grade"], lambda v: str(v), base_trades) + [
            "",
            "| Direction | Trades | Win | Avg R | Total R |", "|---|---|---|---|---|",
        ] + breakdown(lambda t: t["dir"], lambda v: "Buy" if v == 1 else "Sell", base_trades) + [
            "",
            "| Session | Trades | Win | Avg R | Total R |", "|---|---|---|---|---|",
        ] + breakdown(lambda t: t["session"], lambda v: "London / NY" if v else "Asia / late", base_trades)

    ib_trades = simulate_ib(F, cfg)
    ib_all = stats([t["r"] for t in ib_trades])
    if ib_all.get("n"):
        ib_is = stats([t["r"] for t in ib_trades if t["t"] < split])
        ib_oos = stats([t["r"] for t in ib_trades if t["t"] >= split])
        md += [
            "",
            "## Second setup: inside-day breakout (runs separately)",
            "",
            "After a daily candle that sits inside the previous day's range: buy-stop at its high, sell-stop at its low, "
            "stop at the other side, close at the next daily close. Research round 5.",
            "",
            "| Period | Trades | Win | Avg R | Total R | PF |", "|---|---|---|---|---|---|",
            f"| Earlier 70% | {ib_is.get('n', 0)} | {ib_is.get('win', 0):.0f}% | {ib_is.get('avg', 0):+.2f} | "
            f"{ib_is.get('total', 0):+.1f} | {ib_is.get('pf', 0):.2f} |",
            f"| Latest 30% | {ib_oos.get('n', 0)} | {ib_oos.get('win', 0):.0f}% | {ib_oos.get('avg', 0):+.2f} | "
            f"{ib_oos.get('total', 0):+.1f} | {ib_oos.get('pf', 0):.2f} |",
            f"| Whole period | {ib_all['n']} | {ib_all['win']:.0f}% | {ib_all['avg']:+.2f} | {ib_all['total']:+.1f} | "
            f"{ib_all['pf']:.2f} |",
            "",
            f"- {edge_note(ib_all).replace('*', '**')}",
            f"- Biggest drop from a peak: {ib_all['dd']:.1f}R; longest losing run: {ib_all['streak']} trades",
            "",
            "| Year | Trades | Win | Avg R | Total R |", "|---|---|---|---|---|",
        ] + breakdown(lambda t: t["t"].year, lambda v: str(v), ib_trades)
    md += [
        "",
        "## Caveats",
        "- Backtest prices from Dukascopy (10-year file) or Twelve Data; live alerts use Twelve Data. OANDA can differ slightly.",
        "- Entries assume the stop order fills exactly at its level; if a candle hits both entry and stop, the stop is assumed.",
        "- No news blackout in the backtest (no historical calendar).",
        "- Past results do not guarantee future results. Not financial advice.",
        "",
    ]
    report = "\n".join(md)

    link = f"https://github.com/{repo}/blob/main/backtest.md" if repo else "backtest.md"
    if b_all.get("n"):
        slack = (":test_tube: *Backtest finished: gold Heikin Ashi strategy*\n"
                 f"{first:%b %Y} to {last:%b %Y}, costs included.\n"
                 f"*Current rules:* {b_all['n']} trades, {b_all['win']:.0f}% winners, avg *{b_all['avg']:+.2f}R* per trade, "
                 f"total {b_all['total']:+.1f}R, biggest drop {b_all['dd']:.1f}R.\n"
                 f"Test period only: {b_oos.get('n', 0)} trades, avg {b_oos.get('avg', 0):+.2f}R.\n"
                 f"{edge_note(b_all)}\n"
                 + "\n".join(verdicts)
                 + (f"\n*Inside-day setup (separate):* {ib_all['n']} trades, {ib_all['win']:.0f}% winners, "
                    f"avg *{ib_all['avg']:+.2f}R*, total {ib_all['total']:+.1f}R." if ib_all.get("n") else "")
                 + f"\nFull report: {link}")
    else:
        slack = f":test_tube: Backtest finished but the baseline produced no trades. Report: {link}"
    return report, slack


# --------------------------------------------------------------------------
# Live run
# --------------------------------------------------------------------------
def status_message(F, st, cfg, now):
    i = len(F.h1) - 1
    last = F.h1[i]
    dc = F.daily_ctx(i)
    col = "green" if bull(F.ha[i]) else ("red" if bear(F.ha[i]) else "flat")
    trend = {1: "up", -1: "down", 0: "unclear"}[dc["trend"]] if dc else "unknown"
    lv = ", ".join(px(L) for L in (dc["levels"] if dc else [])) or "none"
    a = F.adx[i]
    hk = F.h4_idx[i]
    h4c = "green" if hk >= 0 and bull(F.h4_ha[hk]) else "red"
    pct = F.atr_pct[i]
    idea = st.get("idea")
    if idea:
        idea_txt = (f"{side_word(idea['dir'])} | entry {px(idea['entry'])} | stop {px(idea['stop'])} | "
                    f"{'in the trade' if idea['triggered'] else 'waiting for entry'}")
    else:
        idea_txt = "none"
    ib = st.get("ib")
    if ib:
        ib_txt = (f"{side_word(ib['dir'])} from {px(ib['entry'])}, stop {px(ib['stop'])}" if ib["triggered"]
                  else f"orders at {px(ib['hi'])} / {px(ib['lo'])}, waiting")
    else:
        ib_txt = "none"
    cloud = {1: "above", -1: "below", 0: "inside"}[F.h4_cloud[hk]] if hk >= 0 else "unknown"
    return (":satellite_antenna: *Gold signals: status check*\n"
            f"Last 1H candle: closed {uk_day(last['t'] + H1)} UK at {px(last['c'])}, Heikin Ashi {col}\n"
            f"Daily trend: *{trend}* | 4-hour candles: {h4c}, price {cloud} the cloud | ADX {a:.0f} | "
            f"volatility rank {pct:.0f}%\n"
            f"Daily levels: {lv}\n"
            f"Active trend setup: {idea_txt}\n"
            f"Active inside-day setup: {ib_txt}\n"
            "Data and Slack are working.")


def run_live(state, journal, h1_raw, now, cfg, sizing=None, news_fn=None, nursery=None):
    out = []
    if nursery is None:
        nursery = load_nursery(cfg)
    h1 = closed_h1(h1_raw, now)
    if len(h1) < 500:
        raise RuntimeError(f"Only {len(h1)} closed H1 candles returned")
    F = Features(h1, cfg)
    last_t = h1[-1]["t"].isoformat()
    last_k = F.d_idx[-1]

    if "last_h1" not in state:
        state["last_h1"] = last_t
        state["last_daily_k_end"] = F.daily[last_k]["end"].isoformat() if last_k >= 0 else None
        return out

    if last_k >= 0 and state.get("last_daily_k_end") != F.daily[last_k]["end"].isoformat():
        e = daily_hold(F, last_k, state.get("idea"), cfg)
        if e:
            out.append(fmt_event(e, cfg, sizing))
        state["last_daily_k_end"] = F.daily[last_k]["end"].isoformat()

    new_idx = [i for i, b in enumerate(h1) if b["t"].isoformat() > state["last_h1"]]
    news = None
    led, closed_trades = [], []
    for i in new_idx[-cfg["max_catchup_bars"]:]:
        if not F.warm(i):
            continue
        # fetch news lazily, only when a setup is possible on this bar
        if news is None and news_fn and any(evaluate(F, i, d, dict(cfg, filters={}), None) for d in (1, -1)):
            news = news_fn() or []
        before = state_label(state)
        evs = (step(F, i, state, cfg, news) + ib_step(F, i, state, cfg)
               + h4_step(F, i, state, cfg))
        led.append(ledger_row(F, i, cfg, evs, before, "live"))
        for e in evs:
            if e["type"] in ("exit", "stop", "target", "ib_stop", "ib_close",
                             "h4_stop", "h4_target"):
                journal_add(journal, e)
                closed_trades.append(journal[-1])
            tier = tier_of(nursery, (e.get("idea") or {}).get("strategy", "trend"))
            if tier == "candidate":
                continue   # tracked in the journal and the ledger, never alerted
            if e["type"] in ("entry", "ib_entry", "h4_entry") and not cfg["alert_entry_hit"]:
                continue
            # shadow tier gets no size: it is being watched, not traded
            msg = fmt_event(e, cfg, sizing if tier == "live" else None)
            if msg and tier == "shadow":
                msg = (":microscope: _Shadow (paper): this strategy is being tracked for evidence, "
                       "not traded. No size given._\n" + msg)
            if msg:
                lag_h = (now - e["t"]).total_seconds() / 3600
                if lag_h > cfg["late_alert_hours"]:
                    msg = (f":hourglass: _Late alert ({lag_h:.0f}h): this happened at {uk_day(e['t'])} UK. "
                           "The bot's scheduled run was delayed. Check the current price before acting._\n" + msg)
                # the mention goes first, so Slack pushes it and a reader sees why
                if cfg.get("slack_mention"):
                    msg = cfg["slack_mention"] + " " + msg
                out.append(msg)
    skipped = len(new_idx) - cfg["max_catchup_bars"]
    if skipped > 0:
        out.append(f":warning: The bot didn't run for {len(new_idx)} hours, so the oldest {skipped} hour"
                   f"{'s were' if skipped != 1 else ' was'} not checked for setups.")
    if cfg.get("ledger"):
        # the ledger must never stop an alert going out
        try:
            ledger_append(cfg["ledger_csv"], led)
            outcomes_append(cfg["outcomes_csv"], closed_trades)
        except (OSError, ValueError) as e:  # noqa: BLE001
            print(f"ledger write failed: {e}", file=sys.stderr)
    state["last_h1"] = last_t
    return out


# --------------------------------------------------------------------------
# IO
# --------------------------------------------------------------------------
def post_slack(url, text):
    if not url:
        print("[no SLACK_WEBHOOK_URL] " + text)
        return
    body = json.dumps({"text": text, "link_names": 1}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        if r.status != 200:
            raise RuntimeError(f"Slack returned HTTP {r.status}")


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")


def sizing_from_env(api_key):
    acct = os.environ.get("ACCOUNT_SIZE", "").replace(",", "").strip()
    if not acct:
        return None
    try:
        account = float(acct)
    except ValueError:
        return None
    ccy = (os.environ.get("ACCOUNT_CCY", "") or "USD").strip().upper()

    risk = float(os.environ.get("RISK_PCT", "") or CONFIG["default_risk_pct"])
    # brokers differ: 100 oz a lot is standard, but micro and cent accounts are
    # not. A wrong contract size silently misstates every lot size we post.
    oz = os.environ.get("CONTRACT_OZ", "").strip()
    if oz:
        try:
            if float(oz) > 0:
                CONFIG["contract_oz"] = float(oz)
        except ValueError:
            print(f"CONTRACT_OZ not a number: {oz!r}, using {CONFIG['contract_oz']}", file=sys.stderr)
    try:
        rate = fetch_usd_rate(api_key, ccy)
    except Exception as e:  # noqa: BLE001
        print(f"FX rate unavailable: {e}", file=sys.stderr)
        return None
    return {"account": account, "ccy": ccy, "risk_pct": risk, "usd_rate": rate}


def main():
    api_key = os.environ.get("TWELVEDATA_API_KEY", "")
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    mode = (os.environ.get("MODE", "run") or "run").strip()
    state_path = os.environ.get("STATE_FILE", "state.json")
    journal_path = os.environ.get("JOURNAL_FILE", "journal.json")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "SLACK_MENTION" in os.environ:          # "" switches mentions off
        CONFIG["slack_mention"] = os.environ["SLACK_MENTION"].strip()
    state = load_json(state_path, {})
    journal = load_json(journal_path, [])
    now = datetime.now(UTC)
    msgs = []

    try:
        if mode == "scorecard":
            nursery = load_nursery(CONFIG)
            m = scorecard(journal, now, nursery)
            msgs = [m] if m else []
            msgs.append(gate(nursery, journal, CONFIG, now))
            save_json(CONFIG["nursery_file"], nursery)
        elif mode == "gate":
            nursery = load_nursery(CONFIG)
            msgs = [gate(nursery, journal, CONFIG, now)]
            save_json(CONFIG["nursery_file"], nursery)
        elif mode == "backfill":
            h1 = closed_h1(load_history(CONFIG), now)
            out_path = CONFIG["ledger_backfill_csv"]
            n, jr = ledger_backfill(CONFIG, h1, out_path)
            msgs = [f":books: *Feature ledger backfilled.* {n:,} hours of features written to `{out_path}` "
                    f"from {len(h1):,} candles, with {len(jr):,} closed trades.\n"
                    "Rows are marked `source=backfill`: they are reconstructed from the history file, "
                    "not what the bot saw live. The hourly run appends live rows to "
                    f"`{CONFIG['ledger_csv']}` from now on."]
        else:
            if not api_key:
                raise RuntimeError("TWELVEDATA_API_KEY secret is missing")
            if mode == "backtest":
                if os.path.exists(CONFIG["history_csv"]):
                    h1 = closed_h1(load_history(CONFIG), now)
                else:
                    h1 = closed_h1(fetch_h1_history(api_key, CONFIG["symbol"], CONFIG["backtest_pages"]), now)
                F = Features(h1, CONFIG)
                report, slack = backtest_report(F, CONFIG, h1, repo)
                with open("backtest.md", "w") as f:
                    f.write(report)
                msgs = [slack]
            else:
                h1_raw = fetch_h1(api_key, CONFIG["symbol"], CONFIG["h1_bars"])
                if mode == "test":
                    h1 = closed_h1(h1_raw, now)
                    m = status_message(Features(h1, CONFIG), state, CONFIG, now)
                    if CONFIG.get("slack_mention"):
                        m = CONFIG["slack_mention"] + " " + m
                    msgs = [m]
                else:
                    sizing = sizing_from_env(api_key) if os.environ.get("ACCOUNT_SIZE") else None
                    msgs = run_live(state, journal, h1_raw, now, CONFIG, sizing, fetch_news,
                                    load_nursery(CONFIG))
        state["fail_count"] = 0
    except Exception as e:  # noqa: BLE001 - report every failure the same way
        print(f"ERROR: {e}", file=sys.stderr)
        state["fail_count"] = state.get("fail_count", 0) + 1
        if mode != "run" or state["fail_count"] == CONFIG["fail_alert_after"]:
            msgs = [f":warning: Gold signals bot failed ({mode}, {state['fail_count']} in a row): {e}"]
        else:
            msgs = []
        save_json(state_path, state)
        for m in msgs:
            try:
                post_slack(webhook, m)
            except Exception as se:  # noqa: BLE001
                print(f"Slack post failed: {se}", file=sys.stderr)
        sys.exit(1)

    for m in msgs:
        print(m + "\n")
        post_slack(webhook, m)
    save_json(state_path, state)
    save_json(journal_path, journal)


if __name__ == "__main__":
    main()
