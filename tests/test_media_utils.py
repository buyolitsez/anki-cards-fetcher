from __future__ import annotations

from cambridge_fetch.media import _derive_media_name


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
