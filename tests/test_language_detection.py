from __future__ import annotations

from cambridge_fetch.language_detection import detect_word_language


def test_detect_en_word():
    assert detect_word_language("house") == "en"


def test_detect_ru_word():
    assert detect_word_language("дом") == "ru"


def test_detect_mixed_script_returns_none():
    assert detect_word_language("дом-test") is None


def test_detect_non_letters_returns_none():
    assert detect_word_language(" 1234 -!? ") is None


def test_detect_phrase_with_punctuation_and_digits():
    assert detect_word_language("house 2024!") == "en"
    assert detect_word_language("дом, 2024!") == "ru"
