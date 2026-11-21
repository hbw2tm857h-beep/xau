"""Friday-night recap for #announcements: the week's closed trades members
were alerted to, the total, and what is still open. Reuses track_record.py's
reading of journal.json, nursery.json and state.json. Standard library only.

    python3 weekly_recap.py            # post it
    python3 weekly_recap.py --dry-run  # print it instead
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

import track_record as T

UTC = timezone.utc


def recap(journal, nursery, state, now):
    since = (now - timedelta(days=7)).isoformat()
    week = [r for r in T.rows(journal, nursery) if r[0] >= since]
    start = (now - timedelta(days=now.weekday())).date()
    head = f"## Week in review · {start:%-d %b} to {now:%-d %b}"
    if week:
        total = sum(r[4] for r in week)
        wins = sum(r[4] > 0 for r in week)
        lines = [f"**{r:+.2f}R** · {m} {sd} {k} · {datetime.fromisoformat(t):%a %-d %b}"
                 for t, m, sd, k, r, h, o, c in week]
        body = (f"**{len(week)} trade{'s' if len(week) != 1 else ''} closed, {wins} winner{'s' if wins != 1 else ''}"
                f" · {total:+.2f}R**\nThat's {total:+.2f}% at 1% risk per trade.\n\n" + "\n".join(lines))
    else:
        body = "No trades closed this week."
    still = T.open_rows(state, nursery) if hasattr(T, "open_rows") else []
    tail = ("\n\n**Still open**\n" + "\n".join(x.split("\n")[0] for x in still)) if still else ""
    return f"{head}\n{body}{tail}\n\n-# Every trade is in #track-record."


def main():
    journal = json.load(open(os.environ.get("JOURNAL_FILE", "journal.json")))
    nursery = json.load(open(os.environ.get("NURSERY_FILE", "nursery.json")))
    state = json.load(open(os.environ.get("STATE_FILE", "state.json")))
    text = recap(journal, nursery, state, datetime.now(UTC))
    if "--dry-run" in sys.argv:
        print(text)
        return
    hook = os.environ.get("DISCORD_WEBHOOK_ANNOUNCEMENTS", "").strip()
    if not hook:
        print("DISCORD_WEBHOOK_ANNOUNCEMENTS is not set; nothing posted.")
        return
    body = json.dumps({"content": text, "username": "LumnFx", "allowed_mentions": {"parse": []}}).encode()
    urllib.request.urlopen(urllib.request.Request(hook, data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "LumnFx weekly recap"}), timeout=20)
    print("Weekly recap posted.")


if __name__ == "__main__":
    main()
