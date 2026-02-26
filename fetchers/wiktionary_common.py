"""Shared utilities and base class for Wiktionary fetchers (ru + en)."""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import quote

from ..exceptions import FetchError
from ..http_client import USER_AGENT, require_bs4, require_requests
from ..logger import get_logger
from ..models import Sense
from ..wikimedia_urls import normalize_wikimedia_image_url
from .base import BaseFetcher

logger = get_logger(__name__)

_WIKTIONARY_TIMEOUT = 15
_MIN_IMAGE_SIZE = 80
_IMAGE_BLACKLIST = ("icon", "logo", "svg", "favicon")


# ---------------------------------------------------------------------------
# opensearch helpers (unchanged)
# ---------------------------------------------------------------------------

def _safe_limit(limit: int, minimum: int = 1, maximum: int = 20) -> int:
    try:
        value = int(limit)
    except Exception:
        value = minimum
    return max(minimum, min(value, maximum))


def _parse_opensearch_payload(payload, query: str, limit: int) -> List[str]:
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for item in payload[1]:
        if not isinstance(item, str):
            continue
        candidate = item.strip()
        if not candidate:
            continue
        key = candidate.casefold()
        if key == query.casefold() or key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= limit:
            break
    return out


def suggest_via_opensearch(
    *,
    requests_mod,
    api_base: str,
    query: str,
    limit: int,
    user_agent: str,
) -> List[str]:
    safe_query = query.strip()
    if not requests_mod or not safe_query:
        return []
    safe_limit = _safe_limit(limit)
    try:
        resp = requests_mod.get(
            api_base,
            headers={"User-Agent": user_agent},
            params={
                "action": "opensearch",
                "search": safe_query,
                "limit": safe_limit,
                "namespace": 0,
                "format": "json",
            },
            timeout=_WIKTIONARY_TIMEOUT,
        )
    except Exception:
        return []
    if resp.status_code >= 400:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    return _parse_opensearch_payload(payload, safe_query, safe_limit)


# ---------------------------------------------------------------------------
# BaseWiktionaryFetcher — shared fetch / language-section / picture logic
# ---------------------------------------------------------------------------

class BaseWiktionaryFetcher(BaseFetcher):
    """Shared base for ru.wiktionary and en.wiktionary fetchers.

    Subclasses must define:
    - ``WIKI_BASE``: page URL template with ``{word}`` placeholder
    - ``API_BASE``: MediaWiki API endpoint
    - ``TARGET_LANGUAGE``: language name used for section detection
    - ``WIKI_REFERER``: referer URL for picture downloads
    - ``_parse_senses(lang_root)``: language-specific sense extraction
    """

    WIKI_BASE: str
    API_BASE: str
    TARGET_LANGUAGE: str
    WIKI_REFERER: str = ""

    # --- public interface ---------------------------------------------------

    def fetch(self, word: str) -> List[Sense]:
        logger.info("%s: fetching '%s'", self.LABEL, word)
        requests = require_requests()
        BeautifulSoup = require_bs4()

        url = self.WIKI_BASE.format(word=quote(word.strip()))
        logger.debug("%s: requesting %s", self.LABEL, url)
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=_WIKTIONARY_TIMEOUT)
        except Exception as e:
            logger.error("%s: request failed for '%s': %s", self.LABEL, word, e)
            raise FetchError(f"Wiktionary request failed: {e}") from e
        if resp.status_code == 404:
            logger.debug("%s: 404 for '%s'", self.LABEL, word)
            return []
        if resp.status_code >= 400:
            logger.error("%s: HTTP %d for '%s'", self.LABEL, resp.status_code, word)
            raise FetchError(f"Wiktionary returned {resp.status_code} for '{word}'.")

        soup = BeautifulSoup(resp.text, "html.parser")
        lang_root = self._find_language_section(soup)
        if not lang_root:
            logger.debug("%s: no '%s' section found for '%s'", self.LABEL, self.TARGET_LANGUAGE, word)
            return []

        senses = self._parse_senses(lang_root)
        picture = self._extract_picture(lang_root)
        if picture:
            for s in senses:
                if not s.picture_url:
                    s.picture_url = picture
                if not s.picture_referer:
                    s.picture_referer = self.WIKI_REFERER
        logger.info("%s: found %d senses for '%s'", self.LABEL, len(senses), word)
        return senses

    def suggest(self, word: str, limit: int = 8) -> List[str]:
        try:
            requests = require_requests()
        except Exception:
            return []
        return suggest_via_opensearch(
            requests_mod=requests,
            api_base=self.API_BASE,
            query=word,
            limit=limit,
            user_agent=USER_AGENT,
        )

    # --- abstract (must be overridden) --------------------------------------

    def _parse_senses(self, lang_root) -> List[Sense]:  # pragma: no cover
        raise NotImplementedError

    # --- shared section detection -------------------------------------------

    def _find_language_section(self, soup):
        """Find the HTML section for ``TARGET_LANGUAGE`` (Parsoid + classic)."""
        lang_cf = self.TARGET_LANGUAGE.casefold()

        # 1) Parsoid <section> with aria-labelledby matching language name
        for sec in soup.find_all("section"):
            aria = (sec.get("aria-labelledby") or "").casefold()
            if lang_cf in aria:
                return sec

        # 2) Classic h1/h2 where id/text matches
        headline = soup.find(id=self.TARGET_LANGUAGE)
        if not headline:
            for span in soup.select(".mw-headline"):
                text = (span.get_text(strip=True) or "").casefold()
                sid = (span.get("id") or "").casefold()
                if text == lang_cf or sid == lang_cf:
                    headline = span
                    break

        # 3) URL-encoded IDs (ru.wiktionary)
        if not headline:
            from urllib.parse import unquote
            for tag in soup.find_all(id=True):
                raw_id = tag.get("id", "")
                if raw_id.startswith(".D"):
                    decoded = unquote(raw_id.replace(".", "%"))
                    if decoded.casefold() == lang_cf:
                        headline = tag
                        break

        if not headline:
            return None

        heading_tags = ("h1", "h2", "h3", "h4", "h5", "h6")
        if headline.name in heading_tags or headline.name == "section":
            return headline
        return headline.find_parent(list(heading_tags))

    # --- shared picture extraction ------------------------------------------

    def _extract_picture(self, lang_root) -> Optional[str]:
        """Pick a representative image from the language section."""
        if not lang_root:
            return None
        for img in lang_root.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src:
                continue
            src = src.split(",")[0].split()[0]
            if any(bad in src.lower() for bad in _IMAGE_BLACKLIST):
                continue
            if "upload.wikimedia.org" not in src and "wikimedia.org" not in src:
                continue
            try:
                width = int(img.get("data-file-width") or img.get("width") or 0)
                height = int(img.get("data-file-height") or img.get("height") or 0)
            except Exception:
                width = height = 0
            if width and height and (width < _MIN_IMAGE_SIZE or height < _MIN_IMAGE_SIZE):
                continue
            return normalize_wikimedia_image_url(src)
        return None
