from __future__ import annotations

from aqt import mw
from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import tooltip

from ..config import DEFAULT_CONFIG, get_config, save_config
from ..fetchers import get_fetchers
from ..image_search import DEFAULT_IMAGE_PROVIDER, get_image_provider_choices
from ..logger import get_logger
from .source_utils import configured_source_ids, ensure_source_selection

logger = get_logger(__name__)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cambridge/Wiktionary — Settings")
        self.cfg = get_config()
        col = mw.col

        # note type selector
        self.ntype_combo = QComboBox()
        self.ntype_combo.addItem("Auto (first in list)", "")
        for name in col.models.allNames():
            self.ntype_combo.addItem(name, name)
        cfg_model = (self.cfg.get("note_type") or "").strip()
        idx = self.ntype_combo.findData(cfg_model)
        if idx == -1:
            idx = 0
        self.ntype_combo.setCurrentIndex(idx)

        # deck selector
        self.deck_combo = QComboBox()
        self.deck_combo.addItem("Current selected deck", "")
        for name in col.decks.allNames():
            self.deck_combo.addItem(name, name)
        cfg_deck = (self.cfg.get("deck") or "").strip()
        idx = self.deck_combo.findData(cfg_deck)
        if idx == -1:
            idx = 0
        self.deck_combo.setCurrentIndex(idx)

        # default sources
        self.source_checks = {}
        selected_sources = configured_source_ids(self.cfg)
        for fetcher in get_fetchers(self.cfg):
            chk = QCheckBox(fetcher.LABEL)
            chk.setChecked(fetcher.ID in selected_sources)
            self.source_checks[fetcher.ID] = chk
        ensure_source_selection(self.source_checks)

        # remember last
        self.remember_chk = QCheckBox("Remember last selections in dialog")
        self.remember_chk.setChecked(bool(self.cfg.get("remember_last", True)))

        # dialect priority radio
        self.uk_first = QCheckBox("UK > US")
        self.us_first = QCheckBox("US > UK")
        # behave like radio: allow only one checked
        self.uk_first.stateChanged.connect(lambda _: self._sync_dialect_checks("uk"))
        self.us_first.stateChanged.connect(lambda _: self._sync_dialect_checks("us"))
        current_dialect = [d.lower() for d in self.cfg.get("dialect_priority", [])]
        if current_dialect[:2] == ["uk", "us"]:
            self.uk_first.setChecked(True)
        else:
            self.us_first.setChecked(True)

        # image search settings
        self.image_provider = QComboBox()
        for label, provider_id in get_image_provider_choices():
            self.image_provider.addItem(label, provider_id)
        self.image_provider.setEnabled(self.image_provider.count() > 1)
        image_cfg = self.cfg.get("image_search", {}) if isinstance(self.cfg.get("image_search"), dict) else {}
        img_provider = image_cfg.get("provider", DEFAULT_IMAGE_PROVIDER)
        idx = self.image_provider.findData(img_provider)
        if idx == -1:
            idx = 0
        self.image_provider.setCurrentIndex(idx)

        self.image_max = QComboBox()
        for n in (8, 12, 16, 20, 24, 30):
            self.image_max.addItem(str(n), n)
        img_max = int(image_cfg.get("max_results") or 12)
        idx = self.image_max.findData(img_max)
        if idx == -1:
            self.image_max.addItem(str(img_max), img_max)
            idx = self.image_max.findData(img_max)
        self.image_max.setCurrentIndex(idx)

        self.image_safe = QCheckBox("Safe search (adult filter)")
        self.image_safe.setChecked(bool(image_cfg.get("safe_search", True)))

        # typo suggestions settings
        typo_cfg = self.cfg.get("typo_suggestions", {}) if isinstance(self.cfg.get("typo_suggestions"), dict) else {}
        self.suggest_enabled = QCheckBox("Suggest close matches when nothing is found")
        self.suggest_enabled.setChecked(bool(typo_cfg.get("enabled", True)))
        self.suggest_max = QComboBox()
        for n in (5, 8, 12, 16, 20, 24, 30):
            self.suggest_max.addItem(str(n), n)
        typo_max = int(typo_cfg.get("max_results") or 12)
        idx = self.suggest_max.findData(typo_max)
        if idx == -1:
            self.suggest_max.addItem(str(typo_max), typo_max)
            idx = self.suggest_max.findData(typo_max)
        self.suggest_max.setCurrentIndex(idx)

        # log level
        self.log_level_combo = QComboBox()
        for level in ("WARNING", "INFO", "DEBUG", "ERROR", "CRITICAL"):
            self.log_level_combo.addItem(level, level)
        current_level = (self.cfg.get("log_level") or "WARNING").upper()
        idx = self.log_level_combo.findData(current_level)
        if idx == -1:
            idx = 0
        self.log_level_combo.setCurrentIndex(idx)

        # buttons
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Close")
        save_btn.clicked.connect(self.on_save)
        cancel_btn.clicked.connect(self.reject)

        form = QVBoxLayout()
        form.addWidget(QLabel("Default note type:"))
        form.addWidget(self.ntype_combo)
        form.addWidget(QLabel("Default deck:"))
        form.addWidget(self.deck_combo)
        form.addWidget(QLabel("Default sources for fetch:"))
        for chk in self.source_checks.values():
            form.addWidget(chk)
        form.addWidget(self.remember_chk)
        form.addWidget(QLabel("Audio/IPA dialect priority (Cambridge only):"))
        dialect_row = QHBoxLayout()
        dialect_row.addWidget(self.uk_first)
        dialect_row.addWidget(self.us_first)
        form.addLayout(dialect_row)

        form.addWidget(QLabel("Image search:"))
        form.addWidget(QLabel("Provider:"))
        form.addWidget(self.image_provider)
        form.addWidget(QLabel("Max results:"))
        form.addWidget(self.image_max)
        form.addWidget(self.image_safe)

        form.addWidget(QLabel("Typos / fuzzy suggestions:"))
        form.addWidget(self.suggest_enabled)
        form.addWidget(QLabel("Max suggestion results:"))
        form.addWidget(self.suggest_max)

        form.addWidget(QLabel("Logging:"))
        form.addWidget(QLabel("Log level (WARNING = quiet, DEBUG = verbose):"))
        form.addWidget(self.log_level_combo)

        # field mappings
        form.addWidget(QLabel("Field mapping (comma-separated per logical key):"))
        self.map_edits = {}
        for key, label in [
            ("word", "Word fields"),
            ("definition", "Definition fields"),
            ("examples", "Examples fields"),
            ("synonyms", "Synonyms fields"),
            ("pos", "Part of speech fields"),
            ("ipa", "IPA fields"),
            ("audio", "Audio fields"),
            ("picture", "Picture fields"),
        ]:
            form.addWidget(QLabel(label + ":"))
            edit = QLineEdit()
            vals = self.cfg.get("field_map", {}).get(key, [])
            if isinstance(vals, str):
                vals = [v.strip() for v in vals.split(",") if v.strip()]
            edit.setText(", ".join(vals))
            self.map_edits[key] = edit
            form.addWidget(edit)

        form.addWidget(QLabel("Wiktionary (ru) only:"))
        self.wiki_map_edits = {}
        for key, label in [
            ("syllables", "Syllables/stress fields"),
        ]:
            form.addWidget(QLabel(label + ":"))
            edit = QLineEdit()
            vals = (self.cfg.get("wiktionary", {}).get("field_map", {}).get(key, []) or [])
            if isinstance(vals, str):
                vals = [v.strip() for v in vals.split(",") if v.strip()]
            edit.setText(", ".join(vals))
            self.wiki_map_edits[key] = edit
            form.addWidget(edit)

        content = QWidget(self)
        content.setLayout(form)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)

        buttons = QHBoxLayout()
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)

        root = QVBoxLayout()
        root.addWidget(scroll)
        root.addLayout(buttons)
        self.setLayout(root)
        self.setMinimumWidth(560)
        self.resize(640, 760)

    def _sync_dialect_checks(self, prefer: str):
        if prefer == "uk":
            self.us_first.blockSignals(True)
            self.us_first.setChecked(False)
            self.us_first.blockSignals(False)
            if not self.uk_first.isChecked():
                self.uk_first.setChecked(True)
        else:
            self.uk_first.blockSignals(True)
            self.uk_first.setChecked(False)
            self.uk_first.blockSignals(False)
            if not self.us_first.isChecked():
                self.us_first.setChecked(True)

    def on_save(self):
        note_type = self.ntype_combo.currentData() or None
        deck = self.deck_combo.currentData() or None
        sources = ensure_source_selection(self.source_checks)
        dialect_priority = ["uk", "us"] if self.uk_first.isChecked() else ["us", "uk"]
        image_search = {
            "provider": self.image_provider.currentData() or DEFAULT_IMAGE_PROVIDER,
            "max_results": int(self.image_max.currentData() or 12),
            "safe_search": self.image_safe.isChecked(),
        }
        typo_suggestions = {
            "enabled": self.suggest_enabled.isChecked(),
            "max_results": int(self.suggest_max.currentData() or 12),
        }
        log_level = self.log_level_combo.currentData() or "WARNING"
        # collect mapping
        fmap = {}
        for key, edit in self.map_edits.items():
            vals = [v.strip() for v in edit.text().split(",") if v.strip()]
            if vals:
                fmap[key] = vals
        # fill missing keys from defaults
        for k, v in DEFAULT_CONFIG["field_map"].items():
            fmap.setdefault(k, v)
        wiki_fmap = {}
        for key, edit in self.wiki_map_edits.items():
            vals = [v.strip() for v in edit.text().split(",") if v.strip()]
            if vals:
                wiki_fmap[key] = vals
        for k, v in DEFAULT_CONFIG.get("wiktionary", {}).get("field_map", {}).items():
            wiki_fmap.setdefault(k, v)
        logger.info("Saving settings (log_level=%s)", log_level)
        save_config(
            {
                "note_type": note_type,
                "deck": deck,
                "remember_last": self.remember_chk.isChecked(),
                "dialect_priority": dialect_priority,
                "sources": sources,
                "field_map": fmap,
                "wiktionary": {"field_map": wiki_fmap},
                "image_search": image_search,
                "typo_suggestions": typo_suggestions,
                "log_level": log_level,
            }
        )
        tooltip("Settings saved.", parent=self)
        self.accept()
