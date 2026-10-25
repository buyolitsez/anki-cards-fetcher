# Telegram Bot + Desktop Bridge Deployment

This repo now contains three pieces:

- the normal Anki add-on
- a FastAPI + SQLite sync server
- a private Telegram bot that queues `NoteDraft`s for desktop import

The server does not run an Anki collection. Desktop Anki remains the only writer to the real collection.

## 1. Prepare your Anki collection

1. Open desktop Anki with your real collection.
2. Sync it to AnkiWeb first.
3. If AnkiWeb is empty, use `Upload to AnkiWeb` from desktop so your current decks become the source of truth.
4. Confirm your desktop decks and note types are in the state you want the bot to target.

## 2. Create the Telegram bot

1. Open Telegram and talk to `@BotFather`.
2. Run `/newbot`.
3. Pick the display name and username.
4. Copy the bot token.
5. Message your new bot once so your Telegram user id will show up in updates later.
6. Keep the bot private. The server supports an allowlist via `TELEGRAM_ALLOWED_USER_IDS`.

## 3. Prepare the server

Example target: Ubuntu 24.04 server.

Install base packages:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip zip caddy
```

Clone the repo:

```bash
sudo mkdir -p /opt/cambridge_fetch
sudo chown "$USER":"$USER" /opt/cambridge_fetch
git clone <your-repo-url> /opt/cambridge_fetch
cd /opt/cambridge_fetch
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e '.[server,telegram]'
```

Python 3.10 is supported. You do not need Python 3.11 for this repo.

## 4. Create the server environment file

Create `/opt/cambridge_fetch/.env`:

```bash
TELEGRAM_BOT_TOKEN=123456:abc
TELEGRAM_ALLOWED_USER_IDS=123456789
PAIR_BOOTSTRAP_TOKEN=choose-a-long-random-string
DATABASE_URL=sqlite:////opt/cambridge_fetch/data/app.db
PUBLIC_BASE_URL=https://anki-sync.example.com
# Optional: Claude connector, see section 13
MCP_PATH_TOKEN=another-long-random-string
MCP_ALLOWED_HOSTS=anki-sync.example.com
```

Notes:

- `TELEGRAM_ALLOWED_USER_IDS` should be your numeric Telegram user id.
- `PAIR_BOOTSTRAP_TOKEN` is entered once in the Anki add-on to pair the desktop client.
- If you do not want a public domain, use Tailscale and set `PUBLIC_BASE_URL` to the Tailscale URL you will use from the desktop add-on.

## 5. Create the systemd service for the API

Create `/etc/systemd/system/cambridge-fetch-api.service`:

```ini
[Unit]
Description=Cambridge Fetch API
After=network.target

[Service]
WorkingDirectory=/opt/cambridge_fetch
EnvironmentFile=/opt/cambridge_fetch/.env
ExecStart=/opt/cambridge_fetch/.venv/bin/uvicorn cambridge_fetch.server.app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

## 6. Create the systemd service for the Telegram bot

Create `/etc/systemd/system/cambridge-fetch-bot.service`:

```ini
[Unit]
Description=Cambridge Fetch Telegram Bot
After=network.target

[Service]
WorkingDirectory=/opt/cambridge_fetch
EnvironmentFile=/opt/cambridge_fetch/.env
ExecStart=/opt/cambridge_fetch/.venv/bin/python -m cambridge_fetch.telegram_bot.app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Enable both services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cambridge-fetch-api.service
sudo systemctl enable --now cambridge-fetch-bot.service
sudo systemctl status cambridge-fetch-api.service
sudo systemctl status cambridge-fetch-bot.service
```

## 7. Put HTTPS in front of the API

Recommended: use a domain and Caddy.

Create `/etc/caddy/Caddyfile`:

```caddy
anki-sync.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Reload:

```bash
sudo systemctl reload caddy
```

If you do not want a public domain:

1. Install Tailscale on the server and desktop.
2. Expose the API only on the Tailscale interface or localhost.
3. Use the Tailscale URL in the add-on settings.

## 8. Build the public Anki add-on package

The add-on package should not contain:

- `.env`
- `server/`
- `telegram_bot/`
- test files
- local caches and logs

Use the included script from the repo root:

```bash
./build_ankiaddon.sh
./build_ankiaddon.sh cambridge_fetch --desktop
```

This creates `dist/cambridge_fetch.ankiaddon`.

## 9. Install the add-on locally

1. Use the generated `.ankiaddon` in Anki.
2. Restart Anki.
3. Open `Tools -> Dictionary Fetch — Settings`.
4. Fill in:
   - `Server URL`
   - `Bootstrap token`
   - optional desktop label
5. Click `Pair Desktop`.
6. The add-on will receive a long-lived device token and immediately push:
   - presets
   - language-default preset mapping
   - deck list
   - note type list
   - duplicate index from your existing collection

## 10. Verify the end-to-end flow

1. Message the Telegram bot with `fence` or `забор`.
2. Pick a candidate.
3. Review the expanded preview.
4. Tap `Add`.
5. Open desktop Anki.
6. Use `Tools -> Dictionary Fetch — Import Telegram Queue` or let auto-import run.
7. Sync Anki normally.
8. Confirm the note appears on your phone/tablet after Anki sync.

## 11. Ongoing operation

- Keep `auto_pull_on_startup` enabled.
- Use a periodic pull interval only if you want desktop Anki to keep checking while it stays open.
- Keep `auto_push_manifest` enabled so deck/note-type/preset changes are reflected on the server.
- If you rename decks or note types, open settings once and save so the manifest/duplicate index are refreshed.

## 12. Security notes

- Do not commit `.env`.
- Keep the bot token and bootstrap token only on the server and your personal desktop.
- Keep `TELEGRAM_ALLOWED_USER_IDS` restricted to your own Telegram id.
- The public `.ankiaddon` should be built with `build_ankiaddon.sh`, not by zipping the whole repo.

## 13. Claude connector (MCP)

The API can also serve a remote MCP server, so Claude can queue cards the same way the Telegram bot does:
ask Claude to explain a word, then say "add it to Anki" (optionally with where you saw it).

1. Install the extra: `pip install -e '.[server,telegram]'` (the `server` extra includes `mcp`).
2. Set `MCP_PATH_TOKEN` in `.env` to a long random string (`python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`).
   The token is part of the URL and is the only credential, so keep the URL private.
3. Set `MCP_ALLOWED_HOSTS` to the public host name (enables Host header checks; leave empty to disable them).
4. Restart `cambridge-fetch-api.service`. The endpoint is `https://anki-sync.example.com/mcp/<MCP_PATH_TOKEN>`.
   Claude only connects over HTTPS, so put Caddy in front of the API (section 7).
5. In Claude: Settings -> Connectors -> Add custom connector, paste that URL, no OAuth.

Tools:

- `add_to_anki(word, context?, meaning?, sense_index?, preset_id?, allow_duplicate?)`: fetches the word with the preset's
  sources, picks the sense that matches `meaning`, puts `context` in front of the examples (or into fields mapped as
  `context`), refuses duplicates already in Anki or in the queue. Words unknown to the dictionaries are added with
  `meaning` as the definition.
- `lookup_word(word)`: senses and duplicate status, queues nothing.
- `recent_cards(limit)`: cards queued from Claude and whether desktop Anki imported them.
- `cancel_card(queue_id)`: drop a card that is still pending.
