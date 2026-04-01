from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from aqt import mw
from aqt.qt import QTimer
from aqt.utils import showWarning, tooltip

from ..config import get_config, save_config
from ..core.duplicates import configured_word_fields, normalize_duplicate_text
from ..core.manifest import manifest_to_dict
from ..core.types import NoteDraft
from ..http_client import require_requests
from ..logger import get_logger
from ..ui.background import run_in_background
from .importer import DraftImportError, add_note_from_draft

logger = get_logger(__name__)

_SYNC_TIMER: Optional[QTimer] = None


class SyncClient:
    def __init__(self, server_url: str, device_token: str = ""):
        self.server_url = server_url.rstrip("/")
        self.device_token = device_token.strip()
        self.requests = require_requests()

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.device_token:
            headers["Authorization"] = f"Bearer {self.device_token}"
        return headers

    def pair(self, bootstrap_token: str, device_label: str) -> Dict:
        resp = self.requests.post(
            f"{self.server_url}/api/v1/pair",
            json={"bootstrap_token": bootstrap_token, "device_label": device_label},
            headers=self._headers(),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def push_manifest(self, payload: Dict) -> Dict:
        resp = self.requests.put(
            f"{self.server_url}/api/v1/manifest",
            json=payload,
            headers=self._headers(),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def push_duplicate_index(self, payload: Dict) -> Dict:
        resp = self.requests.put(
            f"{self.server_url}/api/v1/duplicate-index",
            json=payload,
            headers=self._headers(),
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def pending_queue(self, limit: int = 25) -> List[Dict]:
        resp = self.requests.get(
            f"{self.server_url}/api/v1/queue/pending",
            params={"limit": limit},
            headers=self._headers(),
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        return list(payload.get("items") or [])

    def mark_complete(self, item_id: int, note_id: int) -> None:
        resp = self.requests.post(
            f"{self.server_url}/api/v1/queue/{item_id}/complete",
            json={"note_id": note_id},
            headers=self._headers(),
            timeout=20,
        )
        resp.raise_for_status()

    def mark_failed(self, item_id: int, reason: str) -> None:
        resp = self.requests.post(
            f"{self.server_url}/api/v1/queue/{item_id}/fail",
            json={"reason": reason},
            headers=self._headers(),
            timeout=20,
        )
        resp.raise_for_status()


def _telegram_sync_cfg() -> Dict:
    cfg = get_config()
    value = cfg.get("telegram_sync")
    return value if isinstance(value, dict) else {}


def _persist_sync_cfg(updated_cfg: Dict) -> None:
    current = _telegram_sync_cfg()
    merged = {**current, **updated_cfg}
    save_config({"telegram_sync": merged})


def _manifest_payload() -> Dict:
    cfg = get_config()
    col = mw.col
    manifest_path = Path(__file__).resolve().parents[1] / "manifest.json"
    addon_version = "1.0"
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        addon_version = str(manifest_payload.get("version") or addon_version)
    except Exception:
        pass
    return manifest_to_dict(
        addon_version=addon_version,
        presets=list(cfg.get("presets") or []),
        active_preset_id=cfg.get("active_preset_id"),
        language_default_presets=dict(cfg.get("language_default_presets") or {}),
        decks=list(col.decks.allNames()),
        note_types=list(col.models.allNames()),
    )


def _find_note_ids(col, deck_name: str, note_type_name: str) -> List[int]:
    query = f'deck:"{deck_name.replace(chr(34), r"\\\"")}" note:"{note_type_name.replace(chr(34), r"\\\"")}"'
    finder = getattr(col, "find_notes", None)
    if callable(finder):
        return list(finder(query) or [])
    legacy_finder = getattr(col, "findNotes", None)
    if callable(legacy_finder):
        return list(legacy_finder(query) or [])
    return []


def _get_note(col, note_id: int):
    getter = getattr(col, "get_note", None)
    if callable(getter):
        return getter(note_id)
    legacy_getter = getattr(col, "getNote", None)
    if callable(legacy_getter):
        return legacy_getter(note_id)
    return None


def _build_duplicate_index_payload() -> Dict:
    cfg = get_config()
    col = mw.col
    items: Dict[str, List[str]] = {}
    for preset in (cfg.get("presets") if isinstance(cfg.get("presets"), list) else []):
        preset_id = str(preset.get("id") or "").strip()
        deck_name = str(preset.get("deck") or "").strip()
        note_type_name = str(preset.get("note_type") or "").strip()
        field_names = configured_word_fields(preset.get("field_map") or {})
        if not preset_id or not deck_name or not note_type_name or not field_names:
            continue
        values = set()
        for note_id in _find_note_ids(col, deck_name, note_type_name):
            note = _get_note(col, note_id)
            if note is None:
                continue
            for field_name in field_names:
                if field_name not in note:
                    continue
                normalized = normalize_duplicate_text(note[field_name] or "")
                if normalized:
                    values.add(normalized)
        items[preset_id] = sorted(values)
    return {"items": items}


def push_manifest_and_index_now() -> Dict:
    sync_cfg = _telegram_sync_cfg()
    server_url = str(sync_cfg.get("server_url") or "").strip()
    device_token = str(sync_cfg.get("device_token") or "").strip()
    if not server_url or not device_token:
        raise RuntimeError("Telegram sync is not paired yet.")
    client = SyncClient(server_url=server_url, device_token=device_token)
    manifest_result = client.push_manifest(_manifest_payload())
    duplicate_result = client.push_duplicate_index(_build_duplicate_index_payload())
    _persist_sync_cfg({"last_sync_error": ""})
    return {"manifest": manifest_result, "duplicate_index": duplicate_result}


def pair_device_and_sync() -> Dict:
    sync_cfg = _telegram_sync_cfg()
    server_url = str(sync_cfg.get("server_url") or "").strip()
    bootstrap_token = str(sync_cfg.get("bootstrap_token") or "").strip()
    device_label = str(sync_cfg.get("device_label") or "").strip() or f"desktop-{uuid.uuid4().hex[:8]}"
    if not server_url or not bootstrap_token:
        raise RuntimeError("Set server URL and bootstrap token first.")
    client = SyncClient(server_url=server_url)
    paired = client.pair(bootstrap_token=bootstrap_token, device_label=device_label)
    device_token = str(paired.get("device_token") or "").strip()
    if not device_token:
        raise RuntimeError("Pairing succeeded but no device token was returned.")
    _persist_sync_cfg({"device_token": device_token, "device_label": device_label})
    return push_manifest_and_index_now()


def import_pending_queue(limit: int = 25) -> Dict:
    sync_cfg = _telegram_sync_cfg()
    server_url = str(sync_cfg.get("server_url") or "").strip()
    device_token = str(sync_cfg.get("device_token") or "").strip()
    if not server_url or not device_token:
        return {"imported": 0, "failed": 0, "items": []}

    client = SyncClient(server_url=server_url, device_token=device_token)
    items = client.pending_queue(limit=limit)
    imported = 0
    failed = 0
    results: List[Dict] = []

    for item in items:
        item_id = int(item.get("id") or 0)
        draft = NoteDraft.from_dict(item.get("draft") or {})
        try:
            note_id = add_note_from_draft(mw.col, draft)
        except Exception as exc:
            failed += 1
            reason = str(exc)
            client.mark_failed(item_id, reason)
            results.append({"id": item_id, "status": "failed", "reason": reason})
            continue
        client.mark_complete(item_id, note_id)
        imported += 1
        results.append({"id": item_id, "status": "completed", "note_id": note_id})

    if imported:
        mw.reset()
    _persist_sync_cfg({"last_sync_error": ""})
    return {"imported": imported, "failed": failed, "items": results}


def _run_ui_action(task, success_message: str, parent=None) -> None:
    def on_done(future):
        try:
            result = future.result()
        except Exception as exc:
            logger.exception("Telegram sync action failed")
            _persist_sync_cfg({"last_sync_error": str(exc)})
            showWarning(f"Telegram sync failed: {exc}")
            return
        tooltip(success_message.format(result=result), parent=parent)

    run_in_background(task, on_done)


def run_pair_and_sync(parent=None) -> None:
    _run_ui_action(
        task=pair_device_and_sync,
        success_message="Desktop paired and metadata synced.",
        parent=parent,
    )


def run_push_manifest(parent=None) -> None:
    _run_ui_action(
        task=push_manifest_and_index_now,
        success_message="Manifest and duplicate index synced.",
        parent=parent,
    )


def run_manual_import(parent=None) -> None:
    _run_ui_action(
        task=lambda: import_pending_queue(limit=25),
        success_message="Imported {result[imported]} Telegram draft(s).",
        parent=parent,
    )


def initialize_sync_hooks(parent=None) -> None:
    global _SYNC_TIMER
    cfg = _telegram_sync_cfg()
    if cfg.get("auto_pull_on_startup"):
        QTimer.singleShot(1500, lambda: run_manual_import(parent=parent))
    interval_minutes = int(cfg.get("pull_interval_minutes") or 0)
    if interval_minutes <= 0:
        return
    _SYNC_TIMER = QTimer(parent)
    _SYNC_TIMER.setInterval(interval_minutes * 60 * 1000)
    _SYNC_TIMER.timeout.connect(lambda: run_manual_import(parent=parent))
    _SYNC_TIMER.start()
