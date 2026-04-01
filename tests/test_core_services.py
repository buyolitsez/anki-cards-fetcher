from __future__ import annotations

from cambridge_fetch.core.services import build_note_draft, resolve_preset
from cambridge_fetch.models import Sense


def test_resolve_preset_prefers_explicit_preset():
    manifest = {
        "active_preset_id": "default",
        "language_default_presets": {"en": "default", "ru": "ru"},
        "presets": [
            {"id": "default", "name": "English", "sources": ["cambridge"], "note_type": "Basic", "deck": "English"},
            {"id": "ru", "name": "Russian", "sources": ["wiktionary"], "note_type": "Basic", "deck": "Russian"},
        ],
    }

    resolved = resolve_preset("дом", "default", manifest)

    assert resolved.preset_id == "default"
    assert resolved.sources == ["cambridge"]


def test_build_note_draft_renders_field_values():
    preset = resolve_preset(
        "fence",
        "default",
        {
            "active_preset_id": "default",
            "presets": [
                {
                    "id": "default",
                    "name": "Default",
                    "sources": ["cambridge"],
                    "note_type": "Basic",
                    "deck": "Words",
                    "max_examples": 2,
                    "max_synonyms": 2,
                    "field_map": {
                        "word": ["Word"],
                        "definition": ["Definition"],
                        "examples": ["Examples"],
                        "synonyms": ["Synonyms"],
                        "audio": ["Audio"],
                        "picture": ["Picture"],
                    },
                    "wiktionary": {"field_map": {"syllables": ["Syllables"]}},
                    "dialect_priority": ["uk", "us"],
                }
            ],
        },
    )
    sense = Sense(
        definition="a barrier around a field",
        examples=["A wooden fence.", "They painted the fence."],
        synonyms=["barrier", "rail"],
        pos="noun",
        ipa={"uk": "/fens/"},
        audio_urls={"uk": "https://example.com/fence.mp3"},
        picture_url="https://example.com/fence.jpg",
    )

    draft = build_note_draft("fence", "cambridge", sense, preset)

    assert draft.deck_name == "Words"
    assert draft.note_type_name == "Basic"
    assert draft.field_values["Word"] == "fence"
    assert draft.field_values["Definition"] == "a barrier around a field"
    assert "1. A wooden fence." in draft.field_values["Examples"]
    assert draft.audio_url == "https://example.com/fence.mp3"
    assert draft.picture_url == "https://example.com/fence.jpg"
