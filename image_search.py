from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
import base64
from urllib.parse import unquote_to_bytes

try:
    import requests
except Exception:  # pragma: no cover - runtime guard
    requests = None  # type: ignore

from .media import USER_AGENT


@dataclass
class ImageResult:
    image_url: str
    thumb_url: Optional[str] = None
    title: Optional[str] = None
    source_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    thumb_bytes: Optional[bytes] = None


def search_images(
    query: str,
    provider: str = "duckduckgo",
    max_results: int = 12,
    safe_search: bool = True,
    offset: int = 0,
    allow_fallback: bool = True,
) -> Tuple[List[ImageResult], str]:
    if not requests:
        raise RuntimeError("requests module not found. Install requests in the Anki environment.")
    q = (query or "").strip()
    if not q:
        return [], provider
    provider = (provider or "duckduckgo").lower()
    if provider == "wikimedia":
        return _search_wikimedia(q, max_results, offset=offset), "wikimedia"
    # default/fallback: duckduckgo
    try:
        results = _search_duckduckgo(q, max_results, safe_search=safe_search, offset=offset)
        if results:
            return results, "duckduckgo"
        if allow_fallback:
            return _search_wikimedia(q, max_results, offset=offset), "wikimedia"
        return [], provider
    except Exception:
        if not allow_fallback:
            raise
        # fallback to Wikimedia on DDG failure
        return _search_wikimedia(q, max_results, offset=offset), "wikimedia"


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
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(
        "https://duckduckgo.com/",
        params={"q": query, "iax": "images", "ia": "images"},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    vqd = _extract_ddg_vqd(resp.text or "")
    if not vqd:
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
        "Accept": "application/json,text/javascript,*/*;q=0.8",
        "Referer": "https://duckduckgo.com/",
    }
    resp = requests.get("https://duckduckgo.com/i.js", params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json() if resp.text else {}
    results: List[ImageResult] = []
    for item in data.get("results", []) or []:
        image_url = item.get("image")
        if not image_url:
            continue
        results.append(
            ImageResult(
                image_url=image_url,
                thumb_url=item.get("thumbnail"),
                title=item.get("title"),
                source_url=item.get("url"),
                width=_safe_int(item.get("width")),
                height=_safe_int(item.get("height")),
            )
        )
        if max_results and len(results) >= max_results:
            break
    return results


def _search_wikimedia(query: str, max_results: int, offset: int = 0) -> List[ImageResult]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,*/*;q=0.8",
    }
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": max_results or 12,
        "gsroffset": max(0, int(offset or 0)),
        "gsrnamespace": 6,
        "prop": "imageinfo",
        "iiprop": "url|mime|size",
        "iiurlwidth": 220,
        "format": "json",
    }
    resp = requests.get("https://commons.wikimedia.org/w/api.php", params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json() if resp.text else {}
    pages = (data.get("query") or {}).get("pages") or {}
    results: List[ImageResult] = []
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        url = info.get("url")
        if not url:
            continue
        results.append(
            ImageResult(
                image_url=url,
                thumb_url=info.get("thumburl"),
                title=page.get("title"),
                source_url=url,
                width=_safe_int(info.get("width")),
                height=_safe_int(info.get("height")),
            )
        )
        if max_results and len(results) >= max_results:
            break
    return results


def _extract_ddg_vqd(html: str) -> Optional[str]:
    patterns = [
        r"vqd=([^\&]+)\&",
        r'vqd=\"([^\"]+)\"',
        r"vqd='([^']+)'",
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
