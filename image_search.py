from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
import base64
from urllib.parse import unquote_to_bytes, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

try:
    import requests
except Exception:  # pragma: no cover - runtime guard
    requests = None  # type: ignore

from .logger import get_logger
from .media import USER_AGENT

logger = get_logger(__name__)

DEFAULT_IMAGE_PROVIDER = "duckduckgo"
# Keep provider registry even with a single provider so engines can be restored later
# without changing UI/config wiring.
IMAGE_PROVIDER_CHOICES: Tuple[Tuple[str, str], ...] = (("DuckDuckGo", DEFAULT_IMAGE_PROVIDER),)


@dataclass
class ImageResult:
    image_url: str
    thumb_url: Optional[str] = None
    title: Optional[str] = None
    source_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    thumb_bytes: Optional[bytes] = None


def get_image_provider_choices() -> Tuple[Tuple[str, str], ...]:
    return IMAGE_PROVIDER_CHOICES


def search_images(
    query: str,
    provider: str = DEFAULT_IMAGE_PROVIDER,
    max_results: int = 12,
    safe_search: bool = True,
    offset: int = 0,
    allow_fallback: bool = True,
) -> Tuple[List[ImageResult], str, bool]:
    logger.info("Image search: query='%s', provider=%s, max=%d, offset=%d", query, provider, max_results, offset)
    if not requests:
        raise RuntimeError("requests module not found. Install requests in the Anki environment.")
    q = (query or "").strip()
    if not q:
        return [], provider, False
    _ = allow_fallback  # kept for compatibility with existing call sites
    provider = (provider or DEFAULT_IMAGE_PROVIDER).lower()
    supported = {provider_id for _, provider_id in IMAGE_PROVIDER_CHOICES}
    if provider not in supported:
        provider = DEFAULT_IMAGE_PROVIDER
    # Current release supports only DuckDuckGo, but provider plumbing stays generic.
    results = _search_duckduckgo(q, max_results, safe_search=safe_search, offset=offset)
    logger.info("Image search: got %d results for '%s'", len(results), q)
    return results, provider, False


def attach_thumbnails(
    results: List[ImageResult],
    max_bytes: int = 800_000,
    timeout: int = 10,
):
    if not requests:
        return
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/*,*/*;q=0.8",
    }
    for res in results:
        url = res.thumb_url or res.image_url
        if not url:
            continue
        if url.startswith("data:image/"):
            data = _decode_data_url(url)
            if data:
                res.thumb_bytes = data
            continue
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code >= 400:
                continue
            content = resp.content or b""
            if max_bytes and len(content) > max_bytes:
                continue
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if ctype and not ctype.startswith("image/"):
                continue
            res.thumb_bytes = content
        except Exception:
            continue


def _search_duckduckgo(
    query: str, max_results: int, safe_search: bool = True, offset: int = 0
) -> List[ImageResult]:
    timeout = 15
    html_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    logger.debug("DuckDuckGo: fetching VQD token for '%s'", query)
    vqd, referer = _fetch_ddg_vqd(query, html_headers, timeout=timeout)
    if not vqd:
        logger.error("DuckDuckGo: VQD token not found for '%s'", query)
        raise RuntimeError("DuckDuckGo token not found.")

    params = {
        "l": "us-en",
        "o": "json",
        "q": query,
        "vqd": vqd,
        "f": "",
        "p": "1" if safe_search else "-1",
        "s": str(max(0, int(offset or 0))),
    }
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
        "Origin": "https://duckduckgo.com",
        "DNT": "1",
    }
    data = _ddg_fetch_json("https://duckduckgo.com/i.js", params, headers, timeout=timeout)
    items = data.get("results") or data.get("data") or []
    if not isinstance(items, list):
        items = []
    results: List[ImageResult] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        image_url = item.get("image") or item.get("image_url") or item.get("media")
        if not image_url:
            continue
        results.append(
            ImageResult(
                image_url=image_url,
                thumb_url=item.get("thumbnail") or item.get("thumb"),
                title=item.get("title") or item.get("alt"),
                source_url=item.get("url") or item.get("source"),
                width=_safe_int(item.get("width")),
                height=_safe_int(item.get("height")),
            )
        )
        if max_results and len(results) >= max_results:
            break
    return results


def _fetch_ddg_vqd(query: str, headers: dict, timeout: int = 15) -> Tuple[Optional[str], str]:
    candidates = [
        {"q": query, "t": "h_", "iax": "images", "ia": "images"},
        {"q": query},
    ]
    last_url = "https://duckduckgo.com/"
    for params in candidates:
        url = "https://duckduckgo.com/?" + urlencode(params)
        html = _ddg_fetch_text(url, headers, timeout=timeout)
        last_url = url
        vqd = _extract_ddg_vqd(html)
        if vqd:
            return vqd, last_url
    return None, last_url


def _ddg_fetch_text(url: str, headers: dict, timeout: int = 15) -> str:
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except HTTPError as exc:
        raise RuntimeError(f"DuckDuckGo request failed ({exc.code}).") from exc
    return data.decode("utf-8", "replace")


def _ddg_fetch_json(url: str, params: dict, headers: dict, timeout: int = 15) -> dict:
    req = Request(url + "?" + urlencode(params), headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except HTTPError as exc:
        raise RuntimeError(f"DuckDuckGo request failed ({exc.code}).") from exc
    try:
        return json.loads(data.decode("utf-8", "replace"))
    except Exception as exc:
        raise RuntimeError("DuckDuckGo returned invalid JSON.") from exc


def _extract_ddg_vqd(html: str) -> Optional[str]:
    patterns = [
        r"vqd=['\"]([A-Za-z0-9-]+)['\"]",
        r"vqd=([A-Za-z0-9-]+)&",
        r"vqd=([A-Za-z0-9-]+)",
        r"\"vqd\"\s*:\s*\"([^\"]+)\"",
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def _safe_int(val) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        return None


def _decode_data_url(url: str) -> Optional[bytes]:
    try:
        header, data = url.split(",", 1)
    except ValueError:
        return None
    if ";base64" in header:
        try:
            return base64.b64decode(data)
        except Exception:
            return None
    try:
        return unquote_to_bytes(data)
    except Exception:
        return None
