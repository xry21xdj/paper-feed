"""Keyword pre-filter: decides which new papers are worth sending to Claude."""
from __future__ import annotations

import re

from feed.models import Paper


def _pattern(kw: str) -> re.Pattern:
    # Short tokens (LLM, GPT, V2G, SUMO) need whole-word matches; longer phrases may match as a
    # prefix ("charging schedul" -> scheduling/schedules).
    end = r"\b" if len(kw) <= 5 else ""
    flags = 0 if kw.isupper() else re.IGNORECASE
    return re.compile(r"\b" + re.escape(kw) + end, flags)


class KeywordFilter:
    def __init__(self, cfg: dict):
        self.topics = {name: [_pattern(k) for k in t["keywords"]] for name, t in cfg["topics"].items()}
        self.anchors = [_pattern(k) for k in cfg.get("anchor_keywords", [])]

    def tag(self, p: Paper) -> None:
        text = f"{p.title} {p.abstract}"
        p.topics, p.keyword_hits = [], 0
        for name, pats in self.topics.items():
            hits = sum(1 for pat in pats if pat.search(text))
            if hits:
                p.topics.append(name)
                p.keyword_hits += hits

    def keep(self, p: Paper, gated: bool = False, anchored: bool = False) -> bool:
        """`anchored`: the paper comes from a transport journal, so it needs no anchor term, and
        without an abstract it is kept regardless (the title alone rarely hits a keyword)."""
        self.tag(p)
        if anchored:
            return p.keyword_hits >= 1 or not p.abstract
        text = f"{p.title} {p.abstract}"
        return p.keyword_hits >= (2 if gated else 1) and any(a.search(text) for a in self.anchors)
