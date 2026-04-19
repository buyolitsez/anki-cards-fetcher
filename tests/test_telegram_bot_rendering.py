from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

telegram = pytest.importorskip("telegram")

from cambridge_fetch.core.types import CandidateMatch, ResolvedPreset, TranslationCandidate
from cambridge_fetch.models import Sense
from cambridge_fetch.telegram_bot.handlers import (
    _format_preset_details,
    _help_text,
    _normalize_query_word,
    _render_candidates,
    _render_translation_candidates,
    handle_translate_command,
)


def test_render_candidates_includes_target_metadata():
    session = {
        "word": "fence",
        "preset": ResolvedPreset(
            preset_id="default",
            preset_name="Default",
            detected_language="en",
            note_type="Basic",
            deck="Words",
            sources=["cambridge"],
            field_map={},
            wiktionary_field_map={},
            dialect_priority=["us", "uk"],
            max_examples=2,
            max_synonyms=2,
            payload={},
        ),
        "candidates": [
            CandidateMatch(
                source_id="cambridge",
                sense=Sense(definition="a barrier", pos="noun"),
                summary="a barrier",
                preview="preview",
            )
        ],
    }

    text, markup = _render_candidates(session, 0)

    assert "Results for fence" in text
    assert "Target: Words / Basic" in text
    assert markup.inline_keyboard[0][0].callback_data == "cand:0:0"


def test_normalize_query_word_lowercases_input():
    assert _normalize_query_word("  FeNcE ") == "fence"
    assert _normalize_query_word(" ПРИПАРКА ") == "припарка"


def test_render_translation_candidates_uses_translation_callbacks():
    session = {
        "translation_source_word": "багажник",
        "translation_candidates": [
            TranslationCandidate(word="boot", source_id="kaikki_ru_en"),
            TranslationCandidate(word="trunk", source_id="kaikki_ru_en"),
            TranslationCandidate(word="carrier", source_id="kaikki_ru_en"),
        ],
    }

    text, markup = _render_translation_candidates(session, 0)

    assert "Translations for багажник" in text
    assert "Choose the English word to look up:" in text
    assert markup.inline_keyboard[0][0].callback_data == "trsel:0:0"
    assert markup.inline_keyboard[1][0].callback_data == "trsel:1:0"


def test_format_preset_details_lists_sources_and_targets():
    preset = ResolvedPreset(
        preset_id="default",
        preset_name="Default",
        detected_language="en",
        note_type="Basic",
        deck="Words",
        sources=["cambridge", "wiktionary_en"],
        field_map={},
        wiktionary_field_map={},
        dialect_priority=["us", "uk"],
        max_examples=2,
        max_synonyms=2,
        payload={},
    )

    text = _format_preset_details(
        title="Current preset state",
        preset=preset,
        manifest={"active_preset_id": "default", "language_default_presets": {"en": "default", "ru": "ru"}},
        last_used_preset_id="default",
    )

    assert "Sources: cambridge, wiktionary_en" in text
    assert "Deck: Words" in text
    assert "Note type: Basic" in text


def test_help_text_lists_commands():
    text = _help_text()

    assert "/help - show this help" in text
    assert "/tr <russian word> - translate Russian to English, then continue with normal card selection" in text
    assert "/preset - show current preset, deck, note type, and sources" in text
    assert "/preset <word> - show the effective preset for a word" in text


class _FakeMessage:
    def __init__(self):
        self.calls = []

    async def reply_text(self, text, reply_markup=None):
        self.calls.append({"text": text, "reply_markup": reply_markup})


class _FakeRepo:
    def __init__(self):
        self._user = {"last_used_preset_id": None}

    def latest_manifest(self):
        return {
            "client_id": 1,
            "active_preset_id": "default",
            "language_default_presets": {"en": "default", "ru": "ru"},
            "presets": [{"id": "default", "name": "Default", "sources": ["cambridge"], "note_type": "Basic", "deck": "Words"}],
        }

    def ensure_telegram_user(self, telegram_user_id, *, allowed):
        return {"telegram_user_id": str(telegram_user_id), "is_allowed": int(allowed), **self._user}

    def telegram_user(self, telegram_user_id):
        return dict(self._user)


def test_handle_translate_command_rejects_non_russian_input():
    message = _FakeMessage()
    update = SimpleNamespace(effective_user=SimpleNamespace(id=1), effective_message=message)
    context = SimpleNamespace(
        args=["Fence"],
        application=SimpleNamespace(
            bot_data={
                "repository": _FakeRepo(),
                "settings": SimpleNamespace(telegram_allowed_user_ids=[]),
            }
        ),
        user_data={},
    )

    asyncio.run(handle_translate_command(update, context))

    assert message.calls[0]["text"] == "Usage: /tr <russian word>\nExample: /tr багажник"


def test_handle_translate_command_shows_translation_buttons(monkeypatch):
    message = _FakeMessage()
    update = SimpleNamespace(effective_user=SimpleNamespace(id=1), effective_message=message)
    context = SimpleNamespace(
        args=["багажник"],
        application=SimpleNamespace(
            bot_data={
                "repository": _FakeRepo(),
                "settings": SimpleNamespace(telegram_allowed_user_ids=[]),
            }
        ),
        user_data={},
    )

    monkeypatch.setattr(
        "cambridge_fetch.telegram_bot.handlers.translate_word",
        lambda request: SimpleNamespace(
            candidates=[
                TranslationCandidate(word="boot", source_id="kaikki_ru_en"),
                TranslationCandidate(word="trunk", source_id="kaikki_ru_en"),
            ],
            errors=[],
        ),
    )

    asyncio.run(handle_translate_command(update, context))

    assert "Translations for багажник" in message.calls[0]["text"]
    assert message.calls[0]["reply_markup"].inline_keyboard[0][0].callback_data == "trsel:0:0"
