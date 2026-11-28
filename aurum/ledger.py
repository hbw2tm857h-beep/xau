"""Append-only hypothesis / experiment ledger.

Nothing is ever deleted or overwritten. Each line in ``experiments.jsonl`` is one
test of one hypothesis on one data split. The total number of lines (plus the
legacy research trial count) is the denominator used for multiple-testing
corrections, so a lucky result among many tries is discounted accordingly.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .config import STORE, ROOT
from .stats import jsonable, benjamini_hochberg

LEDGER = STORE / "experiments.jsonl"
# Records scored outside the engine (their specs are not engine-replayable): bot rules, bot transfer
# candidates, personal tests. They stay in the ledger and the trial counts, but the engine never re-runs them.
EXTERNAL_ORIGINS = {"bot", "bot_transfer", "personal"}
DISCOVERIES = STORE / "discoveries.json"


def hyp_id(spec: dict) -> str:
    key = json.dumps({k: spec[k] for k in sorted(spec) if k not in ("rationale", "origin", "parent")},
                     sort_keys=True, default=str)
    return "H" + hashlib.sha1(key.encode()).hexdigest()[:10]


from functools import lru_cache


@lru_cache(maxsize=1)
def legacy_trial_count() -> int:
    """Rows logged by earlier research rounds in research/ (prior data snooping)."""
    n = 0
    for p in (ROOT / "research").glob("results*.csv"):
        try:
            n += max(0, sum(1 for _ in open(p)) - 1)
        except OSError:
            pass
    for p in (ROOT / "research").glob("round*_results.json"):
        try:
            obj = json.loads(p.read_text())
            n += len(obj) if isinstance(obj, (list, dict)) else 1
        except Exception:
            n += 1
    return n


class Ledger:
    def __init__(self, path: Path = LEDGER):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._recs: list[dict] | None = None
        self._tested: set | None = None

    def append(self, rec: dict) -> None:
        rec = jsonable({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec})
        with open(self.path, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
        if self._recs is not None:
            self._recs.append(json.loads(json.dumps(rec, default=str)))
            if rec.get("hyp_id"):
                self._tested.add((rec["hyp_id"], rec.get("split")))

    def records(self) -> list[dict]:
        """All records (cached in memory; the file stays the source of truth and is append-only)."""
        if self._recs is None:
            self._recs = ([json.loads(x) for x in self.path.read_text().splitlines() if x.strip()]
                          if self.path.exists() else [])
            self._tested = {(r.get("hyp_id"), r.get("split")) for r in self._recs if r.get("hyp_id")}
        return self._recs

    def frame(self) -> pd.DataFrame:
        r = self.records()
        return pd.json_normalize(r) if r else pd.DataFrame()

    def tested(self, hid: str, split: str) -> bool:
        self.records()
        return (hid, split) in self._tested

    def n_trials(self, include_legacy: bool = True) -> int:
        n = sum(1 for r in self.records() if r.get("split") == "discovery")
        return n + (legacy_trial_count() if include_legacy else 0)

    def sharpe_var(self) -> float:
        s = pd.Series([(r.get("stats") or {}).get("sharpe") for r in self.records()
                       if r.get("split") == "discovery"], dtype=float).dropna()
        return float(s.var()) if len(s) > 5 else 0.01

    def corrected(self) -> pd.DataFrame:
        """All discovery-split tests with BH q-values across the whole ledger."""
        df = self.frame()
        if not len(df):
            return df
        d = df[df["split"] == "discovery"].copy()
        d["q_value_all"] = benjamini_hochberg(d["stats.p"].astype(float).values)
        return d
