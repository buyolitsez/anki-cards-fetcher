from __future__ import annotations

from typing import Iterable, List, Mapping, Set

from ..defaults import DEFAULT_CONFIG


def default_source_id() -> str:
    defaults = DEFAULT_CONFIG.get("sources") or []
    return str(defaults[0] if defaults else "cambridge")


def configured_source_ids(cfg: Mapping) -> Set[str]:
    cfg_sources = cfg.get("sources") if isinstance(cfg.get("sources"), list) else []
    selected = {str(source_id).strip() for source_id in cfg_sources if str(source_id).strip()}
    if selected:
        return selected
    return {default_source_id()}


def ensure_source_selection_list(source_ids: Iterable[str]) -> List[str]:
    selected = []
    seen = set()
    for source_id in source_ids:
        value = str(source_id).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        selected.append(value)
    if selected:
        return selected
    return [default_source_id()]
