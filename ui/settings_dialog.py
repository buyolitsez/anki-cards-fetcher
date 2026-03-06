from __future__ import annotations

import re
from copy import deepcopy
from typing import Dict, List, Optional

from aqt import mw
from aqt.qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from aqt.utils import tooltip

from ..config import DEFAULT_CONFIG, PRESET_PAYLOAD_KEYS, get_config, save_config
from ..fetchers import get_fetchers
from ..image_search import DEFAULT_IMAGE_PROVIDER, get_image_provider_choices
from ..language_detection import language_label, supported_language_codes
from ..logger import get_logger
from .source_utils import ensure_source_selection, set_source_selection

logger = get_logger(__name__)


class FieldPickerRow(QWidget):
    """A QLineEdit paired with a dropdown to pick field names from the note type."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.edit = QLineEdit()
        self.picker = QComboBox()
        self.picker.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.picker.setMinimumWidth(140)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, stretch=3)
        layout.addWidget(self.picker, stretch=1)

        self.picker.activated.connect(self._on_field_selected)
        self.set_fields([])

    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str):
        self.edit.setText(text)

    def set_fields(self, field_names):
        self.picker.blockSignals(True)
        self.picker.clear()
        self.picker.addItem("+ add field…", "")
        for name in field_names:
            self.picker.addItem(name, name)
        self.picker.blockSignals(False)
        self.picker.setEnabled(bool(field_names))

    def _on_field_selected(self, index: int):
        data = self.picker.itemData(index)
        if not data:
            return
        current = self.edit.text().strip()
        parts = [v.strip() for v in current.split(",") if v.strip()]
        if data not in parts:
            parts.append(data)
        self.edit.setText(", ".join(parts))
        self.picker.setCurrentIndex(0)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cambridge/Wiktionary — Settings")
        self.cfg = get_config()
        self.presets: List[Dict] = deepcopy(self.cfg.get("presets") or [])
        self.language_default_presets: Dict[str, Optional[str]] = self._normalize_language_default_presets(
            self.cfg.get("language_default_presets")
        )
        self.language_default_preset_combos: Dict[str, QComboBox] = {}
        self._initial_preset_id = str(self.cfg.get("active_preset_id") or "")
        self._loading_preset = False
        self._editing_preset_id: Optional[str] = None

        self._ensure_presets()

        col = mw.col

        # preset manager
        self.preset_combo = QComboBox()
        self.new_preset_btn = QPushButton("New")
        self.rename_preset_btn = QPushButton("Rename")
        self.duplicate_preset_btn = QPushButton("Duplicate")
        self.delete_preset_btn = QPushButton("Delete")

        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        self.new_preset_btn.clicked.connect(self.on_new_preset)
        self.rename_preset_btn.clicked.connect(self.on_rename_preset)
        self.duplicate_preset_btn.clicked.connect(self.on_duplicate_preset)
        self.delete_preset_btn.clicked.connect(self.on_delete_preset)

        for code in supported_language_codes():
            self.language_default_preset_combos[code] = QComboBox()

        # note type selector (preset-scoped)
        self.ntype_combo = QComboBox()
        self.ntype_combo.addItem("Auto (first in list)", "")
        for name in col.models.allNames():
            self.ntype_combo.addItem(name, name)
        self.ntype_combo.currentIndexChanged.connect(self._refresh_field_pickers)

        # deck selector (preset-scoped)
        self.deck_combo = QComboBox()
        self.deck_combo.addItem("Current selected deck", "")
        for name in col.decks.allNames():
            self.deck_combo.addItem(name, name)

        # sources (preset-scoped)
        self.source_checks = {}
        for fetcher in get_fetchers(self.cfg):
            chk = QCheckBox(fetcher.LABEL)
            self.source_checks[fetcher.ID] = chk

        # remember last
        self.remember_chk = QCheckBox("Remember last selections in dialog")
        self.remember_chk.setChecked(bool(self.cfg.get("remember_last", True)))

        # dialect priority radio
        self.uk_first = QCheckBox("UK > US")
        self.us_first = QCheckBox("US > UK")
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

        form.addWidget(QLabel("Presets:"))
        preset_row = QHBoxLayout()
        preset_row.addWidget(self.preset_combo)
        preset_row.addWidget(self.new_preset_btn)
        preset_row.addWidget(self.rename_preset_btn)
        preset_row.addWidget(self.duplicate_preset_btn)
        preset_row.addWidget(self.delete_preset_btn)
        form.addLayout(preset_row)

        form.addWidget(QLabel("Default preset by language:"))
        for code in supported_language_codes():
            form.addWidget(QLabel(f"{language_label(code)} default preset:"))
            form.addWidget(self.language_default_preset_combos[code])

        form.addWidget(QLabel("Preset note type:"))
        form.addWidget(self.ntype_combo)
        form.addWidget(QLabel("Preset deck:"))
        form.addWidget(self.deck_combo)
        form.addWidget(QLabel("Preset sources for fetch:"))
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
        form.addWidget(QLabel("Field mapping (type or pick from dropdown; comma-separated):"))
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
            edit = FieldPickerRow()
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
            edit = FieldPickerRow()
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
        self.setMinimumWidth(620)
        self.resize(700, 820)

        self._populate_preset_combo(select_id=self._initial_preset_id)

    def _ensure_presets(self):
        if not self.presets:
            payload = {
                key: deepcopy(self.cfg.get(key, DEFAULT_CONFIG.get(key)))
                for key in PRESET_PAYLOAD_KEYS
            }
            self.presets = [
                {
                    "id": "default",
                    "name": "Default",
                    **payload,
                }
            ]

    @staticmethod
    def _find_combo_index_by_data(combo: QComboBox, value) -> int:
        for i in range(combo.count()):
            data = combo.itemData(i)
            if isinstance(data, str) and isinstance(value, str):
                if data.strip().casefold() == value.strip().casefold():
                    return i
                continue
            if data == value:
                return i
        return -1

    def _set_combo_value(self, combo: QComboBox, value: Optional[str], missing_suffix: str):
        combo.blockSignals(True)
        try:
            if not value:
                combo.setCurrentIndex(0)
                return
            idx = self._find_combo_index_by_data(combo, value)
            if idx == -1:
                combo.addItem(f"{value} ({missing_suffix})", value)
                idx = combo.count() - 1
            combo.setCurrentIndex(idx)
        finally:
            combo.blockSignals(False)

    def _set_combo_numeric_value(self, combo: QComboBox, value: int):
        idx = combo.findData(value)
        if idx == -1:
            combo.addItem(str(value), value)
            idx = combo.findData(value)
        if idx != -1:
            combo.setCurrentIndex(idx)

    @staticmethod
    def _slugify(raw: str) -> str:
        value = (raw or "").strip().lower()
        value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
        return value or "preset"

    def _make_unique_preset_id(self, base_name: str) -> str:
        base = self._slugify(base_name)
        existing = {str(p.get("id") or "").strip() for p in self.presets}
        if base not in existing:
            return base
        suffix = 2
        while True:
            candidate = f"{base}-{suffix}"
            if candidate not in existing:
                return candidate
            suffix += 1

    def _make_unique_name(self, base_name: str) -> str:
        candidate = (base_name or "Preset").strip() or "Preset"
        existing = {str(p.get("name") or "").strip().casefold() for p in self.presets}
        if candidate.casefold() not in existing:
            return candidate
        suffix = 2
        while True:
            maybe = f"{candidate} {suffix}"
            if maybe.casefold() not in existing:
                return maybe
            suffix += 1

    def _selected_preset_id(self) -> Optional[str]:
        data = self.preset_combo.currentData()
        if isinstance(data, str) and data.strip():
            return data.strip()
        return None

    def _preset_by_id(self, preset_id: Optional[str]) -> Optional[Dict]:
        if not preset_id:
            return None
        for preset in self.presets:
            if str(preset.get("id") or "") == preset_id:
                return preset
        return None

    @staticmethod
    def _collect_mapping_from_edits(edits: Dict[str, QLineEdit], defaults: Dict[str, List[str]]) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for key, edit in edits.items():
            vals = [v.strip() for v in edit.text().split(",") if v.strip()]
            if vals:
                out[key] = vals
        for key, values in defaults.items():
            out.setdefault(key, values)
        return out

    @staticmethod
    def _apply_mapping_to_edits(edits: Dict[str, QLineEdit], values: Dict, defaults: Dict[str, List[str]]):
        for key, edit in edits.items():
            vals = values.get(key, defaults.get(key, []))
            if isinstance(vals, str):
                vals = [v.strip() for v in vals.split(",") if v.strip()]
            edit.setText(", ".join(vals))

    def _current_preset_payload(self) -> Dict:
        note_type = self.ntype_combo.currentData()
        deck = self.deck_combo.currentData()
        field_map = self._collect_mapping_from_edits(self.map_edits, DEFAULT_CONFIG.get("field_map", {}))
        wiki_defaults = DEFAULT_CONFIG.get("wiktionary", {}).get("field_map", {})
        wiki_field_map = self._collect_mapping_from_edits(self.wiki_map_edits, wiki_defaults)
        return {
            "note_type": note_type.strip() if isinstance(note_type, str) and note_type.strip() else None,
            "deck": deck.strip() if isinstance(deck, str) and deck.strip() else None,
            "sources": ensure_source_selection(self.source_checks),
            "remember_last": self.remember_chk.isChecked(),
            "dialect_priority": ["uk", "us"] if self.uk_first.isChecked() else ["us", "uk"],
            "image_search": {
                "provider": self.image_provider.currentData() or DEFAULT_IMAGE_PROVIDER,
                "max_results": int(self.image_max.currentData() or 12),
                "safe_search": self.image_safe.isChecked(),
            },
            "typo_suggestions": {
                "enabled": self.suggest_enabled.isChecked(),
                "max_results": int(self.suggest_max.currentData() or 12),
            },
            "log_level": self.log_level_combo.currentData() or "WARNING",
            "field_map": field_map,
            "wiktionary": {"field_map": wiki_field_map},
        }

    def _apply_preset_payload(self, preset: Dict):
        self._set_combo_value(self.ntype_combo, preset.get("note_type"), "missing")
        self._set_combo_value(self.deck_combo, preset.get("deck"), "missing")
        set_source_selection(self.source_checks, preset.get("sources") or [])

        self.remember_chk.setChecked(bool(preset.get("remember_last", True)))

        dialect = [str(x).lower() for x in (preset.get("dialect_priority") or [])]
        prefer_uk = dialect[:2] == ["uk", "us"]
        self.uk_first.blockSignals(True)
        self.us_first.blockSignals(True)
        self.uk_first.setChecked(prefer_uk)
        self.us_first.setChecked(not prefer_uk)
        self.uk_first.blockSignals(False)
        self.us_first.blockSignals(False)

        image_cfg = preset.get("image_search") if isinstance(preset.get("image_search"), dict) else {}
        provider = image_cfg.get("provider", DEFAULT_IMAGE_PROVIDER)
        idx = self.image_provider.findData(provider)
        if idx == -1:
            idx = 0
        self.image_provider.setCurrentIndex(idx)
        self._set_combo_numeric_value(self.image_max, int(image_cfg.get("max_results") or 12))
        self.image_safe.setChecked(bool(image_cfg.get("safe_search", True)))

        typo_cfg = preset.get("typo_suggestions") if isinstance(preset.get("typo_suggestions"), dict) else {}
        self.suggest_enabled.setChecked(bool(typo_cfg.get("enabled", True)))
        self._set_combo_numeric_value(self.suggest_max, int(typo_cfg.get("max_results") or 12))

        level = str(preset.get("log_level") or "WARNING").upper()
        idx = self.log_level_combo.findData(level)
        if idx == -1:
            idx = 0
        self.log_level_combo.setCurrentIndex(idx)

        field_map = preset.get("field_map") if isinstance(preset.get("field_map"), dict) else {}
        self._apply_mapping_to_edits(self.map_edits, field_map, DEFAULT_CONFIG.get("field_map", {}))

        wiki_map = (preset.get("wiktionary") or {}).get("field_map", {})
        wiki_defaults = DEFAULT_CONFIG.get("wiktionary", {}).get("field_map", {})
        self._apply_mapping_to_edits(self.wiki_map_edits, wiki_map, wiki_defaults)

    def _store_controls_into_preset(self, preset_id: Optional[str]):
        preset = self._preset_by_id(preset_id)
        if not preset:
            return
        preset.update(self._current_preset_payload())

    def _get_fields_for_note_type(self, note_type_name: str) -> list:
        if not note_type_name or not mw or not mw.col:
            return []
        model = mw.col.models.byName(note_type_name)
        if not model:
            return []
        return [f["name"] for f in model.get("flds", [])]

    def _refresh_field_pickers(self):
        if not hasattr(self, "map_edits") or not hasattr(self, "wiki_map_edits"):
            return
        note_type_name = self.ntype_combo.currentData() or ""
        fields = self._get_fields_for_note_type(note_type_name)
        all_rows = list(self.map_edits.values()) + list(self.wiki_map_edits.values())
        for row in all_rows:
            row.set_fields(fields)

    def _load_preset_into_controls(self, preset_id: Optional[str]):
        preset = self._preset_by_id(preset_id)
        if not preset:
            return
        self._loading_preset = True
        try:
            self._apply_preset_payload(preset)
        finally:
            self._loading_preset = False
        self._refresh_field_pickers()

    def _populate_preset_combo(self, select_id: Optional[str] = None):
        self._ensure_presets()
        current_id = self._selected_preset_id()
        self.preset_combo.blockSignals(True)
        try:
            self.preset_combo.clear()
            for preset in self.presets:
                preset_id = str(preset.get("id") or "").strip()
                if not preset_id:
                    continue
                name = str(preset.get("name") or preset_id).strip() or preset_id
                self.preset_combo.addItem(name, preset_id)
            target = select_id or current_id or self._editing_preset_id or self._initial_preset_id
            idx = self._find_combo_index_by_data(self.preset_combo, target)
            if idx == -1 and self.preset_combo.count():
                idx = 0
            if idx != -1:
                self.preset_combo.setCurrentIndex(idx)
                self._editing_preset_id = str(self.preset_combo.itemData(idx) or "")
            else:
                self._editing_preset_id = None
        finally:
            self.preset_combo.blockSignals(False)
        self._populate_language_default_preset_combos()
        self._load_preset_into_controls(self._editing_preset_id)

    def _normalize_language_default_presets(self, raw) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {code: None for code in supported_language_codes()}
        if not isinstance(raw, dict):
            return out
        for code in supported_language_codes():
            value = raw.get(code)
            out[code] = value.strip() if isinstance(value, str) and value.strip() else None
        return out

    def _populate_language_default_preset_combos(self):
        for code in supported_language_codes():
            combo = self.language_default_preset_combos[code]
            if combo.count():
                data = combo.currentData()
                self.language_default_presets[code] = data.strip() if isinstance(data, str) and data.strip() else None

        preset_lookup = {str(p.get("id") or "").strip(): str(p.get("name") or "").strip() for p in self.presets}
        for code in supported_language_codes():
            combo = self.language_default_preset_combos[code]
            target = self.language_default_presets.get(code)
            combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItem("None", "")
                for preset in self.presets:
                    preset_id = str(preset.get("id") or "").strip()
                    if not preset_id:
                        continue
                    name = str(preset.get("name") or preset_id).strip() or preset_id
                    combo.addItem(name, preset_id)
                if target and target in preset_lookup:
                    idx = combo.findData(target)
                    if idx != -1:
                        combo.setCurrentIndex(idx)
                    else:
                        combo.setCurrentIndex(0)
                else:
                    self.language_default_presets[code] = None
                    combo.setCurrentIndex(0)
            finally:
                combo.blockSignals(False)

    def _collect_language_default_presets(self) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {code: None for code in supported_language_codes()}
        for code in supported_language_codes():
            combo = self.language_default_preset_combos[code]
            data = combo.currentData()
            out[code] = data.strip() if isinstance(data, str) and data.strip() else None
        return out

    def on_preset_changed(self, *_):
        if self._loading_preset:
            return
        prev_id = self._editing_preset_id
        next_id = self._selected_preset_id()
        if prev_id == next_id:
            return
        self._store_controls_into_preset(prev_id)
        self._editing_preset_id = next_id
        self._load_preset_into_controls(next_id)

    def on_new_preset(self):
        self._store_controls_into_preset(self._editing_preset_id)
        base = self._preset_by_id(self._editing_preset_id)
        if not base:
            return
        suggested = self._make_unique_name("Preset")
        name, ok = QInputDialog.getText(self, "New preset", "Preset name:", text=suggested)
        if not ok:
            return
        clean_name = (name or "").strip() or suggested
        clean_name = self._make_unique_name(clean_name)
        new_id = self._make_unique_preset_id(clean_name)
        new_preset = deepcopy(base)
        new_preset["id"] = new_id
        new_preset["name"] = clean_name
        self.presets.append(new_preset)
        self._populate_preset_combo(select_id=new_id)

    def on_rename_preset(self):
        preset = self._preset_by_id(self._editing_preset_id)
        if not preset:
            return
        current_name = str(preset.get("name") or "Preset")
        name, ok = QInputDialog.getText(self, "Rename preset", "Preset name:", text=current_name)
        if not ok:
            return
        clean_name = (name or "").strip() or current_name
        if clean_name == current_name:
            return
        preset["name"] = clean_name
        self._populate_preset_combo(select_id=str(preset.get("id") or ""))

    def on_duplicate_preset(self):
        self._store_controls_into_preset(self._editing_preset_id)
        preset = self._preset_by_id(self._editing_preset_id)
        if not preset:
            return
        source_name = str(preset.get("name") or "Preset")
        suggested = self._make_unique_name(f"{source_name} Copy")
        name, ok = QInputDialog.getText(self, "Duplicate preset", "New preset name:", text=suggested)
        if not ok:
            return
        clean_name = (name or "").strip() or suggested
        clean_name = self._make_unique_name(clean_name)
        new_id = self._make_unique_preset_id(clean_name)
        duplicate = deepcopy(preset)
        duplicate["id"] = new_id
        duplicate["name"] = clean_name
        self.presets.append(duplicate)
        self._populate_preset_combo(select_id=new_id)

    def on_delete_preset(self):
        if len(self.presets) <= 1:
            tooltip("At least one preset is required.", parent=self)
            return
        selected_id = self._editing_preset_id
        if not selected_id:
            return
        remaining = [preset for preset in self.presets if str(preset.get("id") or "") != selected_id]
        if not remaining:
            tooltip("At least one preset is required.", parent=self)
            return
        self.presets = remaining
        self._populate_preset_combo(select_id=str(self.presets[0].get("id") or ""))

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
        self._store_controls_into_preset(self._editing_preset_id)
        self._ensure_presets()
        self.language_default_presets = self._collect_language_default_presets()
        logger.info("Saving settings (presets=%d)", len(self.presets))
        save_config(
            {
                "presets": self.presets,
                "language_default_presets": self.language_default_presets,
            }
        )
        tooltip("Settings saved.", parent=self)
        self.accept()
