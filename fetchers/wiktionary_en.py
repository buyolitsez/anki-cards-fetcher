from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote, unquote

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore

from ..media import USER_AGENT
from ..models import Sense
from .base import BaseFetcher

LOG_PATH = Path(__file__).resolve().parent.parent / "fetch_log.txt"

HEADING_TAGS = ("h2", "h3", "h4", "h5", "h6")
POS_TITLES = {
    "noun",
    "proper noun",
    "verb",
    "adjective",
    "adverb",
    "pronoun",
    "determiner",
    "preposition",
    "conjunction",
    "interjection",
    "numeral",
    "article",
    "particle",
    "prefix",
    "suffix",
    "abbreviation",
    "initialism",
    "acronym",
    "phrase",
    "idiom",
    "proverb",
    "symbol",
    "letter",
    "noun phrase",
    "verb phrase",
    "adjective phrase",
    "adverb phrase",
    "prepositional phrase",
}


def log(line: str):
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class EnglishWiktionaryFetcher(BaseFetcher):
    ID = "wiktionary_en"
    LABEL = "en.wiktionary.org (en)"
    BASE = "https://en.wiktionary.org/wiki/{word}"

    def fetch(self, word: str) -> List[Sense]:
        if not requests:
            raise RuntimeError("requests module not found. Install requests in the Anki environment.")
        if not BeautifulSoup:
            raise RuntimeError("bs4 not found. Install beautifulsoup4 in the Anki environment.")

        url = self.BASE.format(word=quote(word.strip()))
        log(f"[wiktionary-en] fetch '{word}' -> {url}")
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            log(f"[wiktionary-en] status {resp.status_code}, len={len(resp.text)}")
        except Exception as e:
            log(f"[wiktionary-en] request failed: {e}")
            raise RuntimeError(f"Wiktionary request failed: {e}")
        if resp.status_code == 404:
            log(f"[wiktionary-en] 404 for '{word}'")
            return []
        if resp.status_code >= 400:
            raise RuntimeError(f"Wiktionary returned {resp.status_code} for '{word}'.")

        soup = BeautifulSoup(resp.text, "html.parser")
        lang_root = self._language_headline(soup, "English")
        log(f"[wiktionary-en] lang_root found: {bool(lang_root)}")
        if not lang_root:
            return []

        senses = self._parse_senses(lang_root)
        picture = self._extract_picture(lang_root)
        if picture:
            for s in senses:
                if not s.picture_url:
                    s.picture_url = picture
        log(f"[wiktionary-en] senses found: {len(senses)}, picture: {bool(picture)}")
        return senses

    # ----------------------- helpers -----------------------
    def _language_headline(self, soup, language: str):
        lang_cf = language.casefold()
        # parsoid sections
        for sec in soup.find_all("section"):
            aria = (sec.get("aria-labelledby") or "").casefold()
            if lang_cf in aria:
                return sec

        headline = soup.find(id=language)
        if not headline:
            for span in soup.select(".mw-headline"):
                text = (span.get_text(strip=True) or "").casefold()
                sid = (span.get("id") or "").casefold()
                if text == lang_cf or sid == lang_cf:
                    headline = span
                    break
        if not headline:
            return None
        if headline.name in HEADING_TAGS or headline.name == "section":
            return headline
        return headline.find_parent(list(HEADING_TAGS))

    def _iter_headings(self, lang_root):
        if not lang_root:
            return
        if getattr(lang_root, "name", "") == "section":
            for h in lang_root.find_all(list(HEADING_TAGS)):
                if self._heading_text(h).casefold() == "english":
                    continue
                yield h
            return
        for node in lang_root.find_all_next():
            if node.name == "h2" and node is not lang_root:
                break
            if node.name in HEADING_TAGS:
                if self._heading_text(node).casefold() == "english":
                    continue
                yield node

    def _section_nodes(self, heading):
        nodes = []
        if not heading or heading.name not in HEADING_TAGS:
            return nodes
        stop_level = int(heading.name[1])
        for node in heading.find_all_next():
            if node.name in HEADING_TAGS:
                level = int(node.name[1])
                if level <= stop_level:
                    break
            nodes.append(node)
        return nodes

    def _parse_pronunciation_section(self, heading) -> tuple[Dict[str, str], Dict[str, str]]:
        ipa_map: Dict[str, str] = {}
        audio_map: Dict[str, str] = {}
        nodes = self._section_nodes(heading)
        for node in nodes:
            for ipa in getattr(node, "select", lambda *_: [])(".IPA, .ipa"):
                text = self._clean_text(ipa.get_text(" ", strip=True))
                if not text:
                    continue
                key = self._find_region(ipa) or "default"
                if key not in ipa_map:
                    ipa_map[key] = text
        for node in nodes:
            for tag in getattr(node, "select", lambda *_: [])("audio source, audio, a[href], source[src]"):
                url = tag.get("src") or tag.get("href")
                if not url or not self._is_audio_url(url, tag):
                    continue
                url = self._normalize_url(url)
                key = self._find_region(tag) or "default"
                if key not in audio_map:
                    audio_map[key] = url
        return ipa_map, audio_map

    def _parse_senses(self, lang_root) -> List[Sense]:
        senses: List[Sense] = []
        current_ipa: Dict[str, str] = {}
        current_audio: Dict[str, str] = {}
        for heading in self._iter_headings(lang_root):
            title = self._normalize_title(self._heading_text(heading))
            title_l = title.casefold()
            if title_l.startswith("etymology"):
                current_ipa = {}
                current_audio = {}
                continue
            if title_l == "pronunciation":
                current_ipa, current_audio = self._parse_pronunciation_section(heading)
                continue
            if title_l not in POS_TITLES:
                continue
            nodes = self._section_nodes(heading)
            synonyms = self._parse_synonyms(nodes)
            for ol in self._definition_lists(nodes):
                for li in ol.find_all("li", recursive=False):
                    definition = self._extract_definition(li)
                    if not definition:
                        continue
                    examples = self._extract_examples(li)
                    senses.append(
                        Sense(
                            definition=definition,
                            examples=examples,
                            synonyms=synonyms[:],
                            pos=title,
                            ipa=current_ipa.copy(),
                            audio_urls=current_audio.copy(),
                        )
                    )
        return senses

    def _parse_synonyms(self, nodes) -> List[str]:
        synonyms: List[str] = []
        for node in nodes:
            if getattr(node, "name", None) not in HEADING_TAGS:
                continue
            title = self._normalize_title(self._heading_text(node)).casefold()
            if title != "synonyms":
                continue
            for sub in self._section_nodes(node):
                for a in getattr(sub, "select", lambda *_: [])("a"):
                    txt = self._clean_text(a.get_text(" ", strip=True))
                    if txt and txt not in synonyms:
                        synonyms.append(txt)
                for li in getattr(sub, "select", lambda *_: [])("li"):
                    if li.find("a"):
                        continue
                    txt = self._clean_text(li.get_text(" ", strip=True))
                    if txt and txt not in synonyms:
                        synonyms.append(txt)
            break
        return synonyms

    def _definition_lists(self, nodes):
        for node in nodes:
            if getattr(node, "name", None) != "ol":
                continue
            if node.find_parent("li"):
                continue
            yield node

    def _extract_definition(self, li) -> str:
        try:
            soup = BeautifulSoup(str(li), "html.parser")
            li_copy = soup.find("li")
        except Exception:
            li_copy = None
        if not li_copy:
            return ""
        for child in li_copy.find_all(["ul", "ol", "dl"]):
            child.decompose()
        for sup in li_copy.find_all("sup"):
            sup.decompose()
        return self._clean_text(li_copy.get_text(" ", strip=True))

    def _extract_examples(self, li) -> List[str]:
        examples: List[str] = []
        seen: set[str] = set()
        preferred_selectors = [
            ".quotation",
            ".quote",
            ".usage-example",
            ".example",
            ".use-with-mention",
        ]
        for sel in preferred_selectors:
            for node in li.select(sel):
                html = self._example_html(node)
                html, text = self._clean_example_html(html)
                self._add_example(examples, seen, html, text)
        for node in li.select("ul > li, dl > dd"):
            html = self._example_html(node)
            html, text = self._clean_example_html(html)
            self._add_example(examples, seen, html, text)
        return examples

    def _extract_picture(self, lang_root) -> Optional[str]:
        nodes = []
        if getattr(lang_root, "name", "") == "section":
            nodes = list(lang_root.find_all(True))
        elif getattr(lang_root, "name", "") in HEADING_TAGS:
            nodes = self._section_nodes(lang_root)
        for node in nodes:
            if getattr(node, "name", None) != "img":
                continue
            src = node.get("src") or node.get("data-src") or ""
            if not src:
                continue
            src = src.split(",")[0].split()[0]
            if any(bad in src.lower() for bad in ("icon", "logo", "svg", "favicon")):
                continue
            if "upload.wikimedia.org" not in src and "wikimedia.org" not in src:
                continue
            try:
                width = int(node.get("data-file-width") or node.get("width") or 0)
                height = int(node.get("data-file-height") or node.get("height") or 0)
            except Exception:
                width = height = 0
            if width and height and (width < 80 or height < 80):
                continue
            return self._normalize_url(src)
        return None

    def _heading_text(self, node) -> str:
        if not node:
            return ""
        hl = node.find(class_="mw-headline")
        if hl:
            return hl.get_text(" ", strip=True)
        return node.get_text(" ", strip=True)

    def _normalize_title(self, text: str) -> str:
        text = re.sub(r"\s*\([^)]*\)", "", text)
        text = re.sub(r"\s*\d+$", "", text)
        return " ".join(text.split())

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"\[\d+\]", "", text)
        return " ".join(text.split())

    def _example_html(self, node) -> str:
        try:
            soup = BeautifulSoup(str(node), "html.parser")
            root = soup.find()
        except Exception:
            root = None
        if not root:
            return ""
        # Strip references/citations; keep bold tags only.
        for tag in list(root.find_all(True)):
            if not hasattr(tag, "get"):
                continue
            if tag.name in ("b", "strong"):
                continue
            if tag.name == "sup":
                try:
                    tag.decompose()
                except Exception:
                    pass
                continue
            attrs = getattr(tag, "attrs", None) or {}
            classes = " ".join((attrs.get("class") or []))
            if "reference" in classes or "citation" in classes:
                try:
                    tag.decompose()
                except Exception:
                    pass
                continue
            try:
                tag.unwrap()
            except Exception:
                pass
        return root.decode_contents()

    def _clean_example_html(self, html: str) -> tuple[str, str]:
        if not html:
            return "", ""
        text = self._clean_text(self._strip_html(html))
        if not text:
            return "", ""
        # Strip leading bullets/dashes
        html = re.sub(r"^[\u2022*\-–—]\s*", "", html)
        text = re.sub(r"^[\u2022*\-–—]\s*", "", text)
        # Remove citation prefix when it looks like a bibliographic entry.
        if ":" in text and self._looks_like_citation_prefix(text):
            html = html.split(":", 1)[1].strip()
            text = text.split(":", 1)[1].strip()
        # Drop trailing citation fragments like "->OCLC"
        html = re.sub(r"\s*->\s*OCLC.*$", "", html, flags=re.IGNORECASE)
        text = re.sub(r"\s*->\s*OCLC.*$", "", text, flags=re.IGNORECASE)
        # Trim leftover punctuation
        return html.strip(" \t-–—:;"), text.strip(" \t-–—:;")

    def _looks_like_citation_prefix(self, text: str) -> bool:
        prefix = text.split(":", 1)[0]
        lower = prefix.lower()
        if re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", lower):
            return True
        tokens = [
            "published",
            "chapter",
            "volume",
            "vol.",
            "edition",
            "press",
            "company",
            "oclc",
            "isbn",
            "new york",
            "london",
        ]
        if any(tok in lower for tok in tokens):
            return True
        return False

    def _add_example(self, examples: List[str], seen: set[str], html: str, text: str):
        if not text:
            return
        norm = self._norm_example(text)
        if not norm or norm in seen:
            return
        seen.add(norm)
        examples.append(html)

    def _norm_example(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"[\"'“”‘’]", "", text)
        text = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
        return text

    def _strip_html(self, html: str) -> str:
        try:
            soup = BeautifulSoup(html, "html.parser")
            return soup.get_text(" ", strip=True)
        except Exception:
            return re.sub(r"<[^>]+>", " ", html)

    def _is_audio_url(self, url: str, tag) -> bool:
        if re.search(r"\.(mp3|ogg|wav)\b", url, re.IGNORECASE):
            return True
        if "upload.wikimedia.org" in url and "audio" in (tag.get("type") or ""):
            return True
        if "Special:FilePath" in url:
            return True
        return False

    def _normalize_url(self, url: str) -> str:
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/wiki/File:"):
            filename = unquote(url.split("/wiki/File:", 1)[1])
            return f"https://en.wiktionary.org/wiki/Special:FilePath/{quote(filename)}"
        if url.startswith("/wiki/Special:FilePath/"):
            return "https://en.wiktionary.org" + url
        if url.startswith("/"):
            return "https://en.wiktionary.org" + url
        return url

    def _find_region(self, tag) -> Optional[str]:
        # Try to locate UK/US hints near tag
        parents = []
        cur = tag
        for _ in range(5):
            if not cur:
                break
            parents.append(cur)
            cur = getattr(cur, "parent", None)
        for node in parents:
            text = self._clean_text(getattr(node, "get_text", lambda *_: "")(" ", strip=True)).lower()
            region = self._region_from_text(text)
            if region:
                return region
        # check row/label text if in a table
        tr = tag.find_parent("tr") if hasattr(tag, "find_parent") else None
        if tr:
            region = self._region_from_text(self._clean_text(tr.get_text(" ", strip=True)).lower())
            if region:
                return region
        return None

    def _region_from_text(self, text: str) -> Optional[str]:
        if re.search(r"\b(us|u\.s\.)\b", text) or "american" in text:
            return "us"
        if re.search(r"\b(uk|u\.k\.)\b", text) or "british" in text:
            return "uk"
        return None

    @property
    def supports_audio(self) -> bool:
        return True

    @property
    def supports_picture(self) -> bool:
        return True
