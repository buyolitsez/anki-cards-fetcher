from __future__ import annotations

import cambridge_fetch.config as config_mod


class _DummyAddonManager:
    def __init__(self, stored=None):
        self._stored = stored or {}
        self.written = None

    def getConfig(self, _name):
        return dict(self._stored)

    def writeConfig(self, name, cfg):
        self.written = (name, cfg)


def test_normalize_preset_rejects_non_dict():
    assert config_mod.normalize_preset(None) is None
    assert config_mod.normalize_preset("bad") is None


def test_normalize_presets_creates_default_from_fallback():
    presets = config_mod.normalize_presets(
        raw_presets=None,
        fallback_payload={
            "note_type": "Basic",
            "deck": "Default",
            "sources": ["wiktionary_en"],
            "field_map": {"word": ["Term"]},
            "wiktionary": {"field_map": {"syllables": ["Syll"]}},
            "dialect_priority": ["uk", "us"],
            "max_examples": 3,
            "max_synonyms": 6,
            "image_search": {"provider": "duckduckgo", "max_results": 24, "safe_search": False},
            "typo_suggestions": {"enabled": True, "max_results": 18},
            "remember_last": False,
            "log_level": "DEBUG",
        },
    )
    assert len(presets) == 1
    assert presets[0]["id"] == "default"
    assert presets[0]["name"] == "Default"
    assert presets[0]["note_type"] == "Basic"
    assert presets[0]["deck"] == "Default"
    assert presets[0]["sources"] == ["wiktionary_en"]
    assert presets[0]["field_map"]["word"] == ["Term"]
    assert presets[0]["wiktionary"]["field_map"]["syllables"] == ["Syll"]
    assert presets[0]["dialect_priority"] == ["uk", "us"]
    assert presets[0]["max_examples"] == 3
    assert presets[0]["max_synonyms"] == 6
    assert presets[0]["image_search"]["max_results"] == 24
    assert presets[0]["image_search"]["safe_search"] is False
    assert presets[0]["typo_suggestions"]["max_results"] == 18
    assert presets[0]["remember_last"] is False
    assert presets[0]["log_level"] == "DEBUG"


def test_normalized_config_invalid_active_preset_falls_back_to_first():
    cfg = config_mod._normalized_config(
        {
            "presets": [
                {"id": "first", "name": "First", "note_type": "N1", "deck": "D1", "sources": ["cambridge"]},
                {"id": "second", "name": "Second", "note_type": "N2", "deck": "D2", "sources": ["wiktionary"]},
            ],
            "active_preset_id": "missing",
        }
    )
    assert cfg["active_preset_id"] == "first"
    assert cfg["note_type"] == "N1"
    assert cfg["deck"] == "D1"
    assert cfg["sources"] == ["cambridge"]


def test_save_config_legacy_selection_updates_active_preset(monkeypatch, tmp_path):
    manager = _DummyAddonManager(
        stored={
            "presets": [
                {"id": "one", "name": "One", "note_type": "N1", "deck": "D1", "sources": ["cambridge"]},
                {"id": "two", "name": "Two", "note_type": "N2", "deck": "D2", "sources": ["wiktionary"]},
            ],
            "active_preset_id": "two",
        }
    )
    monkeypatch.setattr(config_mod.mw, "addonManager", manager, raising=False)
    monkeypatch.setattr(config_mod, "META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.json")

    config_mod.save_config({"note_type": "Changed", "deck": "Deck X", "sources": ["wiktionary_en"]})

    assert manager.written is not None
    _, saved_cfg = manager.written
    one = next(p for p in saved_cfg["presets"] if p["id"] == "one")
    two = next(p for p in saved_cfg["presets"] if p["id"] == "two")
    assert one["note_type"] == "N1"
    assert one["deck"] == "D1"
    assert one["sources"] == ["cambridge"]
    assert two["note_type"] == "Changed"
    assert two["deck"] == "Deck X"
    assert two["sources"] == ["wiktionary_en"]
    assert saved_cfg["note_type"] == "Changed"
    assert saved_cfg["deck"] == "Deck X"
    assert saved_cfg["sources"] == ["wiktionary_en"]


def test_save_config_active_preset_switch_updates_mirror(monkeypatch, tmp_path):
    manager = _DummyAddonManager(
        stored={
            "presets": [
                {"id": "one", "name": "One", "note_type": "N1", "deck": "D1", "sources": ["cambridge"]},
                {"id": "two", "name": "Two", "note_type": "N2", "deck": "D2", "sources": ["wiktionary"]},
            ],
            "active_preset_id": "one",
        }
    )
    monkeypatch.setattr(config_mod.mw, "addonManager", manager, raising=False)
    monkeypatch.setattr(config_mod, "META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.json")

    config_mod.save_config({"active_preset_id": "two"})

    assert manager.written is not None
    _, saved_cfg = manager.written
    assert saved_cfg["active_preset_id"] == "two"
    assert saved_cfg["note_type"] == "N2"
    assert saved_cfg["deck"] == "D2"
    assert saved_cfg["sources"] == ["wiktionary"]


def test_save_config_routes_other_settings_into_active_preset(monkeypatch, tmp_path):
    manager = _DummyAddonManager(
        stored={
            "presets": [
                {
                    "id": "one",
                    "name": "One",
                    "note_type": "N1",
                    "deck": "D1",
                    "sources": ["cambridge"],
                    "image_search": {"provider": "duckduckgo", "max_results": 12, "safe_search": True},
                    "field_map": {"word": ["Word"]},
                }
            ],
            "active_preset_id": "one",
        }
    )
    monkeypatch.setattr(config_mod.mw, "addonManager", manager, raising=False)
    monkeypatch.setattr(config_mod, "META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.json")

    config_mod.save_config(
        {
            "image_search": {"provider": "duckduckgo", "max_results": 30, "safe_search": False},
            "field_map": {"word": ["Term"], "definition": ["Def"]},
            "remember_last": False,
        }
    )

    assert manager.written is not None
    _, saved_cfg = manager.written
    preset = saved_cfg["presets"][0]
    assert preset["image_search"]["max_results"] == 30
    assert preset["image_search"]["safe_search"] is False
    assert preset["field_map"]["word"] == ["Term"]
    assert preset["field_map"]["definition"] == ["Def"]
    assert preset["remember_last"] is False
    assert saved_cfg["image_search"]["max_results"] == 30
    assert saved_cfg["field_map"]["word"] == ["Term"]
    assert saved_cfg["remember_last"] is False


def test_normalize_language_default_presets_validates_preset_ids():
    presets = [
        {"id": "default", "name": "Default"},
        {"id": "ru", "name": "ru"},
    ]
    out = config_mod.normalize_language_default_presets(
        {"en": "default", "ru": "missing", "de": "x"},
        presets,
    )
    assert out == {"en": "default", "ru": None}


def test_normalized_config_resets_removed_language_default_preset():
    cfg = config_mod._normalized_config(
        {
            "presets": [
                {"id": "default", "name": "Default", "sources": ["cambridge"]},
                {"id": "ru", "name": "ru", "sources": ["wiktionary"]},
            ],
            "active_preset_id": "default",
            "language_default_presets": {"en": "default", "ru": "ru"},
        }
    )
    assert cfg["language_default_presets"] == {"en": "default", "ru": "ru"}

    cfg_removed = config_mod._normalized_config(
        {
            "presets": [
                {"id": "default", "name": "Default", "sources": ["cambridge"]},
            ],
            "active_preset_id": "default",
            "language_default_presets": {"en": "default", "ru": "ru"},
        }
    )
    assert cfg_removed["language_default_presets"] == {"en": "default", "ru": None}
