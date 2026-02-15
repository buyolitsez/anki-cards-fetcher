from __future__ import annotations

import types

import pytest

bs4 = pytest.importorskip("bs4")

import cambridge_fetch.fetchers.cambridge as cambridge_mod
import cambridge_fetch.fetchers.wiktionary as wiktionary_mod
import cambridge_fetch.fetchers.wiktionary_en as wiktionary_en_mod
import cambridge_fetch.fetchers.wiktionary_common as wiktionary_common_mod


def test_cambridge_spellcheck_parser():
    html = """
    <div>
      <h1>Search suggestions for <span class="tb">huose</span></h1>
      <ul class="hul-u">
        <li><a href="https://dictionary.cambridge.org/search/english/direct/?q=hose">hose</a></li>
        <li><a href="https://dictionary.cambridge.org/search/english/direct/?q=choose">choose</a></li>
        <li><a href="https://dictionary.cambridge.org/search/english/direct/?q=huose">huose</a></li>
        <li><a href="https://dictionary.cambridge.org/search/english/direct/?q=Hose">Hose</a></li>
      </ul>
    </div>
    """
    fetcher = cambridge_mod.CambridgeFetcher({"dialect_priority": ["uk", "us"]})
    out = fetcher._parse_spellcheck_suggestions(html, "huose", 8)
    assert out == ["hose", "choose"]


def test_wiktionary_ru_suggest_uses_opensearch(monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            return ["тсет", ["тест", "тесто", "тест"]]

    calls = {}

    def _fake_get(url, **kwargs):
        calls["url"] = url
        calls["params"] = kwargs.get("params") or {}
        return _Resp()

    fake_requests = types.SimpleNamespace(get=_fake_get)
    monkeypatch.setattr(wiktionary_common_mod, "require_requests", lambda: fake_requests)
    fetcher = wiktionary_mod.WiktionaryFetcher({})
    out = fetcher.suggest("тсет", limit=5)
    assert out == ["тест", "тесто"]
    assert calls["url"] == wiktionary_mod.WiktionaryFetcher.API_BASE
    assert calls["params"]["action"] == "opensearch"
    assert calls["params"]["limit"] == 5


def test_wiktionary_en_suggest_uses_opensearch(monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            return ["huose", ["house", "houser", "house"]]

    calls = {}

    def _fake_get(url, **kwargs):
        calls["url"] = url
        calls["params"] = kwargs.get("params") or {}
        return _Resp()

    fake_requests = types.SimpleNamespace(get=_fake_get)
    monkeypatch.setattr(wiktionary_common_mod, "require_requests", lambda: fake_requests)
    fetcher = wiktionary_en_mod.EnglishWiktionaryFetcher({})
    out = fetcher.suggest("huose", limit=5)
    assert out == ["house", "houser"]
    assert calls["url"] == wiktionary_en_mod.EnglishWiktionaryFetcher.API_BASE
    assert calls["params"]["action"] == "opensearch"
    assert calls["params"]["limit"] == 5
