// LumnFx Discord app: slash commands over Discord's HTTP interactions API,
// running as a Cloudflare Worker. No gateway connection and no dependencies.
//
//   /open    trades and orders running now
//   /stats   the live track record in numbers, with the latest trades
//   /alerts  choose which markets ping you (Gold, Crypto, US indices)
//   /help    what the bot does
//
// Data comes from the public repo's state.json, journal.json and nursery.json,
// which the hourly run commits, so answers match #track-record.
// Secrets (set with `wrangler secret put`): DISCORD_BOT_TOKEN.
// Vars (wrangler.toml): DISCORD_APP_ID, DISCORD_PUBLIC_KEY, GUILD_ID.

import { openText, statsText } from "./data.js";

const RAW = "https://raw.githubusercontent.com/hbw2tm857h-beep/xau/main/";
const API = "https://discord.com/api/v10";
const EPHEMERAL = 64;

// Market alert roles, as used by signals.py's discord_role_mentions.
const ROLES = [
  { key: "gold", label: "Gold", id: "1573546702672236686" },
  { key: "crypto", label: "Crypto", id: "1573546792585273395" },
  { key: "us", label: "US indices", id: "1573546811111641098" },
];

export const COMMANDS = [
  { name: "open", description: "Trades and orders running right now", type: 1 },
  { name: "stats", description: "The live track record in numbers", type: 1 },
  { name: "alerts", description: "Choose which markets ping you", type: 1 },
  { name: "help", description: "What the LumnFx bot can do", type: 1 },
];

const HELP = [
  "## LumnFx bot",
  "`/open` Trades and orders running right now.",
  "`/stats` The live track record: win rate, total R, profit factor, biggest drop and the latest trades.",
  "`/alerts` Choose which markets ping you: Gold, Crypto, US indices.",
  "-# Only you can see the bot's replies. Alerts themselves are posted in the signal channels.",
].join("\n");

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });

const reply = (content, extra = {}) =>
  ({ type: 4, data: { content, flags: EPHEMERAL, allowed_mentions: { parse: [] }, ...extra } });

function hex(s) {
  return new Uint8Array(s.match(/.{2}/g).map((b) => parseInt(b, 16)));
}

async function verify(publicKey, signature, timestamp, body) {
  try {
    const key = await crypto.subtle.importKey("raw", hex(publicKey), { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify("Ed25519", key, hex(signature), new TextEncoder().encode(timestamp + body));
  } catch {
    return false;
  }
}

async function load(name) {
  const r = await fetch(RAW + name, { cf: { cacheTtl: 60, cacheEverything: true } });
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
  return r.json();
}

function alertButtons(memberRoles) {
  return [{
    type: 1,
    components: ROLES.map((r) => {
      const on = memberRoles.includes(r.id);
      return { type: 2, style: on ? 3 : 2, label: `${r.label}: ${on ? "on" : "off"}`, custom_id: `role:${r.key}` };
    }),
  }];
}

const ALERTS_TEXT = "## Your alerts\nTap a market to turn its pings on or off. Green means you'll be pinged.";

async function command(i, env) {
  const name = i.data.name;
  try {
    if (name === "open") {
      const [state, nursery] = await Promise.all([load("state.json"), load("nursery.json")]);
      return reply(openText(state, nursery));
    }
    if (name === "stats") {
      const [journal, nursery] = await Promise.all([load("journal.json"), load("nursery.json")]);
      return reply(statsText(journal, nursery));
    }
  } catch (e) {
    return reply("Couldn't load the latest data just now. Try again in a minute.");
  }
  if (name === "alerts") {
    if (!i.member) return reply("Use this in the LumnFx server.");
    return reply(ALERTS_TEXT, { components: alertButtons(i.member.roles) });
  }
  if (name === "help") return reply(HELP);
  return reply("Unknown command.");
}

async function component(i, env) {
  const [kind, key] = (i.data.custom_id || "").split(":");
  const role = ROLES.find((r) => r.key === key);
  if (kind !== "role" || !role || !i.member) return { type: 6 };
  const roles = [...i.member.roles];
  const has = roles.includes(role.id);
  const r = await fetch(`${API}/guilds/${i.guild_id}/members/${i.member.user.id}/roles/${role.id}`, {
    method: has ? "DELETE" : "PUT",
    headers: { Authorization: `Bot ${env.DISCORD_BOT_TOKEN}`, "X-Audit-Log-Reason": "Member changed alerts with /alerts" },
  });
  if (!r.ok) {
    return { type: 7, data: { content: `${ALERTS_TEXT}\n-# Couldn't change ${role.label} just now. Try again.`,
      components: alertButtons(roles) } };
  }
  const now = has ? roles.filter((x) => x !== role.id) : [...roles, role.id];
  return { type: 7, data: { content: ALERTS_TEXT, components: alertButtons(now) } };
}

// Registers the commands on the server. Runs after Discord's signed PING,
// which it sends whenever the interactions URL is saved in the developer portal.
async function register(env) {
  const r = await fetch(`${API}/applications/${env.DISCORD_APP_ID}/guilds/${env.GUILD_ID}/commands`, {
    method: "PUT",
    headers: { Authorization: `Bot ${env.DISCORD_BOT_TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(COMMANDS),
  });
  console.log(`register commands: HTTP ${r.status}`);
}

export default {
  async fetch(req, env, ctx) {
    if (req.method !== "POST") return new Response("LumnFx bot", { status: 200 });
    const signature = req.headers.get("x-signature-ed25519");
    const timestamp = req.headers.get("x-signature-timestamp");
    const body = await req.text();
    if (!signature || !timestamp || !(await verify(env.DISCORD_PUBLIC_KEY, signature, timestamp, body))) {
      return new Response("Bad request signature", { status: 401 });
    }
    const i = JSON.parse(body);
    if (i.type === 1) {
      if (env.DISCORD_BOT_TOKEN) ctx.waitUntil(register(env));
      return json({ type: 1 });
    }
    if (i.type === 2) return json(await command(i, env));
    if (i.type === 3) return json(await component(i, env));
    return json(reply("Unsupported interaction."));
  },
};
