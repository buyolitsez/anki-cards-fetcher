from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import traceback
from typing import Callable, Dict, List, Optional, Tuple

from aqt import dialogs, mw
from aqt.qt import (
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
from ..media import download_to_media
from ..models import Sense
from ..typo import fallback_queries, rank_suggestions
from .image_search_dialog import ImageSearchDialog


class SuggestionPickerDialog(QDialog):
    def __init__(
        self,
        parent,
        word: str,
        candidates: List[str],
        validate_word: Callable[[str], bool],
        target_count: int,
    ):
        super().__init__(parent)
        self.selected_word: Optional[str] = None
        self._validate_word = validate_word
        self._target_count = max(1, int(target_count))
        self._total = len(candidates)
        self._seen: set[str] = set()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._future_to_word: Dict[Future, str] = {}
        self._checked = 0
        self._confirmed = 0
        self._finished = False

        self.setWindowTitle("Suggestions / Варианты")
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"No exact match for '{word}'.\nТочного совпадения нет. Проверка вариантов..."))
        self.status_label = QLabel("Checking candidates...")
        layout.addWidget(self.status_label)
        self.lst = QListWidget()
        layout.addWidget(self.lst)
        btns = QHBoxLayout()
        self.use_btn = QPushButton("Try selected")
        close_btn = QPushButton("Close")
        self.use_btn.setEnabled(False)
        self.use_btn.clicked.connect(self._accept_selected)
        close_btn.clicked.connect(self.reject)
        self.lst.itemDoubleClicked.connect(lambda _: self._accept_selected())
        self.lst.currentRowChanged.connect(lambda _: self.use_btn.setEnabled(self.lst.currentItem() is not None))
        btns.addWidget(self.use_btn)
        btns.addWidget(close_btn)
        layout.addLayout(btns)
        self.setLayout(layout)

        max_workers = min(8, max(3, self._target_count))
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="typo-check")
        for candidate in candidates:
            future = self._executor.submit(self._safe_validate, candidate)
            self._future_to_word[future] = candidate

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll_futures)
        self._timer.start()
        self._update_status()

    def _safe_validate(self, candidate: str) -> bool:
        try:
            return bool(self._validate_word(candidate))
        except Exception:
            return False

    def _poll_futures(self):
        if self._finished:
            return
        done = [f for f in list(self._future_to_word.keys()) if f.done()]
        if not done:
            return
        for future in done:
            candidate = self._future_to_word.pop(future)
            self._checked += 1
            is_valid = False
            try:
                is_valid = bool(future.result())
            except Exception:
                is_valid = False
            if is_valid:
                key = candidate.casefold()
                if key not in self._seen:
                    self._seen.add(key)
                    self.lst.addItem(candidate)
                    self._confirmed += 1
                    if self.lst.count() == 1:
                        self.lst.setCurrentRow(0)
        if self._confirmed >= self._target_count:
            self._finish(cancel_pending=True)
        elif not self._future_to_word:
            self._finish(cancel_pending=False)
        self._update_status()

    def _update_status(self):
        if self._finished:
            if self._confirmed:
                self.status_label.setText(f"Ready: {self._confirmed} valid suggestions.")
            else:
                self.status_label.setText("No valid suggestions found.")
            return
        self.status_label.setText(
            f"Checking... {self._checked}/{self._total} | valid: {self._confirmed}"
        )

    def _accept_selected(self):
        item = self.lst.currentItem()
        if not item:
            return
        self.selected_word = item.text().strip()
        if not self.selected_word:
            return
        self.accept()

    def _finish(self, cancel_pending: bool):
        if self._finished:
            return
        self._finished = True
        if self._timer.isActive():
            self._timer.stop()
        self._shutdown_executor(cancel_pending=cancel_pending)

    def _shutdown_executor(self, cancel_pending: bool):
        if not self._executor:
            return
        try:
            self._executor.shutdown(wait=False, cancel_futures=cancel_pending)
        except TypeError:
            self._executor.shutdown(wait=False)
        self._executor = None

    def closeEvent(self, event):  # type: ignore[override]
        self._finish(cancel_pending=True)
        super().closeEvent(event)


class FetchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = get_config()
        self.senses: List[Sense] = []
        self._typo_cache: Dict[Tuple[str, str, int], List[str]] = {}
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
        self.clear_image_btn = QPushButton("Clear Image")

        self.source_combo = QComboBox()
        self.ntype_combo = QComboBox()
        self.deck_combo = QComboBox()

        self._populate_models()

        top = QHBoxLayout()
        top.addWidget(QLabel("Word:"))
        top.addWidget(self.word_edit)
        top.addWidget(QLabel("Source:"))
        top.addWidget(self.source_combo)
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
        buttons.addWidget(self.clear_image_btn)
        buttons.addWidget(self.edit_btn)
        buttons.addWidget(self.insert_btn)

        main = QVBoxLayout()
        main.addLayout(top)
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
        self.clear_image_btn.clicked.connect(self.on_clear_image)
        self.ntype_combo.currentTextChanged.connect(self._remember_selection)
        self.deck_combo.currentTextChanged.connect(self._remember_selection)
        self.source_combo.currentIndexChanged.connect(self._remember_selection)

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
        self.source_combo.clear()
        fetchers = get_fetchers(self.cfg)
        for fetcher in fetchers:
            self.source_combo.addItem(fetcher.LABEL, fetcher.ID)
        cfg_source = (self.cfg.get("source") or "").strip()
        idx = self.source_combo.findData(cfg_source)
        if idx == -1:
            idx = 0
        self.source_combo.setCurrentIndex(idx)

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
        if not self.cfg.get("remember_last", True):
            return
        save_config(
            {
                "note_type": self.ntype_combo.currentText(),
                "deck": self.deck_combo.currentText(),
                "source": self.source_combo.currentData(),
            }
        )

    def _current_fetcher(self):
        source_id = self.source_combo.currentData() or "cambridge"
        # Reload config before creating fetcher because settings may have changed
        cfg = get_config()
        return get_fetcher_by_id(source_id, cfg)

    def _resolve_field_map(self, source_id: str) -> Dict[str, List[str]]:
        base_map = self.cfg.get("field_map", {})
        if source_id == "wiktionary":
            wiki_map = (self.cfg.get("wiktionary") or {}).get("field_map") or {}
            if wiki_map:
                merged = dict(base_map)
                merged.update(wiki_map)
                return merged
        return base_map

    def on_fetch(self):
        self.cfg = get_config()
        word = self.word_edit.text().strip()
        if not word:
            showWarning("Enter a word first.")
            return
        fetcher = self._current_fetcher()
        try:
            senses = fetcher.fetch(word)
        except Exception as e:
            showWarning(f"Fetch error: {e}")
            traceback.print_exc()
            return
        if not senses:
            if self._try_typo_suggestions(word, fetcher):
                return
            showInfo("No definitions found.")
            return
        self.senses = senses
        self.sense_list.clear()
        for sense in senses:
            item = QListWidgetItem(sense.preview_text(self.cfg["max_examples"], self.cfg["max_synonyms"]))
            self.sense_list.addItem(item)
        self.sense_list.setCurrentRow(0)

    def _try_typo_suggestions(self, word: str, fetcher) -> bool:
        typo_cfg = self.cfg.get("typo_suggestions") if isinstance(self.cfg.get("typo_suggestions"), dict) else {}
        if not typo_cfg or not bool(typo_cfg.get("enabled", True)):
            return False
        try:
            max_results = int(typo_cfg.get("max_results") or 12)
        except Exception:
            max_results = 12
        max_results = max(1, min(max_results, 40))
        source_id = self.source_combo.currentData() or "cambridge"
        cfg_snapshot = get_config()
        suggestions = self._collect_typo_suggestions(word, source_id, cfg_snapshot, max_results)
        if not suggestions:
            return False
        selected = self._pick_suggestion(word, suggestions, max_results, source_id, cfg_snapshot)
        if not selected:
            return True
        self.word_edit.setText(selected)
        self.on_fetch()
        return True

    def _collect_typo_suggestions(self, word: str, source_id: str, cfg_snapshot, max_results: int) -> List[str]:
        cache_key = (source_id, word.casefold(), max_results)
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

        max_workers = min(6, max(1, len(queries)))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="typo-suggest") as pool:
            future_to_query: Dict[Future, str] = {}
            for query in queries:
                future = pool.submit(self._suggest_for_query, source_id, cfg_snapshot, query, fetch_limit)
                future_to_query[future] = query
            for future in as_completed(future_to_query):
                try:
                    suggested = future.result()
                except Exception:
                    traceback.print_exc()
                    suggested = []
                for item in suggested:
                    if isinstance(item, str):
                        add_candidate(item)
                if len(candidates) >= target_candidates:
                    for pending in future_to_query:
                        if not pending.done():
                            pending.cancel()
                    break

        ranked_limit = max(max_results * 4, max_results + 12)
        ranked = rank_suggestions(word, candidates, ranked_limit)
        self._typo_cache[cache_key] = ranked
        if len(self._typo_cache) > 80:
            try:
                oldest = next(iter(self._typo_cache))
                del self._typo_cache[oldest]
            except Exception:
                self._typo_cache.clear()
        return ranked[:]

    def _suggest_for_query(self, source_id: str, cfg_snapshot, query: str, fetch_limit: int) -> List[str]:
        fetcher = get_fetcher_by_id(source_id, cfg_snapshot)
        return fetcher.suggest(query, limit=fetch_limit)

    def _pick_suggestion(
        self,
        word: str,
        suggestions: List[str],
        max_results: int,
        source_id: str,
        cfg_snapshot,
    ) -> Optional[str]:

        def validate(candidate: str) -> bool:
            checker = get_fetcher_by_id(source_id, cfg_snapshot)
            return bool(checker.fetch(candidate))

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

    def on_select(self, row: int):
        if row < 0 or row >= len(self.senses):
            self.preview.clear()
            return
        sense = self.senses[row]
        ipa = self._choose_ipa(sense.ipa)
        text = [
            f"Definition: {sense.definition}",
            f"Syllables: {sense.syllables or '-'}",
            f"Examples: {' | '.join(sense.examples[:self.cfg['max_examples']]) or '-'}",
            f"Synonyms: {', '.join(sense.synonyms[:self.cfg['max_synonyms']]) or '-'}",
            f"POS: {sense.pos or '-'}",
            f"IPA: {ipa or '-'}",
            f"Audio: {', '.join(sense.audio_urls.keys()) or '-'}",
            f"Picture: {'yes' if sense.picture_url else 'no'}",
        ]
        self.preview.setPlainText("\n".join(text))

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
            item = self.sense_list.item(row)
            if item:
                item.setText(sense.preview_text(self.cfg["max_examples"], self.cfg["max_synonyms"]))
            self.on_select(row)

    def on_clear_image(self):
        row = self.sense_list.currentRow()
        if row < 0 or row >= len(self.senses):
            showWarning("Select a sense first.")
            return
        sense = self.senses[row]
        sense.picture_url = None
        sense.picture_referer = None
        item = self.sense_list.item(row)
        if item:
            item.setText(sense.preview_text(self.cfg["max_examples"], self.cfg["max_synonyms"]))
        self.on_select(row)

    def on_insert(self, open_editor: bool = False):
        row = self.sense_list.currentRow()
        if row < 0 or row >= len(self.senses):
            showWarning("Select a sense first.")
            return
        sense = self.senses[row]
        col = mw.col

        # resolve model & deck from user choices
        model_name = self.ntype_combo.currentText()
        model = col.models.byName(model_name)
        deck_name = self.deck_combo.currentText()
        deck_id = col.decks.id(deck_name)
        col.decks.select(deck_id)
        col.models.setCurrent(model)

        if hasattr(col, "new_note"):
            note = col.new_note(model)
        else:
            # Legacy API: newNote uses current model unless forDeck=True
            try:
                note = col.newNote(False)
            except TypeError:
                note = col.newNote()
        source_id = self.source_combo.currentData() or "cambridge"
        fmap: Dict[str, List[str]] = self._resolve_field_map(source_id)

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

        # audio
        audio_tag = ""
        audio_url = self._choose_audio(sense.audio_urls)
        if audio_url:
            try:
                filename, _ = download_to_media(audio_url)
                audio_tag = f"[sound:{filename}]"
            except Exception as e:
                showWarning(f"Audio download failed: {e}")
        set_field("audio", audio_tag)

        # picture
        pic_tag = ""
        if sense.picture_url:
            try:
                fname, _ = download_to_media(sense.picture_url, referer=sense.picture_referer)
                pic_tag = f'<img src=\"{fname}\">'
            except Exception as e:
                showWarning(f"Image download failed: {e}")
        set_field("picture", pic_tag)

        # ensure deck id set on note for older API
        try:
            note.model()["did"] = deck_id
        except Exception:
            pass

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
                added = True
            except TypeError:
                col.addNote(note)
                added = True

        if self.cfg.get("remember_last", True):
            save_config({"note_type": model["name"], "deck": deck_name, "source": self.source_combo.currentData()})
        mw.reset()
        tooltip("Note added.", parent=self)
        if open_editor:
            self._open_browser(note.id)
        self.accept()

    def _choose_audio(self, audio_map: Dict[str, str]) -> Optional[str]:
        for pref in self.cfg.get("dialect_priority", []):
            if pref in audio_map:
                return audio_map[pref]
        if "default" in audio_map:
            return audio_map["default"]
        if audio_map:
            return next(iter(audio_map.values()))
        return None

    def _choose_ipa(self, ipa_map: Dict[str, str]) -> Optional[str]:
        for pref in self.cfg.get("dialect_priority", []):
            if pref in ipa_map:
                return ipa_map[pref]
        if "default" in ipa_map:
            return ipa_map["default"]
        if ipa_map:
            return next(iter(ipa_map.values()))
        return None

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
            traceback.print_exc()

    def closeEvent(self, event):  # type: ignore[override]
        # Safety: persist selected note type/deck even if signals were not triggered
        self._remember_selection()
        super().closeEvent(event)
