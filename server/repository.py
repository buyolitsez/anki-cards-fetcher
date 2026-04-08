from __future__ import annotations

import json
import secrets
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from ..core.manifest import latest_manifest_payload
from ..core.types import NoteDraft


class Repository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS desktop_clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_label TEXT NOT NULL,
                    device_token TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS preset_manifests (
                    client_id INTEGER PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES desktop_clients(id)
                );

                CREATE TABLE IF NOT EXISTS duplicate_index (
                    client_id INTEGER PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES desktop_clients(id)
                );

                CREATE TABLE IF NOT EXISTS pending_note_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER NOT NULL,
                    telegram_user_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    draft_json TEXT NOT NULL,
                    failure_reason TEXT,
                    imported_note_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (client_id) REFERENCES desktop_clients(id)
                );

                CREATE TABLE IF NOT EXISTS import_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_item_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    note_id INTEGER,
                    reason TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (queue_item_id) REFERENCES pending_note_drafts(id)
                );

                CREATE TABLE IF NOT EXISTS telegram_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id TEXT NOT NULL UNIQUE,
                    is_allowed INTEGER NOT NULL DEFAULT 1,
                    last_used_preset_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def pair_device(self, device_label: str) -> Dict:
        token = secrets.token_urlsafe(24)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO desktop_clients (device_label, device_token) VALUES (?, ?)",
                (device_label, token),
            )
            client_id = int(cur.lastrowid)
        return {"client_id": client_id, "device_token": token, "device_label": device_label}

    def client_by_token(self, device_token: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM desktop_clients WHERE device_token = ?",
                (device_token,),
            ).fetchone()
        return row

    def save_manifest(self, device_token: str, payload: Dict) -> Dict:
        client = self.client_by_token(device_token)
        if client is None:
            raise LookupError("Unknown device token.")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preset_manifests (client_id, payload_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(client_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (int(client["id"]), json.dumps(payload)),
            )
        return {"status": "ok"}

    def save_duplicate_index(self, device_token: str, payload: Dict) -> Dict:
        client = self.client_by_token(device_token)
        if client is None:
            raise LookupError("Unknown device token.")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO duplicate_index (client_id, payload_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(client_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (int(client["id"]), json.dumps(payload)),
            )
        return {"status": "ok"}

    def latest_manifest(self) -> Dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT pm.client_id, pm.payload_json
                FROM preset_manifests pm
                ORDER BY pm.updated_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return {}
        payload = latest_manifest_payload(json.loads(row["payload_json"]))
        payload["client_id"] = int(row["client_id"])
        return payload

    def duplicate_index_for_client(self, client_id: int) -> Dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM duplicate_index WHERE client_id = ?",
                (client_id,),
            ).fetchone()
        if row is None:
            return {"items": {}}
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            return {"items": {}}
        return payload

    def ensure_telegram_user(self, telegram_user_id: int, *, allowed: bool) -> Dict:
        user_id = str(int(telegram_user_id))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO telegram_users (telegram_user_id, is_allowed, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    is_allowed = excluded.is_allowed,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, 1 if allowed else 0),
            )
            row = conn.execute(
                "SELECT * FROM telegram_users WHERE telegram_user_id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else {}

    def set_last_used_preset(self, telegram_user_id: int, preset_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE telegram_users
                SET last_used_preset_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_user_id = ?
                """,
                (preset_id, str(int(telegram_user_id))),
            )

    def telegram_user(self, telegram_user_id: int) -> Dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_users WHERE telegram_user_id = ?",
                (str(int(telegram_user_id)),),
            ).fetchone()
        return dict(row) if row else {}

    def enqueue_draft(self, *, client_id: int, telegram_user_id: int, draft: NoteDraft) -> Dict:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO pending_note_drafts (client_id, telegram_user_id, draft_json)
                VALUES (?, ?, ?)
                """,
                (client_id, str(int(telegram_user_id)), json.dumps(draft.to_dict())),
            )
            item_id = int(cur.lastrowid)
        return {"id": item_id, "status": "pending"}

    def list_pending(self, device_token: str, limit: int) -> List[Dict]:
        client = self.client_by_token(device_token)
        if client is None:
            raise LookupError("Unknown device token.")
        safe_limit = max(1, min(int(limit or 25), 200))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, draft_json, telegram_user_id, created_at
                FROM pending_note_drafts
                WHERE client_id = ? AND status = 'pending'
                ORDER BY id ASC
                LIMIT ?
                """,
                (int(client["id"]), safe_limit),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "telegram_user_id": row["telegram_user_id"],
                "created_at": row["created_at"],
                "draft": json.loads(row["draft_json"]),
            }
            for row in rows
        ]

    def mark_complete(self, device_token: str, item_id: int, note_id: int) -> Dict:
        client = self.client_by_token(device_token)
        if client is None:
            raise LookupError("Unknown device token.")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pending_note_drafts
                SET status = 'completed', imported_note_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND client_id = ?
                """,
                (note_id, item_id, int(client["id"])),
            )
            conn.execute(
                "INSERT INTO import_events (queue_item_id, status, note_id) VALUES (?, 'completed', ?)",
                (item_id, note_id),
            )
        return {"status": "completed"}

    def mark_failed(self, device_token: str, item_id: int, reason: str) -> Dict:
        client = self.client_by_token(device_token)
        if client is None:
            raise LookupError("Unknown device token.")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pending_note_drafts
                SET status = 'failed', failure_reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND client_id = ?
                """,
                (reason, item_id, int(client["id"])),
            )
            conn.execute(
                "INSERT INTO import_events (queue_item_id, status, reason) VALUES (?, 'failed', ?)",
                (item_id, reason),
            )
        return {"status": "failed"}
