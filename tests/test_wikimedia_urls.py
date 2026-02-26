from __future__ import annotations

from cambridge_fetch.wikimedia_urls import normalize_wikimedia_image_url


def test_normalize_wikimedia_image_url_rewrites_thumb_to_original():
    raw = (
        "//upload.wikimedia.org/wikipedia/commons/thumb/c/c6/"
        "Cocarde_Russie_1994.png/175px-Cocarde_Russie_1994.png"
    )
    assert normalize_wikimedia_image_url(raw) == (
        "https://upload.wikimedia.org/wikipedia/commons/c/c6/Cocarde_Russie_1994.png"
    )


def test_normalize_wikimedia_image_url_keeps_non_thumb():
    raw = "https://upload.wikimedia.org/wikipedia/commons/c/c6/Cocarde_Russie_1994.png"
    assert normalize_wikimedia_image_url(raw) == raw


def test_normalize_wikimedia_image_url_keeps_non_wikimedia():
    raw = "https://example.com/thumb/a/b/file.png/120px-file.png"
    assert normalize_wikimedia_image_url(raw) == raw
