from __future__ import annotations

import types

import pytest

bs4 = pytest.importorskip("bs4")

import cambridge_fetch.fetchers.cambridge as cambridge_mod


def _patch_requests(monkeypatch, html: str):
    class _Resp:
        def __init__(self, text: str):
            self.status_code = 200
            self.text = text

    def _fake_get(*_args, **_kwargs):
        return _Resp(html)

    monkeypatch.setattr(cambridge_mod, "requests", types.SimpleNamespace(get=_fake_get))


def _make_fetcher():
    return cambridge_mod.CambridgeFetcher({"dialect_priority": ["uk", "us"]})


def test_cambridge_inline_examples(monkeypatch):
    html = """
    <html><body>
      <div class="entry">
        <div class="entry-body__el">
          <span class="pos dpos">noun</span>
          <div class="def-block">
            <div class="def ddef_d db">a building</div>
            <div class="examp dexamp"><span class="eg deg">The house is big.</span></div>
          </div>
        </div>
      </div>
    </body></html>
    """
    _patch_requests(monkeypatch, html)
    fetcher = _make_fetcher()
    senses = fetcher._parse_page("http://example/{word}", "house")
    assert len(senses) == 1
    assert senses[0].pos == "noun"
    assert senses[0].examples == ["The house is big."]


def test_cambridge_daccord_examples_fallback(monkeypatch):
    html = """
    <html><body>
      <div class="entry">
        <div class="entry-body__el">
          <span class="pos dpos">noun</span>
          <div class="def-block">
            <div class="def ddef_d db">a structure</div>
          </div>
        </div>
        <div class="daccord">
          <section>
            <header class="ca_h daccord_h">Examples</header>
            <div><ul class="hul-u"><li class="eg dexamp hax">The fence is high.</li></ul></div>
          </section>
        </div>
      </div>
    </body></html>
    """
    _patch_requests(monkeypatch, html)
    fetcher = _make_fetcher()
    senses = fetcher._parse_page("http://example/{word}", "fence")
    assert len(senses) == 1
    assert senses[0].examples == ["The fence is high."]


def test_cambridge_ipa_map(monkeypatch):
    html = """
    <html><body>
      <div class="entry">
        <div class="dpron-i">
          <span class="region dreg">uk</span>
          <span class="pron dpron">/<span class="ipa dipa">ədˈhɪə.rənt</span>/</span>
        </div>
        <div class="dpron-i">
          <span class="region dreg">us</span>
          <span class="pron dpron">/<span class="ipa dipa">ədˈhɪr.ənt</span>/</span>
        </div>
        <div class="entry-body__el">
          <span class="pos dpos">noun</span>
          <div class="def-block">
            <div class="def ddef_d db">a person who adheres</div>
          </div>
        </div>
      </div>
    </body></html>
    """
    _patch_requests(monkeypatch, html)
    fetcher = _make_fetcher()
    senses = fetcher._parse_page("http://example/{word}", "adherent")
    assert len(senses) == 1
    ipa = senses[0].ipa
    assert ipa.get("uk", "").startswith("/")
    assert ipa.get("us", "").startswith("/")


def test_cambridge_fetch_uses_amp_when_base_times_out(monkeypatch):
    amp_html = """
    <html><body>
      <div class="entry">
        <div class="entry-body__el">
          <span class="pos dpos">noun</span>
          <div class="def-block">
            <div class="def ddef_d db">a barrier around an area</div>
          </div>
        </div>
      </div>
    </body></html>
    """

    class _Resp:
        def __init__(self, text: str):
            self.status_code = 200
            self.text = text

    def _fake_get(url, *_args, **_kwargs):
        if "/dictionary/english/" in url:
            raise TimeoutError("read timed out")
        return _Resp(amp_html)

    monkeypatch.setattr(cambridge_mod, "requests", types.SimpleNamespace(get=_fake_get))
    fetcher = _make_fetcher()
    senses = fetcher.fetch("fence")
    assert senses
    assert senses[0].definition == "a barrier around an area"


def test_cambridge_fetch_raises_clear_timeout_when_all_requests_fail(monkeypatch):
    def _fake_get(*_args, **_kwargs):
        raise TimeoutError("read timed out")

    monkeypatch.setattr(cambridge_mod, "requests", types.SimpleNamespace(get=_fake_get))
    fetcher = _make_fetcher()
    with pytest.raises(RuntimeError, match="Cambridge request timed out"):
        fetcher.fetch("fence")


def test_cambridge_fetch_raises_cloudflare_block_message(monkeypatch):
    class _Resp:
        def __init__(self):
            self.status_code = 403
            self.text = "<html><title>Just a moment...</title><!-- cf-chl --></html>"
            self.headers = {"server": "cloudflare"}

    def _fake_get(*_args, **_kwargs):
        return _Resp()

    monkeypatch.setattr(cambridge_mod, "requests", types.SimpleNamespace(get=_fake_get))
    fetcher = _make_fetcher()
    with pytest.raises(RuntimeError, match="Cloudflare challenge"):
        fetcher.fetch("fence")
