from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import quote
from pathlib import Path

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None  # type: ignore

from ..media import USER_AGENT
from ..models import Sense
from .base import BaseFetcher

LOG_PATH = Path(__file__).resolve().parent.parent / "fetch_log.txt"


def log(line: str):
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class WiktionaryFetcher(BaseFetcher):
    ID = "wiktionary"
    LABEL = "ru.wiktionary.org (ru)"
    BASE = "https://ru.wiktionary.org/wiki/{word}"

    def fetch(self, word: str) -> List[Sense]:
        if not requests:
            raise RuntimeError("requests module not found. Install requests in the Anki environment.")
        if not BeautifulSoup:
            raise RuntimeError("bs4 not found. Install beautifulsoup4 in the Anki environment.")

        url = self.BASE.format(word=quote(word.strip()))
        log(f"[wiktionary] fetch '{word}' -> {url}")
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            log(f"[wiktionary] status {resp.status_code}, len={len(resp.text)}")
        except Exception as e:
            log(f"[wiktionary] request failed: {e}")
            raise RuntimeError(f"Wiktionary request failed: {e}")
        if resp.status_code == 404:
            log(f"[wiktionary] 404 for '{word}'")
            return []
        if resp.status_code >= 400:
            raise RuntimeError(f"Wiktionary returned {resp.status_code} for '{word}'.")

        soup = BeautifulSoup(resp.text, "html.parser")
        lang_section = self._language_section(soup, "Русский")
        log(f"[wiktionary] lang_section nodes: {len(lang_section) if lang_section else 0}")
        if not lang_section:
            return []

        senses = self._parse_senses(lang_section)
        picture = self._extract_picture(lang_section)
        syllables = self._extract_syllables(lang_section)
        if picture:
            for s in senses:
                if not s.picture_url:
                    s.picture_url = picture
        if syllables:
            for s in senses:
                if not s.syllables:
                    s.syllables = syllables
        log(f"[wiktionary] senses found: {len(senses)}, picture: {bool(picture)}")
        return senses

    # ----------------------- helpers -----------------------
    def _language_section(self, soup, language: str):
        """Возвращает тег секции (section/h2 блок) для заданного языка."""
        lang_cf = language.casefold()

        # 1) parsoid section с aria-labelledby="Русский"
        for sec in soup.find_all("section"):
            aria = (sec.get("aria-labelledby") or "").casefold()
            if lang_cf in aria or "русск" in aria:
                return sec

        # 2) классический h1/h2 с id или текстом Русский
        headline = soup.find(id=language)
        if not headline:
            for span in soup.select(".mw-headline"):
                text = (span.get_text(strip=True) or "").casefold()
                sid = (span.get("id") or "").casefold()
                if text == lang_cf or sid == lang_cf or "русск" in text:
                    headline = span
                    break
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
            heads = [f"{(span.get('id') or '').strip()}|{(span.get_text(strip=True) or '')}" for span in soup.select('.mw-headline')][:10]
            log("[wiktionary] headline not found; sample headlines: " + " || ".join(heads))
            return None

        h_tag = headline if headline.name in ("h1", "h2") else headline.find_parent(["h1", "h2"])
        if not h_tag:
            log("[wiktionary] h1/h2 parent not found")
            return None

        # оборачиваем в фиктивный объект с children для совместимости
        return h_tag

    def _parse_senses(self, lang_root) -> List[Sense]:
        senses: List[Sense] = []
        synonyms: List[str] = []

        def clean_txt(text: str) -> str:
            txt = re.sub(r"\[\d+\]", "", text)  # убираем сноски вида [1]
            return " ".join(txt.split())

        if not lang_root:
            return []

        def sections_by_title(title: str):
            title_l = title.lower()
            for sec in lang_root.find_all("section"):
                aria = (sec.get("aria-labelledby") or "").lower()
                if title_l in aria:
                    yield sec
                    continue
                head = sec.find(["h2", "h3", "h4", "h5", "h6"])
                if head and (head.get_text(strip=True) or "").lower() == title_l:
                    yield sec

        def iter_section(title: str):
            for sec in sections_by_title(title):
                lst = sec.find(["ol", "ul"])
                if lst:
                    for li in lst.find_all("li", recursive=False):
                        yield li

        # собрать определения
        for li in iter_section("Значение"):
            raw = clean_txt(li.get_text(" ", strip=True))
            if not raw:
                continue
            definition, examples = self._split_examples(raw)
            senses.append(
                Sense(
                    definition=definition,
                    examples=examples,
                    synonyms=[],  # заполнится позже общим списком
                    pos=None,
                )
            )

        # собрать синонимы (общие для всех sense)
        for li in iter_section("Синонимы"):
            for a in li.find_all("a"):
                txt = clean_txt(a.get_text(" ", strip=True))
                if txt and txt not in synonyms:
                    synonyms.append(txt)

        if synonyms:
            for s in senses:
                s.synonyms = synonyms[:]
        log(f"[wiktionary] senses parsed: {len(senses)}, synonyms: {len(synonyms)}")
        return senses

    def _extract_picture(self, lang_root) -> Optional[str]:
        """Pick a representative image from the language section, if any."""
        if not lang_root:
            return None
        # Prefer thumbnails of photos/illustrations, ignore icons/logos
        for img in lang_root.find_all("img"):
            src = img.get("src") or ""
            if not src:
                continue
            if any(bad in src.lower() for bad in ("icon", "logo", "svg", "favicon")):
                continue
            if "upload.wikimedia.org" not in src:
                continue
            try:
                width = int(img.get("data-file-width") or img.get("width") or 0)
                height = int(img.get("data-file-height") or img.get("height") or 0)
            except Exception:
                width = height = 0
            if width < 80 or height < 80:
                continue
            return src
        return None

    def _extract_syllables(self, lang_root) -> Optional[str]:
        """Extract syllabified/stressed headword like 'о́·мут'."""
        if not lang_root:
            return None
        # Prefer explicit hyphenation marker
        hyph = lang_root.select_one(".hyph-dot")
        if hyph:
            parent = hyph.find_parent(["b", "strong", "span"])
            if parent:
                text = parent.get_text("", strip=True)
                if text:
                    return text
        # Fallback: any short Cyrillic text containing a middle dot
        for text in lang_root.stripped_strings:
            if "·" in text and re.search(r"[А-Яа-я]", text):
                # avoid very long strings
                if len(text) <= 40:
                    return text
        # Fallback: parse template data-mw that contains {{по-слогам|...}}
        for tag in lang_root.find_all(attrs={"data-mw": True}):
            data = tag.get("data-mw") or ""
            if "по-слогам" not in data:
                continue
            m = re.search(r"по-слогам\\|([^}]+)", data)
            if not m:
                continue
            parts = [p for p in m.group(1).split("|") if p and p != "."]
            if parts:
                return "·".join(parts)
        return None

    def _split_examples(self, raw: str):
        """Викисловарь пишет примеры после символа ◆"""
        if "◆" in raw:
            parts = [p.strip(" —:;") for p in raw.split("◆") if p.strip(" —:;")]
            definition = parts[0] if parts else raw
            examples = parts[1:] if len(parts) > 1 else []
            return definition, examples
        return raw, []

    def _headline_text(self, node) -> str:
        if not node:
            return ""
        hl = node.find(class_="mw-headline")
        if hl:
            return hl.get_text(strip=True)
        return node.get_text(strip=True)
