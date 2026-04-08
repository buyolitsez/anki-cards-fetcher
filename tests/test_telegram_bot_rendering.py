from __future__ import annotations

import pytest

telegram = pytest.importorskip("telegram")

from cambridge_fetch.core.types import CandidateMatch, ResolvedPreset
from cambridge_fetch.models import Sense
from cambridge_fetch.telegram_bot.handlers import _format_preset_details, _help_text, _normalize_query_word, _render_candidates


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
    assert "/preset - show current preset, deck, note type, and sources" in text
    assert "/preset <word> - show the effective preset for a word" in text
