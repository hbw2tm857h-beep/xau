//+------------------------------------------------------------------+
//| AurumExportHistory.mq5                                           |
//| Exports your closed positions to MQL5\Files\aurum_history.csv     |
//| for the Aurum research lab. READ-ONLY: it never places, changes  |
//| or closes an order. Run it as a script (drag onto any chart).    |
//+------------------------------------------------------------------+
#property copyright   "Aurum research"
#property version     "1.00"
#property description "Exports closed positions (with the INITIAL stop from each opening order and the magic number) to a CSV for Aurum. Read-only."
#property script_show_inputs

input datetime InpFrom     = D'2000.01.01 00:00'; // Export positions opened from this date
input bool     InpGoldOnly = true;                // Only XAU / gold symbols
input string   InpFile     = "aurum_history.csv"; // File name (saved in MQL5\Files)

struct Pos
  {
   ulong    id;
   string   sym;
   int      dir;
   double   vol;
   datetime ot;
   double   op;
   double   sl;
   double   tp;
   datetime ct;
   double   cvol;
   double   cpx;     // volume-weighted close price (sum of price * volume)
   double   profit;
   double   comm;
   double   swap;
   long     magic;
   string   cmt;
  };

Pos P[];
int N = 0;

int FindPos(const ulong id)
  {
   for(int i = N - 1; i >= 0; i--)
      if(P[i].id == id)
         return i;
   return -1;
  }

bool IsGold(const string s)
  {
   string u = s;
   StringToUpper(u);
   return StringFind(u, "XAU") >= 0 || StringFind(u, "GOLD") >= 0;
  }

string Clean(string s)
  {
   StringReplace(s, ",", ";");
   StringReplace(s, "\"", "'");
   return s;
  }

void OnStart()
  {
   if(!HistorySelect(InpFrom, TimeCurrent() + 86400))
     {
      Print("Aurum export: HistorySelect failed");
      return;
     }
   int deals = HistoryDealsTotal();
   for(int k = 0; k < deals; k++)
     {
      ulong d = HistoryDealGetTicket(k);
      if(d == 0)
         continue;
      long entry = HistoryDealGetInteger(d, DEAL_ENTRY);
      long type  = HistoryDealGetInteger(d, DEAL_TYPE);
      if(type != DEAL_TYPE_BUY && type != DEAL_TYPE_SELL)
         continue;                                   // skip balance, credit, etc.
      string sym = HistoryDealGetString(d, DEAL_SYMBOL);
      if(InpGoldOnly && !IsGold(sym))
         continue;
      ulong pid = (ulong)HistoryDealGetInteger(d, DEAL_POSITION_ID);
      double vol = HistoryDealGetDouble(d, DEAL_VOLUME);
      double px  = HistoryDealGetDouble(d, DEAL_PRICE);
      datetime t = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
      int i = FindPos(pid);
      if(entry == DEAL_ENTRY_IN)
        {
         if(i < 0)
           {
            N++;
            ArrayResize(P, N, 256);
            i = N - 1;
            P[i].id = pid; P[i].sym = sym; P[i].dir = (type == DEAL_TYPE_BUY ? 1 : -1);
            P[i].vol = 0; P[i].ot = t; P[i].op = 0; P[i].sl = 0; P[i].tp = 0; P[i].ct = 0;
            P[i].cvol = 0; P[i].cpx = 0; P[i].profit = 0; P[i].comm = 0; P[i].swap = 0;
            P[i].magic = HistoryDealGetInteger(d, DEAL_MAGIC);
            P[i].cmt = HistoryDealGetString(d, DEAL_COMMENT);
            // the stop and target attached to the ORDER that opened the position = the initial plan
            ulong ord = (ulong)HistoryDealGetInteger(d, DEAL_ORDER);
            if(ord > 0 && HistoryOrderSelect(ord))
              {
               P[i].sl = HistoryOrderGetDouble(ord, ORDER_SL);
               P[i].tp = HistoryOrderGetDouble(ord, ORDER_TP);
              }
           }
         // scaling in: volume-weighted entry price
         P[i].op = (P[i].op * P[i].vol + px * vol) / (P[i].vol + vol);
         P[i].vol += vol;
         P[i].comm += HistoryDealGetDouble(d, DEAL_COMMISSION);
        }
      else if(i >= 0)                                // OUT, OUT_BY or INOUT: (partial) close
        {
         P[i].cvol += vol;
         P[i].cpx  += px * vol;
         P[i].ct = t;
         P[i].profit += HistoryDealGetDouble(d, DEAL_PROFIT);
         P[i].comm   += HistoryDealGetDouble(d, DEAL_COMMISSION);
         P[i].swap   += HistoryDealGetDouble(d, DEAL_SWAP);
        }
     }
   double off = (double)(TimeTradeServer() - TimeGMT()) / 3600.0;
   int h = FileOpen(InpFile, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
     {
      Print("Aurum export: cannot open file ", InpFile);
      return;
     }
   FileWrite(h, "Position,Symbol,Type,Volume,Open Time,Open Price,Initial SL,Initial TP,Close Time,Close Price,"
                "Profit,Commission,Swap,Magic,Comment,Server UTC Offset h");
   int written = 0;
   for(int i = 0; i < N; i++)
     {
      if(P[i].cvol < P[i].vol * 0.999 || P[i].ct == 0)
         continue;                                   // still open: skip
      int dg = (int)SymbolInfoInteger(P[i].sym, SYMBOL_DIGITS);
      if(dg <= 0)
         dg = 3;
      string row = StringFormat("%I64u,%s,%s,%.2f,%s,%s,%s,%s,%s,%s,%.2f,%.2f,%.2f,%I64d,%s,%.1f",
                                P[i].id, P[i].sym, (P[i].dir > 0 ? "buy" : "sell"), P[i].vol,
                                TimeToString(P[i].ot, TIME_DATE | TIME_SECONDS), DoubleToString(P[i].op, dg),
                                (P[i].sl > 0 ? DoubleToString(P[i].sl, dg) : ""), (P[i].tp > 0 ? DoubleToString(P[i].tp, dg) : ""),
                                TimeToString(P[i].ct, TIME_DATE | TIME_SECONDS), DoubleToString(P[i].cpx / P[i].cvol, dg),
                                P[i].profit, P[i].comm, P[i].swap, P[i].magic, Clean(P[i].cmt), off);
      FileWrite(h, row);
      written++;
     }
   FileClose(h);
   string where = TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\" + InpFile;
   Print("Aurum export: ", written, " closed positions written to ", where);
   Alert("Aurum export: ", written, " closed positions saved to\n", where);
  }
//+------------------------------------------------------------------+
