// What the bot says, computed from the same files the hourly run writes
// (state.json, journal.json, nursery.json). These mirror track_record.py so
// the bot, <#1573110539008090112> and the Open now post always agree.

export const GO_LIVE = "2026-11-14";
const ALERTED = new Set(["live", "shadow"]);
const MARKET = {
  trend: ["Gold", "trend"], inside_day: ["Gold", "breakout"], h4_trend: ["Gold", "4H trend"],
  btc_trend: ["BTC/USD", "trend"], eth_inside_day: ["ETH/USD", "breakout"],
};
const IBS = { SPY: "S&P 500", QQQ: "Nasdaq 100", DIA: "Dow", IWM: "Russell 2000" };
const MARKET_NAMES = { btc: "BTC/USD", eth: "ETH/USD" };

export function px(x) {
  return x == null ? "-" : Number(x).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const sgn = (r) => (r >= 0 ? "+" : "") + r.toFixed(2);
const day = (t) => new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

function tiers(nursery) {
  const out = {};
  for (const [k, v] of Object.entries(nursery.strategies || nursery)) out[k] = v && typeof v === "object" ? v.tier : v;
  return out;
}

function how(j) {
  const h = j.how, r = j.r || 0;
  if (h === "target") return "TP2 hit";
  if (h === "stop" || h === "h4_stop") return r > -0.5 ? "TP1, then entry" : "stopped out";
  if (h === "ib_stop") return "stopped out";
  if (h === "ib_close") return "daily close";
  if (h === "ibs_exit") return "exit signal";
  return "closed";
}

// Closed trades members were alerted to, oldest first.
export function rows(journal, nursery) {
  const tier = tiers(nursery);
  const out = [];
  for (const j of journal) {
    const s = j.strategy || "trend";
    if (!ALERTED.has(tier[s]) || (j.exit_time || "") < GO_LIVE) continue;
    const [market, kind] = s === "us_ibs" ? [IBS[j.symbol] || j.symbol || "US index", "rebound"] : MARKET[s] || [s, ""];
    out.push({ s, t: j.exit_time, market, side: j.dir === 1 ? "BUY" : "SELL", kind, r: j.r, how: how(j),
      open: px(j.entry), close: px(j.exit) });
  }
  return out.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));
}

export function stats(rs) {
  const wins = rs.filter((r) => r > 0), losses = rs.filter((r) => r < 0);
  let peak = 0, run = 0, dd = 0, streak = 0, worst = 0;
  for (const r of rs) {
    run += r; peak = Math.max(peak, run); dd = Math.max(dd, peak - run);
    streak = r < 0 ? streak + 1 : 0; worst = Math.max(worst, streak);
  }
  const total = rs.reduce((a, b) => a + b, 0);
  const lost = -losses.reduce((a, b) => a + b, 0);
  return { n: rs.length, wins: wins.length, total, avg: rs.length ? total / rs.length : 0,
    pf: lost > 0 ? wins.reduce((a, b) => a + b, 0) / lost : null, dd, streak: worst };
}

// Positions and pending orders members were alerted to.
export function openRows(state, nursery) {
  const tier = tiers(nursery);
  const books = [["Gold", state], ...Object.entries(state.markets || {}).map(([k, m]) => [MARKET_NAMES[k] || k, m])];
  const out = [];
  for (const [market, book] of books) {
    for (const key of ["idea", "ib"]) {
      const p = (book || {})[key];
      if (!p || !ALERTED.has(tier[p.strategy || (key === "idea" ? "trend" : "inside_day")])) continue;
      if (key === "ib" && !p.triggered) {
        out.push(`**${market} breakout** · orders waiting\n-# Buy-stop ${px(p.hi)} · Sell-stop ${px(p.lo)}`);
        continue;
      }
      const side = p.dir === 1 ? "BUY" : "SELL";
      if (!p.triggered) {
        out.push(`**${market} ${side}** · order waiting at ${px(p.entry)}\n-# Stop loss ${px(p.stop)}`);
        continue;
      }
      if (key === "ib") {
        out.push(`**${market} ${side}** · in from ${px(p.entry)}\n-# Stop loss ${px(p.stop)} · Exit at the daily close`);
        continue;
      }
      const stage = p.done ? "TP1 hit, stop at entry" : `TP1 ${px(p.partial)}`;
      out.push(`**${market} ${side}** · in from ${px(p.entry)}\n-# Stop loss ${px(p.stop)} · ${stage} · TP2 ${px(p.target)}`);
    }
  }
  return out;
}

export function openText(state, nursery) {
  const rs = openRows(state, nursery);
  return `## Open now\n${rs.length ? rs.join("\n") : "No open trades right now."}`;
}

export function statsText(journal, nursery) {
  const rs = rows(journal, nursery);
  if (!rs.length) return "## Track record\nNo closed trades yet.";
  const s = stats(rs.map((r) => r.r));
  const pf = s.pf == null ? "no losses" : s.pf.toFixed(2);
  const last = rs.slice(-5).reverse()
    .map((r) => `**${sgn(r.r)}R** · ${r.market} ${r.side} ${r.kind} · ${day(r.t)}\n-# Open ${r.open} · Close ${r.close} · ${r.how}`);
  return [
    `## Track record since 14 November 2026`,
    `**${s.n} trade${s.n === 1 ? "" : "s"}, ${s.wins} winner${s.wins === 1 ? "" : "s"} · ${sgn(s.total)}R**`,
    `Average ${sgn(s.avg)}R per trade · Profit factor ${pf} · Biggest drop ${s.dd.toFixed(2)}R · Longest losing run ${s.streak}`,
    `That's ${sgn(s.total)}% at 1% risk per trade.`,
    "",
    "**Latest trades**",
    ...last,
    "-# Every trade is in <#1573110539008090112>.",
  ].join("\n");
}

const UKZ = "Europe/London";
const ukTime = (d) => d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: UKZ });
const ukDay = (d) => d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: UKZ });

function tradeLine(r) {
  return `**${sgn(r.r)}R** · ${r.market} ${r.side} ${r.kind} · ${day(r.t)}\n-# Open ${r.open} · Close ${r.close} · ${r.how}`;
}

function summary(rs) {
  const s = stats(rs.map((r) => r.r));
  return `**${s.n} trade${s.n === 1 ? "" : "s"}, ${s.wins} winner${s.wins === 1 ? "" : "s"} · ${sgn(s.total)}R**`;
}

// /status: is the bot running, and when did it last check?
export function statusText(state, now = new Date()) {
  const lr = state.last_run || {};
  if (!lr.started) return "## Status\nNo hourly check recorded yet.";
  const t = new Date(lr.started);
  const mins = Math.round((now - t) / 60000);
  const ago = mins < 60 ? `${mins} min ago` : `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, "0")}m ago`;
  const healthy = !lr.error && !(lr.failed || []).length && mins <= 90;
  const next = new Date(t.getTime() + 3600000);
  return [
    "## Status",
    healthy ? "**Running normally.**" : "**The last check needs a look.** Alerts may be delayed.",
    `Last check: ${ukDay(t)} ${ukTime(t)} UK (${ago})`,
    `Next check: about ${ukTime(next)} UK`,
    "-# The bot checks every market a few minutes after each hourly candle closes.",
  ].join("\n");
}

const MARKET_KEYS = { gold: ["Gold"], btc: ["BTC/USD"], eth: ["ETH/USD"],
  us: ["S&P 500", "Nasdaq 100", "Dow", "Russell 2000", "US index"] };
const MARKET_LABEL = { gold: "Gold", btc: "Bitcoin", eth: "Ether", us: "US indices" };

// /history: closed trades for one market, newest first.
export function historyText(journal, nursery, key) {
  const rs = rows(journal, nursery).filter((r) => (MARKET_KEYS[key] || []).includes(r.market));
  const head = `## ${MARKET_LABEL[key] || key} · closed trades`;
  if (!rs.length) return `${head}\nNo closed trades yet since alerts went live on 14 November 2026.`;
  const shown = rs.slice(-10).reverse().map(tradeLine);
  const more = rs.length > 10 ? `\n-# Showing the latest 10 of ${rs.length}.` : "";
  return `${head}\n${summary(rs)}\n\n${shown.join("\n")}${more}`;
}

// /month: this calendar month so far.
export function monthText(journal, nursery, now = new Date()) {
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)).toISOString();
  const rs = rows(journal, nursery).filter((r) => r.t >= start);
  const name = now.toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
  if (!rs.length) return `## ${name} so far\nNo trades closed yet this month.`;
  const s = stats(rs.map((r) => r.r));
  const pf = s.pf == null ? "no losses" : s.pf.toFixed(2);
  return [`## ${name} so far`, summary(rs),
    `Average ${sgn(s.avg)}R per trade · Profit factor ${pf} · Biggest drop ${s.dd.toFixed(2)}R`,
    `That's ${sgn(s.total)}% at 1% risk per trade.`, "", ...rs.slice().reverse().map(tradeLine)].join("\n");
}

const STRATEGY_NAMES = { trend: "Gold trend", inside_day: "Gold breakout", btc_trend: "Bitcoin trend",
  eth_inside_day: "Ether breakout", us_ibs: "US index rebounds" };

// /backtest: what testing expects from each alerted strategy, beside live results.
export function backtestText(journal, nursery) {
  const tier = tiers(nursery);
  const strategies = nursery.strategies || {};
  const live = rows(journal, nursery);
  const lines = Object.keys(STRATEGY_NAMES).filter((k) => ALERTED.has(tier[k])).map((k) => {
    const x = strategies[k] || {};
    const mine = live.filter((r) => r.s === k).map((r) => r.r);
    const now = mine.length ? `${mine.length} trade${mine.length === 1 ? "" : "s"}, ${sgn(mine.reduce((a, b) => a + b, 0) / mine.length)}R average`
      : "no trades yet";
    return `**${STRATEGY_NAMES[k]}**\nTested: ${x.expected_n} trades, ${x.expected_win}% winners, ${sgn(x.expected_avg_r)}R per trade after costs\n-# Live: ${now}`;
  });
  return ["## Tested vs live", ...lines, "-# Testing covers years of history the rules were never tuned on. Full write-ups are in <#1573110551326887976>."].join("\n");
}

// /hours: which markets are open right now.
export function hoursText(now = new Date()) {
  const ny = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
  const wd = ny.getDay(), h = ny.getHours() + ny.getMinutes() / 60;   // Sun = 0
  const goldOpen = !(wd === 6 || (wd === 5 && h >= 17) || (wd === 0 && h < 18));
  const usOpen = wd >= 1 && wd <= 5 && h >= 9.5 && h < 16;
  const dot = (o) => (o ? "🟢 open" : "⚪ closed");
  return [
    `## Markets now · ${ukTime(now)} UK`,
    `**Gold** ${dot(goldOpen)}\n-# Sunday 23:00 to Friday 22:00 UK, with a daily break around 22:00`,
    `**Bitcoin and Ether** ${dot(true)}\n-# Every day, around the clock`,
    `**US indices** ${dot(usOpen)}\n-# 14:30 to 21:00 UK on weekdays. Rebound alerts come just after the close`,
    "-# UK times shift by an hour for a few weeks a year when the UK and US change clocks on different dates.",
  ].join("\n");
}

export const GLOSSARY = {
  r: ["R", "The amount you risk on a trade: the distance from entry to stop loss. +2R means you made twice what you risked; -1R means the stop was hit. At 1% risk per trade, 1R is 1% of your account."],
  tp1: ["Take profit 1 (TP1)", "The first target. Close half the trade there and move the stop to your entry, so the rest can't lose."],
  tp2: ["Take profit 2 (TP2)", "The final target for the rest of the trade."],
  stop: ["Stop loss", "The price where the trade closes for a loss if it goes wrong. Always set it when the order fills."],
  stoporder: ["Buy-stop and sell-stop", "Pending orders that only fill if price moves to them: a buy-stop sits above the price, a sell-stop below. The trade only starts if the market confirms the move."],
  insideday: ["Inside day", "A day whose high and low both stay inside the day before. It often comes before a breakout, so orders go above its high and below its low."],
  heikin: ["Heikin Ashi", "Candles averaged from normal candles. They smooth out noise, so trends show as runs of one colour."],
  pf: ["Profit factor", "Money won on winning trades divided by money lost on losing ones. Above 1 makes money; above 1.3 is good."],
  drawdown: ["Biggest drop", "The largest fall from a high point in results to a later low, in R. It shows the worst run you'd have sat through."],
  ibs: ["US index rebounds", "Buys a US index after a sharp fall that closes near the day's low, then sells on the first close above the previous day's high."],
};

export function glossaryText(key) {
  const g = GLOSSARY[key];
  return g ? `## ${g[0]}\n${g[1]}\n-# More terms in <#1573453645805256824>.` : "Term not found. See <#1573453645805256824>.";
}

// /calendar: this week's high-impact US releases, saved to calendar.json by
// the calendar workflow (Forex Factory's feed rate-limits Cloudflare). The
// whole week is shown; releases already out are struck through.
export function calendarText(saved, now = new Date()) {
  const ev = saved.map((r) => ({ t: new Date(r.t), title: r.title })).sort((a, b) => a.t - b.t);
  if (!ev.length) return "## US news this week\nNo high-impact US releases this week.\n-# Next week's list arrives on Sunday evening.";
  const days = new Map();
  let upcoming = 0;
  for (const e of ev) {
    const d = ukDay(e.t);
    if (!days.has(d)) days.set(d, []);
    const past = e.t < new Date(now.getTime() - 3600000);
    if (!past) upcoming++;
    days.get(d).push(past ? `~~${ukTime(e.t)} · ${e.title}~~` : `${ukTime(e.t)} · ${e.title}`);
  }
  const note = upcoming ? `${upcoming} still to come. Struck-through releases are already out.`
    : "All of this week's releases are out. Next week's list arrives on Sunday evening.";
  return ["## US news this week", ...[...days].map(([d, ls]) => `**${d}**\n${ls.join("\n")}`), note,
    "-# High-impact US releases, UK time. Gold, US indices and crypto can move fast around these."].join("\n");
}
