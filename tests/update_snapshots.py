from __future__ import annotations

from pathlib import Path
import time
import requests

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

TARGETS = {
    "cambridge_test.html": "https://dictionary.cambridge.org/dictionary/english/test",
    "cambridge_fence.html": "https://dictionary.cambridge.org/dictionary/english/fence",
    "wiktionary_omut.html": "https://ru.wiktionary.org/wiki/%D0%BE%D0%BC%D1%83%D1%82",
    "wiktionary_test.html": "https://ru.wiktionary.org/wiki/%D1%82%D0%B5%D1%81%D1%82",
}


def fetch(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    return resp.text


def main() -> int:
    for name, url in TARGETS.items():
        print(f"Downloading {url} -> {name}")
        html = fetch(url)
        (SNAPSHOT_DIR / name).write_text(html, encoding="utf-8")
        time.sleep(1.0)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
