from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

from aqt import mw

from .language_detection import default_language_default_presets, supported_language_codes
from .logger import get_logger, set_log_level

logger = get_logger(__name__)

DEFAULT_IMAGE_PROVIDER = "duckduckgo"
SUPPORTED_SOURCE_IDS = ("cambridge", "wiktionary", "wiktionary_en")
DEFAULT_SOURCE_ID = "cambridge"
DEFAULT_PRESET_ID = "default"
DEFAULT_PRESET_NAME = "Default"

PRESET_PAYLOAD_KEYS = (
    "note_type",
    "deck",
    "sources",
    "remember_last",
    "field_map",
    "wiktionary",
    "dialect_priority",
    "max_examples",
    "max_synonyms",
    "image_search",
    "typo_suggestions",
    "log_level",
)
PRESET_SCOPED_UPDATE_KEYS = PRESET_PAYLOAD_KEYS + ("source",)

DEFAULT_PRESET_CONFIG: Dict = {
    "note_type": None,
    "deck": None,
    "remember_last": True,
    "field_map": {
        "word": ["Word", "Front"],
        "definition": ["Definition"],
        "examples": ["Examples", "Example"],
        "synonyms": ["Synonyms"],
        "pos": ["POS"],
        "ipa": ["IPA"],
        "audio": ["Audio"],
        "picture": ["Picture"],
    },
    "wiktionary": {
        "field_map": {
            "syllables": ["Syllables"],
        }
    },
    "dialect_priority": ["us", "uk"],
    "max_examples": 2,
    "max_synonyms": 4,
    "sources": [DEFAULT_SOURCE_ID],
    "image_search": {
        "provider": DEFAULT_IMAGE_PROVIDER,
        "max_results": 12,
        "safe_search": True,
    },
    "typo_suggestions": {
        "enabled": True,
        "max_results": 12,
    },
    "log_level": "WARNING",
}


DEFAULT_CONFIG: Dict = {
    **json.loads(json.dumps(DEFAULT_PRESET_CONFIG)),
    "presets": [
        {
            "id": DEFAULT_PRESET_ID,
            "name": DEFAULT_PRESET_NAME,
            **json.loads(json.dumps(DEFAULT_PRESET_CONFIG)),
        }
    ],
    "active_preset_id": DEFAULT_PRESET_ID,
    "language_default_presets": default_language_default_presets(),
}

# Add-on id helper (Anki may require the folder name in some versions)
try:
    ADDON_NAME = mw.addonManager.addonFromModule(__name__.split(".")[0])
except Exception:
    ADDON_NAME = os.path.basename(os.path.dirname(__file__))
ADDON_DIR = Path(os.path.dirname(__file__))
META_PATH = ADDON_DIR / "meta.json"
CONFIG_PATH = ADDON_DIR / "config.json"


def _read_meta_config() -> Dict:
    try:
        with META_PATH.open("r", encoding="utf-8") as f:
            meta = json.load(f)
        if isinstance(meta, dict) and isinstance(meta.get("config"), dict):
            logger.debug("Loaded config from meta.json")
            return meta["config"]
    except FileNotFoundError:
        logger.debug("meta.json not found, skipping")
    except Exception:
        logger.exception("Failed to read meta.json")
    return {}


def _read_config_json() -> Dict:
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        logger.debug("Loaded config from config.json")
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        logger.debug("config.json not found, using defaults")
        return {}
    except Exception:
        logger.exception("Failed to read config.json")
        return {}


def _deep_copy_defaults() -> Dict:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def _clean_optional_string(raw) -> Optional[str]:
    if isinstance(raw, str):
        value = raw.strip()
        return value or None
    return None


def _slugify_preset_id(raw: str) -> str:
    value = (raw or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "preset"


def _unique_preset_id(base_id: str, seen_ids: set[str]) -> str:
    candidate = _slugify_preset_id(base_id)
    if candidate not in seen_ids:
        seen_ids.add(candidate)
        return candidate
    suffix = 2
    while True:
        candidate_with_suffix = f"{candidate}-{suffix}"
        if candidate_with_suffix not in seen_ids:
            seen_ids.add(candidate_with_suffix)
            return candidate_with_suffix
        suffix += 1


def _normalize_int(raw, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except Exception:
        value = int(default)
    return max(minimum, min(value, maximum))


def normalize_dialect_priority(raw) -> list[str]:
    defaults = [str(x).lower() for x in DEFAULT_PRESET_CONFIG.get("dialect_priority", ["us", "uk"])]
    values = raw if isinstance(raw, (list, tuple)) else []
    out: list[str] = []
    for item in values:
        if not isinstance(item, str):
            continue
        key = item.strip().lower()
        if key in ("us", "uk") and key not in out:
            out.append(key)
    for key in defaults:
        if key not in out:
            out.append(key)
    return out[:2]


def normalize_max_examples(raw) -> int:
    default = int(DEFAULT_PRESET_CONFIG.get("max_examples", 2) or 2)
    return _normalize_int(raw, default=default, minimum=1, maximum=20)


def normalize_max_synonyms(raw) -> int:
    default = int(DEFAULT_PRESET_CONFIG.get("max_synonyms", 4) or 4)
    return _normalize_int(raw, default=default, minimum=1, maximum=50)


def _normalize_wiktionary_section(raw_section) -> Dict:
    wiki_default = DEFAULT_PRESET_CONFIG.get("wiktionary", {})
    stored_wiki = raw_section if isinstance(raw_section, dict) else {}
    merged = {**wiki_default, **stored_wiki}
    merged["field_map"] = normalize_field_map(
        {
            **(wiki_default.get("field_map", {}) if isinstance(wiki_default, dict) else {}),
            **(stored_wiki.get("field_map") or {}),
        }
    )
    return merged


def _normalize_preset_payload(raw_payload: Dict, fallback_payload: Dict) -> Dict:
    fallback_source_list = normalize_sources(fallback_payload.get("sources"), fallback_source=DEFAULT_SOURCE_ID)
    fallback_source = fallback_source_list[0] if fallback_source_list else DEFAULT_SOURCE_ID

    raw_note_type = _clean_optional_string(raw_payload.get("note_type"))
    raw_deck = _clean_optional_string(raw_payload.get("deck"))

    raw_sources = raw_payload.get("sources") if "sources" in raw_payload else fallback_source_list
    source_fallback = raw_payload.get("source") if "source" in raw_payload else fallback_source

    fallback_field_map = fallback_payload.get("field_map") if isinstance(fallback_payload.get("field_map"), dict) else {}
    raw_field_map = raw_payload.get("field_map") if isinstance(raw_payload.get("field_map"), dict) else {}
    field_map = normalize_field_map(
        {
            **DEFAULT_PRESET_CONFIG.get("field_map", {}),
            **fallback_field_map,
            **raw_field_map,
        }
    )

    if "wiktionary" in raw_payload:
        wiktionary_payload = raw_payload.get("wiktionary")
    else:
        wiktionary_payload = fallback_payload.get("wiktionary")

    raw_image = raw_payload.get("image_search") if "image_search" in raw_payload else fallback_payload.get("image_search")
    raw_typo = (
        raw_payload.get("typo_suggestions") if "typo_suggestions" in raw_payload else fallback_payload.get("typo_suggestions")
    )
    raw_log_level = raw_payload.get("log_level") if "log_level" in raw_payload else fallback_payload.get("log_level")

    return {
        "note_type": raw_note_type if raw_note_type is not None else _clean_optional_string(fallback_payload.get("note_type")),
        "deck": raw_deck if raw_deck is not None else _clean_optional_string(fallback_payload.get("deck")),
        "sources": normalize_sources(raw_sources, fallback_source=source_fallback),
        "remember_last": bool(raw_payload.get("remember_last", fallback_payload.get("remember_last", True))),
        "field_map": field_map,
        "wiktionary": _normalize_wiktionary_section(wiktionary_payload),
        "dialect_priority": normalize_dialect_priority(
            raw_payload.get("dialect_priority") if "dialect_priority" in raw_payload else fallback_payload.get("dialect_priority")
        ),
        "max_examples": normalize_max_examples(
            raw_payload.get("max_examples") if "max_examples" in raw_payload else fallback_payload.get("max_examples")
        ),
        "max_synonyms": normalize_max_synonyms(
            raw_payload.get("max_synonyms") if "max_synonyms" in raw_payload else fallback_payload.get("max_synonyms")
        ),
        "image_search": normalize_image_search(raw_image),
        "typo_suggestions": normalize_typo_suggestions(raw_typo),
        "log_level": normalize_log_level(raw_log_level),
    }


def normalize_preset(raw_preset) -> Optional[Dict]:
    if not isinstance(raw_preset, dict):
        return None
    raw_id = raw_preset.get("id")
    raw_name = raw_preset.get("name")
    out = {
        "id": raw_id.strip().lower() if isinstance(raw_id, str) else "",
        "name": raw_name.strip() if isinstance(raw_name, str) else "",
    }
    for key in PRESET_SCOPED_UPDATE_KEYS:
        if key in raw_preset:
            out[key] = raw_preset.get(key)
    return out


def normalize_presets(raw_presets, fallback_payload: Dict) -> list[Dict]:
    fallback = _normalize_preset_payload({}, fallback_payload)

    out: list[Dict] = []
    seen_ids: set[str] = set()
    for raw_preset in (raw_presets if isinstance(raw_presets, (list, tuple)) else []):
        normalized = normalize_preset(raw_preset)
        if not normalized:
            continue
        preset_id = _unique_preset_id(normalized.get("id") or normalized.get("name") or "preset", seen_ids)
        preset_name = normalized.get("name") or f"Preset {len(out) + 1}"
        payload = _normalize_preset_payload(normalized, fallback)
        out.append({"id": preset_id, "name": preset_name, **payload})

    if out:
        return out

    return [{"id": DEFAULT_PRESET_ID, "name": DEFAULT_PRESET_NAME, **fallback}]


def normalize_active_preset_id(raw_id, presets: list[Dict]) -> str:
    existing_ids = {str(preset.get("id") or "").strip() for preset in presets}
    if isinstance(raw_id, str):
        candidate = raw_id.strip()
        if candidate in existing_ids:
            return candidate
    if presets:
        return str(presets[0].get("id") or DEFAULT_PRESET_ID)
    return DEFAULT_PRESET_ID


def normalize_language_default_presets(raw, presets: list[Dict]) -> Dict[str, Optional[str]]:
    defaults = default_language_default_presets()
    out: Dict[str, Optional[str]] = defaults.copy()
    if not isinstance(raw, dict):
        return out

    existing_ids = {str(preset.get("id") or "").strip() for preset in presets}
    for code in supported_language_codes():
        value = raw.get(code)
        if not isinstance(value, str):
            continue
        preset_id = value.strip()
        if preset_id and preset_id in existing_ids:
            out[code] = preset_id
    return out


def get_preset_by_id(cfg: Dict, preset_id: Optional[str]) -> Optional[Dict]:
    presets = cfg.get("presets") if isinstance(cfg.get("presets"), list) else []
    for preset in presets:
        if str(preset.get("id") or "") == str(preset_id or ""):
            return preset
    return presets[0] if presets else None


def get_active_preset(cfg: Dict) -> Optional[Dict]:
    return get_preset_by_id(cfg, cfg.get("active_preset_id"))


def _mirror_active_preset_selection(cfg: Dict):
    active = get_active_preset(cfg)
    if not active:
        active = _normalize_preset_payload({}, DEFAULT_PRESET_CONFIG)
    payload = _normalize_preset_payload(active, DEFAULT_PRESET_CONFIG)
    for key in PRESET_PAYLOAD_KEYS:
        cfg[key] = payload.get(key)


def _apply_preset_scoped_updates(cfg: Dict, updates: Dict):
    cfg.setdefault("presets", _deep_copy_defaults().get("presets", []))
    cfg["active_preset_id"] = normalize_active_preset_id(cfg.get("active_preset_id"), cfg.get("presets") or [])
    active = get_active_preset(cfg)
    if not active:
        return
    for key in PRESET_SCOPED_UPDATE_KEYS:
        if key not in updates:
            continue
        if key in ("sources", "source"):
            raw_sources = updates.get("sources") if "sources" in updates else updates.get("source")
            fallback_sources = normalize_sources(active.get("sources"), fallback_source=DEFAULT_SOURCE_ID)
            fallback_source = fallback_sources[0] if fallback_sources else DEFAULT_SOURCE_ID
            source_fallback = updates.get("source", fallback_source)
            active["sources"] = normalize_sources(raw_sources, fallback_source=source_fallback)
            continue
        if key in ("note_type", "deck"):
            active[key] = _clean_optional_string(updates.get(key))
            continue
        active[key] = updates.get(key)


def _normalized_config(raw_cfg: Dict) -> Dict:
    raw = raw_cfg if isinstance(raw_cfg, dict) else {}
    merged = _deep_copy_defaults()
    merged.update(raw)

    fallback_payload = _normalize_preset_payload(
        {
            "note_type": raw.get("note_type"),
            "deck": raw.get("deck"),
            "sources": raw.get("sources"),
            "source": raw.get("source"),
            "remember_last": raw.get("remember_last"),
            "field_map": raw.get("field_map"),
            "wiktionary": raw.get("wiktionary"),
            "dialect_priority": raw.get("dialect_priority"),
            "max_examples": raw.get("max_examples"),
            "max_synonyms": raw.get("max_synonyms"),
            "image_search": raw.get("image_search"),
            "typo_suggestions": raw.get("typo_suggestions"),
            "log_level": raw.get("log_level"),
        },
        DEFAULT_PRESET_CONFIG,
    )

    merged["presets"] = normalize_presets(raw.get("presets"), fallback_payload)
    merged["active_preset_id"] = normalize_active_preset_id(raw.get("active_preset_id"), merged["presets"])
    merged["language_default_presets"] = normalize_language_default_presets(
        raw.get("language_default_presets"),
        merged["presets"],
    )
    _mirror_active_preset_selection(merged)

    merged.pop("source", None)
    return merged

def get_config() -> Dict:
    stored: Dict = {}
    try:
        stored = mw.addonManager.getConfig(ADDON_NAME) or {}
    except Exception:
        logger.exception("Failed to read config via addonManager")
    if not stored:
        stored = _read_meta_config()
    if not stored:
        stored = _read_config_json()
    cfg = _normalized_config(stored)
    # Apply log level from config so it takes effect immediately.
    set_log_level(cfg.get("log_level", "WARNING"))
    return cfg


def save_config(updates: Dict):
    logger.info("Saving config updates: %s", list(updates.keys()))
    cfg = get_config()
    normalized_updates = dict(updates or {})

    if "active_preset_id" in normalized_updates:
        cfg["active_preset_id"] = normalized_updates.get("active_preset_id")

    if any(key in normalized_updates for key in PRESET_SCOPED_UPDATE_KEYS) and "presets" not in normalized_updates:
        _apply_preset_scoped_updates(cfg, normalized_updates)
        for key in PRESET_SCOPED_UPDATE_KEYS:
            normalized_updates.pop(key, None)

    cfg.update(normalized_updates)
    cfg = _normalized_config(cfg)
    try:
        mw.addonManager.writeConfig(ADDON_NAME, cfg)
    except Exception:
        logger.exception("Failed to write config via addonManager")
    # Apply the new log level immediately.
    set_log_level(cfg.get("log_level", "WARNING"))
    logger.debug("Config saved successfully")


def normalize_field_map(fmap: Dict) -> Dict[str, list]:
    """Ensure every mapping value is a list of field names (trimmed, non-empty)."""
    normalized: Dict[str, list] = {}
    for key, val in fmap.items():
        names: list[str] = []
        if isinstance(val, str):
            parts = val.split(",")
            names = [p.strip() for p in parts if p and p.strip()]
        elif isinstance(val, (list, tuple)):
            for p in val:
                if isinstance(p, str) and p.strip():
                    names.append(p.strip())
        if names:
            normalized[key] = names
    return normalized


def normalize_source_id(raw) -> str:
    if isinstance(raw, str):
        source_id = raw.strip().lower()
        if source_id in SUPPORTED_SOURCE_IDS:
            return source_id
    return DEFAULT_SOURCE_ID


def normalize_sources(raw, fallback_source: Optional[str] = None) -> list[str]:
    fallback = normalize_source_id(fallback_source)
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    selected: list[str] = []
    for item in values:
        if not isinstance(item, str):
            continue
        source_id = item.strip().lower()
        if source_id in SUPPORTED_SOURCE_IDS and source_id not in selected:
            selected.append(source_id)
    if not selected:
        selected.append(fallback)
    return selected


def normalize_image_search(raw) -> Dict:
    """Keep only supported image-search keys and valid provider."""
    default = DEFAULT_PRESET_CONFIG.get("image_search", {})
    out = {
        "provider": default.get("provider", DEFAULT_IMAGE_PROVIDER),
        "max_results": default.get("max_results", 12),
        "safe_search": bool(default.get("safe_search", True)),
    }
    if not isinstance(raw, dict):
        return out
    provider = (raw.get("provider") or out["provider"] or DEFAULT_IMAGE_PROVIDER)
    provider = provider.strip().lower() if isinstance(provider, str) else DEFAULT_IMAGE_PROVIDER
    out["provider"] = provider if provider == DEFAULT_IMAGE_PROVIDER else DEFAULT_IMAGE_PROVIDER
    try:
        max_results = int(raw.get("max_results"))
    except Exception:
        max_results = int(out["max_results"] or 12)
    out["max_results"] = max(1, min(max_results, 100))
    out["safe_search"] = bool(raw.get("safe_search", out["safe_search"]))
    return out


def normalize_typo_suggestions(raw) -> Dict:
    default = DEFAULT_PRESET_CONFIG.get("typo_suggestions", {})
    out = {
        "enabled": bool(default.get("enabled", True)),
        "max_results": int(default.get("max_results", 12) or 12),
    }
    if not isinstance(raw, dict):
        return out
    out["enabled"] = bool(raw.get("enabled", out["enabled"]))
    try:
        max_results = int(raw.get("max_results"))
    except Exception:
        max_results = out["max_results"]
    out["max_results"] = max(1, min(max_results, 40))
    return out


def normalize_log_level(raw) -> str:
    """Validate and normalize the log level string."""
    from .logger import VALID_LEVELS

    if isinstance(raw, str):
        level = raw.strip().upper()
        if level in VALID_LEVELS:
            return level
    return DEFAULT_PRESET_CONFIG.get("log_level", "WARNING")
