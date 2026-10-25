from __future__ import annotations

import dataclasses
import html
import re
from typing import Dict, List, Optional

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from ..core.duplicates import find_duplicate_words, normalize_duplicate_text
from ..core.services import build_note_draft, resolve_preset, search_word
from ..core.types import CandidateMatch, NoteDraft, ResolvedPreset, SearchRequest
from ..defaults import NOTE_DRAFT_SCHEMA_VERSION
from .repository import Repository

MCP_REQUESTER_ID = "claude"

INSTRUCTIONS = """\
Anki card queue of the user. Cards added here are imported into the user's desktop Anki
(the add-on pulls the queue when Anki starts) and then reach AnkiWeb with a normal sync.

When the user asks to add a word to Anki, call add_to_anki with the word in its dictionary
form. Pass `meaning` with a short English gloss of the sense you explained, so the matching
dictionary sense is picked, and pass `context` with the sentence or situation where the
user met the word if they mentioned one. Use lookup_word first only when you need to show
the user the available senses.
"""

_WORD_RE = re.compile(r"[a-zа-яё0-9']+", re.IGNORECASE)
_STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "or", "and", "for", "with", "by", "as", "at",
    "is", "be", "that", "this", "it", "from", "something", "someone", "somebody", "very",
}


def _tokens(text: str) -> set[str]:
    return {token for token in _WORD_RE.findall((text or "").casefold()) if token not in _STOPWORDS}


def pick_candidate(candidates: List[CandidateMatch], meaning: Optional[str]) -> int:
    """Index of the candidate whose definition best matches a free-text gloss."""
    wanted = _tokens(meaning or "")
    if not wanted:
        return 0
    best_index, best_score = 0, 0.0
    for index, candidate in enumerate(candidates):
        sense = candidate.sense
        have = _tokens(" ".join([sense.definition, *sense.synonyms, *sense.examples[:1]]))
        if not have:
            continue
        score = len(wanted & have) / len(wanted)
        if score > best_score:
            best_index, best_score = index, score
    return best_index


def with_context(draft: NoteDraft, preset: ResolvedPreset, context: Optional[str]) -> NoteDraft:
    """Put the user's own context into the `context` fields, or in front of the examples."""
    clean = " ".join((context or "").split())
    if not clean:
        return draft
    target_fields = preset.field_map.get("context") or preset.field_map.get("examples") or []
    value = f"<i>Seen: {html.escape(clean)}</i>"
    field_values = dict(draft.field_values)
    for field_name in target_fields:
        existing = field_values.get(field_name, "")
        field_values[field_name] = f"{value}<br>{existing}" if existing else value
    return dataclasses.replace(draft, field_values=field_values, examples=[clean, *draft.examples])


def manual_draft(word: str, definition: str, preset: ResolvedPreset) -> NoteDraft:
    """Card built from the explanation alone, for words the dictionaries do not know."""
    field_values: Dict[str, str] = {}
    for key, value in (("word", word), ("definition", definition)):
        for field_name in preset.field_map.get(key) or []:
            existing = field_values.get(field_name, "")
            field_values[field_name] = f"{existing}<br>{value}" if existing else value
    return NoteDraft(
        schema_version=NOTE_DRAFT_SCHEMA_VERSION,
        source_id="claude",
        query_word=word,
        resolved_preset_id=preset.preset_id,
        resolved_preset_name=preset.preset_name,
        deck_name=preset.deck,
        note_type_name=preset.note_type,
        field_values=field_values,
        word_field_names=list(preset.field_map.get("word") or []),
        audio_field_names=list(preset.field_map.get("audio") or []),
        picture_field_names=list(preset.field_map.get("picture") or []),
        duplicate_key=normalize_duplicate_text(word),
        definition=definition,
        pos=None,
        examples=[],
        synonyms=[],
        ipa=None,
        audio_url=None,
        audio_region=None,
        picture_url=None,
        picture_referer=None,
        picture_thumb_url=None,
    )


def _candidate_summary(index: int, candidate: CandidateMatch) -> Dict:
    sense = candidate.sense
    return {
        "index": index,
        "source": candidate.source_id,
        "pos": sense.pos,
        "definition": sense.definition,
        "examples": sense.examples[:2],
    }


class AnkiQueueTools:
    """Tool logic, kept apart from the MCP wiring so it can be tested directly."""

    def __init__(self, repository: Repository):
        self.repository = repository

    def _context(self, word: str, preset_id: Optional[str]):
        manifest = self.repository.latest_manifest()
        if not manifest:
            raise ValueError("No desktop manifest on the server yet. Pair and sync the Anki add-on first.")
        preset = resolve_preset(word, preset_id, manifest)
        duplicate_index = self.repository.duplicate_index_for_client(int(manifest["client_id"]))
        normalized_word = normalize_duplicate_text(word)
        is_duplicate = find_duplicate_words(
            normalized_word=normalized_word,
            preset_id=preset.preset_id,
            duplicate_index=duplicate_index.get("items") or {},
        ) or normalized_word in self.repository.pending_duplicate_keys(int(manifest["client_id"]))
        return manifest, preset, is_duplicate

    def lookup_word(self, word: str, preset_id: Optional[str] = None) -> Dict:
        word = " ".join(word.split())
        _manifest, preset, is_duplicate = self._context(word, preset_id)
        result = search_word(SearchRequest(word=word, source_ids=preset.sources, cfg=preset.payload))
        return {
            "word": word,
            "preset": preset.preset_name,
            "deck": preset.deck,
            "already_in_anki": is_duplicate,
            "senses": [_candidate_summary(i, c) for i, c in enumerate(result.candidates)],
            "errors": result.errors,
        }

    def add_to_anki(
        self,
        word: str,
        context: Optional[str] = None,
        meaning: Optional[str] = None,
        sense_index: Optional[int] = None,
        preset_id: Optional[str] = None,
        allow_duplicate: bool = False,
    ) -> Dict:
        word = " ".join(word.split())
        if not word:
            raise ValueError("word is empty.")
        manifest, preset, is_duplicate = self._context(word, preset_id)
        if is_duplicate and not allow_duplicate:
            return {
                "status": "duplicate",
                "message": f"'{word}' is already in deck {preset.deck} or waiting in the queue. Nothing was queued; "
                "call again with allow_duplicate=true to add it anyway.",
            }

        result = search_word(SearchRequest(word=word, source_ids=preset.sources, cfg=preset.payload))
        candidates = result.candidates
        if candidates:
            if sense_index is not None and 0 <= sense_index < len(candidates):
                chosen = sense_index
            else:
                chosen = pick_candidate(candidates, meaning)
            candidate = candidates[chosen]
            draft = build_note_draft(word=word, source_id=candidate.source_id, sense=candidate.sense, preset=preset)
        elif meaning:
            chosen = None
            draft = manual_draft(word, meaning, preset)
        else:
            return {
                "status": "not_found",
                "message": f"No dictionary entry for '{word}'. Call again with `meaning` to add a card "
                "with your own definition.",
                "errors": result.errors,
            }

        draft = with_context(draft, preset, context)
        queued = self.repository.enqueue_draft(
            client_id=int(manifest["client_id"]),
            telegram_user_id=MCP_REQUESTER_ID,
            draft=draft,
        )
        return {
            "status": "queued",
            "queue_id": queued["id"],
            "word": word,
            "deck": preset.deck,
            "note_type": preset.note_type,
            "chosen_sense": draft.definition,
            "other_senses": [
                _candidate_summary(i, c) for i, c in enumerate(candidates) if i != chosen
            ][:8],
            "message": "Queued. It appears in Anki the next time the desktop add-on imports the queue.",
        }

    def recent_cards(self, limit: int = 10) -> Dict:
        return {"items": self.repository.recent_drafts(MCP_REQUESTER_ID, limit)}

    def cancel_card(self, queue_id: int) -> Dict:
        cancelled = self.repository.cancel_pending(MCP_REQUESTER_ID, queue_id)
        if not cancelled:
            return {"status": "not_cancelled", "message": "Only cards that are still pending can be cancelled."}
        return {"status": "cancelled", "queue_id": queue_id}


def create_mcp(repository: Repository, *, allowed_hosts: List[str] | None = None) -> FastMCP:
    tools = AnkiQueueTools(repository)
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(allowed_hosts),
        allowed_hosts=list(allowed_hosts or []),
    )
    mcp = FastMCP("Anki cards", instructions=INSTRUCTIONS, stateless_http=True, transport_security=security)

    @mcp.tool()
    async def add_to_anki(
        word: str,
        context: Optional[str] = None,
        meaning: Optional[str] = None,
        sense_index: Optional[int] = None,
        preset_id: Optional[str] = None,
        allow_duplicate: bool = False,
    ) -> Dict:
        """Queue an Anki card for a word or phrase.

        Definition, IPA, audio and examples come from Cambridge / Wiktionary using the user's preset.
        word: the word in dictionary form. context: where the user saw it (a sentence, a show, a book).
        meaning: short English gloss of the sense discussed; picks the matching dictionary sense and is
        used as the definition when no dictionary has the word. sense_index: exact sense from lookup_word.
        """
        return await anyio.to_thread.run_sync(
            lambda: tools.add_to_anki(word, context, meaning, sense_index, preset_id, allow_duplicate)
        )

    @mcp.tool()
    async def lookup_word(word: str, preset_id: Optional[str] = None) -> Dict:
        """List dictionary senses for a word and whether it is already in Anki. Queues nothing."""
        return await anyio.to_thread.run_sync(lambda: tools.lookup_word(word, preset_id))

    @mcp.tool()
    async def recent_cards(limit: int = 10) -> Dict:
        """Recently queued cards from Claude and their import status (pending, completed, failed)."""
        return tools.recent_cards(limit)

    @mcp.tool()
    async def cancel_card(queue_id: int) -> Dict:
        """Remove a card from the queue if desktop Anki has not imported it yet."""
        return tools.cancel_card(queue_id)

    return mcp
