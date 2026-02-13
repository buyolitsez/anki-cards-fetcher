from __future__ import annotations

from typing import List


def _safe_limit(limit: int, minimum: int = 1, maximum: int = 20) -> int:
    try:
        value = int(limit)
    except Exception:
        value = minimum
    return max(minimum, min(value, maximum))


def _parse_opensearch_payload(payload, query: str, limit: int) -> List[str]:
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for item in payload[1]:
        if not isinstance(item, str):
            continue
        candidate = item.strip()
        if not candidate:
            continue
        key = candidate.casefold()
        if key == query.casefold() or key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= limit:
            break
    return out


def suggest_via_opensearch(
    *,
    requests_mod,
    api_base: str,
    query: str,
    limit: int,
    user_agent: str,
) -> List[str]:
    safe_query = query.strip()
    if not requests_mod or not safe_query:
        return []
    safe_limit = _safe_limit(limit)
    try:
        resp = requests_mod.get(
            api_base,
            headers={"User-Agent": user_agent},
            params={
                "action": "opensearch",
                "search": safe_query,
                "limit": safe_limit,
                "namespace": 0,
                "format": "json",
            },
            timeout=15,
        )
    except Exception:
        return []
    if resp.status_code >= 400:
        return []
    try:
        payload = resp.json()
    except Exception:
        return []
    return _parse_opensearch_payload(payload, safe_query, safe_limit)
