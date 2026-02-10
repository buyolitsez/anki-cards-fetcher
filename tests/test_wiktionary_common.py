from __future__ import annotations

import cambridge_fetch.fetchers.wiktionary_common as wc


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_parse_opensearch_payload_filters_duplicates_and_query():
    payload = ["house", ["house", "House", "home", "home", "", 10]]
    assert wc._parse_opensearch_payload(payload, "house", limit=8) == ["home"]


def test_suggest_via_opensearch_success_clamps_limit():
    calls = {}

    class _Requests:
        def get(self, url, **kwargs):
            calls["url"] = url
            calls["kwargs"] = kwargs
            return _Resp(payload=["huose", ["house", "hose", "house"]])

    out = wc.suggest_via_opensearch(
        requests_mod=_Requests(),
        api_base="https://example.org/api",
        query="huose",
        limit=999,
        user_agent="ua",
        log_tag="tag",
    )
    assert out == ["house", "hose"]
    assert calls["url"] == "https://example.org/api"
    assert calls["kwargs"]["params"]["limit"] == 20


def test_suggest_via_opensearch_request_error_logs(monkeypatch):
    log_messages = []
    monkeypatch.setattr(wc, "log_fetch", log_messages.append)

    class _Requests:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    out = wc.suggest_via_opensearch(
        requests_mod=_Requests(),
        api_base="https://example.org/api",
        query="test",
        limit=5,
        user_agent="ua",
        log_tag="wiktionary-en",
    )
    assert out == []
    assert log_messages
    assert "wiktionary-en" in log_messages[0]


def test_log_fetch_swallows_io_errors(monkeypatch):
    class _BrokenPath:
        def open(self, *_args, **_kwargs):
            raise OSError("nope")

    monkeypatch.setattr(wc, "LOG_PATH", _BrokenPath())
    wc.log_fetch("message")


def test_safe_limit_handles_invalid_values():
    assert wc._safe_limit("bad") == 1
    assert wc._safe_limit(-5) == 1


def test_parse_opensearch_payload_invalid_shape():
    assert wc._parse_opensearch_payload({"bad": 1}, "q", 5) == []
    assert wc._parse_opensearch_payload(["q"], "q", 5) == []


def test_parse_opensearch_payload_respects_limit():
    payload = ["q", ["one", "two", "three"]]
    assert wc._parse_opensearch_payload(payload, "z", 2) == ["one", "two"]


def test_suggest_via_opensearch_early_return_cases():
    assert wc.suggest_via_opensearch(
        requests_mod=None,
        api_base="https://example.org/api",
        query="test",
        limit=5,
        user_agent="ua",
        log_tag="tag",
    ) == []
    assert wc.suggest_via_opensearch(
        requests_mod=object(),
        api_base="https://example.org/api",
        query="   ",
        limit=5,
        user_agent="ua",
        log_tag="tag",
    ) == []


def test_suggest_via_opensearch_http_error_and_bad_json():
    class _RequestsHttpErr:
        def get(self, *_args, **_kwargs):
            return _Resp(status_code=500, payload=[])

    assert wc.suggest_via_opensearch(
        requests_mod=_RequestsHttpErr(),
        api_base="https://example.org/api",
        query="test",
        limit=5,
        user_agent="ua",
        log_tag="tag",
    ) == []

    class _RespBadJson:
        status_code = 200

        def json(self):
            raise ValueError("bad")

    class _RequestsBadJson:
        def get(self, *_args, **_kwargs):
            return _RespBadJson()

    assert wc.suggest_via_opensearch(
        requests_mod=_RequestsBadJson(),
        api_base="https://example.org/api",
        query="test",
        limit=5,
        user_agent="ua",
        log_tag="tag",
    ) == []
