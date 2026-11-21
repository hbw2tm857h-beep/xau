// What the bot says, computed from the same files the hourly run writes
// (state.json, journal.json, nursery.json). These mirror track_record.py so
// the bot, #track-record and the Open now post always agree.

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
    out.push({ t: j.exit_time, market, side: j.dir === 1 ? "BUY" : "SELL", kind, r: j.r, how: how(j),
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
    "-# Every trade is in #track-record.",
  ].join("\n");
}
