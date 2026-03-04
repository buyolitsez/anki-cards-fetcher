from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

_LATIN_RE = re.compile(r"^[A-Za-z]$")
_CYRILLIC_RE = re.compile(r"^[А-Яа-яЁё]$")

LANGUAGE_LABELS: Dict[str, str] = {
    "en": "English",
    "ru": "Russian",
}


def supported_language_codes() -> Tuple[str, ...]:
    return tuple(LANGUAGE_LABELS.keys())


def default_language_default_presets() -> Dict[str, Optional[str]]:
    return {code: None for code in supported_language_codes()}


def language_label(code: str) -> str:
    return LANGUAGE_LABELS.get(code, code)


def detect_word_language(word: str) -> Optional[str]:
    text = (word or "").strip()
    if not text:
        return None
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return None

    has_latin = False
    has_cyrillic = False
    for ch in letters:
        if _LATIN_RE.match(ch):
            has_latin = True
            continue
        if _CYRILLIC_RE.match(ch):
            has_cyrillic = True
            continue
        return None

    if has_latin and has_cyrillic:
        return None
    if has_latin:
        return "en"
    if has_cyrillic:
        return "ru"
    return None


@dataclass(frozen=True)
class LanguagePresetDecision:
    detected_language: Optional[str]
    target_preset_id: Optional[str]
    clear_override_lock: bool


def decide_language_default_preset(
    *,
    word: str,
    cfg: Dict,
    current_preset_id: Optional[str],
    manual_preset_id: Optional[str],
    override_locked: bool,
) -> LanguagePresetDecision:
    text = (word or "").strip()
    if not text:
        return LanguagePresetDecision(detected_language=None, target_preset_id=None, clear_override_lock=True)

    language = detect_word_language(text)
    preset_ids = {
        str(preset.get("id") or "").strip()
        for preset in (cfg.get("presets") if isinstance(cfg.get("presets"), list) else [])
    }
    current = current_preset_id.strip() if isinstance(current_preset_id, str) else None
    manual = manual_preset_id.strip() if isinstance(manual_preset_id, str) else None
    if manual not in preset_ids:
        manual = None

    if not language:
        if manual and current != manual:
            return LanguagePresetDecision(detected_language=None, target_preset_id=manual, clear_override_lock=False)
        return LanguagePresetDecision(detected_language=None, target_preset_id=None, clear_override_lock=False)

    if override_locked:
        return LanguagePresetDecision(detected_language=language, target_preset_id=None, clear_override_lock=False)

    mapping = cfg.get("language_default_presets")
    presets_map = mapping if isinstance(mapping, dict) else {}
    raw_target = presets_map.get(language)
    target = raw_target.strip() if isinstance(raw_target, str) and raw_target.strip() else None
    if not target:
        return LanguagePresetDecision(detected_language=language, target_preset_id=None, clear_override_lock=False)

    if target not in preset_ids:
        return LanguagePresetDecision(detected_language=language, target_preset_id=None, clear_override_lock=False)

    if current == target:
        return LanguagePresetDecision(detected_language=language, target_preset_id=None, clear_override_lock=False)

    return LanguagePresetDecision(detected_language=language, target_preset_id=target, clear_override_lock=False)
