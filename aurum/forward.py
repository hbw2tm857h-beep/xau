"""Forward test: the only data no hypothesis has ever seen.

``freeze`` writes the current validated / weak / contaminated-holdout hypotheses to
store/frozen.json with a timestamp equal to the last decision bar in the data.
``score`` evaluates them ONLY on trades decided after that timestamp. Run it after
the data files are refreshed (the "Fetch gold history" workflow) and rebuild the
caches with ``python -m aurum run --rebuild``.
"""
from __future__ import annotations

import json
import time

import pandas as pd

from .config import STORE
from .hypothesis import mask, trade_r, describe
from .stats import summarise

FROZEN = STORE / "frozen.json"
FORWARD_LOG = STORE / "forward_scores.jsonl"


def freeze(discoveries: list[dict], data_end: str,
           statuses=("validated", "weak_holdout", "passed_validation")) -> list[dict]:
    old = json.loads(FROZEN.read_text()) if FROZEN.exists() else []
    have = {x["hyp_id"] for x in old}
    new = [{"hyp_id": d["hyp_id"], "spec": d["spec"], "definition": d["definition"], "status_at_freeze": d["status"],
            "frozen_at": data_end, "frozen_on": time.strftime("%Y-%m-%d")}
           for d in discoveries if d["status"] in statuses and d["hyp_id"] not in have]
    FROZEN.write_text(json.dumps(old + new, indent=1))
    return old + new


def score(t: pd.DataFrame, cf) -> list[dict]:
    if not FROZEN.exists():
        return []
    out = []
    for h in json.loads(FROZEN.read_text()):
        if any(c["f"] not in t for c in h["spec"].get("conditions", [])):
            out.append({**h, "forward": None, "note": "feature unavailable"}); continue
        m = mask(t, h["spec"]) & (t["tc"] > pd.Timestamp(h["frozen_at"]))
        r = trade_r(t, cf, h["spec"].get("exit", "base"))[m].dropna()
        s = summarise(r.values)
        if s["n"] < 30:
            verdict = f"accumulating ({s['n']}/30 trades)"
        elif s["avg_r"] > 0 and s["t"] >= 1.0:
            verdict = "forward_confirmed"
        elif s["avg_r"] < 0:
            verdict = "forward_failed"
        else:
            verdict = "forward_inconclusive"
        rec = {"hyp_id": h["hyp_id"], "definition": h["definition"], "frozen_at": h["frozen_at"],
               "status_at_freeze": h.get("status_at_freeze"), "forward": s, "verdict": verdict,
               "scored_on": time.strftime("%Y-%m-%d %H:%M")}
        out.append(rec)
        with open(FORWARD_LOG, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    return out
