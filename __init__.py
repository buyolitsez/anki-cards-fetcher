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
        # Cambridge меняет вёрстку; соберём ссылки из нескольких вариантов.
        candidates = []
        candidates.extend(entry.select("[data-src-mp3], [data-src-ogg]"))
        candidates.extend(entry.select("source[src], audio[src], audio source[src]"))
        candidates.extend(entry.select("a[href*='/media/']"))

        for tag in candidates:
            url = (
                tag.get("data-src-mp3")
                or tag.get("data-src-ogg")
                or tag.get("src")
                or tag.get("href")
            )
            if not url:
                continue
            if not re.search(r"\.mp3|\.ogg", url, re.IGNORECASE):
                continue
            region_key = self._find_region(tag)
            # сохраняем первый вариант для региона; если регион не найден — кладём как default
            key = region_key or "default"
            if key not in audio:
                audio[key] = url

        # fallback: первая попавшаяся data-src-mp3
        if not audio:
            src = entry.select_one("[data-src-mp3]")
            if src:
                url = src.get("data-src-mp3")
                if url:
                    audio["default"] = url
        return audio

    def _find_region(self, tag) -> Optional[str]:
        """Пытается вычислить регион (us/uk) исходя из ближайших .region или классов."""
        parent = tag
        for _ in range(5):
            region_el = parent.select_one(".region, .dregion") if hasattr(parent, "select_one") else None
            if region_el:
                txt = self._text(region_el).lower()
                if "us" in txt:
                    return "us"
                if "uk" in txt:
                    return "uk"
            if not getattr(parent, "parent", None):
                break
            parent = parent.parent
        classes = " ".join(tag.get("class", [])).lower()
        if "us" in classes:
            return "us"
        if "uk" in classes:
            return "uk"
        return None

    def _parse_picture(self, entry) -> Optional[str]:
        # Cambridge иногда хранит картинки в img[data-src] или img[src] с путём /media/
        for img in entry.select("img, source, picture source"):
            src = img.get("data-src") or img.get("srcset") or img.get("src")
            if not src:
                continue
            # srcset может содержать несколько ссылок через запятую — берём первую
            src = src.split(",")[0].split()[0]
            if any(ext in src.lower() for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")) and "/media/" in src:
                return src
        # amp-img fallback
        amp = entry.select_one("amp-img")
        if amp:
            src = amp.get("data-src") or amp.get("src")
            if src:
                return src
        return None


# ----------------------------- Media helpers --------------------------------
def download_to_media(url: str) -> Tuple[str, str]:
    """Скачивает файл и кладёт в медиатеку. Возвращает (filename, local_path)."""
    if not requests:
        raise RuntimeError("Модуль requests не найден. Установи requests в окружение Anki.")
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("/"):
        url = "https://dictionary.cambridge.org" + url
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
        self.edit_btn = QPushButton("Insert & Edit")
        self.insert_btn = QPushButton("Insert")

        self.ntype_combo = QComboBox()
        self.deck_combo = QComboBox()

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

    # ---------- UI helpers ----------
    def _populate_models(self):
        # reload config to pick up persisted selections
        self.cfg = get_config()
        col = mw.col
        # note types
        self.ntype_combo.clear()
        models = col.models.allNames()
        self.ntype_combo.addItems(models)
        cfg_model = (self.cfg.get("note_type") or "").strip()
        if cfg_model:
            idx = self.ntype_combo.findText(cfg_model, Qt.MatchFixedString)
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
            idx = self.deck_combo.findText(cfg_deck, Qt.MatchFixedString)
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
            }
        )

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

        # resolve model & deck from user choices
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
                query = f"nid:{note.id}"
                if hasattr(browser, "search_for_nids"):
                    browser.search_for_nids([note.id])
                else:
                    # set search text if possible
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
        self.accept()

    def _choose_audio(self, audio_map: Dict[str, str]) -> Optional[str]:
        for pref in self.cfg.get("dialect_priority", []):
            if pref in audio_map:
                return audio_map[pref]
        # fallback на default или первое значение
        if "default" in audio_map:
            return audio_map["default"]
        if audio_map:
            return next(iter(audio_map.values()))
        return None

    def closeEvent(self, event):  # type: ignore[override]
        # страхуемся: сохраняем выбранные тип и колоду даже если сигналы не сработали
        self._remember_selection()
        super().closeEvent(event)


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
