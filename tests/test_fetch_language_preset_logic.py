from __future__ import annotations

from cambridge_fetch.language_detection import decide_language_default_preset


def _cfg():
    return {
        "presets": [
            {"id": "default", "name": "Default"},
            {"id": "ru", "name": "ru"},
        ],
        "language_default_presets": {"en": "default", "ru": "ru"},
    }


def test_decide_language_default_preset_switches_when_detected():
    decision = decide_language_default_preset(
        word="дом",
        cfg=_cfg(),
        current_preset_id="default",
        manual_preset_id="default",
        override_locked=False,
    )
    assert decision.detected_language == "ru"
    assert decision.target_preset_id == "ru"
    assert decision.clear_override_lock is False


def test_decide_language_default_preset_returns_none_for_ambiguous():
    decision = decide_language_default_preset(
        word="дом-test",
        cfg=_cfg(),
        current_preset_id="default",
        manual_preset_id="default",
        override_locked=False,
    )
    assert decision.detected_language is None
    assert decision.target_preset_id is None
    assert decision.clear_override_lock is False


def test_decide_language_default_preset_honors_manual_override_lock():
    decision = decide_language_default_preset(
        word="house",
        cfg=_cfg(),
        current_preset_id="ru",
        manual_preset_id="ru",
        override_locked=True,
    )
    assert decision.detected_language == "en"
    assert decision.target_preset_id is None
    assert decision.clear_override_lock is False


def test_decide_language_default_preset_clears_lock_when_word_empty():
    decision = decide_language_default_preset(
        word="   ",
        cfg=_cfg(),
        current_preset_id="ru",
        manual_preset_id="ru",
        override_locked=True,
    )
    assert decision.detected_language is None
    assert decision.target_preset_id is None
    assert decision.clear_override_lock is True


def test_decide_language_default_preset_rolls_back_to_manual_on_ambiguous():
    decision = decide_language_default_preset(
        word="дом-test",
        cfg=_cfg(),
        current_preset_id="ru",
        manual_preset_id="default",
        override_locked=False,
    )
    assert decision.detected_language is None
    assert decision.target_preset_id == "default"
    assert decision.clear_override_lock is False
