from __future__ import annotations

import json

import cambridge_fetch.config as config_mod


class _DummyAddonManager:
    def __init__(self, stored=None):
        self._stored = stored or {}
        self.written = None

    def getConfig(self, _name):
        return dict(self._stored)

    def writeConfig(self, name, cfg):
        self.written = (name, cfg)


def test_get_config_normalizes_legacy_source_and_nested(monkeypatch):
    manager = _DummyAddonManager(
        stored={
            "source": "wiktionary_en",
            "field_map": {"word": " Term , Front ", "definition": [" Def "]},
            "wiktionary": {"field_map": {"syllables": " Slg "}},
            "image_search": {"provider": "bing", "max_results": "500", "safe_search": 0},
            "typo_suggestions": {"enabled": "", "max_results": "-5"},
        }
    )
    monkeypatch.setattr(config_mod.mw, "addonManager", manager, raising=False)

    cfg = config_mod.get_config()

    assert cfg["sources"] == ["wiktionary_en"]
    assert "source" not in cfg
    assert cfg["field_map"]["word"] == ["Term", "Front"]
    assert cfg["field_map"]["definition"] == ["Def"]
    assert cfg["wiktionary"]["field_map"]["syllables"] == ["Slg"]
    assert cfg["image_search"]["provider"] == config_mod.DEFAULT_IMAGE_PROVIDER
    assert cfg["image_search"]["max_results"] == 100
    assert cfg["image_search"]["safe_search"] is False
    assert cfg["typo_suggestions"]["enabled"] is False
    assert cfg["typo_suggestions"]["max_results"] == 1


def test_save_config_normalizes_and_writes_files(monkeypatch, tmp_path):
    manager = _DummyAddonManager(stored={})
    monkeypatch.setattr(config_mod.mw, "addonManager", manager, raising=False)
    monkeypatch.setattr(config_mod, "META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.json")

    config_mod.save_config({"sources": [], "source": "wiktionary"})

    assert manager.written is not None
    _, saved_cfg = manager.written
    assert saved_cfg["sources"] == ["wiktionary"]
    assert "source" not in saved_cfg

    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    plain = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert meta["config"]["sources"] == ["wiktionary"]
    assert plain["sources"] == ["wiktionary"]


def test_normalize_helpers_bounds_and_defaults():
    assert config_mod.normalize_sources(["bad", "wiktionary"], fallback_source="cambridge") == ["wiktionary"]
    assert config_mod.normalize_sources([], fallback_source="wiktionary_en") == ["wiktionary_en"]

    image = config_mod.normalize_image_search({"provider": "x", "max_results": -2, "safe_search": 1})
    assert image == {
        "provider": config_mod.DEFAULT_IMAGE_PROVIDER,
        "max_results": 1,
        "safe_search": True,
    }

    typo = config_mod.normalize_typo_suggestions({"enabled": 0, "max_results": 99})
    assert typo == {"enabled": False, "max_results": 40}
