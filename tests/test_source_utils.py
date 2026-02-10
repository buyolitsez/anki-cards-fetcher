from __future__ import annotations

from cambridge_fetch.ui.source_utils import configured_source_ids, ensure_source_selection


class _Check:
    def __init__(self, checked: bool = False):
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        self._checked = bool(checked)


def test_configured_source_ids_uses_fallback():
    assert configured_source_ids({}) == {"cambridge"}


def test_ensure_source_selection_keeps_current_choice():
    checks = {"cambridge": _Check(True), "wiktionary": _Check(False)}
    assert ensure_source_selection(checks) == ["cambridge"]


def test_ensure_source_selection_checks_default_then_first():
    checks = {"wiktionary": _Check(False), "cambridge": _Check(False)}
    assert ensure_source_selection(checks) == ["cambridge"]
    assert checks["cambridge"].isChecked() is True

    checks_no_default = {"wiktionary_en": _Check(False), "wiktionary": _Check(False)}
    assert ensure_source_selection(checks_no_default) == ["wiktionary_en"]
    assert checks_no_default["wiktionary_en"].isChecked() is True


def test_configured_source_ids_returns_clean_values():
    assert configured_source_ids({"sources": [" cambridge ", "", "wiktionary"]}) == {"cambridge", "wiktionary"}


def test_ensure_source_selection_empty_dict_returns_default():
    assert ensure_source_selection({}) == ["cambridge"]
