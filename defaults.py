from __future__ import annotations

import json
from typing import Dict

DEFAULT_IMAGE_PROVIDER = "duckduckgo"
SUPPORTED_SOURCE_IDS = ("cambridge", "wiktionary", "wiktionary_en")
DEFAULT_SOURCE_ID = "cambridge"
DEFAULT_PRESET_ID = "default"
DEFAULT_PRESET_NAME = "Default"
NOTE_DRAFT_SCHEMA_VERSION = 1

DEFAULT_TELEGRAM_SYNC_CONFIG: Dict = {
    "server_url": "",
    "bootstrap_token": "",
    "device_token": "",
    "device_label": "main-desktop",
    "auto_pull_on_startup": True,
    "pull_interval_minutes": 0,
    "auto_push_manifest": True,
    "last_sync_error": "",
}

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
    "language_default_presets": {"en": None, "ru": None},
    "telegram_sync": json.loads(json.dumps(DEFAULT_TELEGRAM_SYNC_CONFIG)),
}


def deep_copy_defaults() -> Dict:
    return json.loads(json.dumps(DEFAULT_CONFIG))
