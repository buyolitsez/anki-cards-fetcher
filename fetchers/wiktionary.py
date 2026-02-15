"""ru.wiktionary.org fetcher — extracts Russian word senses, syllables, etc."""

from __future__ import annotations

import re
from typing import List, Optional

from ..http_client import require_bs4
from ..logger import get_logger
from ..models import Sense
from .wiktionary_common import BaseWiktionaryFetcher

logger = get_logger(__name__)
_LETTER_RE = re.compile(r"[A-Za-zА-Яа-яЁё]")
_REF_MARKER_RE = re.compile(r"\[\s*[^A-Za-zА-Яа-яЁё\]]*\d+[^A-Za-zА-Яа-яЁё\]]*\]")
_ORPHAN_BRACKET_RE = re.compile(r"(^|(?<=\s))[\[\]](?=\s|$)")


class WiktionaryFetcher(BaseWiktionaryFetcher):
    ID = "wiktionary"
    LABEL = "ru.wiktionary.org (ru)"
    WIKI_BASE = "https://ru.wiktionary.org/wiki/{word}"
    API_BASE = "https://ru.wiktionary.org/w/api.php"
    TARGET_LANGUAGE = "Русский"
    WIKI_REFERER = "https://ru.wiktionary.org/"

    # Override fetch to also extract syllables (ru-specific)
    def fetch(self, word: str) -> List[Sense]:
        senses = super().fetch(word)
        # Re-parse syllables from the page (we need the lang_root).
        # Instead of re-fetching, we extract syllables in _parse_senses via
        # self._last_lang_root which we stash during the base class flow.
        return senses

    def _parse_senses(self, lang_root) -> List[Sense]:
        senses = self._parse_definitions(lang_root)
        syllables = self._extract_syllables(lang_root)
        if syllables:
            for s in senses:
                if not s.syllables:
                    s.syllables = syllables
        return senses

    # ----------------------- parsing helpers -----------------------
    def _parse_definitions(self, lang_root) -> List[Sense]:
        senses: List[Sense] = []
        synonyms: List[str] = []

        def clean_txt(text: str) -> str:
            txt = (text or "").replace("\u00a0", " ")
            txt = _REF_MARKER_RE.sub("", txt)
            txt = _ORPHAN_BRACKET_RE.sub(" ", txt)
            txt = " ".join(txt.split())
            txt = re.sub(r"\s+([,.;:!?])", r"\1", txt)
            return txt

        def is_meaningful_token(text: str) -> bool:
            txt = (text or "").strip()
            if not txt:
                return False
            if txt in {"?", "-", "—"}:
                return False
            return bool(_LETTER_RE.search(txt))

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

        # collect definitions
        for li in iter_section("Значение"):
            examples = self._extract_examples_from_li(li)
            raw = clean_txt(self._definition_text_from_li(li))
            if not raw:
                continue
            definition, raw_examples = self._split_examples(raw)
            if not examples:
                examples = raw_examples
            senses.append(
                Sense(
                    definition=definition,
                    examples=examples,
                    synonyms=[],
                    pos=None,
                )
            )

        # collect synonyms (shared across all senses)
        for li in iter_section("Синонимы"):
            anchors = li.select(".mw-reference-text a") or li.find_all("a")
            for a in anchors:
                if a.find_parent(class_="mw-cite-backlink"):
                    continue
                txt = clean_txt(a.get_text(" ", strip=True))
                if is_meaningful_token(txt) and txt not in synonyms:
                    synonyms.append(txt)

        if synonyms:
            for s in senses:
                s.synonyms = synonyms[:]
        return senses

    def _definition_text_from_li(self, li) -> str:
        try:
            BS = require_bs4()
            soup = BS(str(li), "html.parser")
            li_copy = soup.find("li")
        except Exception:
            li_copy = None
        if not li_copy:
            return ""
        for bad in li_copy.select(".example-fullblock, .example-block, .source, .example-details"):
            bad.decompose()
        return li_copy.get_text(" ", strip=True)

    def _extract_examples_from_li(self, li) -> List[str]:
        examples: List[str] = []
        seen: set[str] = set()
        blocks = li.select(".example-fullblock .example-block, .example-block")
        for block in blocks:
            html = self._clean_example_block_html(block)
            if not html:
                continue
            key = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip().casefold()
            if key in seen:
                continue
            seen.add(key)
            examples.append(html)
        return examples

    def _clean_example_block_html(self, block) -> str:
        try:
            BS = require_bs4()
            soup = BS(str(block), "html.parser")
            node = soup.find()
        except Exception:
            node = None
        if not node:
            return ""
        for bad in node.select(".example-details, .citation-source, .example-date"):
            bad.decompose()
        for selected in node.select(".example-select"):
            selected.name = "b"
            selected.attrs = {}
        for tag in list(node.find_all(True)):
            if tag.name == "b":
                tag.attrs = {}
                continue
            if tag.name == "br":
                tag.replace_with(" ")
                continue
            tag.unwrap()
        html = node.decode_contents()
        html = html.replace("\u00a0", " ")
        html = re.sub(r"\s+", " ", html).strip()
        html = re.sub(r"\s+([,.;:!?])", r"\1", html)
        html = re.sub(r"<b>\s+", "<b>", html)
        html = re.sub(r"\s+</b>", "</b>", html)
        return html

    def _extract_syllables(self, lang_root) -> Optional[str]:
        if not lang_root:
            return None
        hyph = lang_root.select_one(".hyph-dot")
        if hyph:
            parent = hyph.find_parent(["b", "strong", "span"])
            if parent:
                text = parent.get_text("", strip=True)
                if text:
                    return text
        for b in lang_root.select("p > b"):
            text = b.get_text("", strip=True)
            if not text:
                continue
            if "{" in text or "}" in text:
                continue
            if re.search(r"[А-Яа-я]", text) and len(text) <= 40:
                return text
        for text in lang_root.stripped_strings:
            if "·" in text and re.search(r"[А-Яа-я]", text):
                if len(text) <= 40 and "{" not in text and "}" not in text:
                    return text
        for tag in lang_root.find_all(attrs={"data-mw": True}):
            data = tag.get("data-mw") or ""
            if "по-слогам" not in data:
                continue
            m = re.search(r"по-слогам\|([^}]+)", data)
            if not m:
                continue
            parts = [p for p in m.group(1).split("|") if p and p != "."]
            if parts:
                return "·".join(parts)
        return None

    def _split_examples(self, raw: str):
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
