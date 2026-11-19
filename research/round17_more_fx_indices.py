"""Round 17: the gold strategies on 30 more markets (pre-registered 19 Nov 2026).

Rounds 10 and 16 found two passes among 37 markets (Bitcoin trend, Ether
inside-day). This round finishes the sweep over what Dukascopy offers: the ten
stock indices downloaded for round 15 (only IBS was run on them) and twenty FX
pairs round 10 did not cover. Round 10's code, cost method and pass mark,
unchanged. The FX data is downloaded after this file is committed.

  Indices   Russell 2000, Euro Stoxx 50, IBEX 35, AEX, FTSE MIB, ASX 200,
            Hang Seng, China A50, Singapore, WIG 20 (costs as round 15)
  EM/Nordic USDMXN 5, USDZAR 8, USDSEK 4, USDNOK 4, USDPLN 5, USDHUF 6,
            USDCNH 4, USDSGD 3, USDCZK 6 (round-trip cost, bp)
  Crosses   AUDNZD, CADJPY, CHFJPY, NZDJPY, EURCHF, EURCAD, EURAUD, GBPAUD,
            GBPCAD, GBPCHF, AUDCAD, all 2 bp

USDTRY is left out: lira interest of 10-50% a year makes the swap on any held
position too large to ignore, and these tests do not model financing.

Strategies: trend, insideday, h4 (round 10). Pass: 150+ trades, average at
least +0.05R, positive in every period with 10+ trades and at least three such
periods, one-sided p < 0.05 / 90 = 0.00056.
"""
import math
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import round10_markets as R10  # noqa: E402

NEW = {
    "Russell 2000": ("ussc2000idxusd", 2.0), "Euro Stoxx 50": ("eusidxeur", 1.5), "IBEX 35": ("espidxeur", 2.0),
    "AEX": ("nldidxeur", 2.0), "FTSE MIB": ("itaidxeur", 2.0), "ASX 200": ("ausidxaud", 2.0),
    "Hang Seng": ("hkgidxhkd", 2.0), "China A50": ("chiidxusd", 3.0), "Singapore": ("sgdidxsgd", 3.0),
    "WIG 20": ("plnidxpln", 3.0),
    "USDMXN": ("usdmxn", 5.0), "USDZAR": ("usdzar", 8.0), "USDSEK": ("usdsek", 4.0), "USDNOK": ("usdnok", 4.0),
    "USDPLN": ("usdpln", 5.0), "USDHUF": ("usdhuf", 6.0), "USDCNH": ("usdcnh", 4.0), "USDSGD": ("usdsgd", 3.0),
    "USDCZK": ("usdczk", 6.0),
    "AUDNZD": ("audnzd", 2.0), "CADJPY": ("cadjpy", 2.0), "CHFJPY": ("chfjpy", 2.0), "NZDJPY": ("nzdjpy", 2.0),
    "EURCHF": ("eurchf", 2.0), "EURCAD": ("eurcad", 2.0), "EURAUD": ("euraud", 2.0), "GBPAUD": ("gbpaud", 2.0),
    "GBPCAD": ("gbpcad", 2.0), "GBPCHF": ("gbpchf", 2.0), "AUDCAD": ("audcad", 2.0),
}
R10.ALPHA = 0.05 / 90


def _corr(x, y):
    mx, my = sum(x) / len(x), sum(y) / len(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return num / den if den else 0.0


R10.st.correlation = getattr(R10.st, "correlation", _corr)

if __name__ == "__main__":
    for name, (iid, bps) in NEW.items():
        R10.MARKETS[name] = ([f"markets/{iid}_h1.csv.gz"], bps)
    R10.main(set(NEW))
    shutil.move(os.path.join(HERE, "results_round10_partial.csv"),
                os.path.join(HERE, "results_round17_more_fx_indices.csv"))
