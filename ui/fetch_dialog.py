from __future__ import annotations

import traceback
from typing import Dict, List, Optional

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
    QVBoxLayout,
    Qt,
)
from aqt.utils import showInfo, showWarning, tooltip

from ..config import get_config, save_config
from ..fetchers import get_fetcher_by_id, get_fetchers
from ..media import download_to_media
from ..models import Sense


class FetchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = get_config()
        self.senses: List[Sense] = []
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
        # обновляем cfg перед созданием, т.к. могли поменять настройки
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
            showInfo("No definitions found.")
            return
        self.senses = senses
        self.sense_list.clear()
        for sense in senses:
            item = QListWidgetItem(sense.preview_text(self.cfg["max_examples"], self.cfg["max_synonyms"]))
            self.sense_list.addItem(item)
        self.sense_list.setCurrentRow(0)

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
                fname, _ = download_to_media(sense.picture_url)
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
        # страхуемся: сохраняем выбранные тип и колоду даже если сигналы не сработали
        self._remember_selection()
        super().closeEvent(event)
