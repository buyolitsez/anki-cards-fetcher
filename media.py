from __future__ import annotations

import importlib
import os
from typing import Optional, Tuple
from urllib.parse import unquote, urlsplit

from aqt import mw

from .logger import get_logger

logger = get_logger(__name__)

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


def _ext_from_content_type(content_type: str) -> str:
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
    }
    return mapping.get(ctype, "")


def _derive_media_name(url: str, content_type: str = "") -> str:
    """Return a filesystem-safe media name derived from URL/content-type."""
    path = urlsplit(url).path or ""
    raw_name = path.rsplit("/", 1)[-1] if path else ""
    # Decode %-escapes to avoid broken local URLs like `%2C` in filename.
    name = unquote(raw_name).strip()
    if not name:
        name = "download"
    # Keep local media path safe and single-file.
    name = "".join("_" if ch in '/\\\x00\r\n\t' else ch for ch in name)
    name = os.path.basename(name)
    if name in {".", "..", ""}:
        name = "download"
    if "." not in name:
        ext = _ext_from_content_type(content_type)
        if ext:
            name += ext
    return name


def download_to_media(url: str, referer: Optional[str] = "https://dictionary.cambridge.org/") -> Tuple[str, str]:
    """Download a file into Anki media. Returns (filename, local_path).

    Also validates content-type to avoid saving HTML/captcha pages as audio/images.
    """
    logger.info("Downloading media: %s", url)
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
        logger.error("Unexpected content-type '%s' for URL: %s", ctype, url)
        raise RuntimeError(f"Expected audio/image file, got {ctype or 'unknown'}")
    # derive filename
    name = _derive_media_name(url, ctype)
    # avoid collisions
    filename = mw.col.media.writeData(name, resp.content)
    path = mw.col.media.dir() + "/" + filename
    logger.debug("Media saved as '%s' (%d bytes)", filename, len(resp.content))
    return filename, path
