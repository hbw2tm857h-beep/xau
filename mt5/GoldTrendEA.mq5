//+------------------------------------------------------------------+
//|                                                 GoldTrendEA.mq5  |
//|  Gold H1 Heikin Ashi trend-ride, confirmed by the daily trend and |
//|  the 4-hour Heikin Ashi candle. The same rules as the xau signals |
//|  bot (research/README.md): tested 2008-2026 on Dukascopy H1 data, |
//|  715 trades, 60% winners, +0.18R per trade after costs.           |
//|                                                                  |
//|  Default: ALERTS ONLY (MT5 push + optional Slack). Set           |
//|  InpAutoTrade = true to place and manage trades - test on a      |
//|  demo account first.                                             |
//|                                                                  |
//|  Rules (checked when each H1 candle closes):                     |
//|   1. Daily trend: last daily Heikin Ashi candle and the daily    |
//|      close vs the 50 EMA agree (up or down).                     |
//|   2. Last closed 4-hour Heikin Ashi candle is the same colour,   |
//|      and that 4-hour close is beyond the Ichimoku cloud (above   |
//|      for buys, below for sells; 9/26/52). Research round 4.      |
//|   3. H1 Heikin Ashi candle: first one of the new colour with no  |
//|      wick against the move (no lower wick for buys), body at     |
//|      least as big as the previous candle, colour flip within 12. |
//|   4. Room to the next daily support/resistance level of at least |
//|      0.5 x daily ATR (levels from daily-close pivots).           |
//|  Trade: stop order 0.30 beyond the signal candle, stop beyond    |
//|  the last 5 candles + 0.2 x H1 ATR. Half off at +1R and stop to  |
//|  entry, rest at +2R. Order cancelled if the HA colour flips or   |
//|  12 hours pass. One trade at a time.                             |
//|                                                                  |
//|  Second setup (research round 5, separate magic InpMagic + 1):   |
//|  inside-day breakout on D1 - see OnNewD1(). Half risk by default.|
//+------------------------------------------------------------------+
#property copyright "Bradley - Built by Lumn"
#property version   "2.20"
#property description "Gold H1 Heikin Ashi trend-ride with 4H confirmation. Alerts by default; optional auto-trading."

#include <Trade/Trade.mqh>

input group "Mode"
input bool   InpAutoTrade        = false; // Place and manage trades (false = alerts only)
input double InpRiskPercent      = 1.0;   // Risk per trade (% of balance)
input long   InpMagic            = 261114;

input group "Strategy (tested values: re-test before changing)"
input int    InpDailyEMA         = 50;
input int    InpATRPeriod        = 14;
input int    InpSRLookbackDays   = 180;
input int    InpSRPivot          = 3;
input double InpSRMergeATR       = 0.5;
input int    InpSRMaxLevels      = 12;
input bool   InpRequireCloud     = true;  // 4H close beyond the Ichimoku cloud
input bool   InpRequireRoom      = true;
input double InpMinRoomATR       = 0.5;
input int    InpMaxBarsSinceFlip = 12;
input double InpMinBodyGrowth    = 1.0;
input double InpEntryBuffer      = 0.30;  // $ beyond the signal candle
input int    InpStopSwingBars    = 5;
input double InpStopBufferATR    = 0.2;
input double InpPartialR         = 1.0;
input double InpPartialFrac      = 0.5;
input double InpTargetR          = 2.0;
input int    InpEntryExpiryBars  = 12;

input group "Second setup: inside-day breakout (research round 5)"
input bool   InpInsideDay        = true;  // Alert/trade the inside-day breakout too
input double InpInsideDayRisk    = 0.5;   // x InpRiskPercent for these trades (tested: half size)

input group "Notifications"
input bool   InpPush             = true;  // MT5 push to your phone
input bool   InpSlack            = false; // Post to Slack (add hooks.slack.com to WebRequest list)
input string InpSlackWebhook     = "";
input bool   InpDrawLevels       = true;

//--- trade idea / position state (persisted in terminal global variables)
struct Idea
  {
   int      dir;        // 1 buy, -1 sell, 0 none
   double   entry, stop, risk, partial, target;
   bool     triggered, partialDone;
   int      age;
   datetime sigTime;
   ulong    orderTicket;
  };

Idea     g;
datetime g_lastH1 = 0;

//--- inside-day breakout state (separate magic number: InpMagic + 1)
struct InsideDay
  {
   int      state;      // 0 none, 1 orders waiting, 2 in the trade
   int      dir;
   double   hi, lo, entry, stop;
  };
InsideDay ib;
datetime g_lastD1 = 0;
CTrade   ibTrade;
double   g_levels[];
int      hEMA = INVALID_HANDLE, hATRd = INVALID_HANDLE, hATRh = INVALID_HANDLE;
CTrade   trade;
string   GV;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(StringFind(_Symbol, "XAU") < 0)
      Print("GoldTrendEA: tested on gold only. Attached to ", _Symbol, " - results unknown.");
   hEMA  = iMA(_Symbol, PERIOD_D1, InpDailyEMA, 0, MODE_EMA, PRICE_CLOSE);
   hATRd = iATR(_Symbol, PERIOD_D1, InpATRPeriod);
   hATRh = iATR(_Symbol, PERIOD_H1, InpATRPeriod);
   if(hEMA == INVALID_HANDLE || hATRd == INVALID_HANDLE || hATRh == INVALID_HANDLE)
      return(INIT_FAILED);
   trade.SetExpertMagicNumber(InpMagic);
   ibTrade.SetExpertMagicNumber(InpMagic + 1);
   GV = "GTE_" + _Symbol + "_" + (string)InpMagic + "_";
   LoadState();
   LoadIB();
   EventSetTimer(10);
   Print("GoldTrendEA started: ", (InpAutoTrade ? "AUTO-TRADING" : "alerts only"),
         ", risk ", DoubleToString(InpRiskPercent, 2), "%");
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   SaveState();
   SaveIB();
   if(!MQLInfoInteger(MQL_TESTER))
      ObjectsDeleteAll(0, "GTE_LV_");
   IndicatorRelease(hEMA);
   IndicatorRelease(hATRd);
   IndicatorRelease(hATRh);
  }

void OnTick()  { Process(); }
void OnTimer() { Process(); }

//+------------------------------------------------------------------+
void Process()
  {
   datetime t = iTime(_Symbol, PERIOD_H1, 0);
   if(t != 0 && t != g_lastH1)
     {
      bool first = (g_lastH1 == 0);
      g_lastH1 = t;
      if(!first)
         OnNewH1();
      else
         BuildLevels();
     }
   ManageIntrabar();

   if(InpInsideDay)
     {
      datetime d1 = iTime(_Symbol, PERIOD_D1, 0);
      if(d1 != 0 && d1 != g_lastD1)
        {
         bool firstD = (g_lastD1 == 0);
         g_lastD1 = d1;
         if(!firstD)
            OnNewD1();
        }
      ManageIB();
     }
  }

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
double Buf(int h, int shift)
  {
   double v[];
   if(CopyBuffer(h, 0, shift, 1, v) != 1)
      return(EMPTY_VALUE);
   return(v[0]);
  }

// Heikin Ashi for a timeframe; index 0 = forming bar (series order)
bool HA(ENUM_TIMEFRAMES tf, int count, double &o[], double &h[], double &l[], double &c[])
  {
   MqlRates r[];
   ArraySetAsSeries(r, true);
   int n = CopyRates(_Symbol, tf, 0, count, r);
   if(n < 50)
      return(false);
   ArrayResize(o, n); ArrayResize(h, n); ArrayResize(l, n); ArrayResize(c, n);
   for(int i = n - 1; i >= 0; i--)
     {
      c[i] = (r[i].open + r[i].high + r[i].low + r[i].close) / 4.0;
      o[i] = (i == n - 1) ? (r[i].open + r[i].close) / 2.0 : (o[i + 1] + c[i + 1]) / 2.0;
      h[i] = MathMax(r[i].high, MathMax(o[i], c[i]));
      l[i] = MathMin(r[i].low, MathMin(o[i], c[i]));
     }
   return(true);
  }

bool Bull(const double &o[], const double &c[], int i) { return(c[i] > o[i]); }
bool Bear(const double &o[], const double &c[], int i) { return(c[i] < o[i]); }
bool NoLowerWick(const double &o[], const double &l[], const double &c[], int i)
  { return(MathMin(o[i], c[i]) - l[i] <= _Point * 0.5); }
bool NoUpperWick(const double &o[], const double &h[], const double &c[], int i)
  { return(h[i] - MathMax(o[i], c[i]) <= _Point * 0.5); }

//+------------------------------------------------------------------+
//| Ichimoku cloud on H4 (9/26/52, cloud shifted 26 bars forward):    |
//| +1 last closed H4 close above the cloud, -1 below, 0 inside.      |
//+------------------------------------------------------------------+
double MidHL(ENUM_TIMEFRAMES tf, int shift, int p)
  {
   int hi = iHighest(_Symbol, tf, MODE_HIGH, p, shift);
   int lo = iLowest(_Symbol, tf, MODE_LOW, p, shift);
   if(hi < 0 || lo < 0) return(0);
   return((iHigh(_Symbol, tf, hi) + iLow(_Symbol, tf, lo)) / 2.0);
  }

int CloudDir()
  {
   if(Bars(_Symbol, PERIOD_H4) < 26 + 52 + 2) return(0);
   int s = 1 + 25;                       // cloud drawn at bar 1 was computed 25 bars earlier
   double ten = MidHL(PERIOD_H4, s, 9), kij = MidHL(PERIOD_H4, s, 26), sb = MidHL(PERIOD_H4, s, 52);
   if(ten == 0 || kij == 0 || sb == 0) return(0);
   double sa = (ten + kij) / 2.0;
   double c = iClose(_Symbol, PERIOD_H4, 1);
   if(c > MathMax(sa, sb)) return(1);
   if(c < MathMin(sa, sb)) return(-1);
   return(0);
  }

string Px(double p) { return(DoubleToString(p, 2)); }
string Side(int d)  { return(d == 1 ? "BUY" : "SELL"); }

//+------------------------------------------------------------------+
//| Daily direction: daily HA colour + close vs EMA                  |
//+------------------------------------------------------------------+
int DailyTrend()
  {
   double o[], h[], l[], c[];
   if(!HA(PERIOD_D1, 400, o, h, l, c))
      return(0);
   double e = Buf(hEMA, 1);
   double cl = iClose(_Symbol, PERIOD_D1, 1);
   if(e == EMPTY_VALUE)
      return(0);
   if(Bull(o, c, 1) && cl > e)
      return(1);
   if(Bear(o, c, 1) && cl < e)
      return(-1);
   return(0);
  }

//+------------------------------------------------------------------+
//| Daily support/resistance from pivot closes                       |
//+------------------------------------------------------------------+
void BuildLevels()
  {
   ArrayResize(g_levels, 0);
   double cl[];
   ArraySetAsSeries(cl, true);
   int n = CopyClose(_Symbol, PERIOD_D1, 1, InpSRLookbackDays, cl);
   double atr = Buf(hATRd, 1);
   int k = InpSRPivot;
   if(n < 2 * k + 5 || atr == EMPTY_VALUE)
      return;
   double cand[];
   for(int i = k; i < n - k; i++)
     {
      bool hi = true, lo = true;
      for(int j = 1; j <= k; j++)
        {
         if(!(cl[i] > cl[i - j] && cl[i] > cl[i + j])) hi = false;
         if(!(cl[i] < cl[i - j] && cl[i] < cl[i + j])) lo = false;
        }
      if(hi || lo)
        {
         int s = ArraySize(cand);
         ArrayResize(cand, s + 1);
         cand[s] = cl[i];
        }
     }
   int m = ArraySize(cand);
   if(m == 0)
      return;
   ArraySort(cand);
   double merged[];
   double sum = cand[0], last = cand[0];
   int cnt = 1;
   for(int i = 1; i <= m; i++)
     {
      if(i < m && cand[i] - last <= InpSRMergeATR * atr)
        {
         sum += cand[i]; cnt++; last = cand[i];
         continue;
        }
      int s = ArraySize(merged);
      ArrayResize(merged, s + 1);
      merged[s] = sum / cnt;
      if(i < m) { sum = cand[i]; last = cand[i]; cnt = 1; }
     }
   // keep the levels nearest to yesterday's close
   double ref = cl[0];
   int mm = ArraySize(merged);
   for(int a = 0; a < mm - 1; a++)
      for(int b = 0; b < mm - 1 - a; b++)
         if(MathAbs(merged[b] - ref) > MathAbs(merged[b + 1] - ref))
           { double t = merged[b]; merged[b] = merged[b + 1]; merged[b + 1] = t; }
   int keep = (mm < InpSRMaxLevels) ? mm : InpSRMaxLevels;
   ArrayResize(g_levels, keep);
   for(int i = 0; i < keep; i++)
      g_levels[i] = merged[i];
   ArraySort(g_levels);

   if(InpDrawLevels && !MQLInfoInteger(MQL_TESTER))
     {
      ObjectsDeleteAll(0, "GTE_LV_");
      for(int i = 0; i < keep; i++)
        {
         string nm = "GTE_LV_" + (string)i;
         ObjectCreate(0, nm, OBJ_HLINE, 0, 0, g_levels[i]);
         ObjectSetInteger(0, nm, OBJPROP_COLOR, clrGoldenrod);
         ObjectSetInteger(0, nm, OBJPROP_STYLE, STYLE_DOT);
         ObjectSetInteger(0, nm, OBJPROP_BACK, true);
         ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
        }
      ChartRedraw();
     }
  }

double NearestAbove(double p)
  {
   for(int i = 0; i < ArraySize(g_levels); i++)
      if(g_levels[i] > p) return(g_levels[i]);
   return(0);
  }

double NearestBelow(double p)
  {
   for(int i = ArraySize(g_levels) - 1; i >= 0; i--)
      if(g_levels[i] < p) return(g_levels[i]);
   return(0);
  }

//+------------------------------------------------------------------+
//| New closed H1 candle                                             |
//+------------------------------------------------------------------+
void OnNewH1()
  {
   static int lastDay = -1;
   MqlDateTime dt;
   TimeToStruct(iTime(_Symbol, PERIOD_D1, 0), dt);
   if(dt.day_of_year != lastDay)
     {
      lastDay = dt.day_of_year;
      BuildLevels();
     }

   double o[], h[], l[], c[];
   if(!HA(PERIOD_H1, 400, o, h, l, c))
      return;

   bool closedThisBar = false;

   // pending order: cancel on colour flip or expiry
   if(g.dir != 0 && !g.triggered)
     {
      g.age++;
      bool flip = (g.dir == 1) ? Bear(o, c, 1) : Bull(o, c, 1);
      if(flip || g.age >= InpEntryExpiryBars)
        {
         string why = flip ? "the candles changed colour" : (string)InpEntryExpiryBars + " hours passed";
         Notify(":heavy_minus_sign: *Setup cancelled: Gold " + Side(g.dir) + "*. " + why + " before price reached " + Px(g.entry) + ". No trade.",
                "Gold " + Side(g.dir) + " setup cancelled (" + why + ")");
         CancelOrder();
         Reset();
        }
     }
   if(g.dir != 0 && g.triggered)
      return;   // in a trade: no new signals

   // new signal
   for(int d = 1; d >= -1; d -= 2)
     {
      string why;
      if(CheckSignal(d, o, h, l, c, why))
        {
         FireSignal(d, why);
         break;
        }
     }
   SaveState();
  }

bool CheckSignal(int d, const double &o[], const double &h[], const double &l[], const double &c[], string &why)
  {
   // 1-hour trigger: colour + no wick against the move
   if(d == 1 && !(Bull(o, c, 1) && NoLowerWick(o, l, c, 1))) return(false);
   if(d == -1 && !(Bear(o, c, 1) && NoUpperWick(o, h, c, 1))) return(false);

   // first no-wick candle since the colour flip, flip recent
   bool flip = false, earlier = false;
   int since = 0;
   for(int j = 2; j <= InpMaxBarsSinceFlip + 1 && j < ArraySize(o); j++)
     {
      bool opp = (d == 1) ? Bear(o, c, j) : Bull(o, c, j);
      if(opp) { flip = true; since = j - 1; break; }
      bool nw = (d == 1) ? (Bull(o, c, j) && NoLowerWick(o, l, c, j)) : (Bear(o, c, j) && NoUpperWick(o, h, c, j));
      if(nw) earlier = true;
     }
   if(!flip || earlier)
      return(false);

   double b1 = MathAbs(c[1] - o[1]), b2 = MathAbs(c[2] - o[2]);
   if(b1 < b2 * InpMinBodyGrowth)
      return(false);

   // daily trend
   if(DailyTrend() != d)
      return(false);

   // 4-hour Heikin Ashi agrees
   double o4[], h4[], l4[], c4[];
   if(!HA(PERIOD_H4, 400, o4, h4, l4, c4))
      return(false);
   if((d == 1 && !Bull(o4, c4, 1)) || (d == -1 && !Bear(o4, c4, 1)))
      return(false);

   // 4-hour close beyond the Ichimoku cloud
   if(InpRequireCloud && CloudDir() != d)
      return(false);

   // room to the next daily level
   double close1 = iClose(_Symbol, PERIOD_H1, 1);
   double datr = Buf(hATRd, 1);
   double nxt = (d == 1) ? NearestAbove(close1) : NearestBelow(close1);
   if(InpRequireRoom && nxt != 0 && datr != EMPTY_VALUE && MathAbs(nxt - close1) < InpMinRoomATR * datr)
      return(false);

   why = ":white_check_mark: Daily trend " + (d == 1 ? "up" : "down") + "\n"
         ":white_check_mark: 4-hour candles agree\n"
         + (InpRequireCloud ? ":white_check_mark: 4-hour price is " + (d == 1 ? "above" : "below") + " the Ichimoku cloud\n" : "") +
         ":white_check_mark: Candle " + (string)since + " of the new colour, body " + DoubleToString(b2 > 0 ? b1 / b2 : 0, 1) + "x the previous one\n"
         + (nxt != 0 ? ":white_check_mark: Next daily level " + Px(nxt) + " (" + DoubleToString(MathAbs(nxt - close1), 0) + " pts away)" : ":white_check_mark: No daily level in the way");
   return(true);
  }

//+------------------------------------------------------------------+
void FireSignal(int d, string why)
  {
   double hatr = Buf(hATRh, 1);
   if(hatr == EMPTY_VALUE) hatr = 0;
   double hi1 = iHigh(_Symbol, PERIOD_H1, 1), lo1 = iLow(_Symbol, PERIOD_H1, 1);
   double entry, stop;
   if(d == 1)
     {
      entry = hi1 + InpEntryBuffer;
      int li = iLowest(_Symbol, PERIOD_H1, MODE_LOW, InpStopSwingBars, 1);
      stop = iLow(_Symbol, PERIOD_H1, li) - InpStopBufferATR * hatr;
     }
   else
     {
      entry = lo1 - InpEntryBuffer;
      int hi = iHighest(_Symbol, PERIOD_H1, MODE_HIGH, InpStopSwingBars, 1);
      stop = iHigh(_Symbol, PERIOD_H1, hi) + InpStopBufferATR * hatr;
     }
   double risk = MathAbs(entry - stop);
   if(risk <= 0)
      return;

   bool replaced = (g.dir != 0 && !g.triggered);
   if(replaced)
      CancelOrder();

   g.dir = d; g.entry = NormalizeDouble(entry, _Digits); g.stop = NormalizeDouble(stop, _Digits);
   g.risk = risk; g.partial = NormalizeDouble(entry + d * InpPartialR * risk, _Digits);
   g.target = NormalizeDouble(entry + d * InpTargetR * risk, _Digits);
   g.triggered = false; g.partialDone = false; g.age = 0;
   g.sigTime = iTime(_Symbol, PERIOD_H1, 1); g.orderTicket = 0;

   double lots = Lots(risk);
   string sizeTxt = (lots > 0) ? DoubleToString(lots, 2) + " lots (" + DoubleToString(InpRiskPercent, 2) + "% risk)" : "below minimum lot for this risk";
   string icon = (d == 1) ? ":large_green_circle:" : ":red_circle:";
   int pct = (int)MathRound(InpPartialFrac * 100);
   string slack = icon + " *" + Side(d) + " SETUP: Gold (" + _Symbol + ")*" + (InpAutoTrade ? " | auto-trading" : "") + "\n"
                  + (replaced ? "_Replaces the earlier setup that had not triggered._\n" : "")
                  + "*The plan*\n"
                  + "• *Entry:* " + (d == 1 ? "buy" : "sell") + "-stop at *" + Px(g.entry) + "*\n"
                  + "• *Stop:* *" + Px(g.stop) + "* (" + DoubleToString(risk, 2) + " = 1R)\n"
                  + "• *Size:* " + sizeTxt + "\n"
                  + "• *Take profit 1:* close " + (string)pct + "% at *" + Px(g.partial) + "* (+" + DoubleToString(InpPartialR, 1) + "R), stop to entry\n"
                  + "• *Take profit 2:* *" + Px(g.target) + "* (+" + DoubleToString(InpTargetR, 1) + "R)\n"
                  + "• *Cancelled if:* the colour flips or " + (string)InpEntryExpiryBars + " hours pass first\n"
                  + "*Why it qualifies*\n" + why + "\n"
                  + "_Tested 2008-2026: 715 trades, 60% winners, +0.18R per trade after costs. Not financial advice._";
   string push = "Gold " + Side(d) + " setup | entry " + Px(g.entry) + " SL " + Px(g.stop) + " TP1 " + Px(g.partial) + " TP2 " + Px(g.target);
   Notify(slack, push);

   if(InpAutoTrade)
      PlaceOrder(lots);
   SaveState();
  }

//+------------------------------------------------------------------+
//| Position sizing from risk %                                      |
//+------------------------------------------------------------------+
double Lots(double riskPrice, double riskPct = -1)
  {
   if(riskPct < 0)
      riskPct = InpRiskPercent;
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(tv <= 0 || ts <= 0 || step <= 0)
      return(0);
   double money = AccountInfoDouble(ACCOUNT_BALANCE) * riskPct / 100.0;
   double perLot = riskPrice / ts * tv;
   if(perLot <= 0)
      return(0);
   double lots = MathFloor(money / perLot / step) * step;
   if(lots < vmin)
      return(0);
   return(MathMin(lots, vmax));
  }

//+------------------------------------------------------------------+
//| Orders                                                           |
//+------------------------------------------------------------------+
void PlaceOrder(double lots)
  {
   if(lots <= 0)
     {
      Notify(":warning: Gold setup skipped for auto-trading: the stop is too wide for your risk % at the minimum lot size.",
             "Gold setup skipped: stop too wide for risk %");
      return;
     }
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   datetime exp = TimeCurrent() + InpEntryExpiryBars * 3600;
   bool ok;
   if(g.dir == 1)
     {
      if(ask >= g.entry - minDist)
        {
         if(ask - g.entry > 0.2 * g.risk) { Print("GoldTrendEA: price already past entry, skipped"); return; }
         ok = trade.Buy(lots, _Symbol, ask, g.stop, g.target, "GTE");
        }
      else
         ok = trade.BuyStop(lots, g.entry, _Symbol, g.stop, g.target, ORDER_TIME_SPECIFIED, exp, "GTE");
     }
   else
     {
      if(bid <= g.entry + minDist)
        {
         if(g.entry - bid > 0.2 * g.risk) { Print("GoldTrendEA: price already past entry, skipped"); return; }
         ok = trade.Sell(lots, _Symbol, bid, g.stop, g.target, "GTE");
        }
      else
         ok = trade.SellStop(lots, g.entry, _Symbol, g.stop, g.target, ORDER_TIME_SPECIFIED, exp, "GTE");
     }
   if(!ok)
      Notify(":warning: Gold order failed: " + trade.ResultRetcodeDescription(), "Gold order failed: " + trade.ResultRetcodeDescription());
   else
      g.orderTicket = trade.ResultOrder();
  }

void CancelOrder()
  {
   if(!InpAutoTrade)
      return;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t > 0 && OrderGetInteger(ORDER_MAGIC) == InpMagic && OrderGetString(ORDER_SYMBOL) == _Symbol)
         trade.OrderDelete(t);
     }
  }

bool MyPosition(ulong &ticket)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic && PositionGetString(POSITION_SYMBOL) == _Symbol)
        { ticket = t; return(true); }
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| Tick-level management: entry, take profit 1, stop, take profit 2 |
//+------------------------------------------------------------------+
void ManageIntrabar()
  {
   if(g.dir == 0)
      return;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   int d = g.dir;
   double px = (d == 1) ? bid : ask;   // price we would exit at

   if(!g.triggered)
     {
      bool filled;
      if(InpAutoTrade)
        { ulong pt; filled = MyPosition(pt); }
      else
         filled = (d == 1) ? (ask >= g.entry) : (bid <= g.entry);
      if(filled)
        {
         g.triggered = true;
         Notify(":dart: *Entry triggered: Gold " + Side(d) + "* at " + Px(g.entry) + ". Stop " + Px(g.stop) + " | TP1 " + Px(g.partial) + " | TP2 " + Px(g.target),
                "Gold " + Side(d) + " entry " + Px(g.entry) + " triggered");
         SaveState();
        }
      return;
     }

   ulong pos = 0;
   bool open = InpAutoTrade ? MyPosition(pos) : true;

   if(InpAutoTrade && !open)
     {
      // closed by the broker at stop or take profit 2
      double r = LastClosedR();
      string what = (r > 1.0) ? ":trophy: *Take profit 2 hit" : (g.partialDone && r >= 0 ? ":shield: *Closed at entry after take profit 1" : ":octagonal_sign: *Stopped out");
      Notify(what + ": Gold " + Side(d) + "*. Trade result about " + DoubleToString(r, 2) + "R.",
             "Gold " + Side(d) + " closed, about " + DoubleToString(r, 2) + "R");
      Reset();
      SaveState();
      return;
     }

   // stop (alerts mode)
   if(!InpAutoTrade && ((d == 1 && px <= g.stop) || (d == -1 && px >= g.stop)))
     {
      double r = (g.partialDone ? InpPartialFrac * InpPartialR : 0) + (1 - (g.partialDone ? InpPartialFrac : 0)) * (g.stop - g.entry) * d / g.risk;
      string what = g.partialDone ? ":shield: *Closed at entry after take profit 1" : ":octagonal_sign: *Stopped out";
      Notify(what + ": Gold " + Side(d) + "* at " + Px(g.stop) + ". Result " + DoubleToString(r, 2) + "R.",
             "Gold " + Side(d) + " stop " + Px(g.stop) + " | " + DoubleToString(r, 2) + "R");
      Reset();
      SaveState();
      return;
     }

   // take profit 1: close part, stop to entry
   if(!g.partialDone && ((d == 1 && px >= g.partial) || (d == -1 && px <= g.partial)))
     {
      g.partialDone = true;
      g.stop = g.entry;
      if(InpAutoTrade && open && PositionSelectByTicket(pos))
        {
         double vol = PositionGetDouble(POSITION_VOLUME);
         double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
         double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
         double part = MathFloor(vol * InpPartialFrac / step) * step;
         if(part >= vmin && vol - part >= vmin)
            trade.PositionClosePartial(pos, part);
         trade.PositionModify(pos, g.entry, g.target);
        }
      int pct = (int)MathRound(InpPartialFrac * 100);
      Notify(":moneybag: *Take profit 1 hit: Gold " + Side(d) + "* at " + Px(g.partial) + ". Close " + (string)pct + "% and move the stop to entry " + Px(g.entry) + ". The rest targets " + Px(g.target) + ".",
             "Gold " + Side(d) + " TP1 " + Px(g.partial) + ": close " + (string)pct + "%, stop to entry");
      SaveState();
     }

   // take profit 2 (alerts mode; the broker handles it when auto-trading)
   if(!InpAutoTrade && ((d == 1 && px >= g.target) || (d == -1 && px <= g.target)))
     {
      double r = InpPartialFrac * InpPartialR + (1 - InpPartialFrac) * InpTargetR;
      Notify(":trophy: *Take profit 2 hit: Gold " + Side(d) + "* at " + Px(g.target) + ". Trade closed: +" + DoubleToString(r, 2) + "R.",
             "Gold " + Side(d) + " TP2 " + Px(g.target) + " | +" + DoubleToString(r, 2) + "R");
      Reset();
      SaveState();
     }
  }

double LastClosedR()
  {
   // sum of this trade's realised profit, expressed in R of the initial risk
   if(!HistorySelect(g.sigTime, TimeCurrent() + 60))
      return(0);
   double profit = 0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
     {
      ulong t = HistoryDealGetTicket(i);
      if(HistoryDealGetInteger(t, DEAL_MAGIC) == InpMagic && HistoryDealGetString(t, DEAL_SYMBOL) == _Symbol)
         profit += HistoryDealGetDouble(t, DEAL_PROFIT) + HistoryDealGetDouble(t, DEAL_SWAP) + HistoryDealGetDouble(t, DEAL_COMMISSION);
     }
   double riskMoney = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPercent / 100.0;
   return(riskMoney > 0 ? profit / riskMoney : 0);
  }

void Reset()
  {
   g.dir = 0; g.entry = g.stop = g.risk = g.partial = g.target = 0;
   g.triggered = g.partialDone = false; g.age = 0; g.sigTime = 0; g.orderTicket = 0;
  }

//+------------------------------------------------------------------+
//| State persistence (survives terminal restarts)                   |
//+------------------------------------------------------------------+
void SaveState()
  {
   if(MQLInfoInteger(MQL_TESTER))
      return;
   GlobalVariableSet(GV + "dir", g.dir);
   GlobalVariableSet(GV + "entry", g.entry);
   GlobalVariableSet(GV + "stop", g.stop);
   GlobalVariableSet(GV + "risk", g.risk);
   GlobalVariableSet(GV + "partial", g.partial);
   GlobalVariableSet(GV + "target", g.target);
   GlobalVariableSet(GV + "trig", g.triggered ? 1 : 0);
   GlobalVariableSet(GV + "pdone", g.partialDone ? 1 : 0);
   GlobalVariableSet(GV + "age", g.age);
   GlobalVariableSet(GV + "sig", (double)g.sigTime);
  }

void LoadState()
  {
   Reset();
   if(MQLInfoInteger(MQL_TESTER) || !GlobalVariableCheck(GV + "dir"))
      return;
   g.dir = (int)GlobalVariableGet(GV + "dir");
   g.entry = GlobalVariableGet(GV + "entry");
   g.stop = GlobalVariableGet(GV + "stop");
   g.risk = GlobalVariableGet(GV + "risk");
   g.partial = GlobalVariableGet(GV + "partial");
   g.target = GlobalVariableGet(GV + "target");
   g.triggered = GlobalVariableGet(GV + "trig") > 0;
   g.partialDone = GlobalVariableGet(GV + "pdone") > 0;
   g.age = (int)GlobalVariableGet(GV + "age");
   g.sigTime = (datetime)GlobalVariableGet(GV + "sig");
   if(g.dir != 0)
      Print("GoldTrendEA: restored ", Side(g.dir), " idea, entry ", Px(g.entry), (g.triggered ? " (in trade)" : " (pending)"));
  }

//+------------------------------------------------------------------+
//| Second setup: inside-day breakout                                |
//| After a daily candle inside the previous day's range: buy-stop   |
//| at its high, sell-stop at its low (one cancels the other), stop  |
//| at the other side, close at the next daily close. Tested         |
//| 2008-2026: 726 trades, 49% winners, +0.10R after costs. Uses the |
//| broker's D1 candles: these should roll at 17:00 New York (most   |
//| gold brokers on GMT+2/+3 server time do).                        |
//+------------------------------------------------------------------+
void OnNewD1()
  {
   // the previous trade day has closed: settle whatever is left
   if(ib.state == 2)
     {
      double px = (ib.dir == 1) ? SymbolInfoDouble(_Symbol, SYMBOL_BID) : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(InpAutoTrade)
         IBCloseAll();
      double r = (px - ib.entry) * ib.dir / MathAbs(ib.entry - ib.stop);
      Notify(":checkered_flag: *Inside-day trade: close the Gold " + Side(ib.dir) + " now* (daily close, " + Px(px) + "). Result about " + DoubleToString(r, 2) + "R.",
             "Gold inside-day " + Side(ib.dir) + ": close now at the daily close, about " + DoubleToString(r, 2) + "R");
     }
   else if(ib.state == 1)
     {
      if(InpAutoTrade)
         IBCloseAll();
      Notify(":heavy_minus_sign: *Inside-day setup cancelled: Gold*. Price stayed between " + Px(ib.lo) + " and " + Px(ib.hi) + ". No trade.",
             "Gold inside-day cancelled: no breakout");
     }
   IBReset();

   double h1 = iHigh(_Symbol, PERIOD_D1, 1), l1 = iLow(_Symbol, PERIOD_D1, 1);
   double h2 = iHigh(_Symbol, PERIOD_D1, 2), l2 = iLow(_Symbol, PERIOD_D1, 2);
   if(h1 == 0 || h2 == 0 || !(h1 < h2 && l1 > l2))
     { SaveIB(); return; }

   ib.state = 1; ib.hi = NormalizeDouble(h1, _Digits); ib.lo = NormalizeDouble(l1, _Digits);
   double riskPct = InpRiskPercent * InpInsideDayRisk;
   Notify(":package: *INSIDE-DAY SETUP: Gold (XAUUSD)*\n"
          "Yesterday's range (" + Px(ib.lo) + " to " + Px(ib.hi) + ") stayed inside the day before's. Separate from the trend setups.\n"
          "• *Buy-stop:* *" + Px(ib.hi) + "*, stop *" + Px(ib.lo) + "*\n"
          "• *Sell-stop:* *" + Px(ib.lo) + "*, stop *" + Px(ib.hi) + "*\n"
          "• One cancels the other. Risk " + DoubleToString(ib.hi - ib.lo, 2) + " = 1R, at " + DoubleToString(riskPct, 2) + "% of the account\n"
          "• No take-profit: close at the next daily close. Cancelled if neither side trades today.\n"
          "_Tested 2008-2026: 726 trades, 49% winners, +0.10R per trade after costs. Not financial advice._",
          "Gold inside-day setup: buy-stop " + Px(ib.hi) + " / sell-stop " + Px(ib.lo) + ", stop at the other side, close at the daily close");
   if(InpAutoTrade)
     {
      double lots = Lots(ib.hi - ib.lo, riskPct);
      if(lots <= 0)
         Notify(":warning: Inside-day setup skipped for auto-trading: the range is too wide for your risk % at the minimum lot size.",
                "Gold inside-day skipped: range too wide for risk %");
      else
        {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK), bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         bool ok;
         if(ask >= ib.hi)        // gapped through: the research fills at the open
            ok = ibTrade.Buy(lots, _Symbol, ask, ib.lo, 0, "GTE-ID");
         else if(bid <= ib.lo)
            ok = ibTrade.Sell(lots, _Symbol, bid, ib.hi, 0, "GTE-ID");
         else
            ok = ibTrade.BuyStop(lots, ib.hi, _Symbol, ib.lo, 0, ORDER_TIME_GTC, 0, "GTE-ID")
                 && ibTrade.SellStop(lots, ib.lo, _Symbol, ib.hi, 0, ORDER_TIME_GTC, 0, "GTE-ID");
         if(!ok)
            Notify(":warning: Inside-day order failed: " + ibTrade.ResultRetcodeDescription(),
                   "Gold inside-day order failed: " + ibTrade.ResultRetcodeDescription());
        }
     }
   SaveIB();
  }

void ManageIB()
  {
   if(ib.state == 0)
      return;
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID), ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(ib.state == 1)
     {
      int d = 0;
      double fill = 0;
      if(InpAutoTrade)
        {
         for(int i = PositionsTotal() - 1; i >= 0; i--)
           {
            ulong t = PositionGetTicket(i);
            if(t > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic + 1 && PositionGetString(POSITION_SYMBOL) == _Symbol)
              {
               d = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
               fill = PositionGetDouble(POSITION_PRICE_OPEN);
              }
           }
         if(d != 0)
            IBDeletePending();   // one cancels the other
        }
      else if(ask >= ib.hi) { d = 1;  fill = MathMax(ask, ib.hi); }
      else if(bid <= ib.lo) { d = -1; fill = MathMin(bid, ib.lo); }
      if(d == 0)
         return;
      ib.state = 2; ib.dir = d; ib.entry = fill; ib.stop = (d == 1) ? ib.lo : ib.hi;
      Notify(":dart: *Inside-day entry: Gold " + Side(d) + "* at " + Px(fill) + ". " + (d == 1 ? "Delete the sell-stop. " : "Delete the buy-stop. ") +
             "Stop " + Px(ib.stop) + "; close at the daily close.",
             "Gold inside-day " + Side(d) + " entry " + Px(fill) + ", stop " + Px(ib.stop));
      SaveIB();
      return;
     }
   // in the trade: watch the stop
   bool gone;
   if(InpAutoTrade)
     {
      gone = true;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong t = PositionGetTicket(i);
         if(t > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic + 1 && PositionGetString(POSITION_SYMBOL) == _Symbol)
            gone = false;
        }
     }
   else
      gone = (ib.dir == 1) ? (bid <= ib.stop) : (ask >= ib.stop);
   if(gone)
     {
      Notify(":octagonal_sign: *Inside-day stopped out: Gold " + Side(ib.dir) + "* at " + Px(ib.stop) + ". Result about -1R.",
             "Gold inside-day " + Side(ib.dir) + " stopped at " + Px(ib.stop));
      if(InpAutoTrade)
         IBDeletePending();
      IBReset();
      SaveIB();
     }
  }

void IBDeletePending()
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t > 0 && OrderGetInteger(ORDER_MAGIC) == InpMagic + 1 && OrderGetString(ORDER_SYMBOL) == _Symbol)
         ibTrade.OrderDelete(t);
     }
  }

void IBCloseAll()
  {
   IBDeletePending();
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic + 1 && PositionGetString(POSITION_SYMBOL) == _Symbol)
         ibTrade.PositionClose(t);
     }
  }

void IBReset()
  {
   ib.state = 0; ib.dir = 0; ib.hi = ib.lo = ib.entry = ib.stop = 0;
  }

void SaveIB()
  {
   if(MQLInfoInteger(MQL_TESTER))
      return;
   GlobalVariableSet(GV + "ib_state", ib.state);
   GlobalVariableSet(GV + "ib_dir", ib.dir);
   GlobalVariableSet(GV + "ib_hi", ib.hi);
   GlobalVariableSet(GV + "ib_lo", ib.lo);
   GlobalVariableSet(GV + "ib_entry", ib.entry);
   GlobalVariableSet(GV + "ib_stop", ib.stop);
   GlobalVariableSet(GV + "ib_day", (double)iTime(_Symbol, PERIOD_D1, 0));
  }

void LoadIB()
  {
   IBReset();
   if(MQLInfoInteger(MQL_TESTER) || !GlobalVariableCheck(GV + "ib_state"))
      return;
   ib.state = (int)GlobalVariableGet(GV + "ib_state");
   ib.dir = (int)GlobalVariableGet(GV + "ib_dir");
   ib.hi = GlobalVariableGet(GV + "ib_hi");
   ib.lo = GlobalVariableGet(GV + "ib_lo");
   ib.entry = GlobalVariableGet(GV + "ib_entry");
   ib.stop = GlobalVariableGet(GV + "ib_stop");
   // restarted on a later day: let OnNewD1 settle it on the first tick
   datetime saved = (datetime)GlobalVariableGet(GV + "ib_day");
   g_lastD1 = (saved != 0 && saved != iTime(_Symbol, PERIOD_D1, 0)) ? saved : 0;
  }

//+------------------------------------------------------------------+
//| Notifications                                                    |
//+------------------------------------------------------------------+
void Notify(string slackText, string pushText)
  {
   Print(pushText);
   if(MQLInfoInteger(MQL_TESTER))
      return;
   if(InpPush)
     {
      string p = pushText;
      if(StringLen(p) > 255) p = StringSubstr(p, 0, 252) + "...";
      if(!SendNotification(p))
         Print("GoldTrendEA: push failed (", GetLastError(), "). Set your MetaQuotes ID in Tools > Options > Notifications.");
     }
   if(InpSlack && InpSlackWebhook != "")
      SlackPost(slackText);
  }

void SlackPost(string text)
  {
   StringReplace(text, "\\", "\\\\");
   StringReplace(text, "\"", "\\\"");
   StringReplace(text, "\r", "");
   StringReplace(text, "\n", "\\n");
   string json = "{\"text\":\"" + text + "\"}";
   char data[], res[];
   string rh;
   int n = StringToCharArray(json, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(n > 0) ArrayResize(data, n - 1);
   ResetLastError();
   int code = WebRequest("POST", InpSlackWebhook, "Content-Type: application/json\r\n", 5000, data, res, rh);
   if(code == -1)
      Print("GoldTrendEA: Slack failed (", GetLastError(), "). Add https://hooks.slack.com in Tools > Options > Expert Advisors > Allow WebRequest.");
  }
//+------------------------------------------------------------------+
