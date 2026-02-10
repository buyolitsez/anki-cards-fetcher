from __future__ import annotations

from cambridge_fetch.typo import fallback_queries, levenshtein, rank_suggestions


def test_fallback_queries_include_shorter_variants():
    queries = fallback_queries("carta")
    assert "carta" in queries
    assert "cart" in queries


def test_fallback_queries_include_transposition():
    queries = fallback_queries("fnec")
    assert "fenc" in queries


def test_fallback_queries_respect_limit():
    queries = fallback_queries("dictionary", max_queries=5)
    assert len(queries) == 5


def test_rank_suggestions_prefers_min_edit_distance():
    ranked = rank_suggestions(
        "carta",
        ["cartage", "carter", "cart", "car", "cart"],
        limit=5,
    )
    assert ranked[0] == "cart"
    assert "carta" not in ranked


def test_levenshtein_base_cases():
    assert levenshtein("", "abc") == 3
    assert levenshtein("abc", "") == 3
    assert levenshtein("abc", "abc") == 0


def test_fallback_queries_for_short_words():
    assert fallback_queries("  a ") == ["a"]
    assert fallback_queries("  ") == []


def test_rank_suggestions_empty_word_and_blank_candidates():
    assert rank_suggestions("   ", ["a", "b"], limit=5) == []
    assert rank_suggestions("test", ["", "   ", "test", "Test"], limit=5) == []
