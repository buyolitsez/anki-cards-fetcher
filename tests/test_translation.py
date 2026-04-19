from __future__ import annotations

from cambridge_fetch.core.translation import KaikkiRuEnTranslator
from cambridge_fetch.core.types import TranslationRequest


def test_kaikki_ru_en_translator_prefers_other_field_and_dedupes(monkeypatch):
    def fake_load_entries(self, word: str):
        assert word == "багажник"
        return [
            {
                "pos": "noun",
                "translations": [
                    {"lang_code": "en", "word": "luggage", "other": "boot", "raw_tags": ["брит."]},
                    {"lang_code": "en", "word": "rear", "other": "trunk", "raw_tags": ["амер."]},
                    {"lang_code": "en", "word": "carrier", "other": "trunk"},
                    {"lang_code": "en", "word": "carrier"},
                ],
            }
        ]

    monkeypatch.setattr(KaikkiRuEnTranslator, "_load_entries", fake_load_entries)

    translator = KaikkiRuEnTranslator({})
    result = translator.translate(
        TranslationRequest(source_word="багажник", source_lang="ru", target_lang="en", limit=10, cfg={})
    )

    assert [candidate.word for candidate in result.candidates] == ["boot", "trunk", "carrier"]
    assert result.candidates[0].gloss == "luggage"
    assert result.candidates[1].gloss == "rear"


def test_kaikki_ru_en_translator_uses_word_when_other_is_missing(monkeypatch):
    def fake_load_entries(self, word: str):
        return [
            {
                "pos": "noun",
                "translations": [
                    {"lang_code": "en", "sense": "ограда", "word": "fence"},
                ],
            }
        ]

    monkeypatch.setattr(KaikkiRuEnTranslator, "_load_entries", fake_load_entries)

    translator = KaikkiRuEnTranslator({})
    result = translator.translate(
        TranslationRequest(source_word="забор", source_lang="ru", target_lang="en", limit=10, cfg={})
    )

    assert [candidate.word for candidate in result.candidates] == ["fence"]
    assert result.candidates[0].gloss == "ограда"


def test_kaikki_ru_en_translator_returns_empty_candidates_when_no_english_translations(monkeypatch):
    monkeypatch.setattr(
        KaikkiRuEnTranslator,
        "_load_entries",
        lambda self, word: [{"translations": [{"lang_code": "de", "word": "Hund"}]}],
    )

    translator = KaikkiRuEnTranslator({})
    result = translator.translate(
        TranslationRequest(source_word="собака", source_lang="ru", target_lang="en", limit=10, cfg={})
    )

    assert result.candidates == []
    assert result.errors == []
