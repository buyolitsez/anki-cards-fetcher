from __future__ import annotations

import time
from threading import Event, Lock

from cambridge_fetch.typo import collect_typo_suggestions, fallback_queries


def test_collect_typo_suggestions_ranks_and_dedups():
    def suggest_for_query(source_id: str, query: str, fetch_limit: int):
        if source_id == "src1":
            return ["aa", "bb", "aa", "ab", ""]
        return ["bb", "zz", "  "]

    result = collect_typo_suggestions(
        word="ab",
        source_ids=["src1", "src2"],
        max_results=5,
        suggest_for_query=suggest_for_query,
        max_workers=2,
    )

    assert result.cancelled is False
    assert result.suggestions[:3] == ["aa", "bb", "zz"]
    assert "ab" not in result.suggestions


def test_collect_typo_suggestions_cancel_before_start():
    cancel_event = Event()
    cancel_event.set()
    calls = {"count": 0}

    def suggest_for_query(source_id: str, query: str, fetch_limit: int):
        calls["count"] += 1
        return ["x"]

    result = collect_typo_suggestions(
        word="fence",
        source_ids=["src1"],
        max_results=8,
        suggest_for_query=suggest_for_query,
        cancel_event=cancel_event,
    )

    assert result.cancelled is True
    assert result.suggestions == []
    assert calls["count"] == 0


def test_collect_typo_suggestions_cancel_during_execution():
    cancel_event = Event()
    lock = Lock()
    calls = {"count": 0}

    def suggest_for_query(source_id: str, query: str, fetch_limit: int):
        with lock:
            calls["count"] += 1
            if calls["count"] == 1:
                cancel_event.set()
        time.sleep(0.02)
        return ["fencee"]

    max_results = 6
    total_jobs = len(fallback_queries("fence", max_queries=max(8, min(max_results + 6, 18))))
    result = collect_typo_suggestions(
        word="fence",
        source_ids=["src1"],
        max_results=max_results,
        suggest_for_query=suggest_for_query,
        cancel_event=cancel_event,
        max_workers=1,
    )

    assert result.cancelled is True
    assert calls["count"] < total_jobs
