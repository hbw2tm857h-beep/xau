"""Monthly report card for #announcements: every alerted trade closed last
month, with the statistics traders judge a system by (win rate, average R,
profit factor, drawdown, losing streak), set against what the backtest
expected for the same trades. Reuses track_record.py's reading of
journal.json and nursery.json. Standard library only.

    python3 monthly_report.py                    # post last month's report
    python3 monthly_report.py --dry-run          # print it instead
    python3 monthly_report.py --dry-run 2026-11  # a given month
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

import track_record as T

UTC = timezone.utc


def stats(rs):
    """Summary of a list of R results, in the order they closed."""
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    peak = run = dd = 0.0
    streak = worst_streak = 0
    for r in rs:
        run += r
        peak = max(peak, run)
        dd = max(dd, peak - run)
        streak = streak + 1 if r < 0 else 0
        worst_streak = max(worst_streak, streak)
    return {"n": len(rs), "wins": len(wins), "total": sum(rs), "avg": sum(rs) / len(rs) if rs else 0.0,
            "pf": (sum(wins) / -sum(losses)) if losses else None, "dd": dd, "streak": worst_streak,
            "best": max(rs) if rs else 0.0, "worst": min(rs) if rs else 0.0}


def expected(nursery, keys):
    """The backtest's average R per trade for these trades' strategies (one entry per trade)."""
    strategies = nursery.get("strategies") or {}
    xs = [strategies.get(s, {}).get("expected_avg_r") for s in keys]
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def strategy_keys(journal, nursery, since, until):
    """Strategy name of each alerted trade that closed in the window, matching T.rows()."""
    tiers = {k: (v.get("tier") if isinstance(v, dict) else v)
             for k, v in (nursery.get("strategies") or nursery).items()}
    return [j.get("strategy", "trend") for j in journal
            if tiers.get(j.get("strategy", "trend")) in T.ALERTED
            and since <= (j.get("exit_time") or "") < until and (j.get("exit_time") or "") >= T.GO_LIVE]


def month_bounds(year, month):
    start = datetime(year, month, 1, tzinfo=UTC)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC)
    return start, end


def fmt(s):
    pf = "no losses" if s["pf"] is None else f"{s['pf']:.2f}"
    return (f"Trades **{s['n']}** · Winners **{s['wins']}** ({100 * s['wins'] / s['n']:.0f}%)\n"
            f"Total **{s['total']:+.2f}R** · Average **{s['avg']:+.2f}R** per trade · Profit factor **{pf}**\n"
            f"Best **{s['best']:+.2f}R** · Worst **{s['worst']:+.2f}R** · "
            f"Biggest drop from a peak **{s['dd']:.2f}R** · Longest losing run **{s['streak']}**")


def report(journal, nursery, year, month):
    start, end = month_bounds(year, month)
    all_rows = T.rows(journal, nursery)
    rows = [r for r in all_rows if start.isoformat() <= r[0] < end.isoformat()]
    head = f"## Report card · {start:%B %Y}"
    if not rows:
        return f"{head}\nNo alerted trades closed this month.\n\n-# Every trade is in #track-record."
    s = stats([r[4] for r in rows])
    exp = expected(nursery, strategy_keys(journal, nursery, start.isoformat(), end.isoformat()))
    exp_line = (f"\nThe backtest expects **{exp:+.2f}R** per trade from these setups; this month averaged "
                f"**{s['avg']:+.2f}R**.") if exp is not None else ""
    by_market = {}
    for r in rows:
        by_market.setdefault(r[1], []).append(r[4])
    markets = "\n".join(f"{m}: {len(v)} trade{'s' if len(v) != 1 else ''} · {sum(v):+.2f}R"
                        for m, v in sorted(by_market.items(), key=lambda kv: -sum(kv[1])))
    life = stats([r[4] for r in all_rows if r[0] < end.isoformat()])
    return (f"{head}\n{fmt(s)}\n{T.pct_line(rows)}{exp_line}\n\n"
            f"**By market**\n{markets}\n\n"
            f"**Since alerts went live on 14 November 2026**\n"
            f"{life['n']} trades · {life['wins']} winners · {life['total']:+.2f}R · "
            f"biggest drop {life['dd']:.2f}R\n\n-# Every trade, with entry and exit prices, is in #track-record.")


def main():
    journal = json.load(open(os.environ.get("JOURNAL_FILE", "journal.json")))
    nursery = json.load(open(os.environ.get("NURSERY_FILE", "nursery.json")))
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        year, month = map(int, args[0].split("-"))
    else:                                   # run on the 1st: report the month just ended
        now = datetime.now(UTC)
        year, month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    text = report(journal, nursery, year, month)
    if "--dry-run" in sys.argv:
        print(text)
        return
    hook = os.environ.get("DISCORD_WEBHOOK_ANNOUNCEMENTS", "").strip()
    if not hook:
        print("DISCORD_WEBHOOK_ANNOUNCEMENTS is not set; nothing posted.")
        return
    body = json.dumps({"content": text[:2000], "username": "LumnFx", "allowed_mentions": {"parse": []}}).encode()
    urllib.request.urlopen(urllib.request.Request(hook, data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "LumnFx monthly report"}), timeout=20)
    print("Monthly report posted.")


if __name__ == "__main__":
    main()
