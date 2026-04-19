from __future__ import annotations

from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..core.duplicates import find_duplicate_words, normalize_duplicate_text
from ..core.services import build_note_draft, format_note_preview, resolve_preset, search_word, translate_word
from ..core.types import CandidateMatch, ResolvedPreset, SearchRequest, TranslationCandidate, TranslationRequest
from ..language_detection import detect_word_language
from ..server.repository import Repository

PAGE_SIZE = 5


def _normalize_query_word(word: str) -> str:
    return (word or "").strip().lower()


def _repo(context: ContextTypes.DEFAULT_TYPE) -> Repository:
    return context.application.bot_data["repository"]


def _settings(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["settings"]


def _is_allowed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = _settings(context)
    if not settings.telegram_allowed_user_ids:
        return True
    return int(user_id) in settings.telegram_allowed_user_ids


def _session(context: ContextTypes.DEFAULT_TYPE) -> Dict:
    return context.user_data.setdefault("search_session", {})


def _preset_by_id(manifest: Dict, preset_id: str | None) -> Dict:
    target = str(preset_id or "").strip()
    for preset in manifest.get("presets") or []:
        if str(preset.get("id") or "").strip() == target:
            return dict(preset)
    return {}


def _format_preset_details(*, title: str, preset: ResolvedPreset, manifest: Dict, last_used_preset_id: str | None = None) -> str:
    en_default = (manifest.get("language_default_presets") or {}).get("en")
    ru_default = (manifest.get("language_default_presets") or {}).get("ru")
    lines = [
        title,
        f"Preset: {preset.preset_name} ({preset.preset_id})",
        f"Deck: {preset.deck or '-'}",
        f"Note type: {preset.note_type or '-'}",
        f"Sources: {', '.join(preset.sources) if preset.sources else '-'}",
        f"Detected language: {preset.detected_language or '-'}",
        f"Language defaults: en -> {en_default or '-'}, ru -> {ru_default or '-'}",
        f"Desktop active preset: {manifest.get('active_preset_id') or '-'}",
        f"Bot last used preset: {last_used_preset_id or '-'}",
    ]
    return "\n".join(lines)


def _help_text() -> str:
    return "\n".join(
        [
            "Send me a word like fence or забор.",
            "",
            "Commands:",
            "/help - show this help",
            "/tr <russian word> - translate Russian to English, then continue with normal card selection",
            "/preset - show current preset, deck, note type, and sources",
            "/preset <word> - show the effective preset for a word",
            "",
            "Flow:",
            "1. Send a word",
            "2. Choose a result",
            "3. Confirm Add",
            "4. Open desktop Anki to import queued notes",
        ]
    )


def _render_candidates(session: Dict, page: int) -> tuple[str, InlineKeyboardMarkup]:
    candidates = session.get("candidates") or []
    word = session.get("word") or ""
    preset: ResolvedPreset = session["preset"]
    total_pages = max(1, (len(candidates) + PAGE_SIZE - 1) // PAGE_SIZE)
    safe_page = max(0, min(page, total_pages - 1))
    start = safe_page * PAGE_SIZE
    end = start + PAGE_SIZE
    lines = [
        f"Results for {word}",
        f"Preset: {preset.preset_name}",
        f"Target: {preset.deck or '-'} / {preset.note_type or '-'}",
        "",
    ]
    keyboard = []
    for idx, candidate in enumerate(candidates[start:end], start=start):
        sense = candidate.sense
        pos = f"[{sense.pos}] " if sense.pos else ""
        short_definition = (sense.definition or "").strip()
        if len(short_definition) > 70:
            short_definition = short_definition[:67] + "..."
        label = f"{candidate.source_id}: {pos}{short_definition}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"cand:{idx}:{safe_page}")])
    nav = []
    if safe_page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"page:{safe_page - 1}"))
    if safe_page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"page:{safe_page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("Change preset", callback_data="preset:list:0")])
    keyboard.append([InlineKeyboardButton("Cancel", callback_data="cancel")])
    lines.append(f"Page {safe_page + 1}/{total_pages}")
    session["view_mode"] = "results"
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


def _render_translation_candidates(session: Dict, page: int) -> tuple[str, InlineKeyboardMarkup]:
    candidates = session.get("translation_candidates") or []
    source_word = session.get("translation_source_word") or ""
    total_pages = max(1, (len(candidates) + PAGE_SIZE - 1) // PAGE_SIZE)
    safe_page = max(0, min(page, total_pages - 1))
    start = safe_page * PAGE_SIZE
    end = start + PAGE_SIZE
    lines = [
        f"Translations for {source_word}",
        "Choose the English word to look up:",
        "",
    ]
    keyboard = []
    for idx, candidate in enumerate(candidates[start:end], start=start):
        keyboard.append([InlineKeyboardButton(candidate.word, callback_data=f"trsel:{idx}:{safe_page}")])
    nav = []
    if safe_page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"trpage:{safe_page - 1}"))
    if safe_page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"trpage:{safe_page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("Cancel", callback_data="cancel")])
    lines.append(f"Page {safe_page + 1}/{total_pages}")
    session["view_mode"] = "translation_results"
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


def _render_preset_picker(session: Dict, page: int) -> tuple[str, InlineKeyboardMarkup]:
    manifest = session.get("manifest") or {}
    presets = manifest.get("presets") or []
    total_pages = max(1, (len(presets) + PAGE_SIZE - 1) // PAGE_SIZE)
    safe_page = max(0, min(page, total_pages - 1))
    start = safe_page * PAGE_SIZE
    end = start + PAGE_SIZE
    keyboard = [
        [InlineKeyboardButton(str(preset.get("name") or preset.get("id")), callback_data=f"preset:use:{preset.get('id')}")]
        for preset in presets[start:end]
    ]
    nav = []
    if safe_page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"preset:list:{safe_page - 1}"))
    if safe_page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"preset:list:{safe_page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("Back", callback_data="back:results")])
    return "Choose preset", InlineKeyboardMarkup(keyboard)


def _english_default_preset_id(manifest: Dict) -> Optional[str]:
    mapping = manifest.get("language_default_presets") if isinstance(manifest, dict) else {}
    if not isinstance(mapping, dict):
        return None
    value = mapping.get("en")
    text = str(value or "").strip()
    return text or None


def _translate_usage_text() -> str:
    return "Usage: /tr <russian word>\nExample: /tr багажник"


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not _is_allowed(user.id, context):
        return
    _repo(context).ensure_telegram_user(user.id, allowed=True)
    await update.effective_message.reply_text(_help_text())


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.effective_message or not _is_allowed(user.id, context):
        return
    _repo(context).ensure_telegram_user(user.id, allowed=True)
    await update.effective_message.reply_text(_help_text())


async def handle_translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.effective_message or not _is_allowed(user.id, context):
        return
    repo = _repo(context)
    manifest = repo.latest_manifest()
    if not manifest:
        await update.effective_message.reply_text("No desktop manifest uploaded yet. Pair and sync the Anki add-on first.")
        return
    args = getattr(context, "args", None) or []
    if not args:
        await update.effective_message.reply_text(_translate_usage_text())
        return
    word = _normalize_query_word(" ".join(args))
    if not word or detect_word_language(word) != "ru":
        await update.effective_message.reply_text(_translate_usage_text())
        return

    repo.ensure_telegram_user(user.id, allowed=True)
    result = translate_word(
        TranslationRequest(
            source_word=word,
            source_lang="ru",
            target_lang="en",
            limit=20,
            cfg={},
        )
    )
    if not result.candidates:
        details = "\n".join(result.errors[:4]) if result.errors else "No translations found."
        await update.effective_message.reply_text(details)
        return

    session = _session(context)
    session.clear()
    session.update(
        {
            "mode": "translation_pick",
            "manifest": manifest,
            "translation_source_word": word,
            "translation_candidates": result.candidates,
            "translation_errors": result.errors[:],
        }
    )
    text, markup = _render_translation_candidates(session, 0)
    await update.effective_message.reply_text(text, reply_markup=markup)


async def handle_preset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.effective_message or not _is_allowed(user.id, context):
        return
    repo = _repo(context)
    manifest = repo.latest_manifest()
    if not manifest:
        await update.effective_message.reply_text("No desktop manifest uploaded yet. Pair and sync the Anki add-on first.")
        return
    user_row = repo.telegram_user(user.id)
    last_used_preset_id = str(user_row.get("last_used_preset_id") or "").strip() or None
    args = getattr(context, "args", None) or []
    if args:
        word = _normalize_query_word(" ".join(args))
        preset = resolve_preset(word, None, manifest, last_used_preset_id=last_used_preset_id)
        text = _format_preset_details(
            title=f"Effective preset for {word}",
            preset=preset,
            manifest=manifest,
            last_used_preset_id=last_used_preset_id,
        )
    else:
        base_preset_id = last_used_preset_id or str(manifest.get("active_preset_id") or "").strip() or None
        base_preset_payload = _preset_by_id(manifest, base_preset_id)
        if base_preset_payload:
            preset = resolve_preset(
                "",
                str(base_preset_payload.get("id") or ""),
                manifest,
                last_used_preset_id=last_used_preset_id,
            )
        else:
            preset = resolve_preset("", None, manifest, last_used_preset_id=last_used_preset_id)
        text = _format_preset_details(
            title="Current preset state",
            preset=preset,
            manifest=manifest,
            last_used_preset_id=last_used_preset_id,
        )
    await update.effective_message.reply_text(text)


async def _perform_search(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    word: str,
    explicit_preset_id: Optional[str] = None,
) -> None:
    word = _normalize_query_word(word)
    user = update.effective_user
    if not user:
        return
    repo = _repo(context)
    manifest = repo.latest_manifest()
    if not manifest:
        await update.effective_message.reply_text("No desktop manifest uploaded yet. Pair and sync the Anki add-on first.")
        return

    repo.ensure_telegram_user(user.id, allowed=True)
    user_row = repo.telegram_user(user.id)
    last_used_preset_id = str(user_row.get("last_used_preset_id") or "").strip() or None
    resolved = resolve_preset(word, explicit_preset_id, manifest, last_used_preset_id=last_used_preset_id)
    duplicate_index = repo.duplicate_index_for_client(int(manifest["client_id"]))
    result = search_word(SearchRequest(word=word, source_ids=resolved.sources, cfg=resolved.payload))
    if not result.candidates:
        details = "\n".join(result.errors[:4]) if result.errors else "No definitions found."
        await update.effective_message.reply_text(details)
        return

    session = _session(context)
    session.clear()
    session.update(
        {
            "word": word,
            "manifest": manifest,
            "preset": resolved,
            "candidates": result.candidates,
            "duplicate_index": duplicate_index.get("items") or {},
            "errors": result.errors[:],
        }
    )
    text, markup = _render_candidates(session, 0)
    await update.effective_message.reply_text(text, reply_markup=markup)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.effective_message:
        return
    allowed = _is_allowed(user.id, context)
    _repo(context).ensure_telegram_user(user.id, allowed=allowed)
    if not allowed:
        await update.effective_message.reply_text("This bot is private.")
        return
    text = (update.effective_message.text or "").strip()
    text = _normalize_query_word(text)
    if not text:
        return
    if detect_word_language(text) is None:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("English preset", callback_data=f"lang:en:{text}"),
                    InlineKeyboardButton("Russian preset", callback_data=f"lang:ru:{text}"),
                ],
                [InlineKeyboardButton("Cancel", callback_data="cancel")],
            ]
        )
        await update.effective_message.reply_text("Language is ambiguous. Choose preset family:", reply_markup=keyboard)
        return
    await _perform_search(update=update, context=context, word=text)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user or not _is_allowed(user.id, context):
        return
    await query.answer()
    data = query.data or ""
    session = _session(context)
    repo = _repo(context)

    if data.startswith("lang:"):
        _, lang_code, word = data.split(":", 2)
        manifest = repo.latest_manifest()
        mapping = manifest.get("language_default_presets") if manifest else {}
        preset_id = mapping.get(lang_code) if isinstance(mapping, dict) else None
        await _perform_search(update=update, context=context, word=word, explicit_preset_id=preset_id)
        await query.message.delete()
        return

    if data == "cancel":
        await query.edit_message_text("Cancelled.")
        return

    if data.startswith("page:"):
        page = int(data.split(":")[1])
        text, markup = _render_candidates(session, page)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith("trpage:"):
        page = int(data.split(":")[1])
        text, markup = _render_translation_candidates(session, page)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data == "back:results":
        text, markup = _render_candidates(session, 0)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith("preset:list:"):
        page = int(data.split(":")[2])
        text, markup = _render_preset_picker(session, page)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith("preset:use:"):
        preset_id = data.split(":", 2)[2]
        await _perform_search(
            update=update,
            context=context,
            word=str(session.get("word") or ""),
            explicit_preset_id=preset_id,
        )
        await query.message.delete()
        return

    if data.startswith("trsel:"):
        _, idx_raw, _page_raw = data.split(":")
        index = int(idx_raw)
        candidates: list[TranslationCandidate] = session.get("translation_candidates") or []
        if index < 0 or index >= len(candidates):
            return
        manifest = repo.latest_manifest()
        preset_id = _english_default_preset_id(manifest)
        await _perform_search(
            update=update,
            context=context,
            word=candidates[index].word,
            explicit_preset_id=preset_id,
        )
        await query.message.delete()
        return

    if data.startswith("cand:"):
        _, idx_raw, page_raw = data.split(":")
        index = int(idx_raw)
        page = int(page_raw)
        candidates: list[CandidateMatch] = session.get("candidates") or []
        preset: ResolvedPreset = session.get("preset")
        if index < 0 or index >= len(candidates) or not preset:
            return
        candidate = candidates[index]
        duplicate_exists = find_duplicate_words(
            normalized_word=normalize_duplicate_text(session.get("word") or ""),
            preset_id=preset.preset_id,
            duplicate_index=session.get("duplicate_index"),
        )
        text = format_note_preview(
            sense=candidate.sense,
            source_id=candidate.source_id,
            max_examples=preset.max_examples,
            max_synonyms=preset.max_synonyms,
            preset=preset,
            duplicate_exists=duplicate_exists,
        )
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Add", callback_data=f"add:{index}")],
                [InlineKeyboardButton("Back", callback_data=f"page:{page}")],
                [InlineKeyboardButton("Change preset", callback_data="preset:list:0")],
                [InlineKeyboardButton("Cancel", callback_data="cancel")],
            ]
        )
        await query.edit_message_text(text, reply_markup=keyboard)
        return

    if data.startswith("add:"):
        index = int(data.split(":")[1])
        candidates: list[CandidateMatch] = session.get("candidates") or []
        preset: ResolvedPreset = session.get("preset")
        manifest = session.get("manifest") or {}
        if index < 0 or index >= len(candidates) or not preset or not manifest:
            return
        candidate = candidates[index]
        draft = build_note_draft(
            word=str(session.get("word") or ""),
            source_id=candidate.source_id,
            sense=candidate.sense,
            preset=preset,
        )
        repo.enqueue_draft(
            client_id=int(manifest["client_id"]),
            telegram_user_id=user.id,
            draft=draft,
        )
        repo.set_last_used_preset(user.id, preset.preset_id)
        await query.edit_message_text(
            f"Queued '{draft.query_word}' for preset {draft.resolved_preset_name}. Import it in desktop Anki to create the note."
        )
