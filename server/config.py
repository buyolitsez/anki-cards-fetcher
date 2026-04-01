from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path


def _sqlite_path_from_url(url: str) -> Path:
    if not url.startswith("sqlite:///"):
        raise ValueError("Only sqlite:/// DATABASE_URL is supported in v1.")
    return Path(url.removeprefix("sqlite:///"))


@dataclass(frozen=True)
class ServerSettings:
    database_url: str
    pair_bootstrap_token: str
    public_base_url: str
    telegram_bot_token: str
    telegram_allowed_user_ids: tuple[int, ...]

    @property
    def sqlite_path(self) -> Path:
        return _sqlite_path_from_url(self.database_url)

    @classmethod
    def from_env(cls) -> "ServerSettings":
        raw_allowed = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
        allowed_user_ids = tuple(
            int(part.strip())
            for part in raw_allowed.split(",")
            if part.strip()
        )
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:////tmp/cambridge_fetch.db"),
            pair_bootstrap_token=os.getenv("PAIR_BOOTSTRAP_TOKEN", ""),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_allowed_user_ids=allowed_user_ids,
        )
