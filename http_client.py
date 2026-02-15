"""Thin HTTP client wrapper used by all fetchers.

Centralizes ``requests`` import, default headers, timeouts, and logging so
that individual fetchers don't duplicate this boilerplate.
"""

from __future__ import annotations

import importlib
from typing import Optional

from .exceptions import FetchError, MissingDependencyError
from .logger import get_logger

logger = get_logger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 15


def _requests():
    """Lazily import ``requests`` (may not be installed in every Anki env)."""
    try:
        return importlib.import_module("requests")
    except Exception:
        return None


def _beautifulsoup():
    """Lazily import ``BeautifulSoup``."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
        return BeautifulSoup
    except Exception:
        return None


def require_requests():
    """Return the ``requests`` module or raise ``MissingDependencyError``."""
    mod = _requests()
    if not mod:
        raise MissingDependencyError("requests module not found. Install requests in the Anki environment.")
    return mod


def require_bs4():
    """Return ``BeautifulSoup`` or raise ``MissingDependencyError``."""
    cls = _beautifulsoup()
    if not cls:
        raise MissingDependencyError("bs4 not found. Install beautifulsoup4 in the Anki environment.")
    return cls


def get(
    url: str,
    *,
    timeout: int | tuple | None = None,
    referer: Optional[str] = None,
    accept: Optional[str] = None,
    accept_language: Optional[str] = "en-US,en;q=0.9",
    extra_headers: Optional[dict] = None,
):
    """Perform an HTTP GET with standard headers, logging, and error handling.

    Returns a ``requests.Response`` object.
    Raises ``FetchError`` on HTTP errors or connection failures.
    """
    requests = require_requests()
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    if accept_language:
        headers["Accept-Language"] = accept_language
    if referer:
        headers["Referer"] = referer
    if extra_headers:
        headers.update(extra_headers)

    effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
    logger.debug("HTTP GET %s (timeout=%s)", url, effective_timeout)

    try:
        resp = requests.get(url, headers=headers, timeout=effective_timeout)
    except Exception as e:
        logger.error("HTTP request failed: %s — %s", url, e)
        raise FetchError(f"Request failed: {e}") from e

    return resp


def get_soup(url: str, **kwargs):
    """GET *url* and return a ``BeautifulSoup`` parsed document.

    Keyword arguments are forwarded to :func:`get`.
    Raises ``FetchError`` on HTTP 4xx/5xx.
    """
    resp = get(url, **kwargs)
    if resp.status_code >= 400:
        raise FetchError(f"HTTP {resp.status_code} for {url}")
    BeautifulSoup = require_bs4()
    return BeautifulSoup(resp.text, "html.parser")
