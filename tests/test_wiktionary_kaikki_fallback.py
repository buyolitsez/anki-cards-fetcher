from __future__ import annotations

import json
import types

import pytest

import cambridge_fetch.fetchers.wiktionary as wiktionary_mod
import cambridge_fetch.fetchers.wiktionary_common as common_mod


def test_ru_wiktionary_kaikki_fallback_dedupes_duplicate_embedded_json(monkeypatch):
    payload = {
        "word": "тест",
        "pos": "noun",
        "sounds": [{"ipa": "[tɛst]"}],
        "senses": [
            {
                "glosses": ["test (challenge, trial, exam, etc.)"],
                "examples": [{"text": "тест по грамма́тике англи́йского языка́"}],
            }
        ],
    }
    html = f"<html><body><pre>{json.dumps(payload, ensure_ascii=False)}</pre><pre>{json.dumps(payload, ensure_ascii=False)}</pre></body></html>"

    class _Resp:
        def __init__(self, status_code, text="", payload=None):
            self.status_code = status_code
            self.text = text
            self._payload = payload
            self.encoding = None

        def json(self):
            if self._payload is None:
                raise ValueError("no payload")
            return self._payload

    def _fake_get(url, **kwargs):
        if "kaikki.org" in url:
            return _Resp(200, text=html)
        return _Resp(403, text="forbidden")

    fake_requests = types.SimpleNamespace(get=_fake_get)
    monkeypatch.setattr(common_mod, "require_requests", lambda: fake_requests)
    monkeypatch.setattr(wiktionary_mod, "require_requests", lambda: fake_requests)

    fetcher = wiktionary_mod.WiktionaryFetcher({})
    senses = fetcher.fetch("тест")

    assert len(senses) == 1
    assert senses[0].definition == "test (challenge, trial, exam, etc.)"
    assert senses[0].examples == ["тест по грамма́тике англи́йского языка́"]
