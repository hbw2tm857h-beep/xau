"""Round 16: the three gold strategies on 16 markets never tested (pre-registered
19 Nov 2026, before the data below was opened).

Round 10 ran the gold rules, unchanged, on 21 other markets and one result
survived: the trend rules on Bitcoin, now a shadow strategy. That is still the
cleanest kind of test in the project, because none of these rules was ever tuned
on the market being tested. Dukascopy offers more markets than round 10 used, so
this round runs exactly round 10's code, costs method and pass mark on the rest:

  Commodities  copper, platinum, palladium, natural gas, cocoa, coffee, sugar,
               cotton, soybeans, orange juice, diesel
  Crypto       Ether, Litecoin, Bitcoin Cash, Stellar, Cardano

Strategies (round 10, nothing re-tuned): trend (hourly Heikin Ashi with the 4H
cloud), insideday, and the 4-hour trigger. Round-trip costs, in basis points of
price, fixed here: copper 5, platinum 10, palladium 15, natural gas 10, cocoa 10,
coffee 10, sugar 10, cotton 10, soybeans 8, orange juice 20, diesel 8; Ether 8,
Litecoin 10, Bitcoin Cash 10, Stellar 15, Cardano 15.

Pass mark, as round 10: 150+ trades, average at least +0.05R, positive in every
period with 10+ trades and at least three such periods, and one-sided
p < 0.05 / 48 = 0.00104 (16 markets x 3 strategies). Markets whose data starts
late may not reach three periods; that is a fail, not an exception.
"""
import math
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import round10_markets as R10  # noqa: E402

NEW = {
    "Copper": ("coppercmdusd", 5.0), "Platinum": ("xptcmdusd", 10.0), "Palladium": ("xpdcmdusd", 15.0),
    "Natural gas": ("gascmdusd", 10.0), "Cocoa": ("cocoacmdusd", 10.0), "Coffee": ("coffeecmdusx", 10.0),
    "Sugar": ("sugarcmdusd", 10.0), "Cotton": ("cottoncmdusx", 10.0), "Soybeans": ("soybeancmdusx", 8.0),
    "Orange juice": ("ojuicecmdusx", 20.0), "Diesel": ("dieselcmdusd", 8.0),
    "Ether": ("ethusd", 8.0), "Litecoin": ("ltcusd", 10.0), "Bitcoin Cash": ("bchusd", 10.0),
    "Stellar": ("xlmusd", 15.0), "Cardano": ("adausd", 15.0),
}
R10.ALPHA = 0.05 / 48


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
                os.path.join(HERE, "results_round16_commodities_crypto.csv"))
