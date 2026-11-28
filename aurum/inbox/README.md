# Aurum inbox: your trade history

Drop files here and run `python -m aurum personal` (or wait for the weekly cycle).

| What you have | What to drop |
|---|---|
| **MetaTrader 5 (best)** | Run the read-only script `mt5/AurumExportHistory.mq5` (see below) and drop `aurum_history.csv` here. It has the *initial* stop of every trade, separates your manual trades from EA trades, and records the server clock. |
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

## Exporting from MetaTrader 5 with the Aurum script

1. Copy `mt5/AurumExportHistory.mq5` into your terminal's `MQL5/Scripts` folder (File → Open Data Folder → MQL5 → Scripts).
2. In MetaEditor, open it and press Compile (F7). In the terminal's Navigator, it appears under Scripts.
3. Drag it onto any chart. Keep "Only XAU / gold symbols" on and set the start date to before your first trade. Press OK.
4. A message shows where the file was saved (`MQL5/Files/aurum_history.csv`). Put that file in this folder.

The script only reads your history: it never opens, modifies or closes a trade, and it runs alongside your EA without
touching it. Run it again whenever you want Aurum to see newer trades.
