from __future__ import annotations

import re
from typing import Dict, List, Optional
from urllib.parse import quote

from ..config import DEFAULT_CONFIG
from ..exceptions import FetchError, MissingDependencyError
from ..http_client import USER_AGENT, require_bs4, require_requests
from ..logger import get_logger
from ..models import Sense
from .base import BaseFetcher

logger = get_logger(__name__)

_REQUEST_TIMEOUT = (4, 12)
_SUGGEST_TIMEOUT = 15


class CambridgeFetcher(BaseFetcher):
    ID = "cambridge"
    LABEL = "Cambridge Dictionary (en)"
    BASE = "https://dictionary.cambridge.org/dictionary/english/{word}"
    AMP_BASE = "https://dictionary.cambridge.org/amp/english/{word}"
    SPELLCHECK_BASE = "https://dictionary.cambridge.org/spellcheck/english/?q={word}"
    _last_soup = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self.dialect_priority = [d.lower() for d in cfg.get("dialect_priority", DEFAULT_CONFIG["dialect_priority"])]

    def fetch(self, word: str) -> List[Sense]:
        logger.info("Cambridge: fetching '%s'", word)
        require_requests()
        require_bs4()

        senses: List[Sense] = []
        base_error: Optional[Exception] = None
        try:
            senses = self._parse_page(self.BASE, word)
        except Exception as e:
            logger.warning("Cambridge base page failed for '%s': %s", word, e)
            base_error = e

        if not senses:
            logger.debug("Cambridge: trying AMP page for '%s'", word)
            try:
                amp_senses = self._parse_page(self.AMP_BASE, word)
            except Exception:
                amp_senses = []
            if amp_senses:
                senses = amp_senses
            elif base_error:
                raise base_error

        # Fallback: AMP version may contain explicit media links
        if senses and all(not s.audio_urls for s in senses):
            logger.debug("Cambridge: no audio in base senses, trying AMP for audio")
            amp_senses = self._parse_page(self.AMP_BASE, word)
            if amp_senses:
                for i, s in enumerate(senses):
                    if i < len(amp_senses):
                        if amp_senses[i].audio_urls:
                            s.audio_urls = amp_senses[i].audio_urls
                        if amp_senses[i].picture_url:
                            s.picture_url = amp_senses[i].picture_url
                            s.picture_referer = amp_senses[i].picture_referer or "https://dictionary.cambridge.org/"
        # If audio is still missing, do a page-wide fallback search
        if senses and all(not s.audio_urls for s in senses):
            soup = self._last_soup
            if soup:
                global_audio = self._parse_audio(soup)
                if global_audio:
                    logger.debug("Cambridge: found global audio fallback for '%s'", word)
                    for s in senses:
                        s.audio_urls = global_audio.copy()
        logger.info("Cambridge: found %d senses for '%s'", len(senses), word)
        return senses

    def suggest(self, word: str, limit: int = 8) -> List[str]:
        requests = require_requests()
        BeautifulSoup = require_bs4()
        query = word.strip()
        if not query:
            return []
        logger.debug("Cambridge: suggest for '%s' (limit=%d)", query, limit)
        url = self.SPELLCHECK_BASE.format(word=quote(query))
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
                timeout=_SUGGEST_TIMEOUT,
            )
        except Exception:
            logger.debug("Cambridge: spellcheck request failed for '%s'", query)
            return []
        if resp.status_code >= 400:
            logger.debug("Cambridge: spellcheck returned %d for '%s'", resp.status_code, query)
            return []
        return self._parse_spellcheck_suggestions(resp.text, query, limit)

    def _parse_page(self, base_url: str, word: str) -> List[Sense]:
        requests = require_requests()
        BeautifulSoup = require_bs4()
        url = base_url.format(word=word.strip().replace(" ", "-"))
        logger.debug("Cambridge: requesting %s", url)
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
                timeout=_REQUEST_TIMEOUT,
            )
        except Exception as e:
            cls_name = e.__class__.__name__.lower()
            msg = str(e).strip()
            is_timeout = "timeout" in cls_name or "timed out" in msg.lower() or "timeout" in msg.lower()
            if is_timeout:
                logger.error("Cambridge: request timed out for '%s'", word)
                raise FetchError(f"Cambridge request timed out for '{word}'.") from e
            reason = msg or e.__class__.__name__
            logger.error("Cambridge: request failed for '%s': %s", word, reason)
            raise FetchError(f"Cambridge request failed for '{word}': {reason}") from e
        if self._is_cloudflare_challenge(resp):
            logger.error("Cambridge: Cloudflare challenge detected for '%s'", word)
            raise FetchError(
                "Cambridge is temporarily blocking automated requests (Cloudflare challenge). "
                "Try again later or use another source."
            )
        if resp.status_code >= 400:
            raise FetchError(f"Cambridge returned {resp.status_code} for '{word}'.")

        soup = BeautifulSoup(resp.text, "html.parser")
        self._last_soup = soup
        entries = soup.select("div.entry")
        senses: List[Sense] = []
        for entry in entries:
            audio_map = self._parse_audio(entry)
            picture = self._parse_picture(entry)
            picture_referer = "https://dictionary.cambridge.org/" if picture else None
            ipa_map = self._parse_ipa(entry)
            entry_pos = self._text(entry.select_one("span.pos.dpos, span.pos, span.dpos"))
            entry_examples = self._parse_entry_examples(entry)

            sections = entry.select("div.entry-body__el")
            if not sections:
                sections = [entry]

            for section in sections:
                pos = self._text(section.select_one("span.pos.dpos, span.pos, span.dpos")) or entry_pos
                for block in section.select("div.def-block"):
                    definition = self._text(block.select_one("div.def.ddef_d.db, div.def.ddef_d, div.def"))
                    if not definition:
                        continue
                    examples: List[str] = self._parse_examples(block)
                    if not examples and entry_examples:
                        examples = entry_examples.copy()
                    synonyms: List[str] = []
                    for a in block.select(
                        "div.thesref a, div.daccord a, div.daccordLink a, .synonyms a, .daccord-h a"
                    ):
                        text = self._text(a)
                        if text and text not in synonyms:
                            synonyms.append(text)
                    senses.append(
                        Sense(
                            definition=definition,
                            examples=examples,
                            synonyms=synonyms,
                            pos=pos,
                            ipa=ipa_map.copy(),
                            audio_urls=audio_map.copy(),
                            picture_url=picture,
                            picture_referer=picture_referer,
                        )
                    )
        return senses

    def _is_cloudflare_challenge(self, resp) -> bool:
        if not resp:
            return False
        status = int(getattr(resp, "status_code", 0) or 0)
        if status != 403:
            return False
        server = (getattr(resp, "headers", {}) or {}).get("server", "")
        text = getattr(resp, "text", "") or ""
        server_l = str(server).lower()
        text_l = text.lower()
        if "cloudflare" in server_l:
            return True
        return "just a moment" in text_l and "cf-chl" in text_l

    def _parse_entry_examples(self, entry) -> List[str]:
        examples: List[str] = []
        for section in entry.select(".daccord section"):
            header = section.select_one(".daccord_h, header")
            if not header:
                continue
            header_text = self._text(header).lower()
            if "example" not in header_text:
                continue
            for ex in section.select(".eg, .dexamp, .examp, li.eg, li.dexamp"):
                text = self._text(ex)
                if text and text not in examples:
                    examples.append(text)
        return examples

    def _parse_spellcheck_suggestions(self, html: str, query: str, limit: int) -> List[str]:
        BeautifulSoup = require_bs4()
        soup = BeautifulSoup(html, "html.parser")
        out: List[str] = []
        seen: set[str] = set()
        for a in soup.select("ul.hul-u li a"):
            href = (a.get("href") or "").strip()
            if "/search/" not in href and "q=" not in href:
                continue
            text = self._text(a)
            self._append_suggestion(out, seen, text, query, limit)
            if len(out) >= limit:
                break
        return out

    def _append_suggestion(self, out: List[str], seen: set[str], suggestion: str, query: str, limit: int) -> None:
        if not suggestion:
            return
        key = suggestion.casefold()
        if key == query.casefold() or key in seen:
            return
        seen.add(key)
        out.append(suggestion)
        if len(out) > limit:
            del out[limit:]

    def _parse_examples(self, block) -> List[str]:
        examples: List[str] = []
        selectors = [
            ".eg", ".deg", ".examp", ".dexamp",
            "span.eg", "span.deg", "span.xref span.eg",
            ".example", ".dexample", "li.example",
        ]
        for sel in selectors:
            for ex in block.select(sel):
                text = self._text(ex)
                if text and text not in examples:
                    examples.append(text)
        if not examples:
            for ex in block.select("[class]"):
                classes = " ".join(ex.get("class", []))
                if re.search(r"(?:^|\b)(eg|deg|example|examp|dexamp)(?:\b|$)", classes, re.IGNORECASE):
                    text = self._text(ex)
                    if text and text not in examples:
                        examples.append(text)
        return examples

    def _text(self, node) -> str:
        if not node:
            return ""
        return " ".join(node.get_text(" ", strip=True).split())

    def _parse_audio(self, entry) -> Dict[str, str]:
        audio: Dict[str, str] = {}
        candidates = []
        candidates.extend(entry.select("[data-src-mp3], [data-src-ogg]"))
        candidates.extend(entry.select("source[src], audio[src], audio source[src]"))
        candidates.extend(entry.select("a[href*='/media/']"))
        candidates.extend(entry.select("button[data-src-mp3], button[data-src-ogg]"))
        candidates.extend(entry.select("span[data-src-mp3], span[data-src-ogg]"))
        candidates.extend(entry.select("amp-audio source[src]"))

        for tag in candidates:
            url = (
                tag.get("data-src-mp3")
                or tag.get("data-src-ogg")
                or tag.get("src")
                or tag.get("href")
            )
            if not url:
                continue
            plausible = (
                re.search(r"\\.mp3\\b|\\.ogg\\b", url, re.IGNORECASE)
                or "/media/" in url
            )
            if not plausible:
                continue
            region_key = self._find_region(tag)
            key = region_key or "default"
            if key not in audio:
                audio[key] = url

        if not audio:
            src = entry.select_one("[data-src-mp3]")
            if src:
                url = src.get("data-src-mp3")
                if url:
                    audio["default"] = url
        return audio

    def _parse_ipa(self, entry) -> Dict[str, str]:
        ipa: Dict[str, str] = {}
        for block in entry.select(".dpron-i"):
            region_key = self._find_region(block)
            ipa_node = block.select_one(".ipa, .dipa")
            if not ipa_node:
                continue
            text = self._text(ipa_node)
            pron_parent = ipa_node.find_parent(class_="pron")
            if pron_parent:
                pron_text = self._text(pron_parent)
                if "/" in pron_text:
                    pron_text = pron_text.replace("/ ", "/").replace(" /", "/")
                    text = pron_text
            if not text:
                continue
            key = region_key or "default"
            if key not in ipa:
                ipa[key] = text
        if not ipa:
            for ipa_node in entry.select(".ipa, .dipa"):
                text = self._text(ipa_node)
                pron_parent = ipa_node.find_parent(class_="pron")
                if pron_parent:
                    pron_text = self._text(pron_parent)
                    if "/" in pron_text:
                        pron_text = pron_text.replace("/ ", "/").replace(" /", "/")
                        text = pron_text
                if not text:
                    continue
                key = self._find_region(ipa_node) or "default"
                if key not in ipa:
                    ipa[key] = text
        return ipa

    def _find_region(self, tag) -> Optional[str]:
        parent = tag
        for _ in range(5):
            region_el = parent.select_one(".region, .dregion") if hasattr(parent, "select_one") else None
            if region_el:
                txt = self._text(region_el).lower()
                if "us" in txt:
                    return "us"
                if "uk" in txt:
                    return "uk"
            if not getattr(parent, "parent", None):
                break
            parent = parent.parent
        classes = " ".join(tag.get("class", [])).lower()
        if "us" in classes:
            return "us"
        if "uk" in classes:
            return "uk"
        return None

    def _parse_picture(self, entry) -> Optional[str]:
        for img in entry.select("img, source, picture source"):
            src = img.get("data-src") or img.get("srcset") or img.get("src")
            if not src:
                continue
            src = src.split(",")[0].split()[0]
            if any(ext in src.lower() for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")) and "/media/" in src:
                return src
        amp = entry.select_one("amp-img")
        if amp:
            src = amp.get("data-src") or amp.get("src")
            if src:
                return src
        return None

    @property
    def supports_audio(self) -> bool:
        return True

    @property
    def supports_picture(self) -> bool:
        return True
