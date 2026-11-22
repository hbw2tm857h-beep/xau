"""Economic calendar for the #economic-calendar Discord channel.

Posts the week's high-impact US releases on Sunday evening, and a short
reminder on weekday mornings when something is due that day. Data comes from
Forex Factory's public weekly feed. Standard library only, like signals.py.

    python3 calendar_post.py week     # this week's releases
    python3 calendar_post.py today    # today's releases, if any (posts nothing otherwise)
    python3 calendar_post.py week --dry-run
    python3 calendar_post.py today --save   # also write calendar.json for the Discord bot's /calendar
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
POSTED = "calendar_posted.json"
UK = ZoneInfo("Europe/London")
FOOTER = ("-# High-impact US releases from Forex Factory. Times show in your own time zone. Gold, the US indices and crypto "
          "can move fast around these, and a pending order can fill on the spike. The bot doesn't pause "
          "for news.")


def events():
    req = urllib.request.Request(FEED, headers={"User-Agent": "LumnFx calendar (weekly)"})
    for attempt in range(3):                       # the feed rate-limits bursts of requests
        try:
            rows = json.loads(urllib.request.urlopen(req, timeout=30).read())
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise
            time.sleep(60)
    out = []
    for r in rows:
        if r.get("country") != "USD" or r.get("impact") != "High":
            continue
        t = datetime.fromisoformat(r["date"]).astimezone(UK)
        out.append((t, r["title"].strip(), (r.get("forecast") or "").strip(), (r.get("previous") or "").strip()))
    return sorted(out)


def ts(t, style):
    """A Discord timestamp: each reader sees it in their own time zone."""
    return f"<t:{int(t.timestamp())}:{style}>"


def line(t, title, forecast, previous):
    extra = ", ".join(x for x in (f"forecast {forecast}" if forecast else "",
                                  f"previous {previous}" if previous else "") if x)
    return title + (f" · {extra}" if extra else "")


def grouped(ev, style):
    """Releases at the same moment share one time heading."""
    at = {}
    for e in ev:
        at.setdefault(e[0], []).append(e)
    return [f"**{ts(t, style)}**\n" + "\n".join(line(*e) for e in es) for t, es in sorted(at.items())]


def week_post(ev, now):
    d = now.astimezone(UK).date()
    monday = d + timedelta(days=1) if d.weekday() == 6 else d - timedelta(days=d.weekday())
    if not ev:
        return f"## US news, week of {monday:%-d %B}\nNo high-impact US releases this week.\n\n{FOOTER}"
    return f"## US news, week of {monday:%-d %B}\n\n" + "\n\n".join(grouped(ev, "F")) + f"\n\n{FOOTER}"


def today_post(ev, now):
    today = [e for e in ev if e[0].date() == now.astimezone(UK).date()]
    if not today:
        return None
    blocks = [b.replace("**\n", f"** ({ts(t, 'R')})\n", 1) for b, t in zip(grouped(today, "t"), sorted({e[0] for e in today}))]
    return "## Today's US news\n\n" + "\n\n".join(blocks) + f"\n\n{FOOTER}"


def post(text):
    hook = os.environ["DISCORD_WEBHOOK_CALENDAR"]
    body = json.dumps({"content": text, "username": "LumnFx", "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(hook, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "LumnFx calendar"})
    urllib.request.urlopen(req, timeout=30)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "week"
    now = datetime.now(timezone.utc)
    ev = events()
    if "--save" in sys.argv:          # the bot reads this from the repo: the feed blocks Cloudflare
        with open("calendar.json", "w") as f:
            json.dump([{"t": t.isoformat(), "title": title, "forecast": fc, "previous": prev}
                       for t, title, fc, prev in ev], f, indent=1)
    text = week_post(ev, now) if mode == "week" else today_post(ev, now)
    if text is None:
        print("Nothing due today.")
        return
    if "--dry-run" in sys.argv:
        print(text)
        return
    # The metronome starts this on time and GitHub's schedule is the backup, so the
    # same post can be asked for twice; calendar_posted.json remembers what went out.
    d = now.astimezone(UK).date()
    key = (d + timedelta(days=1) if d.weekday() == 6 else d - timedelta(days=d.weekday())) if mode == "week" else d
    try:
        done = json.load(open(POSTED))
    except (OSError, ValueError):
        done = {}
    if done.get(mode) == key.isoformat():
        print(f"The {mode} calendar for {key} was already posted.")
        return
    post(text)
    done[mode] = key.isoformat()
    with open(POSTED, "w") as f:
        json.dump(done, f, indent=1)
    print(f"Posted the {mode} calendar ({len(ev)} releases this week).")


if __name__ == "__main__":
    main()
