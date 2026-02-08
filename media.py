from __future__ import annotations

import importlib
from typing import Optional, Tuple

from aqt import mw

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _requests():
    try:
        return importlib.import_module("requests")
    except Exception:
        return None


def download_to_media(url: str, referer: Optional[str] = "https://dictionary.cambridge.org/") -> Tuple[str, str]:
    """Download a file into Anki media. Returns (filename, local_path).

    Also validates content-type to avoid saving HTML/captcha pages as audio/images.
    """
    requests = _requests()
    if not requests:
        raise RuntimeError("requests module not found. Install requests in the Anki environment.")
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("/"):
        url = "https://dictionary.cambridge.org" + url
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }
    if referer:
        headers["Referer"] = referer
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    ctype = (resp.headers.get("Content-Type") or "").lower()
    is_audio = ctype.startswith("audio/") or url.lower().endswith((".mp3", ".wav", ".ogg"))
    is_image = ctype.startswith("image/") or url.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
    if not (is_audio or is_image or ctype == "application/octet-stream"):
        raise RuntimeError(f"Expected audio/image file, got {ctype or 'unknown'}")
    # derive filename
    name = url.split("/")[-1].split("?")[0]
    # avoid collisions
    filename = mw.col.media.writeData(name, resp.content)
    path = mw.col.media.dir() + "/" + filename
    return filename, path
