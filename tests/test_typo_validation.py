from __future__ import annotations

from cambridge_fetch.typo import collect_validated_typo_suggestions, validate_typo_candidates


def test_validate_typo_candidates_filters_out_invalid_words():
    result = validate_typo_candidates(
        candidates=["fence", "fnec", "fenec", "fence"],
        validate_word=lambda candidate: candidate in {"fence", "fenec"},
        target_count=5,
    )

    assert result.cancelled is False
    assert result.suggestions == ["fence", "fenec"]


def test_collect_validated_typo_suggestions_runs_collection_and_validation():
    result = collect_validated_typo_suggestions(
        word="fnec",
        source_ids=["cambridge"],
        max_results=5,
        suggest_for_query=lambda source_id, query, fetch_limit: ["fence", "fnec", "fennec"],
        validate_word=lambda candidate: candidate in {"fence"},
    )

    assert result.cancelled is False
    assert result.suggestions == ["fence"]


def test_collect_validated_typo_suggestions_keeps_ranked_order():
    result = collect_validated_typo_suggestions(
        word="препарка",
        source_ids=["wiktionary"],
        max_results=5,
        suggest_for_query=lambda source_id, query, fetch_limit: [],
        validate_word=lambda candidate: candidate in {"припарка", "пропарка"},
    )

    assert result.cancelled is False
    assert result.suggestions[:2] == ["припарка", "пропарка"]
