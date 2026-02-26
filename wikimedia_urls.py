from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def normalize_wikimedia_image_url(url: str) -> str:
    """Convert Wikimedia thumbnail URLs to original file URLs.

    For non-Wikimedia or already-non-thumbnail URLs, returns input unchanged.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw

    parts = urlsplit(raw)
    if "wikimedia.org" not in (parts.netloc or ""):
        return raw
    if "/thumb/" not in (parts.path or ""):
        return raw

    segments = (parts.path or "").split("/")
    try:
        thumb_idx = segments.index("thumb")
    except ValueError:
        return raw
    # /.../thumb/<hash1>/<hash2>/<FileName>/<thumb-file-name>
    if len(segments) - thumb_idx < 5:
        return raw

    original_segments = segments[:thumb_idx] + segments[thumb_idx + 1 : -1]
    original_path = "/".join(original_segments)
    if not original_path.startswith("/"):
        original_path = "/" + original_path

    scheme = parts.scheme or "https"
    return urlunsplit((scheme, parts.netloc, original_path, "", ""))
