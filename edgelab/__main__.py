"""Command line:  python -m edgelab <command>

  run         full research run (+ experiments, + dashboard)       [--budget N] [--rebuild] [--trades my.csv]
  experiment  run N more experiments from the queue                 [--budget N]
  audit       look-ahead / leakage audit of features and setups
  dashboard   rebuild the dashboard from the last run
  template    print the personal-trades CSV template
"""
from __future__ import annotations

import argparse
import json


def main():
    ap = argparse.ArgumentParser(prog="edgelab")
    ap.add_argument("command", choices=["run", "experiment", "audit", "dashboard", "template"])
    ap.add_argument("--budget", type=int, default=60)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--trades", default=None)
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
    elif a.command == "template":
        from .profile import TEMPLATE
        print(TEMPLATE)


if __name__ == "__main__":
    main()
