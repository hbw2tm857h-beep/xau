#!/usr/bin/env python3
"""
XAU Heikin Ashi trend-ride signals -> Slack.

ALERT-ONLY. Never places trades. Runs on GitHub Actions a few minutes after
each H1 candle closes, checks the strategy checklist and posts to Slack.

Strategy (from "How to Trade Gold - Ride Massive Trends", The Moving Average):
  1. Daily chart = direction + support/resistance taken from daily closes.
  2. H1 Heikin Ashi = entries. Long: first bullish HA candle after the colour
     change with NO lower wick and a bigger body than the previous candle.
     Short: the mirror (bearish, no upper wick).
  3. Price must have broken a daily level and not be boxed in mid-range.
  4. Stop-order idea just beyond the signal candle.
  5. Exit only when an opposite-colour HA candle closes.
  6. Optional: trail the stop after swings; a no-wick daily candle in your
     direction supports holding overnight.
Additions to make it automatable (all editable in CONFIG): the initial stop
(recent swing + ATR buffer), "daily trend" = daily HA colour + close vs 50 EMA,
and automatic daily levels from pivot closes.

Standard library only. Environment:
  TWELVEDATA_API_KEY   Twelve Data key (free plan is enough)
  SLACK_WEBHOOK_URL    Slack Incoming Webhook for #gold-signals
  MODE                 "run" (default) or "test" (posts a status message)
  STATE_FILE           default state.json
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# --------------------------------------------------------------------------
# CONFIG - edit these on GitHub to tune the strategy
# --------------------------------------------------------------------------
CONFIG = {
    "symbol": "XAU/USD",
    "h1_bars": 5000,              # one API call; ~200 trading days of H1

    # Daily direction
    "daily_trend_mode": "ha_and_ema",   # "ha", "ha_and_ema" or "off"
    "daily_ema": 50,

    # Daily support/resistance from pivot closes (line-chart style)
    "sr_lookback_days": 180,
    "sr_pivot_strength": 3,
    "sr_merge_atr": 0.5,
    "sr_max_levels": 12,

    # Entry checklist
    "require_breakout": True,
    "breakout_bars": 24,
    "require_room": True,
    "min_room_atr": 0.5,          # x daily ATR to the next opposing level
    "first_no_wick_only": True,
    "max_bars_since_flip": 12,
    "min_body_growth": 1.0,
    "wick_tolerance": 0.0,        # $ allowed as "no wick"

    # Levels in the alert
    "entry_buffer": 0.30,         # $ beyond the signal candle
    "stop_swing_bars": 5,
    "stop_buffer_atr": 0.2,       # x H1 ATR
    "atr_period": 14,

    # Trade management alerts
    "alert_entry_hit": True,
    "alert_exit": True,
    "alert_stop_hit": True,
    "alert_trail": False,
    "alert_daily_hold": True,

    # Post a warning to Slack after this many failed runs in a row
    "fail_alert_after": 3,
    # Process at most this many missed H1 candles in one run
    "max_catchup_bars": 6,
}

NY = ZoneInfo("America/New_York")
UK = ZoneInfo("Europe/London")
UTC = timezone.utc
EPS = 1e-9


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def fetch_h1(api_key, symbol, n):
    """Return list of dicts (oldest first) with t (UTC datetime), o, h, l, c."""
    q = urllib.parse.urlencode({
        "symbol": symbol, "interval": "1h", "outputsize": n,
        "timezone": "UTC", "order": "ASC", "apikey": api_key,
    })
    req = urllib.request.Request("https://api.twelvedata.com/time_series?" + q,
                                 headers={"User-Agent": "xau-signals"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    if data.get("status") != "ok":
        raise RuntimeError(f"Twelve Data error: {data.get('code')} {data.get('message')}")
    bars = []
    for v in data["values"]:
        t = datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        bars.append({"t": t, "o": float(v["open"]), "h": float(v["high"]),
                     "l": float(v["low"]), "c": float(v["close"])})
    bars.sort(key=lambda b: b["t"])
    return bars


def closed_h1(bars, now):
    """Drop the still-forming candle."""
    return [b for b in bars if b["t"] + timedelta(hours=1) <= now]


def trading_day(t):
    """Trading day key: days roll at 17:00 New York (OANDA's daily close)."""
    return (t.astimezone(NY) + timedelta(hours=7)).date()


def daily_from_h1(h1, now):
    """Aggregate closed H1 bars into NY-close daily candles; drop today's."""
    days = {}
    order = []
    for b in h1:
        k = trading_day(b["t"])
        if k not in days:
            days[k] = {"t": k, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]}
            order.append(k)
        else:
            d = days[k]
            d["h"] = max(d["h"], b["h"])
            d["l"] = min(d["l"], b["l"])
            d["c"] = b["c"]
    current = trading_day(now)
    return [days[k] for k in order if k < current]


# --------------------------------------------------------------------------
# Indicators
# --------------------------------------------------------------------------
def heikin_ashi(bars):
    ha = []
    for i, b in enumerate(bars):
        c = (b["o"] + b["h"] + b["l"] + b["c"]) / 4.0
        o = (b["o"] + b["c"]) / 2.0 if i == 0 else (ha[-1]["o"] + ha[-1]["c"]) / 2.0
        ha.append({"o": o, "c": c, "h": max(b["h"], o, c), "l": min(b["l"], o, c)})
    return ha


def ema(values, period):
    if len(values) < period:
        return [None] * len(values)
    out = [None] * (period - 1)
    e = sum(values[:period]) / period
    out.append(e)
    k = 2.0 / (period + 1)
    for v in values[period:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def atr(bars, period):
    if len(bars) <= period:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period


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
        return 0, "filter off"
    ha = heikin_ashi(daily)
    last = ha[-1]
    ha_dir = 1 if bull(last) else (-1 if bear(last) else 0)
    if mode == "ha":
        how = "daily HA colour"
        t = ha_dir
    else:
        e = ema([d["c"] for d in daily], cfg["daily_ema"])[-1]
        how = f"daily HA colour + close vs {cfg['daily_ema']} EMA"
        c = daily[-1]["c"]
        if e is None:
            t = 0
        elif ha_dir == 1 and c > e:
            t = 1
        elif ha_dir == -1 and c < e:
            t = -1
        else:
            t = 0
    word = {1: "up", -1: "down", 0: "unclear"}[t]
    return t, f"{word} ({how})"


def build_levels(daily, price, cfg):
    closes = [d["c"] for d in daily[-cfg["sr_lookback_days"]:]]
    k = cfg["sr_pivot_strength"]
    a = atr(daily, cfg["atr_period"])
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


def broken_level(levels, h1, idx, d, cfg):
    """A daily level H1 closed through recently (closed beyond it now)."""
    close1 = h1[idx]["c"]
    prev = [b["c"] for b in h1[max(0, idx - cfg["breakout_bars"]):idx]]
    if not prev:
        return None
    lo, hi = min(prev), max(prev)
    best = None
    for L in levels:
        if d == 1 and L < close1 and lo < L:
            best = L if best is None else max(best, L)
        if d == -1 and L > close1 and hi > L:
            best = L if best is None else min(best, L)
    return best


# --------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------
def check_signal(d, ha, h1, i, ctx, cfg):
    """Return checklist text if bar i passes the checklist for direction d."""
    tol = cfg["wick_tolerance"]
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
        if (d == 1 and bull(y) and no_lower_wick(y, tol)) or \
           (d == -1 and bear(y) and no_upper_wick(y, tol)):
            earlier = True
    if not flip or (cfg["first_no_wick_only"] and earlier):
        return None

    b1 = abs(x["c"] - x["o"])
    b2 = abs(ha[i - 1]["c"] - ha[i - 1]["o"])
    if b1 < b2 * cfg["min_body_growth"]:
        return None

    if cfg["daily_trend_mode"] != "off" and ctx["trend"] != d:
        return None

    close1 = h1[i]["c"]
    broken = broken_level(ctx["levels"], h1, i, d, cfg)
    if cfg["require_breakout"] and broken is None:
        return None

    nxt = nearest_above(ctx["levels"], close1) if d == 1 else nearest_below(ctx["levels"], close1)
    room = abs(nxt - close1) if nxt is not None else None
    if cfg["require_room"] and nxt is not None and ctx["datr"] and room < cfg["min_room_atr"] * ctx["datr"]:
        return None

    side = "bullish" if d == 1 else "bearish"
    ratio = b1 / b2 if b2 > 0 else 0
    lines = [
        f":white_check_mark: Daily direction {'up' if d == 1 else 'down'}",
        f":white_check_mark: First no-wick {side} H1 HA candle since the colour change "
        f"(candle {since} of the new colour)",
        f":white_check_mark: Body bigger than previous (x{ratio:.1f})",
    ]
    if broken is not None:
        lines.append(f":white_check_mark: Closed through daily level {broken:.2f}")
    if nxt is not None:
        lines.append(f":white_check_mark: Next daily {'resistance' if d == 1 else 'support'} "
                     f"{nxt:.2f} ({room:.2f} away)")
    else:
        lines.append(":white_check_mark: No daily level in the way")
    return "\n".join(lines)


def uk(t):
    return t.astimezone(UK).strftime("%a %H:%M")


def make_signal(d, h1, i, why, ctx, cfg):
    b = h1[i]
    swing = h1[max(0, i - cfg["stop_swing_bars"] + 1):i + 1]
    hatr = ctx["hatr"] or 0
    if d == 1:
        entry = b["h"] + cfg["entry_buffer"]
        stop = min(x["l"] for x in swing) - cfg["stop_buffer_atr"] * hatr
        nxt = nearest_above(ctx["levels"], entry)
    else:
        entry = b["l"] - cfg["entry_buffer"]
        stop = max(x["h"] for x in swing) + cfg["stop_buffer_atr"] * hatr
        nxt = nearest_below(ctx["levels"], entry)
    risk = abs(entry - stop)
    side = "LONG" if d == 1 else "SHORT"
    icon = ":large_green_circle:" if d == 1 else ":red_circle:"
    order = "Buy-stop above" if d == 1 else "Sell-stop below"
    exitc = "bearish" if d == 1 else "bullish"
    close_t = b["t"] + timedelta(hours=1)
    msg = [
        f"{icon} *XAUUSD {side} signal* | H1 Heikin Ashi | candle closed {uk(close_t)} UK",
        "*Checklist*", why,
        "*Levels*",
        f"{order} {entry:.2f} (signal candle {'high' if d == 1 else 'low'} + buffer)",
        f"Stop idea: {stop:.2f} (risk {risk:.2f})",
    ]
    if nxt is not None and risk > 0:
        msg.append(f"First daily level ahead: {nxt:.2f} ({abs(nxt - entry) / risk:.1f}R)")
    msg.append(f"Exit rule: first {exitc} H1 HA close. Ignore small pullbacks.")
    msg.append("_Rule-based alert from your strategy, on Twelve Data prices (OANDA can differ by a few points). "
               "Not financial advice. Check spread and news before acting._")
    idea = {"dir": d, "entry": round(entry, 2), "stop": round(stop, 2),
            "triggered": False, "sig_time": b["t"].isoformat()}
    return "\n".join(msg), idea


def process_bar(i, h1, ha, ctx, state, cfg, out):
    """Run trade management then signal checks for closed H1 bar i."""
    b, x = h1[i], ha[i]
    idea = state.get("idea")
    close_t = uk(b["t"] + timedelta(hours=1))

    # 1) price levels inside this candle
    if idea:
        d = idea["dir"]
        side = "long" if d == 1 else "short"
        if not idea["triggered"]:
            hit = b["h"] >= idea["entry"] if d == 1 else b["l"] <= idea["entry"]
            if hit:
                idea["triggered"] = True
                if cfg["alert_entry_hit"]:
                    out.append(f":dart: XAUUSD {side}: price reached the stop-order level "
                               f"{idea['entry']:.2f} (H1 candle to {close_t} UK). Stop idea {idea['stop']:.2f}.")
        if idea and idea["triggered"]:
            stopped = b["l"] <= idea["stop"] if d == 1 else b["h"] >= idea["stop"]
            if stopped:
                if cfg["alert_stop_hit"]:
                    out.append(f":octagonal_sign: XAUUSD {side}: price reached the stop idea "
                               f"{idea['stop']:.2f} (H1 candle to {close_t} UK).")
                state["idea"] = idea = None

    # 2) exit on opposite-colour HA close
    if idea:
        d = idea["dir"]
        side = "LONG" if d == 1 else "SHORT"
        if (d == 1 and bear(x)) or (d == -1 and bull(x)):
            col = "bearish" if d == 1 else "bullish"
            if idea["triggered"]:
                if cfg["alert_exit"]:
                    move = (b["c"] - idea["entry"]) * d
                    out.append(f":checkered_flag: *XAUUSD {side} - EXIT signal* | {close_t} UK\n"
                               f"First {col} H1 Heikin Ashi candle closed at {b['c']:.2f}.\n"
                               f"Move from entry level {idea['entry']:.2f}: {move:+.2f}\n"
                               f"_Strategy rule: exit when an opposite-colour HA candle closes._")
            else:
                out.append(f":heavy_minus_sign: XAUUSD {side.lower()} setup cancelled: the HA colour flipped "
                           f"before price reached {idea['entry']:.2f}.")
            state["idea"] = idea = None

    # 3) optional trail
    if idea and idea["triggered"] and cfg["alert_trail"] and i >= 4:
        s = h1[i - 2]
        nb = [h1[i - 4], h1[i - 3], h1[i - 1], h1[i]]
        hatr = ctx["hatr"] or 0
        if idea["dir"] == 1 and all(s["l"] < z["l"] for z in nb):
            ns = round(s["l"] - cfg["stop_buffer_atr"] * hatr, 2)
            if ns > idea["stop"]:
                idea["stop"] = ns
                out.append(f":arrow_up: XAUUSD long: new H1 swing low {s['l']:.2f}. Trailing stop idea: {ns:.2f}.")
        if idea["dir"] == -1 and all(s["h"] > z["h"] for z in nb):
            ns = round(s["h"] + cfg["stop_buffer_atr"] * hatr, 2)
            if ns < idea["stop"]:
                idea["stop"] = ns
                out.append(f":arrow_down: XAUUSD short: new H1 swing high {s['h']:.2f}. Trailing stop idea: {ns:.2f}.")

    # 4) new signals
    for d in (1, -1):
        if idea and idea["dir"] == d:
            continue
        why = check_signal(d, ha, h1, i, ctx, cfg)
        if why:
            text, new_idea = make_signal(d, h1, i, why, ctx, cfg)
            out.append(text)
            state["idea"] = idea = new_idea
            break


def daily_hold_note(daily, state, cfg):
    idea = state.get("idea")
    if not (cfg["alert_daily_hold"] and idea and idea["triggered"] and daily):
        return None
    x = heikin_ashi(daily)[-1]
    tol = cfg["wick_tolerance"]
    if idea["dir"] == 1 and bull(x) and no_lower_wick(x, tol):
        return (":calendar: XAUUSD long: the daily closed as a no-wick bullish Heikin Ashi candle. "
                "Strategy says this supports holding into the next day.")
    if idea["dir"] == -1 and bear(x) and no_upper_wick(x, tol):
        return (":calendar: XAUUSD short: the daily closed as a no-wick bearish Heikin Ashi candle. "
                "Strategy says this supports holding into the next day.")
    return None


# --------------------------------------------------------------------------
# Slack + state
# --------------------------------------------------------------------------
def post_slack(url, text):
    if not url:
        print("[no SLACK_WEBHOOK_URL] " + text)
        return
    body = json.dumps({"text": text}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        if r.status != 200:
            raise RuntimeError(f"Slack returned HTTP {r.status}")


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path, state):
    with open(path, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def build_context(h1, daily, cfg):
    price = h1[-1]["c"]
    trend, trend_text = daily_trend(daily, cfg)
    return {
        "trend": trend, "trend_text": trend_text,
        "levels": build_levels(daily, price, cfg),
        "datr": atr(daily, cfg["atr_period"]),
        "hatr": atr(h1, cfg["atr_period"]),
    }


def run(state, h1_raw, now, cfg, mode="run"):
    """Pure core: returns list of Slack messages; mutates state."""
    out = []
    h1 = closed_h1(h1_raw, now)
    if len(h1) < 200:
        raise RuntimeError(f"Only {len(h1)} closed H1 candles returned")
    daily = daily_from_h1(h1, now)
    ctx = build_context(h1, daily, cfg)
    ha = heikin_ashi(h1)

    if mode == "test":
        lv = ", ".join(f"{L:.2f}" for L in ctx["levels"]) or "none"
        idea = state.get("idea")
        idea_txt = "none" if not idea else (
            f"{'long' if idea['dir'] == 1 else 'short'} | entry {idea['entry']:.2f} | stop {idea['stop']:.2f} | "
            f"{'triggered' if idea['triggered'] else 'waiting for entry'}")
        last = h1[-1]
        col = "bullish" if bull(ha[-1]) else ("bearish" if bear(ha[-1]) else "doji")
        out.append(":satellite_antenna: *XAU signals test run*\n"
                   f"Last closed H1: {uk(last['t'] + timedelta(hours=1))} UK, close {last['c']:.2f}, HA {col}\n"
                   f"Daily direction: {ctx['trend_text']}\n"
                   f"Daily levels: {lv}\n"
                   f"Active idea: {idea_txt}\n"
                   "Data and Slack are working. Signals will post here automatically.")
        return out

    last_t = h1[-1]["t"].isoformat()
    if "last_h1" not in state:
        state["last_h1"] = last_t                    # first run: start fresh
        state["last_daily"] = daily[-1]["t"].isoformat() if daily else None
        return out

    # daily close since last run?
    if daily and state.get("last_daily") != daily[-1]["t"].isoformat():
        note = daily_hold_note(daily, state, cfg)
        if note:
            out.append(note)
        state["last_daily"] = daily[-1]["t"].isoformat()

    # process every new closed H1 candle (catch up if a run was missed)
    new_idx = [i for i, b in enumerate(h1) if b["t"].isoformat() > state["last_h1"]]
    for i in new_idx[-cfg["max_catchup_bars"]:]:
        process_bar(i, h1, ha, ctx, state, cfg, out)
    state["last_h1"] = last_t
    return out


def main():
    api_key = os.environ.get("TWELVEDATA_API_KEY", "")
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    mode = os.environ.get("MODE", "run") or "run"
    path = os.environ.get("STATE_FILE", "state.json")
    state = load_state(path)
    now = datetime.now(UTC)

    try:
        if not api_key:
            raise RuntimeError("TWELVEDATA_API_KEY secret is missing")
        h1 = fetch_h1(api_key, CONFIG["symbol"], CONFIG["h1_bars"])
        msgs = run(state, h1, now, CONFIG, mode)
        state["fail_count"] = 0
    except Exception as e:  # noqa: BLE001 - report every failure the same way
        print(f"ERROR: {e}", file=sys.stderr)
        state["fail_count"] = state.get("fail_count", 0) + 1
        msgs = []
        if mode == "test" or state["fail_count"] == CONFIG["fail_alert_after"]:
            msgs.append(f":warning: XAU signals bot has failed {state['fail_count']} run(s) in a row: {e}")
        save_state(path, state)
        for m in msgs:
            try:
                post_slack(webhook, m)
            except Exception as se:  # noqa: BLE001
                print(f"Slack post failed: {se}", file=sys.stderr)
        sys.exit(1)

    for m in msgs:
        print(m + "\n")
        post_slack(webhook, m)
    save_state(path, state)


if __name__ == "__main__":
    main()
