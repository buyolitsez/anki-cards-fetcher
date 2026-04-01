from __future__ import annotations

from typing import Dict, Iterable, List, Set

from ..core.source_selection import configured_source_ids, default_source_id


def ensure_source_selection(source_checks: Dict[str, object]) -> List[str]:
    selected = [source_id for source_id, chk in source_checks.items() if getattr(chk, "isChecked", lambda: False)()]
    if selected:
        return selected

    fallback = default_source_id()
    if fallback in source_checks:
        getattr(source_checks[fallback], "setChecked")(True)
        return [fallback]

    if source_checks:
        first_id, first_chk = next(iter(source_checks.items()))
        getattr(first_chk, "setChecked")(True)
        return [first_id]
    return [fallback]


def set_source_selection(source_checks: Dict[str, object], source_ids: Iterable[str]) -> List[str]:
    selected = {str(source_id).strip() for source_id in source_ids if str(source_id).strip()}
    for source_id, chk in source_checks.items():
        checked = source_id in selected
        blocker = getattr(chk, "blockSignals", None)
        if callable(blocker):
            blocker(True)
        getattr(chk, "setChecked")(checked)
        if callable(blocker):
            blocker(False)
    return ensure_source_selection(source_checks)
