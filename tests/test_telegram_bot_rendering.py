from __future__ import annotations

import pytest

telegram = pytest.importorskip("telegram")

from cambridge_fetch.core.types import CandidateMatch, ResolvedPreset
from cambridge_fetch.models import Sense
from cambridge_fetch.telegram_bot.handlers import _render_candidates, _render_suggestions


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


def test_render_suggestions_paginates_and_uses_dropdown_callbacks():
    session = {
        "word": "fnec",
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
        "suggestions": ["fence", "fennec", "finer", "fine", "face", "fancy"],
        "errors": ["cambridge: HTTP 404"],
    }

    text, markup = _render_suggestions(session, 0)

    assert "No exact match for fnec" in text
    assert "Try one of these suggestions:" in text
    assert "cambridge: HTTP 404" in text
    assert markup.inline_keyboard[0][0].callback_data == "sug:0:0"
    assert markup.inline_keyboard[4][0].callback_data == "sug:4:0"
    assert markup.inline_keyboard[5][0].callback_data == "sugpage:1"
