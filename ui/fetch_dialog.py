"""Main fetch dialog — enter a word, pick a sense, insert into Anki."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
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
)
from aqt.utils import showInfo, showWarning, tooltip

from ..config import get_active_preset, get_config, save_config
from ..fetchers import get_fetcher_by_id, get_fetchers
from ..language_detection import decide_language_default_preset
from ..logger import get_logger
from ..media import download_to_media
from ..models import Sense
from ..typo import TypoCollectResult, collect_typo_suggestions
from .image_search_dialog import ImageSearchDialog
from .picture_preview_dialog import PicturePreviewDialog
from .source_utils import configured_source_ids, ensure_source_selection, set_source_selection
from .suggestion_picker_dialog import SuggestionPickerDialog

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_FETCH_WORKERS = 4
_MAX_TYPO_SUGGEST_WORKERS = 8
_TYPO_CACHE_LIMIT = 80
_POLL_INTERVAL_MS = 100
_AUTO_PRESET_DEBOUNCE_MS = 300
_SEARCH_STATE_IDLE = "idle"
_SEARCH_STATE_FETCHING = "fetching"
_SEARCH_STATE_TYPO = "typo_collecting"


class FetchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = get_config()
        self._applying_preset = False
        self.senses: List[Sense] = []
        self.sense_sources: List[str] = []
        self._typo_cache: Dict[Tuple[str, str, int], List[str]] = {}
        self.source_checks: Dict[str, QCheckBox] = {}
        self.source_labels: Dict[str, str] = {}
        self.source_status_labels: Dict[str, QLabel] = {}
        self._search_state = _SEARCH_STATE_IDLE
        self._operation_id = 0
        self._active_operation_id = 0
        self._cancel_event = Event()
        self._fetch_executor: Optional[ThreadPoolExecutor] = None
        self._fetch_timer: Optional[QTimer] = None
        self._fetch_future_to_source: Dict[Future, Tuple[str, int]] = {}
        self._fetch_errors: List[str] = []
        self._fetch_word: str = ""
        self._fetch_source_ids: List[str] = []
        self._typo_executor: Optional[ThreadPoolExecutor] = None
        self._typo_timer: Optional[QTimer] = None
        self._typo_future: Optional[Future] = None
        self._typo_operation_id = 0
        self._typo_word: str = ""
        self._typo_source_ids: List[str] = []
        self._typo_cfg_snapshot: Dict = {}
        self._typo_max_results = 12
        self._typo_errors: List[str] = []
        self._typo_cache_key: Optional[Tuple[str, str, int]] = None
        self._word_lang_timer: Optional[QTimer] = None
        self._auto_preset_override_locked = False
        self._auto_switching_preset = False
        self._last_detected_language: Optional[str] = None
        self._last_manual_preset_id: Optional[str] = None
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

        self.preset_combo = QComboBox()
        self.ntype_combo = QComboBox()
        self.deck_combo = QComboBox()
        self.source_row = QHBoxLayout()

        self._populate_models()

        top = QHBoxLayout()
        top.addWidget(QLabel("Word:"))
        top.addWidget(self.word_edit)
        top.addWidget(self.fetch_btn)

        combos = QHBoxLayout()
        combos.addWidget(QLabel("Preset:"))
        combos.addWidget(self.preset_combo)
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
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        self.word_edit.textChanged.connect(self._on_word_text_changed)
        self.ntype_combo.currentTextChanged.connect(self._remember_selection)
        self.deck_combo.currentTextChanged.connect(self._remember_selection)
        self._update_image_buttons(-1)
        self._set_search_state(_SEARCH_STATE_IDLE)
        self._last_manual_preset_id = self._active_preset_id()

    # ---------- UI helpers ----------
    def _populate_models(self):
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
        self._reset_source_statuses()
        self.source_row.addStretch(1)

        # note types
        self.ntype_combo.clear()
        models = col.models.allNames()
        for name in models:
            self.ntype_combo.addItem(name, name)

        # decks
        self.deck_combo.clear()
        decks = list(col.decks.allNames())
        for name in decks:
            self.deck_combo.addItem(name, name)

        self._populate_presets_combo()
        active_preset = get_active_preset(self.cfg) or {}
        self._apply_preset_to_controls(active_preset)

    @staticmethod
    def _find_combo_index_by_data(combo: QComboBox, value) -> int:
        if value is None:
            return -1
        for i in range(combo.count()):
            data = combo.itemData(i)
            if isinstance(data, str) and isinstance(value, str):
                if data.strip().casefold() == value.strip().casefold():
                    return i
                continue
            if data == value:
                return i
        return -1

    def _select_combo_value(self, combo: QComboBox, value: Optional[str], missing_suffix: str):
        combo.blockSignals(True)
        try:
            if value is None:
                if combo.count():
                    combo.setCurrentIndex(0)
                return
            idx = self._find_combo_index_by_data(combo, value)
            if idx == -1 and value.strip():
                combo.addItem(f"{value} ({missing_suffix})", value)
                idx = combo.count() - 1
            if idx != -1:
                combo.setCurrentIndex(idx)
        finally:
            combo.blockSignals(False)

    def _populate_presets_combo(self):
        presets = self.cfg.get("presets") if isinstance(self.cfg.get("presets"), list) else []
        self.preset_combo.blockSignals(True)
        try:
            self.preset_combo.clear()
            for preset in presets:
                preset_id = str(preset.get("id") or "").strip()
                if not preset_id:
                    continue
                name = str(preset.get("name") or preset_id).strip() or preset_id
                self.preset_combo.addItem(name, preset_id)
            active_id = str(self.cfg.get("active_preset_id") or "")
            idx = self._find_combo_index_by_data(self.preset_combo, active_id)
            if idx == -1 and self.preset_combo.count():
                idx = 0
            if idx != -1:
                self.preset_combo.setCurrentIndex(idx)
        finally:
            self.preset_combo.blockSignals(False)

    def _active_preset_id(self) -> Optional[str]:
        data = self.preset_combo.currentData()
        if isinstance(data, str) and data.strip():
            return data.strip()
        fallback = self.cfg.get("active_preset_id")
        return str(fallback).strip() if isinstance(fallback, str) and fallback.strip() else None

    def _apply_preset_to_controls(self, preset: Dict):
        self._applying_preset = True
        try:
            note_type = preset.get("note_type")
            deck = preset.get("deck")
            source_ids = preset.get("sources") if isinstance(preset.get("sources"), list) else []
            self._select_combo_value(self.ntype_combo, note_type if isinstance(note_type, str) else None, "missing")
            self._select_combo_value(self.deck_combo, deck if isinstance(deck, str) else None, "missing")
            set_source_selection(self.source_checks, source_ids)
        finally:
            self._applying_preset = False
        if not self._is_fetch_running():
            self._reset_source_statuses()

    def _selected_note_type(self) -> Optional[str]:
        data = self.ntype_combo.currentData()
        if isinstance(data, str) and data.strip():
            return data.strip()
        text = self.ntype_combo.currentText().strip()
        return text or None

    def _selected_deck(self) -> Optional[str]:
        data = self.deck_combo.currentData()
        if isinstance(data, str) and data.strip():
            return data.strip()
        text = self.deck_combo.currentText().strip()
        return text or None

    def on_preset_changed(self, *_):
        manual_change = not self._auto_switching_preset
        manual_change_with_word = manual_change and bool(self.word_edit.text().strip())
        preset_id = self._active_preset_id()
        if not preset_id:
            return
        if manual_change:
            self._last_manual_preset_id = preset_id
        save_config({"active_preset_id": preset_id})
        self.cfg = get_config()
        self._populate_presets_combo()
        preset = get_active_preset(self.cfg) or {}
        self._apply_preset_to_controls(preset)
        if manual_change_with_word:
            self._auto_preset_override_locked = True

    def _ensure_word_lang_timer(self):
        if self._word_lang_timer:
            return
        self._word_lang_timer = QTimer(self)
        self._word_lang_timer.setInterval(_AUTO_PRESET_DEBOUNCE_MS)
        try:
            self._word_lang_timer.setSingleShot(True)
        except Exception:
            pass
        self._word_lang_timer.timeout.connect(self._on_word_input_debounced)

    def _on_word_text_changed(self, *_):
        if self._is_fetch_running():
            return
        if not self.word_edit.text().strip():
            self._auto_preset_override_locked = False
            self._last_detected_language = None
            if self._word_lang_timer and self._word_lang_timer.isActive():
                self._word_lang_timer.stop()
            return
        self._ensure_word_lang_timer()
        if not self._word_lang_timer:
            return
        self._word_lang_timer.start()

    def _on_word_input_debounced(self):
        if self._is_fetch_running():
            return
        self._maybe_auto_select_preset_for_word()

    def _maybe_auto_select_preset_for_word(self):
        self.cfg = get_config()
        decision = decide_language_default_preset(
            word=self.word_edit.text(),
            cfg=self.cfg,
            current_preset_id=self._active_preset_id(),
            manual_preset_id=self._last_manual_preset_id,
            override_locked=self._auto_preset_override_locked,
        )
        self._last_detected_language = decision.detected_language
        if decision.clear_override_lock:
            self._auto_preset_override_locked = False
            self._last_detected_language = None
            return
        if not decision.target_preset_id:
            return
        idx = self._find_combo_index_by_data(self.preset_combo, decision.target_preset_id)
        if idx == -1:
            return
        self._auto_switching_preset = True
        try:
            self.preset_combo.setCurrentIndex(idx)
        finally:
            self._auto_switching_preset = False

    def _remember_selection(self, *_):
        if self._applying_preset:
            return
        source_ids = self._selected_source_ids()
        if not self._is_fetch_running():
            self._reset_source_statuses()
        if not self.cfg.get("remember_last", True):
            return
        updates = {
            "note_type": self._selected_note_type(),
            "deck": self._selected_deck(),
            "sources": source_ids,
        }
        active_preset_id = self._active_preset_id()
        if active_preset_id:
            updates["active_preset_id"] = active_preset_id
        save_config(updates)
        self.cfg = get_config()
        self._populate_presets_combo()

    def _selected_source_ids(self) -> List[str]:
        return ensure_source_selection(self.source_checks)

    def _source_label(self, source_id: str) -> str:
        return self.source_labels.get(source_id, source_id)

    def _is_fetch_running(self) -> bool:
        return self._search_state in (_SEARCH_STATE_FETCHING, _SEARCH_STATE_TYPO)

    def _next_operation_id(self) -> int:
        self._operation_id += 1
        return self._operation_id

    def _set_search_state(self, state: str):
        self._search_state = state
        busy = state != _SEARCH_STATE_IDLE
        self.fetch_btn.setText("Cancel" if busy else "Fetch")
        self._set_search_ui_busy(busy)

    def _set_search_ui_busy(self, is_busy: bool):
        self.word_edit.setEnabled(not is_busy)
        self.preset_combo.setEnabled(not is_busy)
        self.ntype_combo.setEnabled(not is_busy)
        self.deck_combo.setEnabled(not is_busy)
        self.sense_list.setEnabled(not is_busy)
        self.insert_btn.setEnabled(not is_busy)
        self.edit_btn.setEnabled(not is_busy)
        self.image_btn.setEnabled(not is_busy)
        for chk in self.source_checks.values():
            chk.setEnabled(not is_busy)
        if is_busy:
            self.preview_image_btn.setVisible(False)
            self.preview_image_btn.setEnabled(False)
            self.clear_image_btn.setEnabled(False)
        else:
            self._update_image_buttons(self.sense_list.currentRow())
        self.fetch_btn.setEnabled(True)

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
        elif state == "canceled":
            label.setText("canceled")
            label.setStyleSheet("color: #8c5a00;")
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

    def _shutdown_typo_executor(self, cancel_pending: bool):
        if not self._typo_executor:
            return
        try:
            self._typo_executor.shutdown(wait=False, cancel_futures=cancel_pending)
        except TypeError:
            self._typo_executor.shutdown(wait=False)
        self._typo_executor = None

    def _cancel_fetch_tasks(self, cancel_pending: bool, mark_loading_canceled: bool):
        if self._fetch_timer and self._fetch_timer.isActive():
            self._fetch_timer.stop()
        if mark_loading_canceled:
            for future, meta in list(self._fetch_future_to_source.items()):
                source_id, operation_id = meta
                if operation_id == self._active_operation_id and not future.done():
                    self._set_source_status(source_id, "canceled")
        if cancel_pending:
            for future in list(self._fetch_future_to_source.keys()):
                if not future.done():
                    future.cancel()
        self._fetch_future_to_source.clear()
        self._shutdown_fetch_executor(cancel_pending=cancel_pending)
        self._fetch_errors = []
        self._fetch_word = ""
        self._fetch_source_ids = []

    def _cancel_typo_tasks(self, cancel_pending: bool):
        if self._typo_timer and self._typo_timer.isActive():
            self._typo_timer.stop()
        if self._typo_future and cancel_pending and not self._typo_future.done():
            self._typo_future.cancel()
        self._typo_future = None
        self._typo_operation_id = 0
        self._typo_word = ""
        self._typo_source_ids = []
        self._typo_cfg_snapshot = {}
        self._typo_max_results = 12
        self._typo_errors = []
        self._typo_cache_key = None
        self._shutdown_typo_executor(cancel_pending=cancel_pending)

    def _cancel_search(self):
        if not self._is_fetch_running():
            return
        self._cancel_event.set()
        self._cancel_fetch_tasks(cancel_pending=True, mark_loading_canceled=True)
        self._cancel_typo_tasks(cancel_pending=True)
        self._set_search_state(_SEARCH_STATE_IDLE)

    def _sense_item_text(self, sense: Sense, source_id: str) -> str:
        preview = sense.preview_text(self.cfg["max_examples"], self.cfg["max_synonyms"])
        return f"[{self._source_label(source_id)}] {preview}"

    # ---------- Fetch orchestration ----------
    def _fetch_for_source(self, source_id: str, cfg_snapshot: Dict, word: str) -> List[Sense]:
        fetcher = get_fetcher_by_id(source_id, cfg_snapshot)
        return fetcher.fetch(word)

    def _start_fetch(self, word: str, source_ids: List[str], cfg_snapshot: Dict):
        self._cancel_fetch_tasks(cancel_pending=True, mark_loading_canceled=False)
        self._cancel_typo_tasks(cancel_pending=True)
        self._cancel_event = Event()
        self._active_operation_id = self._next_operation_id()
        self._set_search_state(_SEARCH_STATE_FETCHING)
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
            self._fetch_future_to_source[future] = (source_id, self._active_operation_id)

        if not self._fetch_timer:
            self._fetch_timer = QTimer(self)
            self._fetch_timer.setInterval(_POLL_INTERVAL_MS)
            self._fetch_timer.timeout.connect(self._poll_fetch_futures)
        if not self._fetch_future_to_source:
            self._finish_fetch(self._active_operation_id)
            return
        self._fetch_timer.start()

    def _poll_fetch_futures(self):
        if not self._fetch_future_to_source:
            return
        done = [f for f in list(self._fetch_future_to_source.keys()) if f.done()]
        if not done:
            return
        for future in done:
            source_id, operation_id = self._fetch_future_to_source.pop(future)
            if operation_id != self._active_operation_id or self._search_state != _SEARCH_STATE_FETCHING:
                continue
            if self._cancel_event.is_set():
                continue
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
        if not self._fetch_future_to_source and self._search_state == _SEARCH_STATE_FETCHING:
            self._finish_fetch(self._active_operation_id)

    def _finish_fetch(self, operation_id: int):
        if operation_id != self._active_operation_id:
            return
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

        if self._cancel_event.is_set():
            self._set_search_state(_SEARCH_STATE_IDLE)
            return

        if not self.senses:
            if self._start_typo_collection(word, source_ids, errors):
                return
            self._set_search_state(_SEARCH_STATE_IDLE)
            self._show_no_definitions(errors)
            return
        if errors:
            tooltip("Some sources failed:\n" + "\n".join(errors[:3]), parent=self)
        self._set_search_state(_SEARCH_STATE_IDLE)

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
        if self._is_fetch_running():
            self._cancel_search()
            return
        if self._word_lang_timer and self._word_lang_timer.isActive():
            self._word_lang_timer.stop()
        self._maybe_auto_select_preset_for_word()
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
    def _parse_typo_max_results(self) -> int:
        typo_cfg = self.cfg.get("typo_suggestions") if isinstance(self.cfg.get("typo_suggestions"), dict) else {}
        try:
            max_results = int(typo_cfg.get("max_results") or 12)
        except Exception:
            max_results = 12
        return max(1, min(max_results, 40))

    def _cache_typo_suggestions(self, cache_key: Tuple[str, str, int], suggestions: List[str]):
        self._typo_cache[cache_key] = suggestions[:]
        if len(self._typo_cache) > _TYPO_CACHE_LIMIT:
            try:
                oldest = next(iter(self._typo_cache))
                del self._typo_cache[oldest]
            except Exception:
                self._typo_cache.clear()

    def _show_no_definitions(self, errors: List[str]):
        if errors:
            showWarning("No definitions found.\n\n" + "\n".join(errors[:4]))
        else:
            showInfo("No definitions found.")

    def _start_typo_collection(self, word: str, source_ids: List[str], errors: List[str]) -> bool:
        logger.debug("Trying typo suggestions for '%s'", word)
        typo_cfg = self.cfg.get("typo_suggestions") if isinstance(self.cfg.get("typo_suggestions"), dict) else {}
        if not typo_cfg or not bool(typo_cfg.get("enabled", True)):
            return False
        max_results = self._parse_typo_max_results()
        cfg_snapshot = get_config()
        source_key = ",".join(source_ids)
        cache_key = (source_key, word.casefold(), max_results)
        cached = self._typo_cache.get(cache_key)
        if cached is not None:
            self._set_search_state(_SEARCH_STATE_IDLE)
            selected = self._pick_suggestion(word, cached[:], max_results, source_ids, cfg_snapshot)
            if selected:
                self.word_edit.setText(selected)
                self.on_fetch()
            return True

        self._set_search_state(_SEARCH_STATE_TYPO)
        self._typo_operation_id = self._active_operation_id
        self._typo_word = word
        self._typo_source_ids = source_ids[:]
        self._typo_cfg_snapshot = cfg_snapshot
        self._typo_max_results = max_results
        self._typo_errors = errors[:]
        self._typo_cache_key = cache_key
        self._typo_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="typo-collect")
        self._typo_future = self._typo_executor.submit(
            self._collect_typo_in_background,
            word,
            source_ids[:],
            cfg_snapshot,
            max_results,
            self._cancel_event,
        )
        if not self._typo_timer:
            self._typo_timer = QTimer(self)
            self._typo_timer.setInterval(_POLL_INTERVAL_MS)
            self._typo_timer.timeout.connect(self._poll_typo_future)
        self._typo_timer.start()
        return True

    def _collect_typo_in_background(
        self,
        word: str,
        source_ids: List[str],
        cfg_snapshot: Dict,
        max_results: int,
        cancel_event: Event,
    ) -> TypoCollectResult:
        def suggest_for_query(source_id: str, query: str, fetch_limit: int) -> List[str]:
            return self._suggest_for_query(source_id, cfg_snapshot, query, fetch_limit)

        return collect_typo_suggestions(
            word=word,
            source_ids=source_ids,
            max_results=max_results,
            suggest_for_query=suggest_for_query,
            cancel_event=cancel_event,
            max_workers=_MAX_TYPO_SUGGEST_WORKERS,
        )

    def _poll_typo_future(self):
        if not self._typo_future:
            return
        if not self._typo_future.done():
            return

        future = self._typo_future
        operation_id = self._typo_operation_id
        word = self._typo_word
        source_ids = self._typo_source_ids[:]
        cfg_snapshot = self._typo_cfg_snapshot
        max_results = self._typo_max_results
        errors = self._typo_errors[:]
        cache_key = self._typo_cache_key
        self._cancel_typo_tasks(cancel_pending=False)

        if operation_id != self._active_operation_id:
            return
        if self._cancel_event.is_set():
            self._set_search_state(_SEARCH_STATE_IDLE)
            return

        try:
            result = future.result()
        except Exception as e:
            logger.error("Typo suggestion collection failed for '%s': %s", word, e)
            result = TypoCollectResult(suggestions=[], cancelled=False)

        if result.cancelled:
            self._set_search_state(_SEARCH_STATE_IDLE)
            return

        suggestions = result.suggestions[:]
        if suggestions:
            if cache_key is not None:
                self._cache_typo_suggestions(cache_key, suggestions)
            self._set_search_state(_SEARCH_STATE_IDLE)
            selected = self._pick_suggestion(word, suggestions, max_results, source_ids, cfg_snapshot)
            if selected:
                self.word_edit.setText(selected)
                self.on_fetch()
            return

        self._set_search_state(_SEARCH_STATE_IDLE)
        self._show_no_definitions(errors)

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
        has_picture = (
            not self._is_fetch_running()
            and 0 <= row < len(self.senses)
            and bool(self.senses[row].picture_url)
        )
        self.preview_image_btn.setVisible(has_picture)
        self.preview_image_btn.setEnabled(has_picture)
        self.clear_image_btn.setEnabled(has_picture and not self._is_fetch_running())

    # ---------- Image ----------
    def on_find_image(self):
        if self._is_fetch_running():
            return
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
        if self._is_fetch_running():
            return
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
        if self._is_fetch_running():
            return
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
        if self._is_fetch_running():
            return
        row = self.sense_list.currentRow()
        if row < 0 or row >= len(self.senses):
            showWarning("Select a sense first.")
            return
        sense = self.senses[row]
        logger.info("Inserting sense #%d: '%s' (editor=%s)", row, sense.definition[:60], open_editor)
        col = mw.col

        model_name = self._selected_note_type()
        if not model_name:
            showWarning("Select a note type first.")
            return
        model = col.models.byName(model_name)
        if not model:
            showWarning(f"Note type not found: {model_name}")
            return
        deck_name = self._selected_deck()
        if not deck_name:
            showWarning("Select a deck first.")
            return
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
            updates = {"note_type": model["name"], "deck": deck_name, "sources": source_ids}
            active_preset_id = self._active_preset_id()
            if active_preset_id:
                updates["active_preset_id"] = active_preset_id
            save_config(updates)
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
                fname, _ = download_to_media(
                    sense.picture_url,
                    referer=sense.picture_referer,
                    fallback_url=sense.picture_thumb_url,
                    fallback_referer=sense.picture_referer,
                )
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
        if self._word_lang_timer and self._word_lang_timer.isActive():
            self._word_lang_timer.stop()
        self._cancel_search()
        # Safety: persist selected note type/deck even if signals were not triggered
        self._remember_selection()
        super().closeEvent(event)
