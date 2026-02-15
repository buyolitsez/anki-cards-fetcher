"""Main fetch dialog — enter a word, pick a sense, insert into Anki."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

from aqt import dialogs, mw
from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QTimer,
    QVBoxLayout,
    Qt,
)
from aqt.utils import showInfo, showWarning, tooltip

from ..config import get_config, save_config
from ..fetchers import get_fetcher_by_id, get_fetchers
from ..logger import get_logger
from ..media import download_to_media
from ..models import Sense
from ..typo import fallback_queries, rank_suggestions
from .image_search_dialog import ImageSearchDialog
from .picture_preview_dialog import PicturePreviewDialog
from .source_utils import configured_source_ids, ensure_source_selection
from .suggestion_picker_dialog import SuggestionPickerDialog

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_FETCH_WORKERS = 4
_MAX_TYPO_SUGGEST_WORKERS = 8
_TYPO_CACHE_LIMIT = 80
_POLL_INTERVAL_MS = 100


class FetchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = get_config()
        self.senses: List[Sense] = []
        self.sense_sources: List[str] = []
        self._typo_cache: Dict[Tuple[str, str, int], List[str]] = {}
        self.source_checks: Dict[str, QCheckBox] = {}
        self.source_labels: Dict[str, str] = {}
        self.source_status_labels: Dict[str, QLabel] = {}
        self._fetch_executor: Optional[ThreadPoolExecutor] = None
        self._fetch_timer: Optional[QTimer] = None
        self._fetch_future_to_source: Dict[Future, str] = {}
        self._fetch_errors: List[str] = []
        self._fetch_word: str = ""
        self._fetch_source_ids: List[str] = []
        self.setWindowTitle("Cambridge / Wiktionary Fetch")

        # widgets
        self.word_edit = QLineEdit()
        self.word_edit.setPlaceholderText("Enter a word…")
        self.fetch_btn = QPushButton("Fetch")
        self.sense_list = QListWidget()
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.edit_btn = QPushButton("Insert & Edit")
        self.insert_btn = QPushButton("Insert")
        self.image_btn = QPushButton("Find Image")
        self.preview_image_btn = QPushButton("Preview Image")
        self.clear_image_btn = QPushButton("Clear Image")

        self.ntype_combo = QComboBox()
        self.deck_combo = QComboBox()
        self.source_row = QHBoxLayout()

        self._populate_models()

        top = QHBoxLayout()
        top.addWidget(QLabel("Word:"))
        top.addWidget(self.word_edit)
        top.addWidget(self.fetch_btn)

        combos = QHBoxLayout()
        combos.addWidget(QLabel("Note type:"))
        combos.addWidget(self.ntype_combo)
        combos.addWidget(QLabel("Deck:"))
        combos.addWidget(self.deck_combo)

        body = QHBoxLayout()
        body.addWidget(self.sense_list, 2)
        body.addWidget(self.preview, 3)

        buttons = QHBoxLayout()
        buttons.addWidget(self.image_btn)
        buttons.addWidget(self.preview_image_btn)
        buttons.addWidget(self.clear_image_btn)
        buttons.addWidget(self.edit_btn)
        buttons.addWidget(self.insert_btn)

        main = QVBoxLayout()
        main.addLayout(top)
        main.addLayout(self.source_row)
        main.addLayout(combos)
        main.addLayout(body)
        main.addLayout(buttons)
        self.setLayout(main)

        # signals
        self.fetch_btn.clicked.connect(self.on_fetch)
        self.sense_list.currentRowChanged.connect(self.on_select)
        self.insert_btn.clicked.connect(lambda: self.on_insert(open_editor=False))
        self.edit_btn.clicked.connect(lambda: self.on_insert(open_editor=True))
        self.sense_list.itemDoubleClicked.connect(lambda _: self.on_insert(open_editor=True))
        self.image_btn.clicked.connect(self.on_find_image)
        self.preview_image_btn.clicked.connect(self.on_preview_image)
        self.clear_image_btn.clicked.connect(self.on_clear_image)
        self.ntype_combo.currentTextChanged.connect(self._remember_selection)
        self.deck_combo.currentTextChanged.connect(self._remember_selection)
        self._update_image_buttons(-1)

    # ---------- UI helpers ----------
    def _populate_models(self):
        # Qt6 renamed MatchFixedString -> MatchFlag.MatchExactly; keep compat with Qt5
        match_fixed = getattr(Qt, "MatchFixedString", None)
        if not match_fixed and hasattr(Qt, "MatchFlag"):
            match_fixed = getattr(Qt.MatchFlag, "MatchExactly", 0)
        # reload config to pick up persisted selections
        self.cfg = get_config()
        col = mw.col
        # sources
        while self.source_row.count():
            item = self.source_row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.source_row.addWidget(QLabel("Sources:"))
        self.source_checks.clear()
        self.source_labels.clear()
        self.source_status_labels.clear()
        fetchers = get_fetchers(self.cfg)
        selected_sources = configured_source_ids(self.cfg)
        for fetcher in fetchers:
            chk = QCheckBox(fetcher.LABEL)
            chk.setChecked(fetcher.ID in selected_sources)
            chk.stateChanged.connect(self._remember_selection)
            status = QLabel("")
            status.setMinimumWidth(64)
            status.setStyleSheet("color: #666;")
            self.source_checks[fetcher.ID] = chk
            self.source_labels[fetcher.ID] = fetcher.LABEL
            self.source_status_labels[fetcher.ID] = status
            self.source_row.addWidget(chk)
            self.source_row.addWidget(status)
        ensure_source_selection(self.source_checks)
        self._reset_source_statuses()
        self.source_row.addStretch(1)

        # note types
        self.ntype_combo.clear()
        models = col.models.allNames()
        self.ntype_combo.addItems(models)
        cfg_model = (self.cfg.get("note_type") or "").strip()
        if cfg_model:
            idx = self.ntype_combo.findText(cfg_model, match_fixed)
            if idx == -1:
                for i, name in enumerate(models):
                    if name.lower() == cfg_model.lower():
                        idx = i
                        break
            if idx != -1:
                self.ntype_combo.setCurrentIndex(idx)
        elif models:
            self.ntype_combo.setCurrentIndex(0)
        # decks
        self.deck_combo.clear()
        decks = list(col.decks.allNames())
        self.deck_combo.addItems(decks)
        cfg_deck = (self.cfg.get("deck") or "").strip()
        if cfg_deck:
            idx = self.deck_combo.findText(cfg_deck, match_fixed)
            if idx == -1:
                for i, name in enumerate(decks):
                    if name.lower() == cfg_deck.lower():
                        idx = i
                        break
            if idx != -1:
                self.deck_combo.setCurrentIndex(idx)
        elif decks:
            self.deck_combo.setCurrentIndex(0)

    def _remember_selection(self, *_):
        source_ids = self._selected_source_ids()
        if not self._is_fetch_running():
            self._reset_source_statuses()
        if not self.cfg.get("remember_last", True):
            return
        save_config(
            {
                "note_type": self.ntype_combo.currentText(),
                "deck": self.deck_combo.currentText(),
                "sources": source_ids,
            }
        )

    def _selected_source_ids(self) -> List[str]:
        return ensure_source_selection(self.source_checks)

    def _source_label(self, source_id: str) -> str:
        return self.source_labels.get(source_id, source_id)

    def _is_fetch_running(self) -> bool:
        return bool(self._fetch_future_to_source)

    def _set_source_status(self, source_id: str, state: str, count: int = 0):
        label = self.source_status_labels.get(source_id)
        if not label:
            return
        if state == "loading":
            label.setText("loading")
            label.setStyleSheet("color: #996600;")
        elif state == "ok":
            label.setText(f"ok ({count})")
            label.setStyleSheet("color: #1f7a1f;")
        elif state == "empty":
            label.setText("empty")
            label.setStyleSheet("color: #666;")
        elif state == "error":
            label.setText("error")
            label.setStyleSheet("color: #b00020;")
        else:
            label.clear()
            label.setStyleSheet("color: #666;")

    def _reset_source_statuses(self):
        for source_id in self.source_status_labels:
            self._set_source_status(source_id, "idle")

    def _shutdown_fetch_executor(self, cancel_pending: bool):
        if not self._fetch_executor:
            return
        try:
            self._fetch_executor.shutdown(wait=False, cancel_futures=cancel_pending)
        except TypeError:
            self._fetch_executor.shutdown(wait=False)
        self._fetch_executor = None

    def _abort_active_fetch(self, cancel_pending: bool):
        if self._fetch_timer and self._fetch_timer.isActive():
            self._fetch_timer.stop()
        if cancel_pending:
            for future in list(self._fetch_future_to_source.keys()):
                if not future.done():
                    future.cancel()
        self._fetch_future_to_source.clear()
        self._shutdown_fetch_executor(cancel_pending=cancel_pending)
        self._fetch_errors = []
        self._fetch_word = ""
        self._fetch_source_ids = []
        self._reset_source_statuses()

    def _sense_item_text(self, sense: Sense, source_id: str) -> str:
        preview = sense.preview_text(self.cfg["max_examples"], self.cfg["max_synonyms"])
        return f"[{self._source_label(source_id)}] {preview}"

    # ---------- Fetch orchestration ----------
    def _fetch_for_source(self, source_id: str, cfg_snapshot: Dict, word: str) -> List[Sense]:
        fetcher = get_fetcher_by_id(source_id, cfg_snapshot)
        return fetcher.fetch(word)

    def _start_fetch(self, word: str, source_ids: List[str], cfg_snapshot: Dict):
        self._abort_active_fetch(cancel_pending=True)
        self.senses = []
        self.sense_sources = []
        self.sense_list.clear()
        self.preview.clear()
        self._update_image_buttons(-1)
        self._fetch_errors = []
        self._fetch_word = word
        self._fetch_source_ids = list(source_ids)

        for source_id in self.source_checks:
            if source_id in source_ids:
                self._set_source_status(source_id, "loading")
            else:
                self._set_source_status(source_id, "idle")

        max_workers = min(_MAX_FETCH_WORKERS, max(1, len(source_ids)))
        self._fetch_executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="multi-fetch")
        for source_id in source_ids:
            try:
                future = self._fetch_executor.submit(self._fetch_for_source, source_id, cfg_snapshot, word)
            except Exception as e:
                self._fetch_errors.append(f"{self._source_label(source_id)}: {e}")
                self._set_source_status(source_id, "error")
                continue
            self._fetch_future_to_source[future] = source_id

        if not self._fetch_timer:
            self._fetch_timer = QTimer(self)
            self._fetch_timer.setInterval(_POLL_INTERVAL_MS)
            self._fetch_timer.timeout.connect(self._poll_fetch_futures)
        if not self._fetch_future_to_source:
            self._finish_fetch()
            return
        self._fetch_timer.start()

    def _poll_fetch_futures(self):
        if not self._fetch_future_to_source:
            return
        done = [f for f in list(self._fetch_future_to_source.keys()) if f.done()]
        if not done:
            return
        for future in done:
            source_id = self._fetch_future_to_source.pop(future)
            try:
                source_senses = future.result() or []
            except Exception as e:
                source_senses = []
                logger.error("Fetch failed for source '%s': %s", source_id, e)
                self._fetch_errors.append(f"{self._source_label(source_id)}: {e}")
                self._set_source_status(source_id, "error")
            else:
                if source_senses:
                    logger.debug("Source '%s' returned %d senses", source_id, len(source_senses))
                    for sense in source_senses:
                        self.senses.append(sense)
                        self.sense_sources.append(source_id)
                        self.sense_list.addItem(QListWidgetItem(self._sense_item_text(sense, source_id)))
                    self._set_source_status(source_id, "ok", len(source_senses))
                else:
                    logger.debug("Source '%s' returned no senses", source_id)
                    self._set_source_status(source_id, "empty")

        if self.sense_list.count() and self.sense_list.currentRow() < 0:
            self.sense_list.setCurrentRow(0)
        if not self._fetch_future_to_source:
            self._finish_fetch()

    def _finish_fetch(self):
        if self._fetch_timer and self._fetch_timer.isActive():
            self._fetch_timer.stop()
        self._shutdown_fetch_executor(cancel_pending=False)
        errors = self._fetch_errors[:]
        word = self._fetch_word
        source_ids = self._fetch_source_ids[:] if self._fetch_source_ids else self._selected_source_ids()
        self._fetch_future_to_source.clear()
        self._fetch_errors = []
        self._fetch_word = ""
        self._fetch_source_ids = []

        if not self.senses:
            if self._try_typo_suggestions(word, source_ids):
                return
            if errors:
                showWarning("No definitions found.\n\n" + "\n".join(errors[:4]))
            else:
                showInfo("No definitions found.")
            return
        if errors:
            tooltip("Some sources failed:\n" + "\n".join(errors[:3]), parent=self)

    def _resolve_field_map(self, source_id: str) -> Dict[str, List[str]]:
        base_map = self.cfg.get("field_map", {})
        if source_id == "wiktionary":
            wiki_map = (self.cfg.get("wiktionary") or {}).get("field_map") or {}
            if wiki_map:
                merged = dict(base_map)
                merged.update(wiki_map)
                return merged
        return base_map

    # ---------- User actions ----------
    def on_fetch(self):
        self.cfg = get_config()
        word = self.word_edit.text().strip()
        if not word:
            showWarning("Enter a word first.")
            return
        source_ids = self._selected_source_ids()
        logger.info("Fetch requested: word='%s', sources=%s", word, source_ids)
        cfg_snapshot = get_config()
        self._start_fetch(word, source_ids, cfg_snapshot)

    # ---------- Typo suggestions ----------
    def _try_typo_suggestions(self, word: str, source_ids: List[str]) -> bool:
        logger.debug("Trying typo suggestions for '%s'", word)
        typo_cfg = self.cfg.get("typo_suggestions") if isinstance(self.cfg.get("typo_suggestions"), dict) else {}
        if not typo_cfg or not bool(typo_cfg.get("enabled", True)):
            return False
        try:
            max_results = int(typo_cfg.get("max_results") or 12)
        except Exception:
            max_results = 12
        max_results = max(1, min(max_results, 40))
        cfg_snapshot = get_config()
        suggestions = self._collect_typo_suggestions(word, source_ids, cfg_snapshot, max_results)
        if not suggestions:
            return False
        selected = self._pick_suggestion(word, suggestions, max_results, source_ids, cfg_snapshot)
        if not selected:
            return True
        self.word_edit.setText(selected)
        self.on_fetch()
        return True

    def _collect_typo_suggestions(self, word: str, source_ids: List[str], cfg_snapshot: Dict, max_results: int) -> List[str]:
        source_key = ",".join(source_ids)
        cache_key = (source_key, word.casefold(), max_results)
        cached = self._typo_cache.get(cache_key)
        if cached is not None:
            return cached[:]

        candidates: List[str] = []
        seen_candidates: set[str] = set()

        def add_candidate(candidate: str):
            item = (candidate or "").strip()
            if not item:
                return
            key = item.casefold()
            if key in seen_candidates:
                return
            seen_candidates.add(key)
            candidates.append(item)

        query_count = max(8, min(max_results + 6, 18))
        fetch_limit = max(8, min(max_results * 2, 20))
        target_candidates = max(max_results * 3, 16)
        queries = fallback_queries(word, max_queries=query_count)
        for query in queries:
            if query.casefold() != word.casefold():
                add_candidate(query)

        max_workers = min(_MAX_TYPO_SUGGEST_WORKERS, max(1, len(queries) * len(source_ids)))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="typo-suggest") as pool:
            future_to_source: Dict[Future, str] = {}
            for source_id in source_ids:
                for query in queries:
                    future = pool.submit(self._suggest_for_query, source_id, cfg_snapshot, query, fetch_limit)
                    future_to_source[future] = source_id
            for future in as_completed(future_to_source):
                try:
                    suggested = future.result()
                except Exception:
                    suggested = []
                for item in suggested:
                    if isinstance(item, str):
                        add_candidate(item)
                if len(candidates) >= target_candidates:
                    for pending in future_to_source:
                        if not pending.done():
                            pending.cancel()
                    break

        ranked_limit = max(max_results * 4, max_results + 12)
        ranked = rank_suggestions(word, candidates, ranked_limit)
        self._typo_cache[cache_key] = ranked
        if len(self._typo_cache) > _TYPO_CACHE_LIMIT:
            try:
                oldest = next(iter(self._typo_cache))
                del self._typo_cache[oldest]
            except Exception:
                self._typo_cache.clear()
        return ranked[:]

    def _suggest_for_query(self, source_id: str, cfg_snapshot: Dict, query: str, fetch_limit: int) -> List[str]:
        fetcher = get_fetcher_by_id(source_id, cfg_snapshot)
        return fetcher.suggest(query, limit=fetch_limit)

    def _pick_suggestion(
        self,
        word: str,
        suggestions: List[str],
        max_results: int,
        source_ids: List[str],
        cfg_snapshot: Dict,
    ) -> Optional[str]:

        def validate(candidate: str) -> bool:
            for source_id in source_ids:
                try:
                    checker = get_fetcher_by_id(source_id, cfg_snapshot)
                    if checker.fetch(candidate):
                        return True
                except Exception:
                    continue
            return False

        dlg = SuggestionPickerDialog(
            self,
            word=word,
            candidates=suggestions,
            validate_word=validate,
            target_count=max_results,
        )
        if not dlg.exec():
            return None
        return dlg.selected_word

    # ---------- Sense selection / preview ----------
    def on_select(self, row: int):
        if row < 0 or row >= len(self.senses):
            self.preview.clear()
            self._update_image_buttons(row)
            return
        sense = self.senses[row]
        source_id = self.sense_sources[row] if row < len(self.sense_sources) else self._selected_source_ids()[0]
        ipa = self._choose_ipa(sense.ipa)
        picture_line = f"Picture: {'yes' if sense.picture_url else 'no'}"
        if sense.picture_url:
            picture_line += f"\nPicture URL: {sense.picture_url}"
        text = [
            f"Source: {self._source_label(source_id)}",
            f"Definition: {sense.definition}",
            f"Syllables: {sense.syllables or '-'}",
            f"Examples: {' | '.join(sense.examples[:self.cfg['max_examples']]) or '-'}",
            f"Synonyms: {', '.join(sense.synonyms[:self.cfg['max_synonyms']]) or '-'}",
            f"POS: {sense.pos or '-'}",
            f"IPA: {ipa or '-'}",
            f"Audio: {', '.join(sense.audio_urls.keys()) or '-'}",
            picture_line,
        ]
        self.preview.setPlainText("\n".join(text))
        self._update_image_buttons(row)

    def _update_image_buttons(self, row: int):
        has_picture = 0 <= row < len(self.senses) and bool(self.senses[row].picture_url)
        self.preview_image_btn.setVisible(has_picture)
        self.preview_image_btn.setEnabled(has_picture)
        self.clear_image_btn.setEnabled(has_picture)

    # ---------- Image ----------
    def on_find_image(self):
        row = self.sense_list.currentRow()
        if row < 0 or row >= len(self.senses):
            showWarning("Select a sense first.")
            return
        query = self.word_edit.text().strip()
        if not query:
            showWarning("Enter a word first.")
            return
        dlg = ImageSearchDialog(self, query=query)
        if dlg.exec():
            if not dlg.selected:
                return
            sense = self.senses[row]
            sense.picture_url = dlg.selected.image_url
            sense.picture_referer = dlg.selected.source_url
            sense.picture_thumb_url = dlg.selected.thumb_url
            sense.picture_thumb_bytes = dlg.selected.thumb_bytes
            self._refresh_sense_item(row)

    def on_preview_image(self):
        row = self.sense_list.currentRow()
        if row < 0 or row >= len(self.senses):
            showWarning("Select a sense first.")
            return
        sense = self.senses[row]
        if not sense.picture_url:
            showInfo("No image for this sense.")
            return
        dlg = PicturePreviewDialog(
            self,
            picture_url=sense.picture_url,
            picture_referer=sense.picture_referer,
            picture_thumb_url=sense.picture_thumb_url,
            picture_thumb_bytes=sense.picture_thumb_bytes,
        )
        dlg.exec()

    def on_clear_image(self):
        row = self.sense_list.currentRow()
        if row < 0 or row >= len(self.senses):
            showWarning("Select a sense first.")
            return
        sense = self.senses[row]
        sense.picture_url = None
        sense.picture_referer = None
        sense.picture_thumb_url = None
        sense.picture_thumb_bytes = None
        self._refresh_sense_item(row)

    # ---------- Insert note ----------
    def on_insert(self, open_editor: bool = False):
        row = self.sense_list.currentRow()
        if row < 0 or row >= len(self.senses):
            showWarning("Select a sense first.")
            return
        sense = self.senses[row]
        logger.info("Inserting sense #%d: '%s' (editor=%s)", row, sense.definition[:60], open_editor)
        col = mw.col

        model_name = self.ntype_combo.currentText()
        model = col.models.byName(model_name)
        deck_name = self.deck_combo.currentText()
        deck_id = col.decks.id(deck_name)
        col.decks.select(deck_id)
        col.models.setCurrent(model)

        note = self._create_note(col, model)
        source_id = self.sense_sources[row] if row < len(self.sense_sources) else self._selected_source_ids()[0]
        fmap: Dict[str, List[str]] = self._resolve_field_map(source_id)

        self._populate_fields(note, sense, fmap)
        self._download_and_set_media(note, sense, fmap)

        # ensure deck id set on note for older API
        try:
            note.model()["did"] = deck_id
        except Exception:
            pass

        self._add_note_to_col(col, note, deck_id)

        if self.cfg.get("remember_last", True):
            source_ids = self._selected_source_ids()
            save_config({"note_type": model["name"], "deck": deck_name, "sources": source_ids})
        mw.reset()
        logger.info("Note added (model=%s, deck=%s)", model_name, deck_name)
        tooltip("Note added.", parent=self)
        if open_editor:
            self._open_browser(note.id)
        self.accept()

    def _create_note(self, col, model):
        """Create a new Anki note, handling legacy API variants."""
        if hasattr(col, "new_note"):
            return col.new_note(model)
        try:
            return col.newNote(False)
        except TypeError:
            return col.newNote()

    def _populate_fields(self, note, sense: Sense, fmap: Dict[str, List[str]]):
        """Map sense data into note fields according to *fmap*."""

        def set_field(key: str, value: str):
            names = fmap.get(key) or []
            if isinstance(names, str):
                names = [n.strip() for n in names.split(",") if n.strip()]
            for name in names:
                if name in note:
                    if not value:
                        continue
                    if note[name]:
                        note[name] = f"{note[name]}<br>{value}"
                    else:
                        note[name] = value

        set_field("word", self.word_edit.text().strip())
        set_field("syllables", sense.syllables or "")
        set_field("definition", sense.definition)
        set_field("pos", sense.pos or "")
        set_field("ipa", self._choose_ipa(sense.ipa) or "")
        ex = sense.examples[: self.cfg["max_examples"]]
        numbered = [f"{i+1}. {txt}" for i, txt in enumerate(ex)]
        set_field("examples", "<br>".join(numbered))
        set_field("synonyms", ", ".join(sense.synonyms[: self.cfg["max_synonyms"]]))

    def _download_and_set_media(self, note, sense: Sense, fmap: Dict[str, List[str]]):
        """Download audio/picture and write the corresponding field tags."""

        def set_field(key: str, value: str):
            names = fmap.get(key) or []
            if isinstance(names, str):
                names = [n.strip() for n in names.split(",") if n.strip()]
            for name in names:
                if name in note:
                    if not value:
                        continue
                    if note[name]:
                        note[name] = f"{note[name]}<br>{value}"
                    else:
                        note[name] = value

        # audio
        audio_tag = ""
        audio_url = self._choose_audio(sense.audio_urls)
        if audio_url:
            try:
                filename, _ = download_to_media(audio_url)
                audio_tag = f"[sound:{filename}]"
            except Exception as e:
                logger.error("Audio download failed: %s (url=%s)", e, audio_url)
                showWarning(f"Audio download failed: {e}")
        set_field("audio", audio_tag)

        # picture
        pic_tag = ""
        if sense.picture_url:
            try:
                fname, _ = download_to_media(sense.picture_url, referer=sense.picture_referer)
                pic_tag = f'<img src="{fname}">'
            except Exception as e:
                logger.error("Image download failed: %s (url=%s)", e, sense.picture_url)
                showWarning(f"Image download failed: {e}")
        set_field("picture", pic_tag)

    @staticmethod
    def _add_note_to_col(col, note, deck_id):
        """Add note via the appropriate Anki API (handles version differences)."""
        added = False
        if hasattr(col, "add_note"):
            try:
                col.add_note(note, deck_id=deck_id)
                added = True
            except TypeError:
                try:
                    col.add_note(note)
                    added = True
                except Exception:
                    pass
        if not added:
            try:
                col.addNote(note, deck_id)
            except TypeError:
                col.addNote(note)

    # ---------- Dialect helpers ----------
    def _choose_audio(self, audio_map: Dict[str, str]) -> Optional[str]:
        return self._choose_by_dialect(audio_map)

    def _choose_ipa(self, ipa_map: Dict[str, str]) -> Optional[str]:
        return self._choose_by_dialect(ipa_map)

    def _choose_by_dialect(self, values: Dict[str, str]) -> Optional[str]:
        for pref in self.cfg.get("dialect_priority", []):
            if pref in values:
                return values[pref]
        if "default" in values:
            return values["default"]
        if values:
            return next(iter(values.values()))
        return None

    def _refresh_sense_item(self, row: int):
        item = self.sense_list.item(row)
        if item and 0 <= row < len(self.senses):
            source_id = self.sense_sources[row] if row < len(self.sense_sources) else self._selected_source_ids()[0]
            item.setText(self._sense_item_text(self.senses[row], source_id))
        self.on_select(row)

    def _open_browser(self, nid: int):
        try:
            browser = dialogs.open("Browser", mw)
            query = f"nid:{nid}"
            if hasattr(browser, "search_for_nids"):
                browser.search_for_nids([nid])
            else:
                try:
                    browser.form.searchEdit.lineEdit().setText(query)  # type: ignore[attr-defined]
                except Exception:
                    pass
                if hasattr(browser, "onSearchActivated"):
                    browser.onSearchActivated()
                elif hasattr(browser, "onSearch"):
                    browser.onSearch()
                elif hasattr(browser, "search"):
                    browser.search()
            browser.activateWindow()
        except Exception:
            logger.exception("Failed to open browser for note %d", nid)

    def closeEvent(self, event):  # type: ignore[override]
        self._abort_active_fetch(cancel_pending=True)
        # Safety: persist selected note type/deck even if signals were not triggered
        self._remember_selection()
        super().closeEvent(event)
