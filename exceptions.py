"""Custom exception hierarchy for the add-on.

Using specific exceptions instead of bare ``RuntimeError`` makes it easier
to catch expected errors (network issues, missing modules) without
accidentally swallowing programming mistakes.
"""

from __future__ import annotations


class AddonError(Exception):
    """Base exception for all add-on errors."""


class FetchError(AddonError):
    """Failed to fetch data from a dictionary source."""


class MediaDownloadError(AddonError):
    """Failed to download an audio or image file."""


class MissingDependencyError(AddonError):
    """A required third-party module (requests, bs4) is not installed."""
