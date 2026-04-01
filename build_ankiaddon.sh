#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$ROOT_DIR/dist"
ADDON_NAME="${1:-cambridge_fetch}"
COPY_TO_DESKTOP="${2:-}"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cambridge_fetch-addon.XXXXXX")"

cleanup() {
  rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

mkdir -p "$DIST_DIR"

include_items=(
  "__init__.py"
  "manifest.json"
  "config.json"
  "defaults.py"
  "exceptions.py"
  "http_client.py"
  "image_search.py"
  "language_detection.py"
  "logger.py"
  "media.py"
  "models.py"
  "typo.py"
  "wikimedia_urls.py"
  "README.md"
  "LICENSE"
  "fetchers"
  "ui"
  "core"
  "anki"
  "user_files"
)

for item in "${include_items[@]}"; do
  if [[ -e "$ROOT_DIR/$item" ]]; then
    cp -R "$ROOT_DIR/$item" "$STAGING_DIR/$item"
  fi
done

rm -rf "$STAGING_DIR/user_files/logs" 2>/dev/null || true
find "$STAGING_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$STAGING_DIR" -name ".DS_Store" -type f -delete
find "$STAGING_DIR" -name "*.pyc" -type f -delete

OUTPUT_PATH="$DIST_DIR/$ADDON_NAME.ankiaddon"
(
  cd "$STAGING_DIR"
  zip -qr "$OUTPUT_PATH" .
)

if [[ "$COPY_TO_DESKTOP" == "--desktop" ]]; then
  cp "$OUTPUT_PATH" "$HOME/Desktop/"
fi

echo "Built $OUTPUT_PATH"
