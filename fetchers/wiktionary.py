from __future__ import annotations

import re
from typing import List
from urllib.parse import quote

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


class WiktionaryFetcher(BaseFetcher):
    ID = "wiktionary"
    LABEL = "ru.wiktionary.org (ru)"
    BASE = "https://ru.wiktionary.org/wiki/{word}"

    def fetch(self, word: str) -> List[Sense]:
        if not requests:
            raise RuntimeError("Модуль requests не найден. Установи requests в окружение Anki.")
        if not BeautifulSoup:
            raise RuntimeError("Модуль bs4 не найден. Установи beautifulsoup4 в окружение Anki.")

        url = self.BASE.format(word=quote(word.strip()))
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        if resp.status_code >= 400:
            raise RuntimeError(f"Wiktionary ответил {resp.status_code} для '{word}'.")

        soup = BeautifulSoup(resp.text, "html.parser")
        lang_section = self._language_section(soup, "Русский")
        if not lang_section:
            return []

        senses = self._parse_senses(lang_section)
        return senses

    # ----------------------- helpers -----------------------
    def _language_section(self, soup, language: str):
        """Возвращает список узлов между заголовком языка и следующим заголовком языка."""
        headline = soup.find("span", id=language)
        if not headline:
            return []
        h_tag = headline.find_parent(["h2", "h3"])
        if not h_tag:
            return []
        nodes = []
        for sib in h_tag.next_siblings:
            name = getattr(sib, "name", None)
            if name in ("h2", "h3"):
                other = sib.find("span", {"class": "mw-headline"})
                if other and other.get("id") not in (None, language):
                    break
            if isinstance(sib, str):
                continue
            nodes.append(sib)
        return nodes

    def _parse_senses(self, nodes) -> List[Sense]:
        senses: List[Sense] = []
        synonyms: List[str] = []

        def clean_txt(text: str) -> str:
            txt = re.sub(r"\[\d+\]", "", text)  # убираем сноски вида [1]
            return " ".join(txt.split())

        # собрать определения
        for i, node in enumerate(nodes):
            if node.name and node.name.startswith("h") and self._headline_text(node) == "Значение":
                # look ahead for list until next header
                for nxt in nodes[i + 1 :]:
                    nxt_name = getattr(nxt, "name", "")
                    if nxt_name.startswith("h"):
                        break
                    if nxt.name in ("ol", "ul"):
                        for li in nxt.find_all("li", recursive=False):
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
                        break
        # собрать синонимы (общие для всех sense)
        for i, node in enumerate(nodes):
            if node.name and node.name.startswith("h") and self._headline_text(node) == "Синонимы":
                for nxt in nodes[i + 1 :]:
                    nxt_name = getattr(nxt, "name", "")
                    if nxt_name.startswith("h"):
                        break
                    if nxt.name in ("ol", "ul"):
                        for li in nxt.find_all("li", recursive=False):
                            for a in li.find_all("a"):
                                txt = clean_txt(a.get_text(" ", strip=True))
                                if txt and txt not in synonyms:
                                    synonyms.append(txt)
                        break
        if synonyms:
            for s in senses:
                s.synonyms = synonyms[:]
        return senses

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
