"""Central configuration: paths, chronological splits, cost model, defaults."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STORE = ROOT / "edgelab" / "store"          # committed research record (ledger, queue)
CACHE = ROOT / "edgelab" / "store" / "cache"  # not committed (rebuildable)
OUTPUT = ROOT / "lab_output"                # dashboard + summary artefacts

# ---------------------------------------------------------------------------
# Chronological splits. Decisions are assigned by their decision timestamp.
#   archive    : H1 only (no M15). Used purely as an extra, very different regime
#                (2003-07 secular bull, low price) for robustness checks.
#   discovery  : everything may be mined / fitted here.
#   validation : thresholds frozen; a hypothesis must survive here to be promoted.
#   holdout    : each hypothesis may be scored here only after it passed validation.
# NOTE: earlier research rounds in research/ looked at all of 2008-2026, so the
# holdout is out-of-sample *for this lab*, not virgin data. The legacy trial
# count is added to the multiple-testing denominator for that reason.
# ---------------------------------------------------------------------------
SPLITS = {
    "archive": ("2003-01-01", "2007-12-31 23:59"),
    "discovery": ("2008-01-01", "2017-12-31 23:59"),
    "validation": ("2018-01-01", "2021-12-31 23:59"),
    "holdout": ("2022-01-01", "2100-01-01"),
}
SPLIT_ORDER = ["archive", "discovery", "validation", "holdout"]

# Embargo between splits: trades whose holding window crosses a split boundary
# are dropped from the later split's statistics (prevents overlap leakage).
EMBARGO_HOURS = 72


@dataclass
class CostModel:
    """Realistic retail XAUUSD costs, in price units ($ per oz).

    spread  = max(spread_min, price * spread_bps / 1e4), charged half on entry and
              half on exit (prices in the data are treated as mid).
    slippage on market/stop fills = slip_atr * ATR(H1); limit fills have none.
    Inside news windows (FOMC / CPI / NFP) spread and slippage are multiplied.
    """
    spread_min: float = 0.20
    spread_bps: float = 0.8          # 0.8 bp -> $0.30 at $3,800, $0.20 floor
    slip_atr: float = 0.02           # 2% of an H1 ATR per market/stop fill
    news_mult: float = 3.0
    rollover_mult: float = 2.0       # 21:00-23:00 UTC daily rollover spreads
    scale: float = 1.0               # global stress multiplier (robustness tests)

    def spread(self, price: float, news: bool = False, rollover: bool = False) -> float:
        s = max(self.spread_min, price * self.spread_bps / 1e4)
        if news:
            s *= self.news_mult
        elif rollover:
            s *= self.rollover_mult
        return s * self.scale

    def slippage(self, atr: float, news: bool = False) -> float:
        s = self.slip_atr * atr
        if news:
            s *= self.news_mult
        return s * self.scale


@dataclass
class TradeDefaults:
    target_r: float = 2.0
    max_hours: int = 48              # time stop
    stop_buffer_atr: float = 0.10
    min_stop_atr: float = 0.5
    max_stop_atr: float = 4.0        # setups needing a wider stop are skipped
    cooldown_bars: int = 3           # same setup+direction cannot re-fire within N bars
    post_exit_hours: int = 24        # path watched after exit (for stop-hunt diagnosis only)


@dataclass
class LabConfig:
    costs: CostModel = field(default_factory=CostModel)
    trade: TradeDefaults = field(default_factory=TradeDefaults)
    decision_tf: str = "H1"
    # legacy research rows (research/results*.csv etc.) count as prior trials
    include_legacy_trials: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT = LabConfig()
