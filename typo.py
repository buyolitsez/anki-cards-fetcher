from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Event
from typing import Callable, List, Optional, Sequence


@dataclass(frozen=True)
class TypoCollectResult:
    suggestions: List[str]
    cancelled: bool


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur.append(min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def fallback_queries(word: str, max_queries: int = 24) -> List[str]:
    q = word.strip()
    if len(q) < 3:
        return [q] if q else []
    out = [q]
    out.append(q[:-1])  # common typo: accidental extra last char
    if len(q) >= 5:
        out.append(q[:-2])
    out.append(q[1:])  # common typo: accidental first char
    # Remove one character in each position (covers accidental extra char).
    for i in range(len(q)):
        out.append(q[:i] + q[i + 1 :])
    # Swap adjacent chars (covers transposition typos: "frmo" -> "from").
    for i in range(len(q) - 1):
        swapped = list(q)
        swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        out.append("".join(swapped))
    seen: set[str] = set()
    uniq: List[str] = []
    for item in out:
        key = item.casefold()
        if key in seen or not item:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq[: max(1, max_queries)]


def rank_suggestions(word: str, candidates: List[str], limit: int) -> List[str]:
    base = word.strip()
    if not base:
        return []
    seen: set[str] = set()
    uniq: List[str] = []
    for candidate in candidates:
        cand = candidate.strip()
        if not cand:
            continue
        key = cand.casefold()
        if key == base.casefold() or key in seen:
            continue
        seen.add(key)
        uniq.append(cand)
    scored = sorted(
        uniq,
        key=lambda cand: (
            levenshtein(base.casefold(), cand.casefold()),
            abs(len(cand) - len(base)),
            cand.casefold(),
        ),
    )
    return scored[:limit]


def _safe_suggest_call(
    suggest_for_query: Callable[[str, str, int], List[str]],
    source_id: str,
    query: str,
    fetch_limit: int,
) -> List[str]:
    try:
        suggested = suggest_for_query(source_id, query, fetch_limit)
    except Exception:
        return []
    if not isinstance(suggested, list):
        return []
    return [item for item in suggested if isinstance(item, str)]


def collect_typo_suggestions(
    *,
    word: str,
    source_ids: Sequence[str],
    max_results: int,
    suggest_for_query: Callable[[str, str, int], List[str]],
    cancel_event: Optional[Event] = None,
    max_workers: int = 8,
    poll_interval: float = 0.05,
) -> TypoCollectResult:
    base = (word or "").strip()
    if not base:
        return TypoCollectResult(suggestions=[], cancelled=False)
    if cancel_event and cancel_event.is_set():
        return TypoCollectResult(suggestions=[], cancelled=True)

    max_results = max(1, min(int(max_results or 1), 40))
    query_count = max(8, min(max_results + 6, 18))
    fetch_limit = max(8, min(max_results * 2, 20))
    target_candidates = max(max_results * 3, 16)
    ranked_limit = max(max_results * 4, max_results + 12)
    queries = fallback_queries(base, max_queries=query_count)

    candidates: List[str] = []
    seen_candidates: set[str] = set()

    def add_candidate(candidate: str):
        item = (candidate or "").strip()
        if not item:
            return
        key = item.casefold()
        if key in seen_candidates:
            return
        seen_candidates.add(key)
        candidates.append(item)

    for query in queries:
        if query.casefold() != base.casefold():
            add_candidate(query)

    total_jobs = len(source_ids) * len(queries)
    if total_jobs <= 0:
        ranked = rank_suggestions(base, candidates, ranked_limit)
        return TypoCollectResult(suggestions=ranked, cancelled=False)

    worker_count = min(max(1, max_workers), max(1, total_jobs))
    pool = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="typo-suggest")
    pending = set()
    cancelled = False

    try:
        stop_submission = False
        for source_id in source_ids:
            if stop_submission:
                break
            for query in queries:
                if cancel_event and cancel_event.is_set():
                    cancelled = True
                    stop_submission = True
                    break
                future = pool.submit(_safe_suggest_call, suggest_for_query, source_id, query, fetch_limit)
                pending.add(future)

        while pending:
            if cancel_event and cancel_event.is_set():
                cancelled = True
                break
            done, pending = wait(pending, timeout=max(0.0, poll_interval), return_when=FIRST_COMPLETED)
            if not done:
                continue
            for future in done:
                for item in future.result():
                    add_candidate(item)
            if len(candidates) >= target_candidates:
                break
    finally:
        for future in pending:
            if not future.done():
                future.cancel()
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)

    ranked = rank_suggestions(base, candidates, ranked_limit)
    return TypoCollectResult(suggestions=ranked, cancelled=cancelled)
