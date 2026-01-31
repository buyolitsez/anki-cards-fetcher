from __future__ import annotations

from typing import Dict, List, Type

from .base import BaseFetcher
from .cambridge import CambridgeFetcher
from .wiktionary import WiktionaryFetcher
from .wiktionary_en import EnglishWiktionaryFetcher

# Регистр доступных источников
REGISTER: Dict[str, Type[BaseFetcher]] = {
    CambridgeFetcher.ID: CambridgeFetcher,
    WiktionaryFetcher.ID: WiktionaryFetcher,
    EnglishWiktionaryFetcher.ID: EnglishWiktionaryFetcher,
}


def get_fetchers(cfg) -> List[BaseFetcher]:
    """Создаёт экземпляры доступных фетчеров."""
    return [
        fetcher_cls(cfg)
        for fetcher_cls in REGISTER.values()
    ]


def get_fetcher_by_id(source_id: str, cfg) -> BaseFetcher:
    fetcher_cls = REGISTER.get(source_id) or CambridgeFetcher
    return fetcher_cls(cfg)
