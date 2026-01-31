from __future__ import annotations

import pytest

bs4 = pytest.importorskip("bs4")
from bs4 import BeautifulSoup

from cambridge_fetch.fetchers.wiktionary_en import EnglishWiktionaryFetcher


def test_wiktionary_en_basic_parse():
    html = """
    <html><body>
      <h2><span class="mw-headline" id="English">English</span></h2>
      <h3><span class="mw-headline" id="Pronunciation">Pronunciation</span></h3>
      <ul>
        <li>(US) <span class="IPA">/haʊs/</span>
          <a href="//upload.wikimedia.org/wikipedia/commons/4/4a/En-us-house.ogg">audio</a>
        </li>
      </ul>
      <h3><span class="mw-headline" id="Noun">Noun</span></h3>
      <ol>
        <li>A building for human habitation.
          <ul><li>This is a house.</li></ul>
        </li>
      </ol>
      <h4><span class="mw-headline" id="Synonyms">Synonyms</span></h4>
      <ul><li><a href="/wiki/home">home</a>, <a href="/wiki/dwelling">dwelling</a></li></ul>
      <img src="//upload.wikimedia.org/wikipedia/commons/1/12/House.jpg" width="120" height="90">
      <h2><span class="mw-headline" id="Spanish">Spanish</span></h2>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    fetcher = EnglishWiktionaryFetcher({})
    lang = fetcher._language_headline(soup, "English")
    assert lang is not None

    senses = fetcher._parse_senses(lang)
    picture = fetcher._extract_picture(lang)

    assert senses
    sense = senses[0]
    assert sense.definition.startswith("A building")
    assert sense.examples == ["This is a house."]
    assert "home" in sense.synonyms
    assert "dwelling" in sense.synonyms
    assert sense.pos == "Noun"
    assert sense.ipa.get("us") == "/haʊs/"
    assert sense.audio_urls.get("us")
    assert picture and "upload.wikimedia.org" in picture
