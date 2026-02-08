from __future__ import annotations

from typing import List


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
