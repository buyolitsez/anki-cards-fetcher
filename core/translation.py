from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Type

from ..fetchers.wiktionary import WiktionaryFetcher
from .duplicates import normalize_duplicate_text
from .types import TranslationCandidate, TranslationRequest, TranslationResult

_ENGLISH_TEXT_RE = re.compile(r"^[A-Za-z][A-Za-z' -]*[A-Za-z]$|^[A-Za-z]$")


def _clean_text(value) -> str:
    return " ".join(str(value or "").strip().split())


def _looks_english(value: str) -> bool:
    text = _clean_text(value)
    return bool(text and _ENGLISH_TEXT_RE.fullmatch(text))


def _split_terms(value: str) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []
    parts = re.split(r"\s*[,;/]\s*", text)
    return [part for part in parts if _looks_english(part)]


class BaseTranslator:
    ID = "base"
    SOURCE_LANG = ""
    TARGET_LANG = ""

    def __init__(self, cfg: Dict):
        self.cfg = dict(cfg or {})

    def translate(self, request: TranslationRequest) -> TranslationResult:  # pragma: no cover - interface
        raise NotImplementedError


class KaikkiRuEnTranslator(BaseTranslator):
    ID = "kaikki_ru_en"
    SOURCE_LANG = "ru"
    TARGET_LANG = "en"

    def translate(self, request: TranslationRequest) -> TranslationResult:
        word = _clean_text(request.source_word).lower()
        limit = max(1, int(request.limit or 10))
        if not word:
            return TranslationResult(source_word=word, candidates=[], errors=[])

        entries = self._load_entries(word)
        candidates: List[TranslationCandidate] = []
        seen: set[str] = set()
        for entry in entries:
            pos = _clean_text(entry.get("pos")) or None
            for item in entry.get("translations") or []:
                if not isinstance(item, dict):
                    continue
                if _clean_text(item.get("lang_code")).lower() != "en":
                    continue
                gloss = _clean_text(item.get("sense")) or None
                fallback_gloss = _clean_text(item.get("word")) or None
                primary_terms = _split_terms(item.get("other") or "")
                if not primary_terms:
                    primary_terms = _split_terms(item.get("word") or "")
                for term in primary_terms:
                    key = normalize_duplicate_text(term)
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    candidates.append(
                        TranslationCandidate(
                            word=term.lower(),
                            pos=pos,
                            gloss=gloss or (fallback_gloss if fallback_gloss and normalize_duplicate_text(fallback_gloss) != key else None),
                            source_id=self.ID,
                        )
                    )
                    if len(candidates) >= limit:
                        return TranslationResult(source_word=word, candidates=candidates, errors=[])
        return TranslationResult(source_word=word, candidates=candidates, errors=[])

    def _load_entries(self, word: str) -> list[dict]:
        return WiktionaryFetcher(self.cfg)._load_kaikki_entries(word)


REGISTER: Sequence[Type[BaseTranslator]] = (
    KaikkiRuEnTranslator,
)


def get_translator(source_lang: str, target_lang: str, cfg: Dict) -> BaseTranslator:
    src = _clean_text(source_lang).lower()
    dst = _clean_text(target_lang).lower()
    for translator_cls in REGISTER:
        if translator_cls.SOURCE_LANG == src and translator_cls.TARGET_LANG == dst:
            return translator_cls(cfg)
    raise LookupError(f"Unsupported translation direction: {src or '-'} -> {dst or '-'}")
