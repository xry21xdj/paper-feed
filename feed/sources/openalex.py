"""Fill in missing abstracts from OpenAlex, looked up by DOI (50 per request).

Lookups by DOI work on the free tier; an `OPENALEX_API_KEY` raises the daily budget.
"""
from __future__ import annotations

import os

import httpx

from feed.models import Paper

API = "https://api.openalex.org/works"


def _rebuild(inv: dict[str, list[int]]) -> str:
    words = sorted((pos, w) for w, positions in inv.items() for pos in positions)
    return " ".join(w for _, w in words)


def add_abstracts(papers: list[Paper], client: httpx.Client) -> int:
    missing = [p for p in papers if not p.abstract and p.id.startswith("doi:")]
    by_doi = {p.id[4:]: p for p in missing}
    params_base = {"select": "doi,abstract_inverted_index", "per-page": 50}
    if os.environ.get("OPENALEX_API_KEY"):
        params_base["api_key"] = os.environ["OPENALEX_API_KEY"]
    filled = 0
    dois = list(by_doi)
    for i in range(0, len(dois), 50):
        chunk = dois[i:i + 50]
        params = dict(params_base, filter="doi:" + "|".join(chunk))
        try:
            r = client.get(API, params=params, timeout=60)
            r.raise_for_status()
        except httpx.HTTPError as e:
            print(f"  openalex: lookup failed ({e}); continuing without abstracts")
            break
        for w in r.json().get("results", []):
            inv = w.get("abstract_inverted_index")
            doi = (w.get("doi") or "").lower().removeprefix("https://doi.org/")
            if inv and doi in by_doi:
                by_doi[doi].abstract = _rebuild(inv)
                filled += 1
    return filled
