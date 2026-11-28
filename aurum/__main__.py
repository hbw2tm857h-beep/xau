"""Command line:  python -m aurum <command>

  run         full research run (+ experiments, + dashboard)       [--budget N] [--rebuild] [--trades my.csv]
  experiment  run N more experiments from the queue                 [--budget N]
  audit       look-ahead / leakage audit of features and setups
  dashboard   rebuild the dashboard from the last run
  template    print the personal-trades CSV template
  update      download new candles from Dukascopy (complete UTC days)
  ingest      read your trade files in aurum/inbox/ (broker exports, CSV, manual, screenshots queue)  [--tz HOURS]
  personal    ingest + personal edge report only (fast)
  history     rebuild aurum/HISTORY.json (the project explained, creation to now)
  cycle       one autonomous research cycle: update -> experiments -> forward test -> log  [--budget N] [--no-fetch]
"""
from __future__ import annotations

import argparse
import json


def main():
    ap = argparse.ArgumentParser(prog="aurum")
    ap.add_argument("command", choices=["run", "experiment", "audit", "dashboard", "template", "update", "cycle", "history", "ingest", "personal"])
    ap.add_argument("--budget", type=int, default=60)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--trades", default=None)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--tz", type=float, default=None, help="ingest: force the broker clock offset (hours ahead of UTC)")
    ap.add_argument("--skip-if-recent", type=float, default=0.0,
                    help="cycle: do nothing if the last cycle finished less than this many hours ago")
    a = ap.parse_args()
    if a.command == "run":
        from .pipeline import run
        run(a.budget, a.rebuild, a.trades)
    elif a.command == "experiment":
        from .pipeline import run
        run(a.budget, False, a.trades)
    elif a.command == "audit":
        from .config import STORE
        from . import data as D
        from .validation import truncation_audit, setup_truncation_audit
        h1 = D.load_h1()
        fa = truncation_audit(h1)
        sa = setup_truncation_audit(h1)
        bad = fa[fa["mismatches"] > 0]
        out = {"feature_columns_checked": int(len(fa)), "feature_checks": int(fa["checks"].sum()),
               "feature_mismatches": int(fa["mismatches"].sum()), "mismatched_columns": bad["column"].tolist(),
               **sa}
        (STORE / "leakage_audit.json").write_text(json.dumps(out, indent=1))
        print(json.dumps(out, indent=1))
    elif a.command == "dashboard":
        from .pipeline import Lab
        from .config import OUTPUT
        from .dashboard import build
        R = json.loads((OUTPUT / "lab_results.json").read_text())
        build(R, Lab())
    elif a.command == "update":
        from .updater import update
        update()
    elif a.command == "cycle":
        from .cycle import run_cycle, hours_since_last
        h = hours_since_last()
        if a.skip_if_recent and h is not None and h < a.skip_if_recent:
            print(f"[cycle] last cycle {h:.1f}h ago (< {a.skip_if_recent}h): skipping, results are current")
        else:
            run_cycle(a.budget, fetch=not a.no_fetch, user_trades=a.trades)
    elif a.command == "history":
        from .history import write
        print(f"wrote {write()}")
    elif a.command == "ingest":
        from .ingest import ingest
        ingest(tz_offset=a.tz)
    elif a.command == "personal":
        from .ingest import ingest
        from .pipeline import Lab
        from .config import OUTPUT, STORE
        from . import personal as PS
        ingest(tz_offset=a.tz)
        R = json.loads((OUTPUT / "lab_results.json").read_text())
        rep = PS.run(Lab(), R, label="owner")
        (STORE / "personal" / "report.json").write_text(json.dumps(rep, default=str))
        print(json.dumps({k: rep.get(k) for k in ("status", "n", "date_range", "r_basis")}, default=str))
        if rep.get("status") == "ok":
            print("Directional verdict:", rep["directional"]["verdict"])
    elif a.command == "template":
        from .ingest import MANUAL_TEMPLATE
        print(MANUAL_TEMPLATE)


if __name__ == "__main__":
    main()
