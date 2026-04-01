from __future__ import annotations

from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..core.duplicates import find_duplicate_words, normalize_duplicate_text
from ..core.services import build_note_draft, format_note_preview, resolve_preset, search_word
from ..core.types import CandidateMatch, ResolvedPreset, SearchRequest
from ..fetchers import get_fetcher_by_id
from ..language_detection import detect_word_language
from ..server.repository import Repository
from ..typo import collect_validated_typo_suggestions

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


def _render_suggestions(session: Dict, page: int) -> tuple[str, InlineKeyboardMarkup]:
    suggestions = session.get("suggestions") or []
    word = session.get("word") or ""
    preset: ResolvedPreset = session["preset"]
    errors = session.get("errors") or []
    total_pages = max(1, (len(suggestions) + PAGE_SIZE - 1) // PAGE_SIZE)
    safe_page = max(0, min(page, total_pages - 1))
    start = safe_page * PAGE_SIZE
    end = start + PAGE_SIZE
    lines = [
        f"No exact match for {word}",
        f"Preset: {preset.preset_name}",
        "Try one of these suggestions:",
    ]
    if errors:
        lines.append("")
        lines.append("Source errors:")
        lines.extend(errors[:3])
    keyboard = []
    for idx, suggestion in enumerate(suggestions[start:end], start=start):
        keyboard.append([InlineKeyboardButton(str(suggestion), callback_data=f"sug:{idx}:{safe_page}")])
    nav = []
    if safe_page > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"sugpage:{safe_page - 1}"))
    if safe_page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"sugpage:{safe_page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("Change preset", callback_data="preset:list:0")])
    keyboard.append([InlineKeyboardButton("Cancel", callback_data="cancel")])
    lines.append("")
    lines.append(f"Page {safe_page + 1}/{total_pages}")
    session["view_mode"] = "suggestions"
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
    keyboard.append([InlineKeyboardButton("Back", callback_data="back:view")])
    return "Choose preset", InlineKeyboardMarkup(keyboard)


def _typo_max_results(preset_payload: Dict) -> int:
    typo_cfg = preset_payload.get("typo_suggestions") if isinstance(preset_payload.get("typo_suggestions"), dict) else {}
    try:
        value = int(typo_cfg.get("max_results") or 12)
    except Exception:
        value = 12
    return max(1, min(value, 40))


def _collect_bot_suggestions(*, word: str, resolved: ResolvedPreset) -> list[str]:
    typo_cfg = resolved.payload.get("typo_suggestions") if isinstance(resolved.payload.get("typo_suggestions"), dict) else {}
    if not bool(typo_cfg.get("enabled", True)):
        return []
    cfg_snapshot = dict(resolved.payload or {})

    def validate_word(candidate: str) -> bool:
        for source_id in resolved.sources:
            try:
                if get_fetcher_by_id(source_id, cfg_snapshot).fetch(candidate):
                    return True
            except Exception:
                continue
        return False

    result = collect_validated_typo_suggestions(
        word=word,
        source_ids=resolved.sources,
        max_results=_typo_max_results(cfg_snapshot),
        suggest_for_query=lambda source_id, query, fetch_limit: get_fetcher_by_id(source_id, cfg_snapshot).suggest(query, limit=fetch_limit),
        validate_word=validate_word,
    )
    return result.suggestions


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not _is_allowed(user.id, context):
        return
    _repo(context).ensure_telegram_user(user.id, allowed=True)
    await update.effective_message.reply_text(
        "Send me a word like fence or забор. I will search your synced presets and queue the approved note for desktop import."
    )


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
    resolved = resolve_preset(word, explicit_preset_id, manifest)
    duplicate_index = repo.duplicate_index_for_client(int(manifest["client_id"]))
    result = search_word(SearchRequest(word=word, source_ids=resolved.sources, cfg=resolved.payload))
    if not result.candidates:
        suggestions = _collect_bot_suggestions(word=word, resolved=resolved)
        if not suggestions:
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
                "suggestions": suggestions,
                "duplicate_index": duplicate_index.get("items") or {},
                "errors": result.errors[:],
            }
        )
        text, markup = _render_suggestions(session, 0)
        await update.effective_message.reply_text(text, reply_markup=markup)
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

    if data.startswith("sugpage:"):
        page = int(data.split(":")[1])
        text, markup = _render_suggestions(session, page)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data == "back:view":
        if session.get("view_mode") == "suggestions":
            text, markup = _render_suggestions(session, 0)
        else:
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

    if data.startswith("sug:"):
        _, idx_raw, _page_raw = data.split(":")
        index = int(idx_raw)
        suggestions: list[str] = session.get("suggestions") or []
        preset: ResolvedPreset = session.get("preset")
        if index < 0 or index >= len(suggestions) or not preset:
            return
        await _perform_search(
            update=update,
            context=context,
            word=str(suggestions[index]),
            explicit_preset_id=preset.preset_id,
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
