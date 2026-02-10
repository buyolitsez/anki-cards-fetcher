from __future__ import annotations

import pytest

from cambridge_fetch.fetchers import get_fetcher_by_id, get_fetchers
from cambridge_fetch.fetchers.base import BaseFetcher
from cambridge_fetch.fetchers.cambridge import CambridgeFetcher


def test_get_fetchers_returns_all_registered_sources():
    fetchers = get_fetchers({})
    ids = {fetcher.ID for fetcher in fetchers}
    assert {"cambridge", "wiktionary", "wiktionary_en"} <= ids


def test_get_fetcher_by_id_falls_back_to_cambridge():
    fetcher = get_fetcher_by_id("unknown-source", {})
    assert isinstance(fetcher, CambridgeFetcher)


def test_base_fetcher_defaults():
    base = BaseFetcher({})
    assert base.suggest("test") == []
    assert base.supports_audio is False
    assert base.supports_picture is False
    with pytest.raises(NotImplementedError):
        base.fetch("test")
