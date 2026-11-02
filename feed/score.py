"""Relevance scoring with Claude (structured JSON output), with a keyword-only fallback."""
from __future__ import annotations

import os

import anthropic
from pydantic import BaseModel, Field

from feed.models import Paper

SYSTEM = """You screen newly published papers for one researcher and decide how relevant each is to \
their work. Their research profile:

{profile}

Topics (use the key as `topic`):
{topics}

Scoring guide:
9-10  directly on the researcher's problems (could be cited or built on next month)
7-8   clearly relevant method or application they would want to read
5-6   adjacent; useful background
0-4   not relevant (matches keywords only superficially)

For each paper give an integer score, the best-fitting topic key, and `reason`: one sentence (max 25 \
words) saying what the paper does and why it matters for this researcher. Some papers have no abstract; \
judge them from the title and venue and do not invent details. Return one entry for every paper id given."""


class Rating(BaseModel):
    id: str
    score: int = Field(ge=0, le=10)
    topic: str
    reason: str


class Ratings(BaseModel):
    ratings: list[Rating]


def _system(cfg: dict) -> str:
    topics = "\n".join(f"- {k}: {t['label']}" for k, t in cfg["topics"].items())
    return SYSTEM.format(profile=cfg["profile"].strip(), topics=topics)


def _paper_block(p: Paper) -> str:
    abstract = p.abstract[:2000] if p.abstract else "(no abstract available)"
    return f"id: {p.id}\ntitle: {p.title}\nvenue: {p.venue}\nabstract: {abstract}"


def keyword_scores(papers: list[Paper], cfg: dict) -> None:
    labels = {k: t["label"] for k, t in cfg["topics"].items()}
    for p in papers:
        p.score = min(10, 4 + p.keyword_hits)
        p.topic = p.topics[0] if p.topics else ""
        p.reason = "Keyword match: " + ", ".join(labels[t] for t in p.topics)
        p.scored_by = "keywords"


def llm_scores(papers: list[Paper], cfg: dict) -> None:
    """Scores papers in place. Falls back to keyword scores when the LLM is switched off, no key is
    set, the account can't be used (bad key, no credit), or a single batch fails."""
    if not cfg["scoring"].get("use_llm", True):
        print("  scoring.use_llm is false: using keyword scores")
        keyword_scores(papers, cfg)
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  ANTHROPIC_API_KEY not set: using keyword scores")
        keyword_scores(papers, cfg)
        return

    client = anthropic.Anthropic(max_retries=4)
    sc = cfg["scoring"]
    system = [{"type": "text", "text": _system(cfg), "cache_control": {"type": "ephemeral"}}]
    valid_topics = set(cfg["topics"])
    in_tok = out_tok = 0

    for i in range(0, len(papers), sc["batch_size"]):
        batch = papers[i:i + sc["batch_size"]]
        by_id = {p.id: p for p in batch}
        prompt = "Rate these papers:\n\n" + "\n\n---\n\n".join(_paper_block(p) for p in batch)
        try:
            resp = client.messages.parse(
                model=sc["model"],
                max_tokens=8000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "low"},
                output_format=Ratings,
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.BadRequestError) as e:
            # Invalid key or no credit: every later batch would fail the same way, so stop calling the API.
            print(f"  Claude API unusable ({type(e).__name__}: {e}); keyword scores for the rest")
            keyword_scores(papers[i:], cfg)
            break
        except (anthropic.APIError, ValueError) as e:  # ValueError: output failed validation
            print(f"  scoring batch {i // sc['batch_size']} failed ({type(e).__name__}: {e}); keyword fallback")
            keyword_scores(batch, cfg)
            continue
        in_tok += resp.usage.input_tokens + (resp.usage.cache_read_input_tokens or 0)
        out_tok += resp.usage.output_tokens
        if resp.stop_reason != "end_turn" or resp.parsed_output is None:
            print(f"  scoring batch {i // sc['batch_size']} stopped with {resp.stop_reason}; keyword fallback")
            keyword_scores(batch, cfg)
            continue
        for r in resp.parsed_output.ratings:
            p = by_id.get(r.id)
            if p is None:
                continue
            p.score, p.reason, p.scored_by = r.score, r.reason.strip(), "llm"
            p.topic = r.topic if r.topic in valid_topics else (p.topics[0] if p.topics else "")
        unrated = [p for p in batch if p.scored_by != "llm"]
        if unrated:
            keyword_scores(unrated, cfg)
    print(f"  claude usage: {in_tok} input / {out_tok} output tokens")

