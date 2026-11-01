from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


@dataclass
class Paper:
    id: str                      # "doi:10.1016/..." or "arxiv:2610.12345"
    title: str
    url: str
    venue: str
    publisher: str
    date: str                    # YYYY-MM-DD
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    # filled later
    topics: list[str] = field(default_factory=list)
    keyword_hits: int = 0
    score: float | None = None
    topic: str = ""
    reason: str = ""
    scored_by: str = ""          # "llm" or "keywords"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Paper":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean(text: str | None) -> str:
    """Strip JATS/HTML tags and collapse whitespace."""
    if not text:
        return ""
    text = _TAG.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    return re.sub(r"^(Abstract|ABSTRACT)[:.]?\s*", "", text)
