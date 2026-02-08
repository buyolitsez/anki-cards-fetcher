from __future__ import annotations

import json
import os
import traceback
from pathlib import Path
from typing import Dict

from aqt import mw

DEFAULT_IMAGE_PROVIDER = "duckduckgo"

DEFAULT_CONFIG: Dict = {
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
    # Dictionary source: cambridge | wiktionary | wiktionary_en
    "source": "cambridge",
    "image_search": {
        "provider": DEFAULT_IMAGE_PROVIDER,
        "max_results": 12,
        "safe_search": True,
    },
    "typo_suggestions": {
        "enabled": True,
        "max_results": 12,
    },
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
            return meta["config"]
    except FileNotFoundError:
        pass
    except Exception:
        traceback.print_exc()
    return {}


def _read_config_json() -> Dict:
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        traceback.print_exc()
        return {}


def get_config() -> Dict:
    stored: Dict = {}
    try:
        stored = mw.addonManager.getConfig(ADDON_NAME) or {}
    except Exception:
        traceback.print_exc()
    if not stored:
        stored = _read_meta_config()
    if not stored:
        stored = _read_config_json()

    merged = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy defaults
    for k, v in stored.items():
        merged[k] = v
    # ensure nested dict keeps defaults too
    merged["field_map"] = normalize_field_map(
        {**DEFAULT_CONFIG.get("field_map", {}), **(stored.get("field_map") or {})}
    )
    # merge wiktionary subsection
    wiki_default = DEFAULT_CONFIG.get("wiktionary", {})
    stored_wiki = stored.get("wiktionary") if isinstance(stored.get("wiktionary"), dict) else {}
    merged["wiktionary"] = {**wiki_default, **(stored_wiki or {})}
    merged["wiktionary"]["field_map"] = normalize_field_map(
        {
            **(wiki_default.get("field_map", {}) if isinstance(wiki_default, dict) else {}),
            **(stored_wiki.get("field_map") or {}),
        }
    )
    merged["image_search"] = normalize_image_search(stored.get("image_search"))
    merged["typo_suggestions"] = normalize_typo_suggestions(stored.get("typo_suggestions"))
    return merged


def save_config(updates: Dict):
    cfg = get_config()
    cfg.update(updates)
    cfg["field_map"] = normalize_field_map(
        {**DEFAULT_CONFIG.get("field_map", {}), **(cfg.get("field_map") or {})}
    )
    wiki_default = DEFAULT_CONFIG.get("wiktionary", {})
    stored_wiki = cfg.get("wiktionary") if isinstance(cfg.get("wiktionary"), dict) else {}
    cfg["wiktionary"] = {**wiki_default, **(stored_wiki or {})}
    cfg["wiktionary"]["field_map"] = normalize_field_map(
        {
            **(wiki_default.get("field_map", {}) if isinstance(wiki_default, dict) else {}),
            **(stored_wiki.get("field_map") or {}),
        }
    )
    cfg["image_search"] = normalize_image_search(cfg.get("image_search"))
    cfg["typo_suggestions"] = normalize_typo_suggestions(cfg.get("typo_suggestions"))
    try:
        mw.addonManager.writeConfig(ADDON_NAME, cfg)
    except Exception:
        traceback.print_exc()
    # mirror to meta.json
    try:
        meta = {}
        if META_PATH.exists():
            with META_PATH.open("r", encoding="utf-8") as f:
                meta = json.load(f) or {}
                if not isinstance(meta, dict):
                    meta = {}
        meta["config"] = cfg
        with META_PATH.open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        traceback.print_exc()
    # plain config.json as fallback
    try:
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        traceback.print_exc()


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


def normalize_image_search(raw) -> Dict:
    """Keep only supported image-search keys and valid provider."""
    default = DEFAULT_CONFIG.get("image_search", {})
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
    default = DEFAULT_CONFIG.get("typo_suggestions", {})
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
