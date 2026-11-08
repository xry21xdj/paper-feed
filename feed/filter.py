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


def all_keywords(cfg: dict) -> list[str]:
    return sorted({k for t in cfg["topics"].values() for k in t["keywords"] + t.get("free_keywords", [])})


class KeywordFilter:
    def __init__(self, cfg: dict):
        self.topics = {name: [_pattern(k) for k in t["keywords"]] for name, t in cfg["topics"].items()}
        self.free = {name: [_pattern(k) for k in t.get("free_keywords", [])] for name, t in cfg["topics"].items()}
        self.topic_anchors = {name: [_pattern(k) for k in t.get("anchors", [])] for name, t in cfg["topics"].items()}
        self.anchors = [_pattern(k) for k in cfg.get("anchor_keywords", [])]

    def tag(self, p: Paper) -> None:
        text = f"{p.title} {p.abstract}"
        p.topics, p.keyword_hits = [], 0
        for name in self.topics:
            hits = sum(1 for pat in self.topics[name] + self.free[name] if pat.search(text))
            if hits:
                p.topics.append(name)
                p.keyword_hits += hits

    def _has_context(self, p: Paper) -> bool:
        text = f"{p.title} {p.abstract}"
        if any(a.search(text) for a in self.anchors):
            return True
        return any(any(pat.search(text) for pat in self.free[t] + self.topic_anchors[t]) for t in p.topics)

    def keep(self, p: Paper, gated: bool = False, anchored: bool = False) -> bool:
        """`anchored`: the paper comes from a transport venue, so it needs no context term, and
        without an abstract it is kept regardless (the title alone rarely hits a keyword)."""
        self.tag(p)
        if anchored:
            return p.keyword_hits >= 1 or not p.abstract
        return p.keyword_hits >= (2 if gated else 1) and self._has_context(p)
