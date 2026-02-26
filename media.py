from __future__ import annotations

import os
from typing import Optional, Tuple
from urllib.parse import unquote, urlsplit

from aqt import mw

from .exceptions import MediaDownloadError, MissingDependencyError
from .http_client import USER_AGENT, require_requests
from .logger import get_logger
from .wikimedia_urls import normalize_wikimedia_image_url

logger = get_logger(__name__)

_MEDIA_DOWNLOAD_TIMEOUT = 20


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
    Raises ``MediaDownloadError`` on failure.
    """
    logger.info("Downloading media: %s", url)
    requests = require_requests()
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
    try:
        request_url = url
        resp = requests.get(request_url, headers=headers, timeout=_MEDIA_DOWNLOAD_TIMEOUT)
        if resp.status_code == 429:
            fallback_url = normalize_wikimedia_image_url(request_url)
            if fallback_url != request_url:
                logger.warning("Thumbnail rate-limited, retrying original Wikimedia URL: %s", fallback_url)
                request_url = fallback_url
                resp = requests.get(request_url, headers=headers, timeout=_MEDIA_DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
    except MissingDependencyError:
        raise
    except Exception as e:
        raise MediaDownloadError(f"Download failed for {url}: {e}") from e
    final_url = getattr(resp, "url", "") or request_url
    ctype = (resp.headers.get("Content-Type") or "").lower()
    is_audio = ctype.startswith("audio/") or url.lower().endswith((".mp3", ".wav", ".ogg"))
    is_image = ctype.startswith("image/") or url.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
    if not (is_audio or is_image or ctype == "application/octet-stream"):
        logger.error("Unexpected content-type '%s' for URL: %s", ctype, url)
        raise MediaDownloadError(f"Expected audio/image file, got {ctype or 'unknown'}")
    # derive filename
    name = _derive_media_name(final_url, ctype)
    # avoid collisions
    filename = mw.col.media.writeData(name, resp.content)
    path = mw.col.media.dir() + "/" + filename
    logger.debug("Media saved as '%s' (%d bytes)", filename, len(resp.content))
    return filename, path
