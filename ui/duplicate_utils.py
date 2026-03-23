from __future__ import annotations

import html
import re
from typing import Iterable, List


_BR_RE = re.compile(r"(?i)<br\s*/?>")
_BLOCK_START_RE = re.compile(r"(?i)<(?:div|p|li|ul|ol|section|article|tr)(?:\s[^>]*)?>")
_BLOCK_END_RE = re.compile(r"(?i)</(?:div|p|li|ul|ol|section|article|tr)>")
_TAG_RE = re.compile(r"<[^>]+>")


def configured_word_fields(field_map: dict) -> List[str]:
    raw_names = field_map.get("word") if isinstance(field_map, dict) else []
    if isinstance(raw_names, str):
        raw_names = [part.strip() for part in raw_names.split(",") if part.strip()]
    out: List[str] = []
    for name in raw_names if isinstance(raw_names, (list, tuple)) else []:
        if not isinstance(name, str):
            continue
        clean = name.strip()
        if clean and clean not in out:
            out.append(clean)
    return out


def normalize_duplicate_text(value: str) -> str:
    text = html.unescape(value or "").replace("\u00a0", " ")
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_START_RE.sub("\n", text)
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = " ".join(text.split())
    return text.casefold()


def split_field_values(value: str) -> List[str]:
    text = html.unescape(value or "").replace("\u00a0", " ")
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_START_RE.sub("\n", text)
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    out: List[str] = []
    for part in text.splitlines():
        clean = " ".join(part.split())
        if clean:
            out.append(clean)
    if not out:
        clean = " ".join(text.split())
        if clean:
            out.append(clean)
    return out


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
