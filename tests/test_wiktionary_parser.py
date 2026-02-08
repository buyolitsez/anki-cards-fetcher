from __future__ import annotations

import pytest

bs4 = pytest.importorskip("bs4")
from bs4 import BeautifulSoup

import cambridge_fetch.fetchers.wiktionary as wiktionary_mod


def _make_fetcher():
    return wiktionary_mod.WiktionaryFetcher({})


def test_wiktionary_syllables_multi():
    html = """
    <section aria-labelledby="Русский">
      <p><b>о́<span class="hyph-dot">·</span>мут</b></p>
    </section>
    """
    soup = BeautifulSoup(html, "html.parser")
    lang = soup.select_one("section")
    fetcher = _make_fetcher()
    assert fetcher._extract_syllables(lang) == "о́·мут"


def test_wiktionary_syllables_single():
    html = """
    <section aria-labelledby="Русский">
      <span data-mw='{"parts":[{"template":{"params":{"слоги":{"wt":"{{по-слогам|тест}}"}}}}]}'></span>
      <p><b>тест</b></p>
    </section>
    """
    soup = BeautifulSoup(html, "html.parser")
    lang = soup.select_one("section")
    fetcher = _make_fetcher()
    assert fetcher._extract_syllables(lang) == "тест"


def test_wiktionary_parse_senses_and_synonyms():
    html = """
    <section aria-labelledby="Русский">
      <section aria-labelledby="Значение">
        <ol>
          <li>значение ◆ пример</li>
          <li>второе</li>
        </ol>
      </section>
      <section aria-labelledby="Синонимы">
        <ol>
          <li><a href="#">пример</a> <a href="#">тест</a></li>
        </ol>
      </section>
    </section>
    """
    soup = BeautifulSoup(html, "html.parser")
    lang = soup.select_one("section")
    fetcher = _make_fetcher()
    senses = fetcher._parse_senses(lang)
    assert len(senses) == 2
    assert senses[0].definition == "значение"
    assert senses[0].examples == ["пример"]
    assert "пример" in senses[0].synonyms
    assert "тест" in senses[0].synonyms


def test_wiktionary_ignores_semantic_ref_markers_and_backlinks():
    html = """
    <section aria-labelledby="Русский">
      <section aria-labelledby="Значение">
        <ol>
          <li>
            устар., также церк. пещера [ ≈ 1 ] [ ≠ 1 ] [ ▲ 1 ] [ ▼ 1 ] [ ‿ 1 ] [ ◇ 1 ] [ ◆ 1 ]
            ◆ пример 1
            ◆ пример 2
          </li>
        </ol>
      </section>
      <section aria-labelledby="Синонимы">
        <ol class="mw-references references">
          <li id="cite_note-1">
            <span class="mw-cite-backlink"><a href="#cite_ref-1">↑</a></span>
            <span class="mw-reference-text reference-text">
              <a href="#">пещера</a>, <a href="#">притон</a>, <a href="#">гнездилище</a>
            </span>
          </li>
        </ol>
      </section>
    </section>
    """
    soup = BeautifulSoup(html, "html.parser")
    lang = soup.select_one("section")
    fetcher = _make_fetcher()
    senses = fetcher._parse_senses(lang)
    assert len(senses) == 1
    assert senses[0].definition == "устар., также церк. пещера"
    assert senses[0].examples == ["пример 1", "пример 2"]
    assert senses[0].synonyms == ["пещера", "притон", "гнездилище"]


def test_wiktionary_uses_wiktionary_example_highlight_markup():
    html = """
    <section aria-labelledby="Русский">
      <section aria-labelledby="Значение">
        <ol>
          <li>
            очень большой человек
            <span class="example-fullblock">
              ◆ <span class="example-block">Исполи́н стоял у <b class="example-select">реки</b>.
                <span class="example-details"><i>источник</i></span>
              </span>
            </span>
          </li>
        </ol>
      </section>
    </section>
    """
    soup = BeautifulSoup(html, "html.parser")
    lang = soup.select_one("section")
    fetcher = _make_fetcher()
    senses = fetcher._parse_senses(lang)
    assert len(senses) == 1
    assert senses[0].examples == ["Исполи́н стоял у <b>реки</b>."]
