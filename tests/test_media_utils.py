from __future__ import annotations

import types

import pytest

import cambridge_fetch.media as media_mod
from cambridge_fetch.media import _derive_media_name, _ext_from_content_type
from cambridge_fetch.exceptions import MediaDownloadError, MissingDependencyError


def test_ext_from_content_type_known_and_unknown():
    assert _ext_from_content_type("image/jpeg; charset=utf-8") == ".jpg"
    assert _ext_from_content_type("application/json") == ""


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
    monkeypatch.setattr(media_mod, "require_requests", lambda: _Requests())

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
    monkeypatch.setattr(media_mod, "require_requests", lambda: _Requests())

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
    monkeypatch.setattr(media_mod, "require_requests", lambda: _Requests())

    with pytest.raises(MediaDownloadError, match="Expected audio/image file"):
        media_mod.download_to_media("https://example.com/index.html")


def test_download_to_media_requires_requests_module(monkeypatch):
    def raise_missing():
        raise MissingDependencyError("requests module not found")

    monkeypatch.setattr(media_mod, "require_requests", raise_missing)
    with pytest.raises(MissingDependencyError, match="requests module not found"):
        media_mod.download_to_media("https://example.com/file.mp3")


def test_download_to_media_retries_wikimedia_thumb_on_429(monkeypatch):
    calls = []

    class _Resp:
        def __init__(self, status_code, url, content_type, content):
            self.status_code = status_code
            self.url = url
            self.headers = {"Content-Type": content_type}
            self.content = content

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class _Requests:
        def get(self, url, **_kwargs):
            calls.append(url)
            if "/thumb/" in url:
                return _Resp(status_code=429, url=url, content_type="text/plain", content=b"rate-limited")
            return _Resp(status_code=200, url=url, content_type="image/png", content=b"png-bytes")

    fake_media = types.SimpleNamespace(
        writeData=lambda name, _content: name,
        dir=lambda: "/tmp/anki-media",
    )
    fake_mw = types.SimpleNamespace(col=types.SimpleNamespace(media=fake_media))

    monkeypatch.setattr(media_mod, "mw", fake_mw)
    monkeypatch.setattr(media_mod, "require_requests", lambda: _Requests())

    thumb_url = (
        "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c6/"
        "Cocarde_Russie_1994.png/175px-Cocarde_Russie_1994.png"
    )
    filename, path = media_mod.download_to_media(thumb_url, referer="https://ru.wiktionary.org/")

    assert calls == [
        thumb_url,
        "https://upload.wikimedia.org/wikipedia/commons/c/c6/Cocarde_Russie_1994.png",
    ]
    assert filename == "Cocarde_Russie_1994.png"
    assert path == "/tmp/anki-media/Cocarde_Russie_1994.png"
