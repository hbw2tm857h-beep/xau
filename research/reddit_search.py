"""Search Reddit for strategy ideas through the official API (OAuth, script app).

Credentials come only from environment variables and are never written anywhere:
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD

Raw results go to research/reddit_raw/ (git-ignored). The catalogue built from them
is written by hand, after reading the threads, to research/reddit_catalogue.md.

    python3 research/reddit_search.py            # run every query
    python3 research/reddit_search.py --limit 50 # results per query (max 100)
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "script:xau-strategy-research:v1.0 (read-only research of public posts)"
SUBREDDITS = ["algotrading", "Forex", "Daytrading", "quant", "BitcoinMarkets"]
QUERIES = [
    "gold strategy backtest",
    "XAUUSD strategy",
    "gold breakout",
    "bitcoin strategy backtest",
    "BTC trend following",
    "nasdaq strategy backtest",
    "NQ strategy",
    "QQQ strategy",
    "opening range breakout",
    "mean reversion backtest",
    "win rate profit factor backtest",
    "sharpe backtest results",
]
OUT = Path(__file__).resolve().parent / "reddit_raw"
MIN_INTERVAL = 1.1   # seconds between calls; the API allows about 100 a minute


def token():
    try:
        cid, secret = os.environ["REDDIT_CLIENT_ID"], os.environ["REDDIT_CLIENT_SECRET"]
        user, pw = os.environ["REDDIT_USERNAME"], os.environ["REDDIT_PASSWORD"]
    except KeyError as e:
        sys.exit(f"Missing environment variable {e.args[0]}")
    body = urllib.parse.urlencode({"grant_type": "password", "username": user, "password": pw}).encode()
    req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", data=body, method="POST")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode())
    req.add_header("User-Agent", USER_AGENT)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if "access_token" not in data:
        # Print the error code only; the response never contains the secret.
        sys.exit(f"Token request failed: {data.get('error', 'unknown error')}")
    return data["access_token"]


_last = 0.0


def get(tok, path, params):
    global _last
    wait = MIN_INTERVAL - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    url = "https://oauth.reddit.com" + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("Authorization", "bearer " + tok)
    req.add_header("User-Agent", USER_AGENT)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                _last = time.time()
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--comments", type=int, default=8, help="top comments kept per thread")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    tok = token()

    posts = {}
    for sub in SUBREDDITS:
        for q in QUERIES:
            res = get(tok, f"/r/{sub}/search", {"q": q, "restrict_sr": 1, "sort": "relevance",
                                                "t": "all", "limit": min(args.limit, 100), "raw_json": 1})
            for child in res["data"]["children"]:
                d = child["data"]
                p = posts.setdefault(d["id"], {
                    "id": d["id"], "subreddit": d["subreddit"], "title": d["title"],
                    "url": "https://www.reddit.com" + d["permalink"], "score": d["score"],
                    "num_comments": d["num_comments"], "created_utc": d["created_utc"],
                    "selftext": d.get("selftext", ""), "queries": [],
                })
                p["queries"].append(q)
        print(f"r/{sub}: {len(posts)} unique posts so far", file=sys.stderr)

    # Top comments for threads with a body worth reading, where authors often post rules or results.
    for p in posts.values():
        if p["num_comments"] == 0 or len(p["selftext"]) < 200:
            continue
        res = get(tok, f"/comments/{p['id']}", {"limit": args.comments, "depth": 1, "sort": "top", "raw_json": 1})
        p["comments"] = [c["data"].get("body", "") for c in res[1]["data"]["children"] if c["kind"] == "t1"][:args.comments]

    path = OUT / "posts.json"
    path.write_text(json.dumps(sorted(posts.values(), key=lambda p: -p["score"]), indent=1))
    print(f"{len(posts)} posts written to {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
