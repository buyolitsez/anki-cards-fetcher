from __future__ import annotations

from cambridge_fetch.models import Sense


def test_sense_preview_text_contains_expected_sections():
    sense = Sense(
        definition="a building",
        examples=["Example one", "Example two", "Example three"],
        synonyms=["home", "dwelling"],
        pos="noun",
        syllables="hou·se",
        ipa={"uk": "/haʊs/"},
        audio_urls={"uk": "https://example.org/house.mp3"},
        picture_url="https://example.org/house.jpg",
    )

    text = sense.preview_text(max_examples=2, max_synonyms=1)

    assert "[noun]" in text
    assert "a building" in text
    assert "Examples: Example one | Example two" in text
    assert "Synonyms: home" in text
    assert "Audio: uk" in text
    assert "Picture available" in text
    assert "Syllables: hou·se" in text
    assert "IPA: uk" in text
