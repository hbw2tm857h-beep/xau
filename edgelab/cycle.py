"""One autonomous research cycle. Designed to be run on a schedule, forever.

    python -m edgelab cycle --budget 300

1. pull new candles (Dukascopy) and rebuild caches if the data changed
2. run the pipeline: engine experiments (agenda first), reality check, forward scoring, dashboard
3. compare with the previous cycle and write what changed to RESEARCH_LOG.md and store/cycles.jsonl

Nothing is overwritten except the dashboard/results snapshot; the ledger, forward scores,
cycle log and research log only ever grow.
"""
from __future__ import annotations

import json
import time

from .config import STORE, ROOT, CACHE
from .stats import jsonable

STATE = STORE / "cycle_state.json"
CYCLES = STORE / "cycles.jsonl"
LOG = ROOT / "edgelab" / "RESEARCH_LOG.md"


def hours_since_last() -> float | None:
    if not CYCLES.exists():
        return None
    lines = [x for x in CYCLES.read_text().splitlines() if x.strip()]
    if not lines:
        return None
    from datetime import datetime
    last = datetime.strptime(json.loads(lines[-1])["ts"], "%Y-%m-%d %H:%M")
    return (datetime.utcnow() - last).total_seconds() / 3600


def _snapshot(R: dict) -> dict:
    return {
        "data_to": R["data"]["h1_to"], "trades": R["data"]["trades"],
        "n_trials": R["experiments"]["n_trials_total"], "n_hypotheses": R["experiments"]["n_hypotheses"],
        "status": {d["hyp_id"]: d["status"] for d in R.get("discoveries", [])},
        "defs": {d["hyp_id"]: d["definition"] for d in R.get("discoveries", [])},
        "rc_p": (R.get("reality_check") or {}).get("p_studentised"),
        "rc_best": (R.get("reality_check") or {}).get("best"),
        "rw": (R.get("reality_check") or {}).get("rw_survivors", []),
        "forward": {f["hyp_id"]: {"verdict": f.get("verdict"), "n": (f.get("forward") or {}).get("n"),
                                  "avg_r": (f.get("forward") or {}).get("avg_r"), "def": f["definition"]}
                    for f in R.get("forward", [])},
        "taxonomy": {t["id"]: t["verdict"] for t in R.get("taxonomy", [])},
    }


def _diff(prev: dict | None, cur: dict) -> list[str]:
    if not prev:
        return ["First recorded cycle."]
    out = []
    if cur["data_to"] != prev["data_to"]:
        out.append(f"Data extended from {prev['data_to'][:16]} to {cur['data_to'][:16]} "
                   f"({cur['trades'] - prev['trades']:+,} reconstructed trades).")
    out.append(f"{cur['n_hypotheses'] - prev['n_hypotheses']:+} hypotheses tested "
               f"(total {cur['n_hypotheses']:,}; trials counted {cur['n_trials']:,}).")
    for hid, st in cur["status"].items():
        old = prev["status"].get(hid)
        if old != st and st in ("validated", "weak_holdout", "passed_validation", "contradicted_holdout"):
            out.append(f"**{st}**: {cur['defs'][hid]}" + (f" (was {old})" if old else " (new)"))
    if cur["rc_p"] is not None:
        out.append(f"Reality Check (studentised) p = {cur['rc_p']:.3f}; best: {cur['rc_best']}; "
                   f"Romano-Wolf survivors: {len(cur['rw'])}.")
        if len(cur["rw"]) > len(prev.get("rw") or []):
            out.append("**A hypothesis now survives family-wise correction**: " + "; ".join(cur["rw"]))
    for hid, fw in cur["forward"].items():
        old = (prev.get("forward") or {}).get(hid, {})
        if fw["n"] and fw["n"] != old.get("n"):
            out.append(f"Forward: {fw['def']} -> n={fw['n']}, avg R {fw['avg_r'] if fw['avg_r'] is None else round(fw['avg_r'], 3)}, "
                       f"{fw['verdict']}")
    for k, v in cur["taxonomy"].items():
        if prev.get("taxonomy", {}).get(k) not in (None, v):
            out.append(f"Taxonomy {k}: verdict changed to '{v}'.")
    return out


def run_cycle(budget: int = 300, fetch: bool = True, user_trades: str | None = None) -> dict:
    t0 = time.time()
    upd = {"bars_added": 0}
    if fetch:
        from .updater import update
        try:
            upd = update()
        except Exception as e:  # network trouble must not stop the research
            upd = {"bars_added": 0, "error": str(e)}
            print(f"[update] failed: {e}")
    rebuild = upd.get("bars_added", 0) > 0
    if rebuild:
        for p in CACHE.glob("*.pkl"):
            p.unlink()
    from .pipeline import run
    R = run(budget=budget, rebuild=False, user_trades=user_trades)
    cur = _snapshot(R)
    prev = json.loads(STATE.read_text()) if STATE.exists() else None
    changes = _diff(prev, cur)
    entry = {"ts": time.strftime("%Y-%m-%d %H:%M", time.gmtime()), "update": upd, "budget": budget,
             "minutes": round((time.time() - t0) / 60, 1), "changes": changes,
             "next": [x["description"] for x in R["experiments"]["next"][:5]]}
    with open(CYCLES, "a") as fh:
        fh.write(json.dumps(jsonable(entry), default=str) + "\n")
    STATE.write_text(json.dumps(jsonable(cur), default=str))
    md = [f"## Cycle {entry['ts']} UTC", ""]
    md += [f"- {c}" for c in changes]
    md += ["", "Next in the queue:"] + [f"- {x}" for x in entry["next"]] + [""]
    old = LOG.read_text() if LOG.exists() else "# Edge Lab research log\n\nNewest first. Written automatically by `python -m edgelab cycle`.\n\n"
    head, _, rest = old.partition("\n\n## ")
    LOG.write_text(head + "\n\n" + "\n".join(md) + ("\n## " + rest if rest else ""))
    print("\n".join(md))
    return entry
