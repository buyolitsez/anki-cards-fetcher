from __future__ import annotations

from typing import Iterable, List

from ..core.types import NoteDraft
from ..exceptions import MediaDownloadError
from ..media import download_to_media
from ..ui.duplicate_utils import find_duplicate_note_ids


class DraftImportError(RuntimeError):
    pass


class PictureDownloadError(DraftImportError):
    pass


def _create_note(col, model):
    if hasattr(col, "new_note"):
        return col.new_note(model)
    try:
        return col.newNote(False)
    except TypeError:
        return col.newNote()


def _add_note_to_col(col, note, deck_id):
    if hasattr(col, "add_note"):
        try:
            col.add_note(note, deck_id=deck_id)
            return
        except TypeError:
            col.add_note(note)
            return
    try:
        col.addNote(note, deck_id)
    except TypeError:
        col.addNote(note)


def _append_to_fields(note, field_names: Iterable[str], value: str) -> None:
    clean_value = str(value or "").strip()
    if not clean_value:
        return
    for field_name in field_names:
        if field_name not in note:
            continue
        if note[field_name]:
            note[field_name] = f"{note[field_name]}<br>{clean_value}"
        else:
            note[field_name] = clean_value


def add_note_from_draft(col, draft: NoteDraft) -> int:
    model_name = (draft.note_type_name or "").strip()
    if not model_name:
        raise DraftImportError("Draft is missing note type.")
    model = col.models.byName(model_name)
    if not model:
        raise DraftImportError(f"Note type not found: {model_name}")

    deck_name = (draft.deck_name or "").strip()
    if not deck_name:
        raise DraftImportError("Draft is missing deck.")
    deck_id = col.decks.id(deck_name)
    col.decks.select(deck_id)
    col.models.setCurrent(model)

    duplicate_ids = find_duplicate_note_ids(
        col,
        deck_name=deck_name,
        note_type_name=model_name,
        field_names=draft.word_field_names,
        word=draft.query_word,
    )
    if duplicate_ids:
        raise DraftImportError(f"Duplicate already exists ({len(duplicate_ids)} note(s)).")

    note = _create_note(col, model)
    for field_name, value in draft.field_values.items():
        if field_name in note and value:
            note[field_name] = value

    if draft.audio_url:
        filename, _ = download_to_media(draft.audio_url)
        _append_to_fields(note, draft.audio_field_names, f"[sound:{filename}]")
    if draft.picture_url:
        try:
            filename, _ = download_to_media(
                draft.picture_url,
                referer=draft.picture_referer,
                fallback_url=draft.picture_thumb_url,
                fallback_referer=draft.picture_referer,
            )
        except MediaDownloadError as exc:
            raise PictureDownloadError(f"Failed to download image for '{draft.query_word}': {exc}") from exc
        _append_to_fields(note, draft.picture_field_names, f'<img src="{filename}">')

    try:
        note.model()["did"] = deck_id
    except Exception:
        pass
    _add_note_to_col(col, note, deck_id)
    return int(getattr(note, "id", 0) or 0)
