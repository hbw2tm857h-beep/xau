"""THE EDGE LAB — a research environment for reverse-engineering discretionary
trading decisions on XAUUSD.

It never connects to a broker and never places trades. Everything here works on
historical candles, reconstructs decisions candle by candle using only the
information available at each decision time, and records every hypothesis it
tests (including failures) so results can be corrected for multiple testing.
"""
__version__ = "0.1.0"
