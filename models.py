from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Sense:
    """Унифицированная структура значения словаря."""

    definition: str
    examples: List[str] = field(default_factory=list)
    synonyms: List[str] = field(default_factory=list)
    pos: Optional[str] = None
    syllables: Optional[str] = None
    ipa: Dict[str, str] = field(default_factory=dict)  # region -> ipa
    audio_urls: Dict[str, str] = field(default_factory=dict)  # region -> url
    picture_url: Optional[str] = None

    def preview_text(self, max_examples: int, max_synonyms: int) -> str:
        lines: List[str] = []
        if self.pos:
            lines.append(f"[{self.pos}]")
        lines.append(self.definition)
        if self.examples:
            ex = self.examples[:max_examples]
            lines.append("Examples: " + " | ".join(ex))
        if self.synonyms:
            syn = ", ".join(self.synonyms[:max_synonyms])
            lines.append("Synonyms: " + syn)
        if self.audio_urls:
            lines.append("Audio: " + ", ".join(self.audio_urls.keys()))
        if self.picture_url:
            lines.append("Picture available")
        if self.syllables:
            lines.append("Syllables: " + self.syllables)
        if self.ipa:
            lines.append("IPA: " + ", ".join(self.ipa.keys()))
        return "\n".join(lines)
