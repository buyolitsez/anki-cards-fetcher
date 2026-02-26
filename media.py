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


def resolve_media_url(url: str, referer: Optional[str] = None) -> str:
    url = (url or "").strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        if referer:
            ref = urlsplit(referer)
            if ref.scheme and ref.netloc:
                return f"{ref.scheme}://{ref.netloc}{url}"
        return "https://dictionary.cambridge.org" + url
    return url


def _download_with_requests(url: str, headers: dict, referer: Optional[str] = None):
    requests = require_requests()
    request_url = resolve_media_url(url, referer=referer)
    resp = requests.get(request_url, headers=headers, timeout=_MEDIA_DOWNLOAD_TIMEOUT)
    if resp.status_code == 429:
        fallback_url = normalize_wikimedia_image_url(request_url)
        if fallback_url != request_url:
            logger.warning("Thumbnail rate-limited, retrying original Wikimedia URL: %s", fallback_url)
            request_url = fallback_url
            resp = requests.get(request_url, headers=headers, timeout=_MEDIA_DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    return resp, request_url


def download_to_media(
    url: str,
    referer: Optional[str] = "https://dictionary.cambridge.org/",
    fallback_url: Optional[str] = None,
    fallback_referer: Optional[str] = None,
) -> Tuple[str, str]:
    """Download a file into Anki media. Returns (filename, local_path).

    Also validates content-type to avoid saving HTML/captcha pages as audio/images.
    Raises ``MediaDownloadError`` on failure.
    """
    logger.info("Downloading media: %s", url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }
    if referer:
        headers["Referer"] = referer
    primary_error = None
    try:
        resp, request_url = _download_with_requests(url, headers, referer=referer)
    except MissingDependencyError:
        raise
    except Exception as e:
        primary_error = e
        if not fallback_url:
            raise MediaDownloadError(f"Download failed for {url}: {e}") from e
        fallback_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        }
        if fallback_referer:
            fallback_headers["Referer"] = fallback_referer
        logger.warning("Primary media URL failed (%s), trying fallback URL: %s", e, fallback_url)
        try:
            resp, request_url = _download_with_requests(fallback_url, fallback_headers, referer=fallback_referer)
        except MissingDependencyError:
            raise
        except Exception as fallback_err:
            raise MediaDownloadError(
                f"Download failed for {url}: {primary_error}; fallback failed for {fallback_url}: {fallback_err}"
            ) from fallback_err
    final_url = getattr(resp, "url", "") or request_url
    ctype = (resp.headers.get("Content-Type") or "").lower()
    type_hint_url = final_url.lower()
    is_audio = ctype.startswith("audio/") or type_hint_url.endswith((".mp3", ".wav", ".ogg"))
    is_image = ctype.startswith("image/") or type_hint_url.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
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
