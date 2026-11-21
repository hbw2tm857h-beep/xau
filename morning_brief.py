"""Weekday morning brief for the #morning-brief Discord channel.

For each market the bot trades, before London opens: the price, the daily
trend as the rules see it, the 4-hour picture, the nearest daily levels, which
setups the rules can take today and what is already running. Then today's
high-impact US releases. Everything comes from the same rules and data as the
hourly alerts (signals.py), so the brief never says something the bot would
not act on. Standard library only.

    python3 morning_brief.py            # post it
    python3 morning_brief.py --dry-run  # print it instead
    python3 morning_brief.py --dry-run --local  # use the repo's history files, no API calls
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

import signals as S
import track_record as T

UTC = timezone.utc


def picture(name, h1, cfg, now):
    """The brief's lines for one market, from closed candles only."""
    bars = [b for b in h1 if b["t"] + S.H1 <= now] if cfg.get("all_hours") else S.closed_h1(h1, now)
    F = S.Features(bars, cfg)
    i = len(bars) - 1
    dc = F.daily_ctx(i)
    if dc is None or not F.warm(i):
        return f"**{name}**\nNot enough data this morning."
    price = bars[-1]["c"]
    k = F.d_idx[i]
    prev_close = F.daily[k]["c"] if k >= 0 else None
    change = f" ({(price / prev_close - 1) * 100:+.1f}% since the daily close)" if prev_close else ""
    trend = dc["trend"]
    ema = dc["ema"]
    trend_txt = {1: f"**up**: last daily Heikin Ashi candle green, price above the {cfg['daily_ema']}-day average",
                 -1: f"**down**: last daily Heikin Ashi candle red, price below the {cfg['daily_ema']}-day average",
                 0: "**no clear trend**: the daily candle and the "
                    f"{cfg['daily_ema']}-day average{f' ({S.px(ema)})' if ema else ''} disagree"}[trend]
    hk = F.h4_idx[i]
    h4c = F.h4_ha[hk] if hk >= 0 else None
    cl = F.h4_cloud[hk] if hk >= 0 else 0
    h4_txt = ("green" if h4c and S.bull(h4c) else "red" if h4c and S.bear(h4c) else "flat") + \
        f", price {'above' if cl == 1 else 'below' if cl == -1 else 'inside'} the Ichimoku cloud"
    lv = S.build_levels(F.daily[:k + 1], price, cfg) if k >= 0 else []
    above, below = S.nearest_above(lv, price), S.nearest_below(lv, price)
    levels = " · ".join(x for x in (f"resistance {S.px(above)}" if above else "",
                                    f"support {S.px(below)}" if below else "") if x) or "none close by"
    watch = []
    if cfg.get("trend", True):
        if trend == 0:
            watch.append("Trend setups: none today until the daily trend picks a side.")
        else:
            side, colour, wick = ("BUY", "green", "lower") if trend == 1 else ("SELL", "red", "upper")
            watch.append(f"Trend setups: **{side} only**. The trigger is a {colour} 1-hour Heikin Ashi candle "
                         f"with no {wick} wick, straight after a run of the opposite colour.")
    if cfg.get("inside_day", True) and k >= 1:
        weekend = cfg.get("ib_weekday_signals") and F.daily[k]["end"].astimezone(UTC).weekday() >= 5
        if S.is_inside_day(F.daily, k) and not weekend:
            d = F.daily[k]
            watch.append(f"Breakout setup: **yesterday was an inside day**. Orders go above {S.px(d['h'])} "
                         f"and below {S.px(d['l'])}.")
        else:
            watch.append("Breakout setup: none today (yesterday wasn't an inside day).")
    return "\n".join([f"**{name}** · {S.px(price)}{change}",
                      f"Daily trend {trend_txt}.",
                      f"4-hour: {h4_txt}.",
                      f"Daily levels: {levels}.",
                      *watch])


def brief(series, state, nursery, events, now):
    parts = [f"## Morning brief · {now.astimezone(S.UK):%A %-d %B}"]
    parts.append(picture("Gold", series["gold"], S.CONFIG, now))
    for key in S.CONFIG.get("markets", {}):
        cfg = S.market_cfg(key)
        if key in series:
            parts.append(picture(cfg["market_name"], series[key], cfg, now))
    running = T.open_rows(state, nursery)
    parts.append("**Running now**\n" + ("\n".join(r.split("\n")[0] for r in running) if running
                                       else "No open trades or orders."))
    if events:
        parts.append("**High-impact US news today (UK time)**\n" + "\n".join(events))
    else:
        parts.append("**High-impact US news today**\nNone scheduled.")
    return "\n\n".join(parts) + "\n\n-# Built from the same rules as the alerts. The bot posts every setup as it happens."


def todays_events(now):
    """Today's high-impact US releases as short lines, or [] if the feed fails."""
    try:
        import calendar_post as C
        today = now.astimezone(S.UK).date()
        return [f"{e['t'].astimezone(S.UK):%H:%M} {e['title']}" for e in C.events()
                if e["t"].astimezone(S.UK).date() == today]
    except Exception as e:  # noqa: BLE001
        print(f"Calendar feed unavailable: {e}", file=sys.stderr)
        return []


def main():
    now = datetime.now(UTC)
    local = "--local" in sys.argv
    if local:
        hist = S.load_history(S.CONFIG)
        now = hist[-1]["t"] + S.H1
        series = {"gold": hist}
    else:
        key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
        if not key:
            print("TWELVEDATA_API_KEY is not set; nothing posted.")
            return
        series = {"gold": S.fetch_h1(key, S.CONFIG["symbol"], S.CONFIG["h1_bars"])}
        for k in S.CONFIG.get("markets", {}):
            try:
                series[k] = S.fetch_h1(key, S.market_cfg(k)["symbol"], S.CONFIG["h1_bars"])
            except Exception as e:  # noqa: BLE001
                print(f"{k}: {e}", file=sys.stderr)
    state = json.load(open(os.environ.get("STATE_FILE", "state.json")))
    nursery = json.load(open(os.environ.get("NURSERY_FILE", "nursery.json")))
    text = brief(series, state, nursery, [] if local else todays_events(now), now)
    if "--dry-run" in sys.argv:
        print(text)
        print(f"\n({len(text)} characters)")
        return
    hook = os.environ.get("DISCORD_WEBHOOK_BRIEF", "").strip()
    if not hook:
        print("DISCORD_WEBHOOK_BRIEF is not set; nothing posted.")
        return
    body = json.dumps({"content": text[:2000], "username": "LumnFx", "allowed_mentions": {"parse": []}}).encode()
    urllib.request.urlopen(urllib.request.Request(hook, data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "LumnFx morning brief"}), timeout=20)
    print("Morning brief posted.")


if __name__ == "__main__":
    main()
