"""ru.wiktionary.org fetcher — extracts Russian word senses, syllables, etc."""

from __future__ import annotations

import html as html_lib
import json
import re
from urllib.parse import quote
from typing import List, Optional

from ..exceptions import FetchError
from ..http_client import USER_AGENT, require_bs4, require_requests
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
    KAIKKI_BASE = "https://kaikki.org/ruwiktionary/%D0%A0%D1%83%D1%81%D1%81%D0%BA%D0%B8%D0%B9/meaning/{one}/{two}/{word}.html"
    TARGET_LANGUAGE = "Русский"
    WIKI_REFERER = "https://ru.wiktionary.org/"

    # Override fetch to also extract syllables (ru-specific)
    def fetch(self, word: str) -> List[Sense]:
        try:
            senses = super().fetch(word)
        except FetchError as exc:
            if "403" not in str(exc):
                raise
            logger.warning("ru.wiktionary returned 403 for '%s', trying Kaikki fallback", word)
            senses = self._fetch_from_kaikki(word)
            if senses:
                return senses
            raise
        if senses:
            return senses
        return self._fetch_from_kaikki(word) or senses

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

    def _fetch_from_kaikki(self, word: str) -> List[Sense]:
        requests = require_requests()
        entries = self._load_kaikki_entries(word)
        if not entries:
            return []

        senses: List[Sense] = []
        seen: set[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = set()
        for entry in entries:
            pos = self._clean_kaikki_text(entry.get("pos"))
            ipa_map = self._kaikki_ipa_map(entry)
            syllables = self._kaikki_syllables(entry)
            shared_synonyms = self._kaikki_synonyms(entry)
            for raw_sense in entry.get("senses") or []:
                glosses = raw_sense.get("glosses") if isinstance(raw_sense, dict) else []
                definition = ""
                if isinstance(glosses, list):
                    definition = next((self._clean_kaikki_text(item) for item in glosses if self._clean_kaikki_text(item)), "")
                if not definition:
                    definition = self._clean_kaikki_text((raw_sense or {}).get("raw_glosses"))
                if not definition:
                    continue
                examples = self._kaikki_examples(raw_sense)
                synonyms = shared_synonyms or self._kaikki_synonyms(raw_sense)
                key = (
                    definition.casefold(),
                    pos.casefold(),
                    tuple(example.casefold() for example in examples),
                    tuple(item.casefold() for item in synonyms),
                )
                if key in seen:
                    continue
                seen.add(key)
                senses.append(
                    Sense(
                        definition=definition,
                        examples=examples,
                        synonyms=synonyms,
                        pos=pos,
                        syllables=syllables,
                        ipa=ipa_map.copy(),
                    )
                )
        logger.info("Kaikki fallback: found %d senses for '%s'", len(senses), word)
        return senses

    def _load_kaikki_entries(self, word: str) -> List[dict]:
        requests = require_requests()
        text = (word or "").strip()
        if not text:
            return []
        first = quote(text[:1])
        first_two = quote(text[:2] if len(text) > 1 else text[:1])
        full = quote(text)
        url = self.KAIKKI_BASE.format(one=first, two=first_two, word=full)
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
                },
                timeout=20,
            )
        except Exception as exc:
            logger.warning("Kaikki request failed for '%s': %s", word, exc)
            return []
        if resp.status_code == 404:
            return []
        if resp.status_code >= 400:
            logger.warning("Kaikki returned HTTP %d for '%s'", resp.status_code, word)
            return []
        resp.encoding = "utf-8"
        blocks = re.findall(r"<pre[^>]*>(.*?)</pre>", resp.text, flags=re.S | re.I)
        decoder = json.JSONDecoder()
        entries: List[dict] = []
        for block in blocks:
            unescaped = html_lib.unescape(block).strip()
            if not unescaped:
                continue
            try:
                parsed, _end = decoder.raw_decode(unescaped)
            except Exception:
                continue
            if isinstance(parsed, dict) and self._clean_kaikki_text(parsed.get("word")) == text:
                entries.append(parsed)
        return entries

    @staticmethod
    def _clean_kaikki_text(value) -> str:
        if not isinstance(value, str):
            return ""
        text = html_lib.unescape(value).replace("\u00a0", " ")
        return " ".join(text.split()).strip()

    def _kaikki_examples(self, raw_sense: dict) -> List[str]:
        examples: List[str] = []
        seen: set[str] = set()
        for item in raw_sense.get("examples") or []:
            if not isinstance(item, dict):
                continue
            text = self._clean_kaikki_text(item.get("text"))
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            examples.append(text)
        return examples

    def _kaikki_synonyms(self, source: dict) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()
        for item in source.get("synonyms") or []:
            if isinstance(item, dict):
                text = self._clean_kaikki_text(item.get("word"))
            else:
                text = self._clean_kaikki_text(item)
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
        return out

    def _kaikki_ipa_map(self, entry: dict) -> dict[str, str]:
        ipa_map: dict[str, str] = {}
        for sound in entry.get("sounds") or []:
            if not isinstance(sound, dict):
                continue
            ipa = self._clean_kaikki_text(sound.get("ipa"))
            if not ipa:
                continue
            tags = [self._clean_kaikki_text(tag).lower() for tag in sound.get("tags") or [] if self._clean_kaikki_text(tag)]
            if "uk" in tags:
                ipa_map.setdefault("uk", ipa)
            elif "us" in tags:
                ipa_map.setdefault("us", ipa)
            else:
                ipa_map.setdefault("default", ipa)
        return ipa_map

    def _kaikki_syllables(self, entry: dict) -> Optional[str]:
        for hyphenation in entry.get("hyphenation") or []:
            if isinstance(hyphenation, dict):
                value = self._clean_kaikki_text(hyphenation.get("hyphenation"))
            else:
                value = self._clean_kaikki_text(hyphenation)
            if value:
                return value
        return None
