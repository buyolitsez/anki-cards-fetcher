from __future__ import annotations

import html
import re
from typing import Dict, Iterable, List, Mapping, Sequence, Set

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


def find_duplicate_words(
    *,
    normalized_word: str,
    preset_id: str,
    duplicate_index: Mapping[str, Sequence[str]] | None,
) -> bool:
    if not normalized_word or not preset_id or not isinstance(duplicate_index, Mapping):
        return False
    values = duplicate_index.get(preset_id) or []
    normalized_values = {str(item).strip() for item in values if str(item).strip()}
    return normalized_word in normalized_values


def build_duplicate_index_map(entries: Iterable[tuple[str, str]]) -> Dict[str, Set[str]]:
    out: Dict[str, Set[str]] = {}
    for preset_id, value in entries:
        clean_preset = str(preset_id).strip()
        clean_value = str(value).strip()
        if not clean_preset or not clean_value:
            continue
        out.setdefault(clean_preset, set()).add(clean_value)
    return out
