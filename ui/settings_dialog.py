from __future__ import annotations

from aqt import mw
from aqt.qt import QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from aqt.utils import tooltip

from ..config import DEFAULT_CONFIG, get_config, save_config
from ..fetchers import get_fetchers


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cambridge/Wiktionary — Settings")
        self.cfg = get_config()
        col = mw.col

        # note type selector
        self.ntype_combo = QComboBox()
        self.ntype_combo.addItem("Авто (первый в списке)", "")
        for name in col.models.allNames():
            self.ntype_combo.addItem(name, name)
        cfg_model = (self.cfg.get("note_type") or "").strip()
        idx = self.ntype_combo.findData(cfg_model)
        if idx == -1:
            idx = 0
        self.ntype_combo.setCurrentIndex(idx)

        # deck selector
        self.deck_combo = QComboBox()
        self.deck_combo.addItem("Текущая выбранная", "")
        for name in col.decks.allNames():
            self.deck_combo.addItem(name, name)
        cfg_deck = (self.cfg.get("deck") or "").strip()
        idx = self.deck_combo.findData(cfg_deck)
        if idx == -1:
            idx = 0
        self.deck_combo.setCurrentIndex(idx)

        # default source
        self.source_combo = QComboBox()
        for fetcher in get_fetchers(self.cfg):
            self.source_combo.addItem(fetcher.LABEL, fetcher.ID)
        cfg_source = (self.cfg.get("source") or DEFAULT_CONFIG["source"]).strip()
        idx = self.source_combo.findData(cfg_source)
        if idx == -1:
            idx = 0
        self.source_combo.setCurrentIndex(idx)

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
        form.addWidget(QLabel("Default source:"))
        form.addWidget(self.source_combo)
        form.addWidget(self.remember_chk)
        form.addWidget(QLabel("Audio dialect priority (Cambridge only):"))
        dialect_row = QHBoxLayout()
        dialect_row.addWidget(self.uk_first)
        dialect_row.addWidget(self.us_first)
        form.addLayout(dialect_row)

        buttons = QHBoxLayout()
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        form.addLayout(buttons)
        self.setLayout(form)

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
        source = self.source_combo.currentData() or DEFAULT_CONFIG["source"]
        dialect_priority = ["uk", "us"] if self.uk_first.isChecked() else ["us", "uk"]
        save_config(
            {
                "note_type": note_type,
                "deck": deck,
                "remember_last": self.remember_chk.isChecked(),
                "dialect_priority": dialect_priority,
                "source": source,
            }
        )
        tooltip("Настройки сохранены.", parent=self)
        self.accept()
