#!/bin/zsh
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-cambridge-fetch-bot.service}"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "$SERVICE_NAME" >/dev/null 2>&1; then
  echo "Restarting $SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  systemctl status "$SERVICE_NAME" --no-pager
  exit 0
fi

if [[ ! -f "$REPO_DIR/.env" ]]; then
  echo "Missing $REPO_DIR/.env"
  exit 1
fi

if [[ ! -x "$REPO_DIR/.venv/bin/python" ]]; then
  echo "Missing Python venv at $REPO_DIR/.venv"
  exit 1
fi

echo "systemd service not found, starting bot manually in background"
cd "$REPO_DIR"
set -a
source .env
set +a
nohup .venv/bin/python -m cambridge_fetch.telegram_bot.app > bot.out 2>&1 &
echo "Bot started with PID $!"
