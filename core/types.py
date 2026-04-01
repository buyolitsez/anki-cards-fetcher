from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..defaults import NOTE_DRAFT_SCHEMA_VERSION
from ..models import Sense


@dataclass(frozen=True)
class SearchRequest:
    word: str
    source_ids: List[str]
    cfg: Dict


@dataclass(frozen=True)
class CandidateMatch:
    source_id: str
    sense: Sense
    summary: str
    preview: str


@dataclass(frozen=True)
class SearchResult:
    word: str
    source_ids: List[str]
    candidates: List[CandidateMatch]
    errors: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedPreset:
    preset_id: str
    preset_name: str
    detected_language: Optional[str]
    note_type: Optional[str]
    deck: Optional[str]
    sources: List[str]
    field_map: Dict[str, List[str]]
    wiktionary_field_map: Dict[str, List[str]]
    dialect_priority: List[str]
    max_examples: int
    max_synonyms: int
    payload: Dict


@dataclass(frozen=True)
class NoteDraft:
    schema_version: int
    source_id: str
    query_word: str
    resolved_preset_id: str
    resolved_preset_name: str
    deck_name: Optional[str]
    note_type_name: Optional[str]
    field_values: Dict[str, str]
    word_field_names: List[str]
    audio_field_names: List[str]
    picture_field_names: List[str]
    duplicate_key: str
    definition: str
    pos: Optional[str]
    examples: List[str]
    synonyms: List[str]
    ipa: Optional[str]
    audio_url: Optional[str]
    audio_region: Optional[str]
    picture_url: Optional[str]
    picture_referer: Optional[str]
    picture_thumb_url: Optional[str]

    def to_dict(self) -> Dict:
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "query_word": self.query_word,
            "resolved_preset_id": self.resolved_preset_id,
            "resolved_preset_name": self.resolved_preset_name,
            "deck_name": self.deck_name,
            "note_type_name": self.note_type_name,
            "field_values": dict(self.field_values),
            "word_field_names": list(self.word_field_names),
            "audio_field_names": list(self.audio_field_names),
            "picture_field_names": list(self.picture_field_names),
            "duplicate_key": self.duplicate_key,
            "definition": self.definition,
            "pos": self.pos,
            "examples": list(self.examples),
            "synonyms": list(self.synonyms),
            "ipa": self.ipa,
            "audio_url": self.audio_url,
            "audio_region": self.audio_region,
            "picture_url": self.picture_url,
            "picture_referer": self.picture_referer,
            "picture_thumb_url": self.picture_thumb_url,
        }

    @classmethod
    def from_dict(cls, payload: Dict) -> "NoteDraft":
        return cls(
            schema_version=int(payload.get("schema_version") or NOTE_DRAFT_SCHEMA_VERSION),
            source_id=str(payload.get("source_id") or ""),
            query_word=str(payload.get("query_word") or ""),
            resolved_preset_id=str(payload.get("resolved_preset_id") or ""),
            resolved_preset_name=str(payload.get("resolved_preset_name") or ""),
            deck_name=payload.get("deck_name"),
            note_type_name=payload.get("note_type_name"),
            field_values={
                str(key): str(value)
                for key, value in (payload.get("field_values") or {}).items()
                if str(key).strip()
            },
            word_field_names=[
                str(value) for value in (payload.get("word_field_names") or []) if str(value).strip()
            ],
            audio_field_names=[
                str(value) for value in (payload.get("audio_field_names") or []) if str(value).strip()
            ],
            picture_field_names=[
                str(value) for value in (payload.get("picture_field_names") or []) if str(value).strip()
            ],
            duplicate_key=str(payload.get("duplicate_key") or ""),
            definition=str(payload.get("definition") or ""),
            pos=payload.get("pos"),
            examples=[str(value) for value in (payload.get("examples") or []) if str(value).strip()],
            synonyms=[str(value) for value in (payload.get("synonyms") or []) if str(value).strip()],
            ipa=payload.get("ipa"),
            audio_url=payload.get("audio_url"),
            audio_region=payload.get("audio_region"),
            picture_url=payload.get("picture_url"),
            picture_referer=payload.get("picture_referer"),
            picture_thumb_url=payload.get("picture_thumb_url"),
        )
