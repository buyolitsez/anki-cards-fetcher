from __future__ import annotations

import types

import pytest

import cambridge_fetch.media as media_mod
from cambridge_fetch.media import _derive_media_name, _ext_from_content_type, _requests


def test_ext_from_content_type_known_and_unknown():
    assert _ext_from_content_type("image/jpeg; charset=utf-8") == ".jpg"
    assert _ext_from_content_type("application/json") == ""


def test_requests_loader_handles_import_error(monkeypatch):
    monkeypatch.setattr(media_mod.importlib, "import_module", lambda _name: (_ for _ in ()).throw(ImportError("x")))
    assert _requests() is None


def test_derive_media_name_decodes_percent_escapes():
    url = (
        "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f4/"
        "Amanab%2C_a_giant._Reproduction.jpg/250px-Amanab%2C_a_giant._Reproduction.jpg"
    )
    name = _derive_media_name(url, "image/jpeg")
    assert "%2C" not in name
    assert "," in name
    assert name.endswith(".jpg")


def test_derive_media_name_appends_extension_from_content_type():
    url = "https://example.com/media/sound"
    assert _derive_media_name(url, "audio/mpeg").endswith(".mp3")


def test_derive_media_name_fallback_for_empty_or_dot_names():
    assert _derive_media_name("https://example.com/", "image/png") == "download.png"
    assert _derive_media_name("https://example.com/..", "audio/ogg") == "download.ogg"


def test_download_to_media_success_with_protocol_relative_url(monkeypatch):
    calls = {}

    class _Resp:
        status_code = 200
        headers = {"Content-Type": "image/jpeg"}
        content = b"jpeg-bytes"

        def raise_for_status(self):
            return None

    class _Requests:
        def get(self, url, **kwargs):
            calls["url"] = url
            calls["headers"] = kwargs.get("headers") or {}
            calls["timeout"] = kwargs.get("timeout")
            return _Resp()

    class _Media:
        def __init__(self):
            self.seen = None

        def writeData(self, name, content):
            self.seen = (name, content)
            return "stored-" + name

        def dir(self):
            return "/tmp/anki-media"

    fake_media = _Media()
    fake_mw = types.SimpleNamespace(col=types.SimpleNamespace(media=fake_media))

    monkeypatch.setattr(media_mod, "mw", fake_mw)
    monkeypatch.setattr(media_mod, "_requests", lambda: _Requests())

    filename, path = media_mod.download_to_media("//cdn.example.com/img/pic.jpg")

    assert calls["url"] == "https://cdn.example.com/img/pic.jpg"
    assert calls["headers"]["Referer"] == "https://dictionary.cambridge.org/"
    assert calls["timeout"] == 20
    assert fake_media.seen == ("pic.jpg", b"jpeg-bytes")
    assert filename == "stored-pic.jpg"
    assert path == "/tmp/anki-media/stored-pic.jpg"


def test_download_to_media_relative_url_and_referer_disabled(monkeypatch):
    calls = {}

    class _Resp:
        status_code = 200
        headers = {"Content-Type": "application/octet-stream"}
        content = b"audio"

        def raise_for_status(self):
            return None

    class _Requests:
        def get(self, url, **kwargs):
            calls["url"] = url
            calls["headers"] = kwargs.get("headers") or {}
            return _Resp()

    fake_media = types.SimpleNamespace(
        writeData=lambda name, _content: name,
        dir=lambda: "/tmp/anki-media",
    )
    fake_mw = types.SimpleNamespace(col=types.SimpleNamespace(media=fake_media))

    monkeypatch.setattr(media_mod, "mw", fake_mw)
    monkeypatch.setattr(media_mod, "_requests", lambda: _Requests())

    filename, path = media_mod.download_to_media("/media/audio.mp3", referer=None)

    assert calls["url"] == "https://dictionary.cambridge.org/media/audio.mp3"
    assert "Referer" not in calls["headers"]
    assert filename == "audio.mp3"
    assert path == "/tmp/anki-media/audio.mp3"


def test_download_to_media_rejects_non_media_content(monkeypatch):
    class _Resp:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        content = b"<html></html>"

        def raise_for_status(self):
            return None

    class _Requests:
        def get(self, *_args, **_kwargs):
            return _Resp()

    fake_media = types.SimpleNamespace(
        writeData=lambda name, _content: name,
        dir=lambda: "/tmp/anki-media",
    )
    fake_mw = types.SimpleNamespace(col=types.SimpleNamespace(media=fake_media))

    monkeypatch.setattr(media_mod, "mw", fake_mw)
    monkeypatch.setattr(media_mod, "_requests", lambda: _Requests())

    with pytest.raises(RuntimeError, match="Expected audio/image file"):
        media_mod.download_to_media("https://example.com/index.html")


def test_download_to_media_requires_requests_module(monkeypatch):
    monkeypatch.setattr(media_mod, "_requests", lambda: None)
    with pytest.raises(RuntimeError, match="requests module not found"):
        media_mod.download_to_media("https://example.com/file.mp3")
