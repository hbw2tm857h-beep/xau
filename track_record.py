"""Keep the #track-record post in Discord up to date.

Reads journal.json and nursery.json after each hourly run and edits the
track-record message in place, so every trade the server was alerted to
appears once it closes. Silent candidates (tracked without alerts) are left
out, because members never saw them. Standard library only.

    python3 track_record.py            # edit the post if anything changed
    python3 track_record.py --dry-run  # print the post instead
"""
import json
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

GO_LIVE = "2026-11-14"
MESSAGE_ID = "1573401910520586334"     # the post in #track-record, created by its webhook
OPEN_MESSAGE_ID = "1573559130092871782"   # the "Open now" post in the same channel, same webhook
ALERTED = ("live", "shadow")           # tiers whose trades are posted to members
MAX_ROWS = 20                          # keep the post under Discord's 2,000 characters
UA = {"User-Agent": "LumnFx track record", "Content-Type": "application/json"}

MARKET = {"trend": ("Gold", "trend"), "inside_day": ("Gold", "breakout"), "h4_trend": ("Gold", "4H trend"),
          "btc_trend": ("BTC/USD", "trend"), "eth_inside_day": ("ETH/USD", "breakout")}
IBS = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "DIA": "Dow", "IWM": "Russell 2000"}


def how(j):
    h, r = j.get("how"), j.get("r", 0)
    if h == "target":
        return "TP2 hit"
    if h in ("stop", "h4_stop"):
        return "TP1, then entry" if r > -0.5 else "stopped out"
    if h == "ib_stop":
        return "stopped out"
    if h == "ib_close":
        return "daily close"
    if h == "ibs_exit":
        return "exit signal"
    return "closed"


def price(x):
    return f"{x:,.2f}" if x is not None else "-"


def rows(journal, nursery):
    tiers = {k: (v.get("tier") if isinstance(v, dict) else v)
             for k, v in (nursery.get("strategies") or nursery).items()}
    out = []
    for j in journal:
        s = j.get("strategy", "trend")
        if tiers.get(s) not in ALERTED or (j.get("exit_time") or "") < GO_LIVE:
            continue
        if s == "us_ibs":
            market, kind = IBS.get(j.get("symbol"), j.get("symbol") or "US index"), "rebound"
        else:
            market, kind = MARKET.get(s, (s, ""))
        side = "BUY" if j.get("dir") == 1 else "SELL"
        out.append((j["exit_time"], market, side, kind, j["r"], how(j), price(j.get("entry")), price(j.get("exit"))))
    return sorted(out)


def render(rs, n=MAX_ROWS):
    head = f"## Live track record\nEvery trade closed since alerts went live on 14 November 2026.\n"
    if not rs:
        return head + "\nNo closed trades yet.\n\n-# Updated as trades close."
    lines = [f"**{r:+.2f}R** · {m} {sd} {k} · {datetime.fromisoformat(t):%-d %b}\n"
             f"-# Open {o} · Close {c} · {h}"
             for t, m, sd, k, r, h, o, c in reversed(rs[-n:])]
    total = sum(r[4] for r in rs)
    wins = sum(r[4] > 0 for r in rs)
    more = f"\n-# Showing the latest {n} of {len(rs)} trades." if len(rs) > n else ""
    return (head + "\n" + "\n".join(lines) + "\n\n"
            f"**{len(rs)} trade{'s' if len(rs) != 1 else ''}, {wins} winner{'s' if wins != 1 else ''} · {total:+.2f}R**\n"
            f"That's {total:+.2f}% at 1% risk per trade.\n{more}\n-# Updated as trades close.").replace("\n\n\n", "\n\n")


MARKET_NAMES = {"btc": "BTC/USD", "eth": "ETH/USD"}


def open_rows(state, nursery):
    """Positions and pending orders members were alerted to, from state.json."""
    tiers = {k: (v.get("tier") if isinstance(v, dict) else v)
             for k, v in (nursery.get("strategies") or nursery).items()}
    books = [("Gold", state)] + [(MARKET_NAMES.get(k, k), m) for k, m in (state.get("markets") or {}).items()]
    out = []
    for market, book in books:
        for key in ("idea", "ib"):
            p = (book or {}).get(key)
            if not p or tiers.get(p.get("strategy", "trend" if key == "idea" else "inside_day")) not in ALERTED:
                continue
            if key == "ib" and not p.get("triggered"):
                out.append(f"**{market} breakout** · orders waiting\n"
                           f"-# Buy-stop {price(p.get('hi'))} · Sell-stop {price(p.get('lo'))}")
                continue
            side = "BUY" if p.get("dir") == 1 else "SELL"
            if not p.get("triggered"):
                out.append(f"**{market} {side}** · order waiting at {price(p.get('entry'))}\n"
                           f"-# Stop loss {price(p.get('stop'))}")
                continue
            if key == "ib":
                out.append(f"**{market} {side}** · in from {price(p.get('entry'))}\n"
                           f"-# Stop loss {price(p.get('stop'))} · Exit at the daily close")
                continue
            stage = "TP1 hit, stop at entry" if p.get("done") else f"TP1 {price(p.get('partial'))}"
            out.append(f"**{market} {side}** · in from {price(p.get('entry'))}\n"
                       f"-# Stop loss {price(p.get('stop'))} · {stage} · TP2 {price(p.get('target'))}")
    return out


def last_check(state):
    """The footer line: when the hourly check last ran cleanly, in UK time."""
    lr = state.get("last_run") or {}
    if not lr.get("started") or lr.get("error") or lr.get("failed"):
        return "-# Updated every hour."
    t = datetime.fromisoformat(lr["started"]).astimezone(ZoneInfo("Europe/London"))
    return f"-# Markets checked every hour · last check {t:%-d %b %H:%M} UK"


def render_open(rows_, footer="-# Updated every hour."):
    body = "\n".join(rows_) if rows_ else "No open trades right now."
    return f"## Open now\nTrades and orders running at the moment.\n\n{body}\n\n{footer}"


def edit(hook, mid, text):
    url = f"{hook}/messages/{mid}"
    current = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20))["content"]
    if current == text:
        return False
    body = json.dumps({"content": text, "allowed_mentions": {"parse": []}}).encode()
    urllib.request.urlopen(urllib.request.Request(url, data=body, headers=UA, method="PATCH"), timeout=20)
    return True


def main():
    journal = json.load(open(os.environ.get("JOURNAL_FILE", "journal.json")))
    nursery = json.load(open(os.environ.get("NURSERY_FILE", "nursery.json")))
    rs = rows(journal, nursery)
    n = MAX_ROWS
    text = render(rs, n)
    while len(text) > 1990 and n > 1:     # Discord's limit is 2,000 characters
        n -= 1
        text = render(rs, n)
    state = json.load(open(os.environ.get("STATE_FILE", "state.json")))
    board = render_open(open_rows(state, nursery), last_check(state))
    if "--dry-run" in sys.argv:
        print(text + "\n\n" + board)
        return
    hook = os.environ.get("DISCORD_WEBHOOK_TRACK", "").strip()
    if not hook:
        print("DISCORD_WEBHOOK_TRACK is not set; nothing posted.")
        return
    print("Track record updated." if edit(hook, MESSAGE_ID, text) else "Track record already up to date.")
    if OPEN_MESSAGE_ID:
        print("Open trades updated." if edit(hook, OPEN_MESSAGE_ID, board) else "Open trades already up to date.")


if __name__ == "__main__":
    main()
