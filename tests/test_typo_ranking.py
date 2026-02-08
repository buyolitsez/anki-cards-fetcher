from __future__ import annotations

from cambridge_fetch.typo import fallback_queries, rank_suggestions


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
