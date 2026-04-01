from .duplicates import (
    configured_word_fields,
    find_duplicate_words,
    normalize_duplicate_text,
    split_field_values,
)
from .manifest import manifest_to_dict
from .services import build_note_draft, format_note_preview, resolve_preset, search_word, summarize_candidate
from .source_selection import configured_source_ids, default_source_id, ensure_source_selection_list
from .types import CandidateMatch, NoteDraft, ResolvedPreset, SearchRequest, SearchResult

__all__ = [
    "CandidateMatch",
    "NoteDraft",
    "ResolvedPreset",
    "SearchRequest",
    "SearchResult",
    "build_note_draft",
    "configured_source_ids",
    "configured_word_fields",
    "default_source_id",
    "ensure_source_selection_list",
    "find_duplicate_words",
    "format_note_preview",
    "manifest_to_dict",
    "normalize_duplicate_text",
    "resolve_preset",
    "search_word",
    "split_field_values",
    "summarize_candidate",
]
