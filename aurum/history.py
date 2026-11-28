"""Builds aurum/HISTORY.json: the whole project explained, from its creation to now.

Static parts (why things were built, what went wrong and how it was handled) are written here
by hand. Everything numeric is read from the research record at build time (ledger, results,
cycle log, frozen hypotheses), so the file stays true as cycles run. Rebuilt at the end of every
cycle; run on demand with `python -m aurum history`.
"""
from __future__ import annotations

import ast
import json
import subprocess
import time
from pathlib import Path

from .config import ROOT, STORE, OUTPUT, SPLITS, DEFAULT
from .stats import jsonable

OUT = ROOT / "aurum" / "HISTORY.json"

PROJECT = {
    "name": "Aurum",
    "previous_name": "The Edge Lab (package 'edgelab'), renamed 2026-11-28 at the owner's request",
    "what_it_is": ("An autonomous research laboratory that reverse-engineers why discretionary XAUUSD (gold) trades "
                   "succeed or fail: it reconstructs trading decisions candle by candle, classifies mistakes, replays "
                   "every trade under alternative decisions, tests hypotheses with strict out-of-sample discipline, "
                   "and feeds what it learns back into the owner's live alert bot (signals.py)."),
    "what_it_is_not": "Not a trading bot. It never connects to a broker, never places orders, never gives trading advice.",
    "repository": "hbw2tm857h-beep/xau",
    "branch": "claude/edge-lab-trading-research-mz973e",
    "owner_brief": {
        "core_objective": ("Reverse-engineer the underlying principles of profitable discretionary trading by systematically "
                           "investigating bad trades, failed setups, execution mistakes, misleading price action and successful trades."),
        "phases_requested": [
            "1 Mistake taxonomy", "2 Historical chart reconstruction (no look-ahead)", "3 Counterfactual testing",
            "4 Success vs failure comparison of look-alike setups", "5 Edge discovery with 10-point reports",
            "6 Personal edge profiling (attempt to disprove the self-assessment)", "7 Autonomous experimentation",
            "8 Interactive research dashboard", "9 Validation (walk-forward, out-of-sample, costs, multiple testing)"],
        "later_requests": [
            "Push it further", "Make the process ongoing", "Open the dashboard",
            "Test every possible combination of mistakes and their remedy",
            "Make my bot understand the anatomy and essence of losing trades so it can better catch good trades",
            "Rename it and provide a JSON that explains everything"],
    },
}

TIMELINE = [
    {"date": "2026-11-27", "stage": "Round 1: build the laboratory",
     "built": [
         "Data layer on the repo's Dukascopy files: H1 2003-2026, M15 2008-2026, H4/D1 on the 17:00 New York close, FOMC/CPI/NFP windows, FRED macro lagged one day.",
         "Causal features (116 columns), swing structure that only becomes known after confirmation, causal daily regimes.",
         "16 discretionary setup archetypes x long/short, each tied to the conventional claim it embodies.",
         "M15-resolved execution simulator: spread + slippage, worse costs in news and rollover, gap fills, stop-first ambiguity.",
         "Mistake taxonomy (56 categories: ex-ante, ex-post, execution), each with a measurable rule and a statistical verdict.",
         "17 counterfactual replays per trade, with hindsight kept separate from policy.",
         "Look-alike winner/loser matching, condition scan, walk-forward ML meta-labelling, append-only experiment ledger and engine.",
         "Truncation-based look-ahead audit, tests, and a single-file dashboard."],
     "findings": [
         "No textbook setup had an out-of-sample edge, even before costs.",
         "The condition scan produced fewer significant cells than chance.",
         "'Late entry after the move' was contradicted: chasing did better (+0.17R / +0.19R).",
         "Look-alike winners and losers differed by only a few hundredths of a standard deviation.",
         "In hindsight 'take the opposite trade' rescued 49% of losers but adds nothing as a rule."]},
    {"date": "2026-11-27", "stage": "Round 2: push further",
     "built": [
         "Trailing and partial exits; two momentum setups; H4/daily 'significant' levels; event studies.",
         "Two-feature interaction scan; White's Reality Check, studentised test and Romano-Wolf step-down over the family.",
         "Per-discovery stress tests (threshold neighbourhood, cost multiples, years, Monte-Carlo drawdown, same-month drift benchmark).",
         "Forward-test registry; H1 extended from M15."],
     "findings": [
         "The whole hypothesis family failed the Reality Check; nothing survived Romano-Wolf.",
         "Momentum is real (0.1-0.3 ATR beyond drift) but too small to trade alone.",
         "Pushing continuation trades into higher-timeframe levels did better, not worse.",
         "Model-selected longs held on a 3 ATR trail after +1R looked validated, but the holdout was contaminated (see integrity log)."]},
    {"date": "2026-11-27/28", "stage": "Make it ongoing",
     "built": [
         "Direct Dukascopy updater (BID minute candles -> M15), verified to match the existing files exactly.",
         "`cycle` command: update -> pre-registered agenda -> engine -> Reality Check -> freeze & forward-score -> research log -> dashboard.",
         "Fixed holdout (2022-01 .. 2026-11-23) plus a 'forward' split for all later data.",
         "Weekly Claude research session (scheduled task) and a GitHub Actions workflow (active once merged to main).",
         "Holdout sealed in every descriptive view after a design leak was found."],
     "findings": [
         "The pre-registered 'late entry + wide stop' idea passed all splits, but its design had seen pooled holdout verdicts.",
         "Cycles kept producing a few validated variants; none passed family-wise correction."]},
    {"date": "2026-11-28", "stage": "Round 3: every mistake x every remedy",
     "built": [
         "Composite remedies: 5 entry x 4 stop x 8 exit fixes + skip + opposite = 162 per trade (~11 million re-simulations).",
         "Atlas over 40 ex-ante mistakes, all pairs and supported triples, per side and per setup: 2,035,040 cells, all counted as trials.",
         "Hindsight map for ex-post diagnoses."],
     "findings": [
         "Remedies that reduce losses replicate (25,192 cells vs ~4,220 expected by luck; 71% sign agreement).",
         "Profit does not replicate (43% sign agreement, worse than a coin flip).",
         "Best ingredients: waiting for a confirming close (helps in 87% of cells) and a 3 ATR trail after +1R (79%). Waiting 3 bars hurts."]},
    {"date": "2026-11-28", "stage": "Round 4: anatomy of the live bot's losing trades",
     "built": [
         "Replay of signals.py's own strategies (trend, 4H trend, inside-day): 1,968 trades since 2008, same counts the bot publishes.",
         "Ex-ante, in-trade and loss-type anatomy; pre-declared rules scored once on the holdout.",
         "Stdlib 'anatomy' code inside signals.py: warning-sign line on setup alerts, flags saved in the journal, opt-in '3 hours in' note, opt-in skip rule. 99.9% parity with the lab."],
     "findings": [
         "Before entry the bot's losers look like its winners; the one consistent warning sign is H1/4H/daily trend disagreement.",
         "68% of losers never reach +0.5R (winners: 4%), but cutting slow starters early lowered expectancy in all 18 versions tested.",
         "Trailing exits and the 4H conflict skip were positive or neutral on the holdout, not strong enough to change live trading yet."]},
    {"date": "2026-11-28", "stage": "Rename and this file",
     "built": ["Package renamed to 'aurum'; HISTORY.json generated from the live record and rebuilt every cycle."]},
]

INTEGRITY_LOG = [
    {"issue": "Weekend filter precedence bug dropped most H1 bars on first load.", "handled": "Fixed before any results were produced."},
    {"issue": "Dashboard charts did not render (Plotly CDN path 404).", "handled": "Switched to a pinned jsDelivr build."},
    {"issue": "Discovery cards showed holdout numbers for hypotheses that failed validation.", "handled": "Holdout is revealed only after validation passes; cards rebuilt."},
    {"issue": "Trade-id collision (momentum_bar vs momentum_burst) corrupted counterfactual joins in one run.", "handled": "643 ledger records from that run removed with a ledger note explaining why; ids made unique and tested."},
    {"issue": "ML exit (3 ATR trail after +1R) was chosen after seeing a table that included holdout.", "handled": "Recorded as contaminated in the ledger and on its cards; table now hides holdout; frozen for forward testing."},
    {"issue": "Cycle-0 agenda was designed from taxonomy verdicts that pooled validation and holdout.", "handled": "Ledger note on all 16 affected hypotheses; every descriptive view now uses discovery + validation only."},
    {"issue": "Quadratic slowdowns as the ledger grew; one cycle hit the time limit.", "handled": "In-memory ledger cache, indexed counterfactual lookups, cached relation sets."},
    {"issue": "Atlas validation file (24 MB) committed once.", "handled": "Replaced by a gzipped file of replicated cells only."},
    {"issue": "Bot '3 hours in' note missed fills before gold's daily break hour.", "handled": "Fires on the first bar at or after the 3-hour mark; tested."},
    {"issue": "Externally scored bot rules in the ledger crashed the engine's report rebuild.", "handled": "Engine and Reality Check skip origin 'bot' records."},
    {"issue": "Earlier research rounds in research/ had already viewed 2008-2026.", "handled": "Their 1,430 logged trials are added to the multiple-testing count; holdout is out-of-sample for this lab only."},
]


def _modules() -> dict:
    out = {}
    for p in sorted((ROOT / "aurum").glob("*.py")):
        doc = ast.get_docstring(ast.parse(p.read_text())) or ""
        out[p.name] = doc.strip().split("\n\n")[0].replace("\n", " ")
    return out


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def build() -> dict:
    R = json.loads((OUTPUT / "lab_results.json").read_text()) if (OUTPUT / "lab_results.json").exists() else {}
    led = _jsonl(STORE / "experiments.jsonl")
    last = {}
    for r in led:
        if r.get("hyp_id"):
            last[r["hyp_id"]] = r.get("status")
    status_counts = {}
    for v in last.values():
        status_counts[v] = status_counts.get(v, 0) + 1
    disc = sorted(R.get("discoveries", []), key=lambda d: -d.get("evidence_score", 0))
    frozen = json.loads((STORE / "frozen.json").read_text()) if (STORE / "frozen.json").exists() else []
    atlas = R.get("atlas") or {}
    bot = R.get("bot") or {}
    tx = R.get("taxonomy") or []
    verdicts = {}
    for t in tx:
        verdicts[t["verdict"]] = verdicts.get(t["verdict"], 0) + 1
    commits = _git("log", "--oneline", "--reverse", "--format=%ad %s", "--date=short")
    history = {
        "schema": "aurum-history/1",
        "generated_at_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
        "project": PROJECT,
        "timeline": TIMELINE,
        "methodology": {
            "decision_rule": "Every decision is made at the close of an H1 bar using only information known then; higher-timeframe bars attach only after their scheduled close.",
            "splits": SPLITS,
            "what_each_split_is_for": {
                "archive": "2003-07, H1 only: robustness in a very different regime.",
                "discovery": "Mining and fitting.",
                "validation": "Must pass with nothing re-fitted.",
                "holdout": "Scored once per hypothesis, only after validation passes. Sealed in all descriptive views.",
                "forward": "Data after 2026-11-23: only frozen hypotheses are scored here, from their freeze time onward."},
            "gates": {"discovery": "n>=40, avg R>0.03, t>=2", "validation": "n>=20, avg R>0, t>=1", "holdout": "n>=15, avg R>0, t>=1 (else weak or contradicted)"},
            "costs": DEFAULT.costs.__dict__,
            "multiple_testing": "Every scan cell, atlas cell and engine test is a trial (plus 1,430 legacy trials). BH-FDR, deflated Sharpe, White's Reality Check, studentised SPA-style test and Romano-Wolf step-down.",
            "look_ahead_audit": "Features and setup signals are rebuilt on data truncated at random bars and must be identical to full-history values.",
            "units": "R = profit or loss divided by the initial risk, after spread and slippage."},
        "architecture": {"modules": _modules(),
                         "commands": {"python -m aurum audit": "look-ahead audit",
                                      "python -m aurum cycle --budget N": "one research cycle (used by the schedulers)",
                                      "python -m aurum run --budget N": "full run without the update/log steps",
                                      "python -m aurum update": "download new candles",
                                      "python -m aurum history": "rebuild this file",
                                      "python -m aurum template": "CSV template for personal trades"}},
        "data_now": R.get("data"),
        "state_now": {
            "trials_counted": (R.get("experiments") or {}).get("n_trials_total"),
            "hypotheses_in_ledger": len(last), "ledger_records": len(led), "status_counts": status_counts,
            "reality_check": {k: (R.get("reality_check") or {}).get(k) for k in
                              ("n_hypotheses", "p_reality_check", "p_studentised", "best", "rw_survivors")},
            "taxonomy_verdicts": verdicts,
            "replicated_mistakes": [{"id": t["id"], "name": t["name"], "verdict": t["verdict"]} for t in tx if t.get("replicated")],
            "atlas": {k: atlas.get(k) for k in ("n_cells", "n_combos", "ev_replicated", "ev_replicated_expected",
                                                 "delta_replicated", "delta_replicated_expected", "ev_sign_agreement",
                                                 "delta_sign_agreement", "components")},
            "top_discoveries": [{"hyp_id": d["hyp_id"], "status": d["status"], "evidence": d.get("evidence_score"),
                                 "definition": d["definition"], "caveats": d.get("caveats", []),
                                 "avg_r_by_split": {k: (v or {}).get("avg_r") for k, v in (d.get("by_split") or {}).items()},
                                 "n_by_split": {k: (v or {}).get("n") for k, v in (d.get("by_split") or {}).items()}}
                                for d in disc[:15]],
            "frozen_for_forward_test": [{"hyp_id": f["hyp_id"], "definition": f["definition"], "frozen_at": f["frozen_at"],
                                         "status_at_freeze": f.get("status_at_freeze")} for f in frozen],
            "forward_results": [{"definition": f["definition"], "verdict": f.get("verdict"),
                                 "n": (f.get("forward") or {}).get("n"), "avg_r": (f.get("forward") or {}).get("avg_r")}
                                for f in R.get("forward", [])],
            "bot": {k: bot.get(k) for k in ("n_trades", "per_strategy", "loss_types", "early", "rules", "forward")},
            "personal_profile": {"source": (R.get("profile") or {}).get("source"),
                                 "tests": [{"id": t["id"], "claim": t["claim"], "verdict": t["verdict"]}
                                           for t in (R.get("profile") or {}).get("tests", [])]},
        },
        "integrity_log": INTEGRITY_LOG,
        "automation": {
            "weekly_claude_session": {"schedule": "Sundays 04:23 UTC", "scheduled_task_id": "trig_012CVbGxciPJWr3ZB2uiw4Cp",
                                      "does": "runs a cycle, pre-registers 3-6 hypotheses in aurum/agenda.json, writes researcher notes, pushes"},
            "github_actions": {"file": ".github/workflows/aurum.yml", "schedule": "Sundays 03:17 UTC",
                               "note": "GitHub runs scheduled workflows only from the default branch: active once merged to main."},
            "cycles_so_far": [{"ts": c.get("ts"), "bars_added": (c.get("update") or {}).get("bars_added"),
                               "changes": len(c.get("changes", []))} for c in _jsonl(STORE / "cycles.jsonl")],
        },
        "files": {"aurum/README.md": "methods and findings, round by round",
                  "aurum/RESEARCH_LOG.md": "what changed in each cycle (newest first)",
                  "aurum/agenda.json": "pre-registered hypotheses for the next cycle",
                  "aurum/store/experiments.jsonl": "append-only ledger of every test",
                  "aurum/store/frozen.json / forward_scores.jsonl": "forward-test registry and scores",
                  "aurum/store/bot_anatomy_model.json": "statistics the live bot reads for its notes",
                  "lab_output/dashboard.html": "the dashboard", "lab_output/lab_results.json": "all results of the last run"},
        "open_questions": [
            "Forward data: do the frozen hypotheses (ML-selected longs with trailing exit, the atlas cells, the late-entry + wide-stop idea) hold after 2026-11-23?",
            "Does the bot's timeframe-conflict warning keep separating weaker trades live? (journal.json now records the flag)",
            "Personal profile: needs the owner's own trade history in aurum/store/my_trades.csv to test the short-side self-assessment.",
            "Better execution data: real historical spreads and tick data around news would tighten every cost-sensitive result."],
        "commit_history": [c for c in commits.splitlines()
                           if any(k in c for k in ("Edge Lab", "Aurum", "aurum", "edgelab", "Bot loss", "Rename"))][-200:],
    }
    return jsonable(history)


def write() -> Path:
    OUT.write_text(json.dumps(build(), indent=1, default=str))
    return OUT
