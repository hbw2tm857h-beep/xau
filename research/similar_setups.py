"""Build data/similar_setups.json: how past setups did, grouped the way the
alerts describe them, so each new-setup alert can say "setups like this won X%
of N times".

Every trade comes from the live code replaying the history files (signals.step,
signals.ib_step and signals.ibs_trades), so the table describes exactly what the
bot would have alerted. The groups were fixed before the table was built, and kept
coarse so each holds enough trades to mean something:

  trend, btc_trend   direction x grade (A/B/C, already in every alert)
  inside_day,        tight or wide inside day: its range over the average daily
  eth_inside_day     range of the previous 14 days, split at the median
  us_ibs             moderate dip (2.5-4 average ranges below the 10-day high)
                     or deep dip (4 or more)

Rounds 4-6 found the context checks behind the grade predict little, so most
groups should sit near their strategy's overall rate; the alert says so when
they do. Re-run after the history files are refreshed:

    python3 research/similar_setups.py
"""
import json
import os
import statistics as st
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import signals as S  # noqa: E402
import round10_btc_checks as B  # noqa: E402
import round12_beyond_gold as M  # noqa: E402

UTC = timezone.utc
CLOSE = ("exit", "stop", "target", "ib_stop", "ib_close")


def replay(cfg, bars, scale=False):
    """Closed trades from the live state machine, with the setup idea attached.

    scale: the extra markets' config holds dollar amounts (entry buffer, cost)
    set for today's price. Over a history where Bitcoin ran from $2,000 to
    $100,000 those would be wildly wrong early on, so with scale=True they are
    resized to each candle's price, as the round 10 and 16 research did."""
    F = S.Features(bars, cfg)
    st_, journal, ideas = {}, [], {}
    ref = bars[-1]["c"]
    for i in range(len(bars)):
        if not F.warm(i):
            continue
        c = cfg
        if scale:
            k = bars[i]["c"] / ref
            c = dict(cfg, entry_buffer=cfg["entry_buffer"] * k, cost_per_trade=cfg["cost_per_trade"] * k)
        for e in S.step(F, i, st_, c) + S.ib_step(F, i, st_, c):
            idea = e.get("idea") or {}
            if e["type"] in ("signal", "ib_signal"):
                ideas[(idea.get("strategy"), idea.get("sig_time"))] = dict(idea)
            if e["type"] in CLOSE:
                S.journal_add(journal, e)
                j = journal[-1]
                j["idea"] = ideas.get((j.get("strategy"), j.get("sig_time")), idea)
    return journal


def summarise(rows, unit="R"):
    rs = [r for r, _ in rows]
    d = 3 if unit == "R" else 1
    return {"n": len(rs), "win": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
            "avg": round(st.mean(rs), d), "sd": round(st.stdev(rs), d) if len(rs) > 1 else 0.0}


def table(label, trades, kind, unit="R", threshold=None):
    """trades: list of (result, group)."""
    groups = {}
    for r, g in trades:
        if g is not None:
            groups.setdefault(g, []).append((r, g))
    out = {"label": label, "kind": kind, "unit": unit, "all": summarise(trades, unit),
           "buckets": {}}
    for g, v in sorted(groups.items()):
        rest = [x for x in trades if x[1] != g]
        out["buckets"][g] = dict(summarise(v, unit), rest=summarise(rest, unit) if len(rest) > 1 else None)
    if threshold is not None:
        out["threshold"] = threshold
    return out


def range_groups(journal, strategy):
    xs = [j["idea"].get("range_atr") for j in journal if j.get("strategy") == strategy]
    xs = [x for x in xs if x is not None]
    thr = round(st.median(xs), 3)
    tr = [(j["r"], None if j["idea"].get("range_atr") is None else
           ("tight inside day" if j["idea"]["range_atr"] < thr else "wide inside day"))
          for j in journal if j.get("strategy") == strategy]
    return tr, thr


def main():
    now = datetime.now(UTC)
    out = {"built": now.strftime("%Y-%m-%d"), "strategies": {}}

    gold = S.closed_h1(S.load_history(S.CONFIG), now)
    jg = replay(S.CONFIG, gold)
    trend = [(j["r"], f"{S.side_word(j['dir'])}, grade {j['grade']}") for j in jg if j.get("strategy", "trend") == "trend"]
    out["strategies"]["trend"] = table("gold trend setups", trend, "dir_grade")
    ib, thr = range_groups(jg, "inside_day")
    out["strategies"]["inside_day"] = table("gold inside-day setups", ib, "range_atr", threshold=thr)

    btc_cfg = S.market_cfg("btc")
    jb = replay(btc_cfg, B.load_247(os.path.join(ROOT, "data", "markets", "btcusd_h1.csv.gz")), scale=True)
    bt = [(j["r"], f"{S.side_word(j['dir'])}, grade {j['grade']}") for j in jb if j.get("strategy") == "btc_trend"]
    out["strategies"]["btc_trend"] = table("Bitcoin trend setups", bt, "dir_grade")

    eth_cfg = S.market_cfg("eth")
    je = replay(eth_cfg, B.load_247(os.path.join(ROOT, "data", "markets", "ethusd_h1.csv.gz")), scale=True)
    ib, thr = range_groups(je, "eth_inside_day")
    out["strategies"]["eth_inside_day"] = table("Ether inside-day setups", ib, "range_atr", threshold=thr)

    M.R10.MARKETS["Russell 2000"] = (["markets/ussc2000idxusd_h1.csv.gz"], 2.0)
    M.SESSION["Russell 2000"] = (ZoneInfo("America/New_York"), 9, 15)
    ibs = []
    for name in ("S&P 500", "Nasdaq 100", "Dow", "Russell 2000"):
        s = M.sessions(name)
        days = [dict(s[d], t_close=s[d]["t"]) for d in sorted(s)]
        ibs += [(t["bps"], "deep dip" if t["depth"] >= 4 else "moderate dip")
                for t in S.ibs_trades(days, S.CONFIG["ibs"]["cost_bps"])]
    out["strategies"]["us_ibs"] = table("US index dips", ibs, "depth", unit="bp", threshold=4.0)

    path = os.path.join(ROOT, S.CONFIG["similar_file"])
    with open(path, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write("\n")
    for k, v in out["strategies"].items():
        a = v["all"]
        print(f"{k:15s} all n={a['n']:4d} win={a['win']:4.1f}% avg={a['avg']:+}")
        for g, b in v["buckets"].items():
            print(f"   {g:22s} n={b['n']:4d} win={b['win']:4.1f}% avg={b['avg']:+}")
    print("written", path)


if __name__ == "__main__":
    main()
