# Aurum inbox: your trade history

Drop files here and run `python -m aurum personal` (or wait for the weekly cycle).

| What you have | What to drop |
|---|---|
| MetaTrader 5 | History tab → right-click → Report → HTML or Excel (the "Positions" section is used) |
| MetaTrader 4 | Account History → right-click → Save as Report (HTML) |
| cTrader, other brokers | The closed-positions / history export (CSV or XLSX). Columns are matched by name. |
| TradingView | Strategy Tester → List of trades → export |
| Notes or a spreadsheet | `manual_trades.csv` (template: `python -m aurum template`) |
| Screenshots | Put them in `screenshots/`. A Claude session reads each one and adds rows to `manual_trades.csv` with `source=screenshot:<file>`; they are only used after you set `confirmed` to `yes`. |

**What makes the analysis much stronger:** the *initial* stop of each trade (most broker exports only keep the
final stop, which is often moved to breakeven), your own setup label, and a one-line reason for the trade. Times can be
in your broker's time zone: Aurum detects the offset by matching your prices to the actual candles.

Your files are research input only. Nothing here is sent anywhere or used to trade.
