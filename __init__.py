"""
Cambridge Fetcher: заполняет карточку Anki из Cambridge Dictionary.
Основной поток:
- меню Tools → Cambridge Fetch (можно назначить хоткей в Anki)
- диалог: ввести слово → Fetch → выбрать подходящее значение → Insert
- создаётся новая нота указанного типа, поля заполняются по мэппингу.

Конфиг (addon config):
{
  "note_type": "Basic (and reversed card)",
  "deck": null,                          # null => текущая выбранная колода
  "field_map": {
    "word": "Word",
    "definition": "Definition",
    "examples": "Examples",
    "synonyms": "Synonyms",
    "audio": "Audio",
    "picture": "Picture"
  },
  "dialect_priority": ["us", "uk"],
  "max_examples": 2,
  "max_synonyms": 4
}
"""

from __future__ import annotations

import json
import os
import re
import traceback
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    import requests
except Exception as e:  # pragma: no cover - handled at runtime
    requests = None  # type: ignore

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None  # type: ignore

from aqt import dialogs, gui_hooks, mw
from aqt.qt import (
    QAction,
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
    QVBoxLayout,
    Qt,
)
from aqt.utils import showInfo, showWarning, tooltip

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ----------------------------- Data models ----------------------------------
@dataclass
class CambridgeSense:
    definition: str
    examples: List[str] = field(default_factory=list)
    synonyms: List[str] = field(default_factory=list)
    pos: Optional[str] = None
    audio_urls: Dict[str, str] = field(default_factory=dict)  # region -> url
    picture_url: Optional[str] = None

    def preview_text(self, max_examples: int, max_synonyms: int) -> str:
        lines = []
        if self.pos:
            lines.append(f"[{self.pos}]")
        lines.append(self.definition)
        if self.examples:
            ex = self.examples[:max_examples]
            lines.append("Examples: " + " | ".join(ex))
        if self.synonyms:
            syn = ", ".join(self.synonyms[:max_synonyms])
            lines.append("Synonyms: " + syn)
        if self.audio_urls:
            lines.append("Audio: " + ", ".join(self.audio_urls.keys()))
        if self.picture_url:
            lines.append("Picture available")
        return "\n".join(lines)


# ----------------------------- Config helpers -------------------------------
DEFAULT_CONFIG = {
    "note_type": None,
    "deck": None,
    "remember_last": True,
    "field_map": {
        "word": "Word",
        "definition": "Definition",
        "examples": "Examples",
        "synonyms": "Synonyms",
        "audio": "Audio",
        "picture": "Picture",
    },
    "dialect_priority": ["us", "uk"],
    "max_examples": 2,
    "max_synonyms": 4,
}


def get_config() -> Dict:
    cfg = mw.addonManager.getConfig(__name__) or {}
    # shallow merge with defaults
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in cfg.items():
        merged[k] = v
    return merged


def save_config(updates: Dict):
    cfg = get_config()
    cfg.update(updates)
    mw.addonManager.writeConfig(__name__, cfg)


# ----------------------------- Fetch & Parse --------------------------------
class CambridgeFetcher:
    BASE = "https://dictionary.cambridge.org/dictionary/english/{word}"

    def __init__(self, dialect_priority: List[str]):
        self.dialect_priority = [d.lower() for d in dialect_priority]

    def fetch(self, word: str) -> List[CambridgeSense]:
        if not requests:
            raise RuntimeError("Модуль requests не найден. Установи requests в окружение Anki.")
        if not BeautifulSoup:
            raise RuntimeError("Модуль bs4 не найден. Установи beautifulsoup4 в окружение Anki.")

        url = self.BASE.format(word=word.strip().replace(" ", "-"))
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        if resp.status_code >= 400:
            raise RuntimeError(f"Cambridge ответил {resp.status_code} для '{word}'.")

        soup = BeautifulSoup(resp.text, "html.parser")
        entries = soup.select("div.entry")
        senses: List[CambridgeSense] = []
        for entry in entries:
            audio_map = self._parse_audio(entry)
            picture = self._parse_picture(entry)
            pos = self._text(entry.select_one("span.pos.dpos"))

            for block in entry.select("div.def-block.ddef_block"):
                definition = self._text(block.select_one("div.def.ddef_d.db"))
                if not definition:
                    continue
                examples = [
                    self._text(ex)
                    for ex in block.select("div.examp.dexamp span.eg.deg")
                    if self._text(ex)
                ]
                synonyms = [
                    self._text(a)
                    for a in block.select("div.thesref a")
                    if self._text(a)
                ]
                senses.append(
                    CambridgeSense(
                        definition=definition,
                        examples=examples,
                        synonyms=synonyms,
                        pos=pos,
                        audio_urls=audio_map.copy(),
                        picture_url=picture,
                    )
                )
        return senses

    def _text(self, node) -> str:
        if not node:
            return ""
        return " ".join(node.get_text(" ", strip=True).split())

    def _parse_audio(self, entry) -> Dict[str, str]:
        audio = {}
        # typical structure: span.dpron-i contains span.region and [data-src-mp3]
        for pron in entry.select("span.dpron-i"):
            region = self._text(pron.select_one("span.region"))
            region_key = region.lower() if region else None
            src_el = pron.select_one("[data-src-mp3]") or pron.select_one("[data-src-ogg]")
            url = None
            if src_el:
                url = src_el.get("data-src-mp3") or src_el.get("data-src-ogg")
            if region_key and url:
                audio[region_key] = url
        # fallback without region labels
        if not audio:
            src = entry.select_one("[data-src-mp3]")
            if src:
                url = src.get("data-src-mp3")
                if url:
                    audio["us"] = url
        return audio

    def _parse_picture(self, entry) -> Optional[str]:
        # Cambridge редко, но даёт иллюстрации в img-thumb
        img = entry.select_one("amp-img.img-thumb") or entry.select_one("img.img-thumb")
        if img:
            return img.get("src") or img.get("data-src")
        return None


# ----------------------------- Media helpers --------------------------------
def download_to_media(url: str) -> Tuple[str, str]:
    """Скачивает файл и кладёт в медиатеку. Возвращает (filename, local_path)."""
    if not requests:
        raise RuntimeError("Модуль requests не найден. Установи requests в окружение Anki.")
    if url.startswith("//"):
        url = "https:" + url
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    # derive filename
    name = url.split("/")[-1].split("?")[0]
    # avoid collisions
    filename = mw.col.media.writeData(name, resp.content)
    path = mw.col.media.dir() + "/" + filename
    return filename, path


# ----------------------------- UI dialog ------------------------------------
class FetchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = get_config()
        self.fetcher = CambridgeFetcher(self.cfg["dialect_priority"])
        self.senses: List[CambridgeSense] = []
        self.setWindowTitle("Cambridge Fetch")

        # widgets
        self.word_edit = QLineEdit()
        self.word_edit.setPlaceholderText("Введите слово...")
        self.fetch_btn = QPushButton("Fetch")
        self.sense_list = QListWidget()
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.insert_btn = QPushButton("Insert")

        self.ntype_combo = QComboBox()
        self.deck_combo = QComboBox()
        self.fill_current_cb = QCheckBox("Использовать текущую выбранную колоду/тип")
        use_current = self.cfg.get("deck") is None and self.cfg.get("note_type") is None
        self.fill_current_cb.setChecked(use_current)

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
        combos.addWidget(self.fill_current_cb)

        body = QHBoxLayout()
        body.addWidget(self.sense_list, 2)
        body.addWidget(self.preview, 3)

        main = QVBoxLayout()
        main.addLayout(top)
        main.addLayout(combos)
        main.addLayout(body)
        main.addWidget(self.insert_btn)
        self.setLayout(main)

        # signals
        self.fetch_btn.clicked.connect(self.on_fetch)
        self.sense_list.currentRowChanged.connect(self.on_select)
        self.insert_btn.clicked.connect(lambda: self.on_insert(open_editor=False))
        self.sense_list.itemDoubleClicked.connect(lambda _: self.on_insert(open_editor=True))

    # ---------- UI helpers ----------
    def _populate_models(self):
        col = mw.col
        # note types
        self.ntype_combo.clear()
        models = col.models.allNames()
        self.ntype_combo.addItems(models)
        if self.cfg.get("note_type") in models:
            self.ntype_combo.setCurrentText(self.cfg["note_type"])
        # decks
        self.deck_combo.clear()
        decks = list(col.decks.allNames())
        self.deck_combo.addItems(decks)
        if self.cfg.get("deck") in decks:
            self.deck_combo.setCurrentText(self.cfg["deck"])

    def on_fetch(self):
        word = self.word_edit.text().strip()
        if not word:
            showWarning("Введите слово.")
            return
        try:
            senses = self.fetcher.fetch(word)
        except Exception as e:
            showWarning(f"Ошибка загрузки: {e}")
            traceback.print_exc()
            return
        if not senses:
            showInfo("Не удалось найти определения.")
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
        text = [
            f"Definition: {sense.definition}",
            f"Examples: {' | '.join(sense.examples[:self.cfg['max_examples']]) or '-'}",
            f"Synonyms: {', '.join(sense.synonyms[:self.cfg['max_synonyms']]) or '-'}",
            f"POS: {sense.pos or '-'}",
            f"Audio: {', '.join(sense.audio_urls.keys()) or '-'}",
            f"Picture: {'yes' if sense.picture_url else 'no'}",
        ]
        self.preview.setPlainText("\n".join(text))

    def on_insert(self, open_editor: bool = False):
        row = self.sense_list.currentRow()
        if row < 0 or row >= len(self.senses):
            showWarning("Сначала выбери значение.")
            return
        sense = self.senses[row]
        col = mw.col

        # resolve model & deck
        if self.fill_current_cb.isChecked():
            model = col.models.current()
            deck_id = col.decks.current()["id"]
            deck_name = col.decks.name(deck_id)
        else:
            model_name = self.ntype_combo.currentText()
            model = col.models.byName(model_name)
            deck_name = self.deck_combo.currentText()
            deck_id = col.decks.id(deck_name)
            col.decks.select(deck_id)
            col.models.setCurrent(model)

        note = col.newNote(model)
        fmap = self.cfg["field_map"]

        def set_field(key: str, value: str):
            field_name = fmap.get(key)
            if field_name and field_name in note:
                note[field_name] = value

        set_field("word", self.word_edit.text().strip())
        set_field("definition", sense.definition)
        set_field("examples", "<br>".join(sense.examples[: self.cfg["max_examples"]]))
        set_field("synonyms", ", ".join(sense.synonyms[: self.cfg["max_synonyms"]]))

        # audio
        audio_tag = ""
        audio_url = self._choose_audio(sense.audio_urls)
        if audio_url:
            try:
                filename, _ = download_to_media(audio_url)
                audio_tag = f"[sound:{filename}]"
            except Exception as e:
                showWarning(f"Аудио не удалось скачать: {e}")
        set_field("audio", audio_tag)

        # picture
        pic_tag = ""
        if sense.picture_url:
            try:
                fname, _ = download_to_media(sense.picture_url)
                pic_tag = f'<img src=\"{fname}\">'
            except Exception as e:
                showWarning(f"Картинку не удалось скачать: {e}")
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
            save_config({"note_type": model["name"], "deck": deck_name})
        mw.reset()
        tooltip("Нота добавлена.", parent=self)
        if open_editor:
            try:
                browser = dialogs.open("Browser", mw)
                if hasattr(browser, "search_for_nids"):
                    browser.search_for_nids([note.id])
                else:
                    browser.onSearch(f"nid:{note.id}")
                browser.activateWindow()
            except Exception:
                traceback.print_exc()
        self.accept()

    def _choose_audio(self, audio_map: Dict[str, str]) -> Optional[str]:
        for pref in self.cfg.get("dialect_priority", []):
            if pref in audio_map:
                return audio_map[pref]
        if audio_map:
            return next(iter(audio_map.values()))
        return None


# ----------------------------- Menu hook ------------------------------------
def open_dialog():
    dlg = FetchDialog(mw)
    dlg.exec()


def on_main_window_ready(mw_obj=None):
    wnd = mw_obj or mw
    action = QAction("Cambridge Fetch", wnd)
    action.triggered.connect(open_dialog)
    wnd.form.menuTools.addAction(action)


# Hooks & config wiring (handle different Anki API shapes)
defaults_attr = getattr(mw.addonManager, "addonConfigDefaults", None)
if isinstance(defaults_attr, dict):
    defaults_attr[__name__] = DEFAULT_CONFIG
elif callable(defaults_attr):
    try:
        defaults_attr(__name__, DEFAULT_CONFIG)  # type: ignore[arg-type]
    except Exception:
        pass
elif hasattr(mw.addonManager, "setConfigDefaults"):
    mw.addonManager.setConfigDefaults(__name__, DEFAULT_CONFIG)

mw.addonManager.setConfigAction(__name__, lambda: open_dialog())
gui_hooks.main_window_did_init.append(on_main_window_ready)
