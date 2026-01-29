from __future__ import annotations

from typing import List

from ..models import Sense


class BaseFetcher:
    ID: str = "base"
    LABEL: str = "Base"

    def __init__(self, cfg):
        self.cfg = cfg

    def fetch(self, word: str) -> List[Sense]:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def supports_audio(self) -> bool:
        return False

    @property
    def supports_picture(self) -> bool:
        return False
