from __future__ import annotations

from typing import Dict, Mapping


def manifest_to_dict(
    *,
    addon_version: str,
    presets: list[Dict],
    active_preset_id: str | None,
    language_default_presets: Dict,
    decks: list[str],
    note_types: list[str],
) -> Dict:
    return {
        "addon_version": addon_version,
        "presets": presets,
        "active_preset_id": active_preset_id,
        "language_default_presets": language_default_presets,
        "decks": decks,
        "note_types": note_types,
    }


def latest_manifest_payload(payload: Mapping | None) -> Dict:
    if not isinstance(payload, Mapping):
        return {}
    return {
        "addon_version": payload.get("addon_version"),
        "presets": list(payload.get("presets") or []),
        "active_preset_id": payload.get("active_preset_id"),
        "language_default_presets": dict(payload.get("language_default_presets") or {}),
        "decks": list(payload.get("decks") or []),
        "note_types": list(payload.get("note_types") or []),
    }
