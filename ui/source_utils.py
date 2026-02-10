from __future__ import annotations

from typing import Dict, List, Set

from ..config import DEFAULT_CONFIG


def default_source_id() -> str:
    defaults = DEFAULT_CONFIG.get("sources") or []
    return str(defaults[0] if defaults else "cambridge")


def configured_source_ids(cfg: Dict) -> Set[str]:
    cfg_sources = cfg.get("sources") if isinstance(cfg.get("sources"), list) else []
    selected = {str(source_id).strip() for source_id in cfg_sources if str(source_id).strip()}
    if selected:
        return selected
    return {default_source_id()}


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
