from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence

from ..defaults import NOTE_DRAFT_SCHEMA_VERSION
from ..fetchers import get_fetcher_by_id
from ..language_detection import detect_word_language
from ..models import Sense
from .duplicates import normalize_duplicate_text
from .source_selection import ensure_source_selection_list
from .translation import get_translator
from .types import (
    CandidateMatch,
    NoteDraft,
    ResolvedPreset,
    SearchRequest,
    SearchResult,
    TranslationRequest,
    TranslationResult,
)


def summarize_candidate(candidate: CandidateMatch | Sense, max_examples: int = 1, max_synonyms: int = 2) -> str:
    sense = candidate.sense if isinstance(candidate, CandidateMatch) else candidate
    preview = sense.preview_text(max_examples=max_examples, max_synonyms=max_synonyms)
    return " ".join(line.strip() for line in preview.splitlines() if line.strip())


def _choose_by_dialect(values: Mapping[str, str], dialect_priority: Sequence[str]) -> tuple[Optional[str], Optional[str]]:
    for pref in dialect_priority:
        if pref in values:
            return values[pref], pref
    if "default" in values:
        return values["default"], "default"
    if values:
        key = next(iter(values.keys()))
        return values[key], key
    return None, None


def resolve_preset(
    word: str,
    explicit_preset_id: Optional[str],
    synced_manifest: Mapping,
    *,
    last_used_preset_id: Optional[str] = None,
) -> ResolvedPreset:
    manifest_presets = synced_manifest.get("presets") if isinstance(synced_manifest.get("presets"), list) else []
    preset_lookup = {str(item.get("id") or "").strip(): item for item in manifest_presets if isinstance(item, dict)}
    detected_language = detect_word_language(word)

    target_preset_id = str(explicit_preset_id or "").strip() or None
    if not target_preset_id:
        mapping = synced_manifest.get("language_default_presets") if isinstance(synced_manifest, Mapping) else {}
        if detected_language and isinstance(mapping, Mapping):
            value = mapping.get(detected_language)
            if isinstance(value, str) and value.strip():
                target_preset_id = value.strip()
    if not target_preset_id:
        if isinstance(last_used_preset_id, str) and last_used_preset_id.strip():
            target_preset_id = last_used_preset_id.strip()
    if not target_preset_id:
        active_id = synced_manifest.get("active_preset_id")
        if isinstance(active_id, str) and active_id.strip():
            target_preset_id = active_id.strip()
    if not target_preset_id and preset_lookup:
        target_preset_id = next(iter(preset_lookup))

    preset = preset_lookup.get(target_preset_id or "") or next(iter(preset_lookup.values()), {})
    preset_id = str(preset.get("id") or target_preset_id or "")
    preset_name = str(preset.get("name") or preset_id or "Preset")
    field_map = preset.get("field_map") if isinstance(preset.get("field_map"), dict) else {}
    wiki_field_map = (
        (preset.get("wiktionary") or {}).get("field_map")
        if isinstance(preset.get("wiktionary"), dict)
        else {}
    )
    sources = ensure_source_selection_list(preset.get("sources") or [])
    dialect_priority = [str(value).lower() for value in (preset.get("dialect_priority") or []) if str(value).strip()]
    if not dialect_priority:
        dialect_priority = ["us", "uk"]

    return ResolvedPreset(
        preset_id=preset_id,
        preset_name=preset_name,
        detected_language=detected_language,
        note_type=preset.get("note_type"),
        deck=preset.get("deck"),
        sources=sources,
        field_map={str(key): list(value) for key, value in field_map.items()},
        wiktionary_field_map={str(key): list(value) for key, value in wiki_field_map.items()},
        dialect_priority=dialect_priority,
        max_examples=max(1, int(preset.get("max_examples") or 2)),
        max_synonyms=max(1, int(preset.get("max_synonyms") or 4)),
        payload=dict(preset),
    )


def search_word(request: SearchRequest) -> SearchResult:
    candidates: List[CandidateMatch] = []
    errors: List[str] = []
    source_ids = ensure_source_selection_list(request.source_ids)
    cfg_snapshot = dict(request.cfg or {})
    max_examples = max(1, int(cfg_snapshot.get("max_examples") or 2))
    max_synonyms = max(1, int(cfg_snapshot.get("max_synonyms") or 4))

    for source_id in source_ids:
        try:
            fetcher = get_fetcher_by_id(source_id, cfg_snapshot)
            senses = fetcher.fetch(request.word) or []
        except Exception as exc:
            errors.append(f"{source_id}: {exc}")
            continue
        for sense in senses:
            match = CandidateMatch(
                source_id=source_id,
                sense=sense,
                summary=summarize_candidate(sense, max_examples=max_examples, max_synonyms=max_synonyms),
                preview=format_note_preview(
                    sense=sense,
                    source_id=source_id,
                    max_examples=max_examples,
                    max_synonyms=max_synonyms,
                ),
            )
            candidates.append(match)

    return SearchResult(word=request.word, source_ids=source_ids, candidates=candidates, errors=errors)


def translate_word(request: TranslationRequest) -> TranslationResult:
    try:
        translator = get_translator(request.source_lang, request.target_lang, request.cfg)
    except Exception as exc:
        return TranslationResult(source_word=request.source_word, candidates=[], errors=[str(exc)])
    try:
        return translator.translate(request)
    except Exception as exc:
        return TranslationResult(
            source_word=request.source_word,
            candidates=[],
            errors=[f"{translator.ID}: {exc}"],
        )


def _append_field(field_values: Dict[str, str], target_fields: Sequence[str], value: str) -> None:
    clean_value = str(value or "").strip()
    if not clean_value:
        return
    for field_name in target_fields:
        clean_name = str(field_name or "").strip()
        if not clean_name:
            continue
        existing = field_values.get(clean_name, "")
        field_values[clean_name] = f"{existing}<br>{clean_value}" if existing else clean_value


def build_note_draft(word: str, source_id: str, sense: Sense, preset: ResolvedPreset) -> NoteDraft:
    field_map = dict(preset.field_map)
    if source_id == "wiktionary":
        merged = dict(field_map)
        merged.update(preset.wiktionary_field_map)
        field_map = merged

    field_values: Dict[str, str] = {}
    ipa_value, _ipa_region = _choose_by_dialect(sense.ipa, preset.dialect_priority)
    audio_value, audio_region = _choose_by_dialect(sense.audio_urls, preset.dialect_priority)

    _append_field(field_values, field_map.get("word") or [], word)
    _append_field(field_values, field_map.get("syllables") or [], sense.syllables or "")
    _append_field(field_values, field_map.get("definition") or [], sense.definition)
    _append_field(field_values, field_map.get("pos") or [], sense.pos or "")
    _append_field(field_values, field_map.get("ipa") or [], ipa_value or "")
    examples = sense.examples[: preset.max_examples]
    numbered_examples = [f"{index + 1}. {text}" for index, text in enumerate(examples)]
    _append_field(field_values, field_map.get("examples") or [], "<br>".join(numbered_examples))
    _append_field(field_values, field_map.get("synonyms") or [], ", ".join(sense.synonyms[: preset.max_synonyms]))

    return NoteDraft(
        schema_version=NOTE_DRAFT_SCHEMA_VERSION,
        source_id=source_id,
        query_word=word,
        resolved_preset_id=preset.preset_id,
        resolved_preset_name=preset.preset_name,
        deck_name=preset.deck,
        note_type_name=preset.note_type,
        field_values=field_values,
        word_field_names=[str(value) for value in (field_map.get("word") or []) if str(value).strip()],
        audio_field_names=[str(value) for value in (field_map.get("audio") or []) if str(value).strip()],
        picture_field_names=[str(value) for value in (field_map.get("picture") or []) if str(value).strip()],
        duplicate_key=normalize_duplicate_text(word),
        definition=sense.definition,
        pos=sense.pos,
        examples=list(examples),
        synonyms=list(sense.synonyms[: preset.max_synonyms]),
        ipa=ipa_value,
        audio_url=audio_value,
        audio_region=audio_region,
        picture_url=sense.picture_url,
        picture_referer=sense.picture_referer,
        picture_thumb_url=sense.picture_thumb_url,
    )


def format_note_preview(
    *,
    sense: Sense,
    source_id: str,
    max_examples: int,
    max_synonyms: int,
    preset: Optional[ResolvedPreset] = None,
    duplicate_exists: bool = False,
) -> str:
    ipa_value, _ = _choose_by_dialect(sense.ipa, preset.dialect_priority if preset else ["us", "uk"])
    lines = [
        f"Source: {source_id}",
        f"Definition: {sense.definition}",
        f"Syllables: {sense.syllables or '-'}",
        f"Examples: {' | '.join(sense.examples[:max_examples]) or '-'}",
        f"Synonyms: {', '.join(sense.synonyms[:max_synonyms]) or '-'}",
        f"POS: {sense.pos or '-'}",
        f"IPA: {ipa_value or '-'}",
        f"Audio: {', '.join(sense.audio_urls.keys()) or '-'}",
        f"Picture: {'yes' if sense.picture_url else 'no'}",
    ]
    if preset:
        lines.extend(
            [
                f"Preset: {preset.preset_name} ({preset.preset_id})",
                f"Deck: {preset.deck or '-'}",
                f"Note type: {preset.note_type or '-'}",
            ]
        )
    if duplicate_exists:
        lines.append("Duplicate warning: already exists in the synced duplicate index")
    return "\n".join(lines)
