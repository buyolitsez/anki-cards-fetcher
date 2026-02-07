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
    pixabay_api_key: Optional[str] = None,
    pexels_api_key: Optional[str] = None,
) -> Tuple[List[ImageResult], str, bool]:
    if not requests:
        raise RuntimeError("requests module not found. Install requests in the Anki environment.")
    q = (query or "").strip()
    if not q:
        return [], provider, False
    provider = (provider or "duckduckgo").lower()
    if provider == "pixabay":
        return _search_pixabay(
            q,
            max_results,
            safe_search=safe_search,
            offset=offset,
            api_key=pixabay_api_key,
        ), "pixabay", False
    if provider == "pexels":
        return _search_pexels(
            q,
            max_results,
            safe_search=safe_search,
            offset=offset,
            api_key=pexels_api_key,
        ), "pexels", False
    if provider == "wikimedia":
        return _search_wikimedia(q, max_results, offset=offset), "wikimedia", False
    # default/fallback: duckduckgo
    try:
        results = _search_duckduckgo(q, max_results, safe_search=safe_search, offset=offset)
        if results:
            return results, "duckduckgo", False
        if allow_fallback:
            return _search_wikimedia(q, max_results, offset=offset), "wikimedia", True
        return [], provider, False
    except Exception:
        if not allow_fallback:
            raise
        # fallback to Wikimedia on DDG failure
        return _search_wikimedia(q, max_results, offset=offset), "wikimedia", True


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
    vqd, referer = _fetch_ddg_vqd(query, html_headers, timeout=timeout)
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


def _search_pixabay(
    query: str,
    max_results: int,
    safe_search: bool,
    offset: int,
    api_key: Optional[str],
) -> List[ImageResult]:
    if not api_key:
        raise RuntimeError("Pixabay provider requires API key. Configure it in Settings.")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,*/*;q=0.8",
    }
    results: List[ImageResult] = []
    per_page = int(max_results or 20)
    per_page = max(3, min(per_page, 200))
    page = max(0, int(offset or 0)) // per_page + 1
    skip = max(0, int(offset or 0)) % per_page
    remaining = max_results or per_page
    while remaining > 0:
        params = {
            "key": api_key,
            "q": query,
            "image_type": "photo",
            "per_page": min(per_page, remaining),
            "page": page,
            "safesearch": "true" if safe_search else "false",
        }
        resp = requests.get("https://pixabay.com/api/", params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json() if resp.text else {}
        hits = data.get("hits") or []
        if skip:
            hits = hits[skip:]
            skip = 0
        if not hits:
            break
        for item in hits:
            image_url = item.get("largeImageURL") or item.get("webformatURL")
            if not image_url:
                continue
            results.append(
                ImageResult(
                    image_url=image_url,
                    thumb_url=item.get("previewURL") or item.get("webformatURL"),
                    title=item.get("tags"),
                    source_url=item.get("pageURL"),
                    width=_safe_int(item.get("imageWidth")),
                    height=_safe_int(item.get("imageHeight")),
                )
            )
            if max_results and len(results) >= max_results:
                break
        if max_results and len(results) >= max_results:
            break
        if len(hits) < params["per_page"]:
            break
        page += 1
        remaining = max_results - len(results) if max_results else 0
    return results


def _search_pexels(
    query: str,
    max_results: int,
    safe_search: bool,
    offset: int,
    api_key: Optional[str],
) -> List[ImageResult]:
    if not api_key:
        raise RuntimeError("Pexels provider requires API key. Configure it in Settings.")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,*/*;q=0.8",
        "Authorization": api_key,
    }
    results: List[ImageResult] = []
    per_page = int(max_results or 15)
    per_page = max(3, min(per_page, 80))
    page = max(0, int(offset or 0)) // per_page + 1
    skip = max(0, int(offset or 0)) % per_page
    remaining = max_results or per_page
    while remaining > 0:
        params = {
            "query": query,
            "per_page": min(per_page, remaining),
            "page": page,
        }
        resp = requests.get("https://api.pexels.com/v1/search", params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json() if resp.text else {}
        items = data.get("photos") or []
        if skip:
            items = items[skip:]
            skip = 0
        if not items:
            break
        for item in items:
            src = item.get("src") or {}
            image_url = src.get("large") or src.get("medium") or src.get("original")
            if not image_url:
                continue
            results.append(
                ImageResult(
                    image_url=image_url,
                    thumb_url=src.get("tiny") or src.get("small") or src.get("medium"),
                    title=item.get("alt") or item.get("url"),
                    source_url=item.get("url"),
                    width=_safe_int(item.get("width")),
                    height=_safe_int(item.get("height")),
                )
            )
            if max_results and len(results) >= max_results:
                break
        if max_results and len(results) >= max_results:
            break
        if len(items) < params["per_page"]:
            break
        page += 1
        remaining = max_results - len(results) if max_results else 0
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
