"""Collect Reddit posts for research/reddit_catalogue.md through Apify.

Uses the actor fatihtahta/reddit-scraper-search-fast (about $0.0015 per post).
This is a scraper, not Reddit's official API (see research/reddit_search.py for that);
it was used at Bradley's instruction on 19 Nov 2026.

    APIFY_TOKEN=... python3 research/reddit_apify.py research/reddit_raw/apify_posts.json

The token comes from the environment only. The free plan runs at most four of these
actors at once, so the subreddits are run four at a time.
"""
import json
import os
import sys
import time
import urllib.request

ACTOR = "fatihtahta~reddit-scraper-search-fast"
SUBS = ["algotrading", "Forex", "Daytrading", "quant", "BitcoinMarkets"]
SEARCHES = ["gold strategy backtest", "XAUUSD strategy", "bitcoin strategy backtest", "nasdaq strategy backtest",
            "NQ opening range breakout", "QQQ strategy", "profit factor win rate backtest", "sharpe ratio backtest results"]
MAX_CHARGE_USD = 0.30   # per run
PARALLEL = 4


def call(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET")
    req.add_header("Authorization", "Bearer " + os.environ["APIFY_TOKEN"])
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def start(sub):
    inp = {"subredditName": sub, "subredditKeywords": SEARCHES, "subredditSort": "relevance",
           "subredditTimeframe": "all", "maxPosts": 20, "scrapeComments": False, "includeNsfw": False}
    return call(f"https://api.apify.com/v2/acts/{ACTOR}/runs?maxTotalChargeUsd={MAX_CHARGE_USD}", inp)["data"]["id"]


def finish(run_id):
    while True:
        d = call(f"https://api.apify.com/v2/actor-runs/{run_id}")["data"]
        if d["status"] not in ("READY", "RUNNING"):
            break
        time.sleep(15)
    items = call(f"https://api.apify.com/v2/datasets/{d['defaultDatasetId']}/items?clean=1&format=json")
    print(f"{run_id} {d['status']} {len(items)} posts ${d.get('usageTotalUsd')}", file=sys.stderr)
    return items


def main():
    out = sys.argv[1]
    items = []
    for i in range(0, len(SUBS), PARALLEL):
        runs = [start(s) for s in SUBS[i:i + PARALLEL]]
        for r in runs:
            items += finish(r)
    with open(out, "w") as f:
        json.dump(items, f)
    print(f"{len(items)} posts written to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
