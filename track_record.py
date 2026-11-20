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

GO_LIVE = "2026-11-14"
MESSAGE_ID = "1573401910520586334"     # the post in #track-record, created by its webhook
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


def main():
    journal = json.load(open(os.environ.get("JOURNAL_FILE", "journal.json")))
    nursery = json.load(open(os.environ.get("NURSERY_FILE", "nursery.json")))
    rs = rows(journal, nursery)
    n = MAX_ROWS
    text = render(rs, n)
    while len(text) > 1990 and n > 1:     # Discord's limit is 2,000 characters
        n -= 1
        text = render(rs, n)
    if "--dry-run" in sys.argv:
        print(text)
        return
    hook = os.environ.get("DISCORD_WEBHOOK_TRACK", "").strip()
    if not hook:
        print("DISCORD_WEBHOOK_TRACK is not set; nothing posted.")
        return
    url = f"{hook}/messages/{MESSAGE_ID}"
    current = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20))["content"]
    if current == text:
        print("Track record already up to date.")
        return
    body = json.dumps({"content": text, "allowed_mentions": {"parse": []}}).encode()
    urllib.request.urlopen(urllib.request.Request(url, data=body, headers=UA, method="PATCH"), timeout=20)
    print("Track record updated.")


if __name__ == "__main__":
    main()
