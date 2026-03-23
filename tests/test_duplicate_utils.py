from __future__ import annotations

from cambridge_fetch.ui.duplicate_utils import (
    configured_word_fields,
    find_duplicate_note_ids,
    normalize_duplicate_text,
    split_field_values,
)


class _DummyCol:
    def __init__(self, notes):
        self.notes = notes
        self.last_query = None

    def find_notes(self, query):
        self.last_query = query
        return list(self.notes.keys())

    def get_note(self, note_id):
        return self.notes[note_id]


def test_configured_word_fields_dedupes_and_cleans():
    assert configured_word_fields({"word": [" Word ", "Front", "Word", ""]}) == ["Word", "Front"]


def test_split_field_values_handles_html_breaks():
    assert split_field_values("House<br> home <div> dwelling </div>") == ["House", "home", "dwelling"]


def test_normalize_duplicate_text_strips_html_and_case():
    assert normalize_duplicate_text("<b>House</b>&nbsp;") == "house"


def test_find_duplicate_note_ids_matches_configured_word_fields_only():
    col = _DummyCol(
        {
            101: {"Word": "House", "Definition": "A building"},
            102: {"Word": "Home<br>House", "Definition": "Place to live"},
            103: {"Front": "House", "Definition": "Ignored for this mapping"},
            104: {"Word": "Mouse", "Definition": "Animal"},
        }
    )

    matches = find_duplicate_note_ids(
        col,
        deck_name="Default",
        note_type_name="Basic",
        field_names=["Word"],
        word="house",
    )

    assert matches == [101, 102]
    assert col.last_query == 'deck:"Default" note:"Basic"'


def test_find_duplicate_note_ids_escapes_deck_and_note_names():
    col = _DummyCol({1: {"Word": "house"}})

    find_duplicate_note_ids(
        col,
        deck_name='English "Core"',
        note_type_name=r"Basic\Two",
        field_names=["Word"],
        word="house",
    )

    assert col.last_query == 'deck:"English \\"Core\\"" note:"Basic\\\\Two"'
