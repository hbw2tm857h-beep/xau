# LumnFx Discord app

Slash commands for the LumnFx server, served by a Cloudflare Worker over
Discord's HTTP interactions API (no always-on process, no dependencies).

| Command | What it does |
|---|---|
| `/open` | Trades and orders running now, as on the Open now post |
| `/stats` | The live track record in numbers and the latest five trades |
| `/alerts` | Buttons to turn Gold, Crypto and US indices pings on or off (adds or removes the role) |
| `/help` | What the bot does |

Replies are visible only to the member who asked. The numbers come from
`state.json`, `journal.json` and `nursery.json` in this repo, which the hourly
run commits; `src/data.js` mirrors `track_record.py`, so the bot and
#track-record always agree.

## Setup

1. Create the application in the Discord developer portal and copy its
   Application ID and Public Key into `wrangler.toml`.
2. On the Bot page, reset the token and store it as a Worker secret (it is
   never committed): `npx wrangler secret put DISCORD_BOT_TOKEN`.
3. `npx wrangler deploy`.
4. In the portal, set the Interactions Endpoint URL to the Worker's URL.
   Discord sends a signed PING, and the Worker registers the slash commands
   on the server when it receives it. Saving the URL again re-registers them.
5. Invite the app with the `bot` and `applications.commands` scopes and the
   Manage Roles permission, then drag its role above Gold, Crypto and
   US indices so `/alerts` can change them.
