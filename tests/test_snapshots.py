from __future__ import annotations

from pathlib import Path
import types
import re

import pytest

bs4 = pytest.importorskip("bs4")
from bs4 import BeautifulSoup

import cambridge_fetch.fetchers.cambridge as cambridge_mod
import cambridge_fetch.fetchers.wiktionary as wiktionary_mod

SNAP_DIR = Path(__file__).resolve().parent / "snapshots"
GOLDEN = {
    "cambridge_fence_example": "The house was surrounded by a tall, wooden fence.",
    "cambridge_test_example": "The class are doing/having a spelling test today.",
    "wiktionary_omut_syllables": "о́·мут",
    "wiktionary_test_syllables": "тест",
}


class _Resp:
    def __init__(self, text: str):
        self.status_code = 200
        self.text = text


def _load(name: str) -> str:
    path = SNAP_DIR / name
    if not path.exists():
        pytest.skip(f"Snapshot missing: {name}. Run tests/update_snapshots.py")
    return path.read_text(encoding="utf-8")


def _patch_requests(monkeypatch, html: str):
    def _fake_get(*_args, **_kwargs):
        return _Resp(html)

    monkeypatch.setattr(cambridge_mod, "requests", types.SimpleNamespace(get=_fake_get))


def _norm(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*([,.;:!?])", r"\1", text)
    return text


def test_snapshot_cambridge_test(monkeypatch):
    html = _load("cambridge_test.html")
    _patch_requests(monkeypatch, html)
    fetcher = cambridge_mod.CambridgeFetcher({"dialect_priority": ["uk", "us"]})
    senses = fetcher._parse_page("http://example/{word}", "test")
    assert senses, "no senses parsed"
    assert any(s.examples for s in senses), "examples should be parsed"
    assert any(s.pos for s in senses), "POS should be parsed"
    examples = [_norm(ex) for s in senses for ex in s.examples]
    assert _norm(GOLDEN["cambridge_test_example"]) in examples


def test_snapshot_cambridge_fence_examples(monkeypatch):
    html = _load("cambridge_fence.html")
    _patch_requests(monkeypatch, html)
    fetcher = cambridge_mod.CambridgeFetcher({"dialect_priority": ["uk", "us"]})
    senses = fetcher._parse_page("http://example/{word}", "fence")
    assert senses, "no senses parsed"
    assert any(s.examples for s in senses), "examples should be parsed from accordion fallback"
    examples = [_norm(ex) for s in senses for ex in s.examples]
    assert _norm(GOLDEN["cambridge_fence_example"]) in examples


def test_snapshot_wiktionary_omut_syllables():
    html = _load("wiktionary_omut.html")
    soup = BeautifulSoup(html, "html.parser")
    fetcher = wiktionary_mod.WiktionaryFetcher({})
    lang = fetcher._language_section(soup, "Русский")
    assert lang is not None, "language section missing"
    assert fetcher._extract_syllables(lang) == GOLDEN["wiktionary_omut_syllables"]


def test_snapshot_wiktionary_test_syllables():
    html = _load("wiktionary_test.html")
    soup = BeautifulSoup(html, "html.parser")
    fetcher = wiktionary_mod.WiktionaryFetcher({})
    lang = fetcher._language_section(soup, "Русский")
    assert lang is not None, "language section missing"
    assert fetcher._extract_syllables(lang) == GOLDEN["wiktionary_test_syllables"]
