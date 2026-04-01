from __future__ import annotations

from typing import Iterable, List

from ..core.duplicates import configured_word_fields, normalize_duplicate_text, split_field_values


def _escape_search_term(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


def _find_note_ids(col, deck_name: str, note_type_name: str) -> List[int]:
    query = f'deck:"{_escape_search_term(deck_name)}" note:"{_escape_search_term(note_type_name)}"'
    finder = getattr(col, "find_notes", None)
    if callable(finder):
        return list(finder(query) or [])
    legacy_finder = getattr(col, "findNotes", None)
    if callable(legacy_finder):
        return list(legacy_finder(query) or [])
    return []


def _get_note(col, note_id: int):
    getter = getattr(col, "get_note", None)
    if callable(getter):
        return getter(note_id)
    legacy_getter = getattr(col, "getNote", None)
    if callable(legacy_getter):
        return legacy_getter(note_id)
    return None


def find_duplicate_note_ids(
    col,
    *,
    deck_name: str,
    note_type_name: str,
    field_names: Iterable[str],
    word: str,
) -> List[int]:
    normalized_word = normalize_duplicate_text(word)
    fields = [name for name in field_names if isinstance(name, str) and name.strip()]
    if not col or not normalized_word or not deck_name or not note_type_name or not fields:
        return []

    matches: List[int] = []
    for note_id in _find_note_ids(col, deck_name, note_type_name):
        note = _get_note(col, note_id)
        if note is None:
            continue
        for field_name in fields:
            try:
                if field_name not in note:
                    continue
                raw_value = note[field_name] or ""
            except Exception:
                continue
            values = split_field_values(raw_value)
            if any(normalize_duplicate_text(candidate) == normalized_word for candidate in values):
                matches.append(note_id)
                break
    return matches
