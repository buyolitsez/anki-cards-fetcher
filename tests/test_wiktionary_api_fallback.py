from __future__ import annotations

import types

import pytest

bs4 = pytest.importorskip("bs4")

import cambridge_fetch.fetchers.wiktionary_common as common_mod
from cambridge_fetch.fetchers.wiktionary import WiktionaryFetcher


def test_wiktionary_fetch_uses_parse_api_fallback_on_403(monkeypatch):
    snapshot_html = """
    <section aria-labelledby="Русский">
      <section aria-labelledby="Значение">
        <ol>
          <li>проверочное значение</li>
        </ol>
      </section>
    </section>
    """

    class _Resp:
        def __init__(self, status_code, text="", payload=None):
            self.status_code = status_code
            self.text = text
            self._payload = payload

        def json(self):
            if self._payload is None:
                raise ValueError("no json")
            return self._payload

    calls = []

    def _fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if url == WiktionaryFetcher.API_BASE:
            return _Resp(
                200,
                payload={"parse": {"text": snapshot_html}},
            )
        return _Resp(403, text="forbidden")

    fake_requests = types.SimpleNamespace(get=_fake_get)
    monkeypatch.setattr(common_mod, "require_requests", lambda: fake_requests)

    fetcher = WiktionaryFetcher({})
    senses = fetcher.fetch("тест")

    assert len(senses) == 1
    assert senses[0].definition == "проверочное значение"
    assert calls[1][0] == WiktionaryFetcher.API_BASE
    assert calls[1][1]["params"]["action"] == "parse"
