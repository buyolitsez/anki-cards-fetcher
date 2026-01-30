from __future__ import annotations

import re
from typing import Dict, List, Optional

try:
    import requests
except Exception:  # pragma: no cover - runtime guard
    requests = None  # type: ignore

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None  # type: ignore

from ..config import DEFAULT_CONFIG
from ..media import USER_AGENT
from ..models import Sense
from .base import BaseFetcher


class CambridgeFetcher(BaseFetcher):
    ID = "cambridge"
    LABEL = "Cambridge Dictionary (en)"
    BASE = "https://dictionary.cambridge.org/dictionary/english/{word}"
    AMP_BASE = "https://dictionary.cambridge.org/amp/english/{word}"
    _last_soup = None

    def __init__(self, cfg):
        super().__init__(cfg)
        self.dialect_priority = [d.lower() for d in cfg.get("dialect_priority", DEFAULT_CONFIG["dialect_priority"])]

    def fetch(self, word: str) -> List[Sense]:
        if not requests:
            raise RuntimeError("requests module not found. Install requests in the Anki environment.")
        if not BeautifulSoup:
            raise RuntimeError("bs4 not found. Install beautifulsoup4 in the Anki environment.")

        senses = self._parse_page(self.BASE, word)
        # fallback: AMP-версия иногда содержит явные ссылки на медиа
        if senses and all(not s.audio_urls for s in senses):
            amp_senses = self._parse_page(self.AMP_BASE, word)
            if amp_senses:
                # переносим audio/picture, если есть
                for i, s in enumerate(senses):
                    if i < len(amp_senses):
                        if amp_senses[i].audio_urls:
                            s.audio_urls = amp_senses[i].audio_urls
                        if amp_senses[i].picture_url:
                            s.picture_url = amp_senses[i].picture_url
        # если аудио нигде не нашли — глобальный поиск по странице (кнопки произношения)
        if senses and all(not s.audio_urls for s in senses):
            soup = self._last_soup  # заполнен в _parse_page
            if soup:
                global_audio = self._parse_audio(soup)
                if global_audio:
                    for s in senses:
                        s.audio_urls = global_audio.copy()
        return senses

    def _parse_page(self, base_url: str, word: str) -> List[Sense]:
        url = base_url.format(word=word.strip().replace(" ", "-"))
        resp = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Cambridge returned {resp.status_code} for '{word}'.")

        soup = BeautifulSoup(resp.text, "html.parser")
        self._last_soup = soup
        entries = soup.select("div.entry")
        senses: List[Sense] = []
        for entry in entries:
            audio_map = self._parse_audio(entry)
            picture = self._parse_picture(entry)
            pos = self._text(entry.select_one("span.pos.dpos"))

            for block in entry.select("div.def-block"):
                definition = self._text(block.select_one("div.def.ddef_d.db, div.def.ddef_d, div.def"))
                if not definition:
                    continue
                examples: List[str] = self._parse_examples(block)
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
                        audio_urls=audio_map.copy(),
                        picture_url=picture,
                    )
                )
        return senses

    def _parse_examples(self, block) -> List[str]:
        examples: List[str] = []
        selectors = [
            ".eg",
            ".deg",
            ".examp",
            ".dexamp",
            "span.eg",
            "span.deg",
            "span.xref span.eg",
            ".example",
            ".dexample",
            "li.example",
        ]
        for sel in selectors:
            for ex in block.select(sel):
                text = self._text(ex)
                if text and text not in examples:
                    examples.append(text)
        # broader fallback: any element whose class contains eg/example/examp
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
        # Cambridge меняет вёрстку; соберём ссылки из нескольких вариантов.
        candidates = []
        candidates.extend(entry.select("[data-src-mp3], [data-src-ogg]"))
        candidates.extend(entry.select("source[src], audio[src], audio source[src]"))
        candidates.extend(entry.select("a[href*='/media/']"))
        candidates.extend(entry.select("button[data-src-mp3], button[data-src-ogg]"))
        candidates.extend(entry.select("span[data-src-mp3], span[data-src-ogg]"))

        # AMP-страницы используют <amp-audio><source src=...>
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
            # сохраняем первый вариант для региона; если регион не найден — кладём как default
            key = region_key or "default"
            if key not in audio:
                audio[key] = url

        # fallback: первая попавшаяся data-src-mp3
        if not audio:
            src = entry.select_one("[data-src-mp3]")
            if src:
                url = src.get("data-src-mp3")
                if url:
                    audio["default"] = url
        return audio

    def _find_region(self, tag) -> Optional[str]:
        """Пытается вычислить регион (us/uk) исходя из ближайших .region или классов."""
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
        # Cambridge иногда хранит картинки в img[data-src] или img[src] с путём /media/
        for img in entry.select("img, source, picture source"):
            src = img.get("data-src") or img.get("srcset") or img.get("src")
            if not src:
                continue
            # srcset может содержать несколько ссылок через запятую — берём первую
            src = src.split(",")[0].split()[0]
            if any(ext in src.lower() for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")) and "/media/" in src:
                return src
        # amp-img fallback
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
