"""OpenAlex: conference papers, and missing abstracts for journal papers (looked up by DOI).

Both work on the free tier; an `OPENALEX_API_KEY` (free) gives the run its own daily budget instead
of sharing one with everyone on the same IP address.
"""
from __future__ import annotations

import datetime as dt
import os
import time

import httpx

from feed.models import Paper, clean

API = "https://api.openalex.org/works"
MAX_PAGES = 10


def _rebuild(inv: dict[str, list[int]]) -> str:
    words = sorted((pos, w) for w, positions in inv.items() for pos in positions)
    return " ".join(w for _, w in words)


def _params(**kw) -> dict:
    if os.environ.get("OPENALEX_API_KEY"):
        kw["api_key"] = os.environ["OPENALEX_API_KEY"]
    return kw


def _or(terms: list[str]) -> str:
    return " OR ".join(f'"{t}"' if " " in t or "-" in t else t for t in terms)


def _searches(cfg: dict) -> list[str]:
    """Title/abstract searches mirroring the keyword filter: topic keyword + transport anchor, topic
    keyword + that topic's own anchors, or a free keyword alone."""
    topics = cfg["topics"].values()
    out = [f"({_or(sorted({k for t in topics for k in t['keywords']}))}) AND ({_or(cfg['anchor_keywords'])})"]
    out += [f"({_or(t['keywords'])}) AND ({_or(t['anchors'])})" for t in topics if t.get("anchors")]
    free = sorted({k for t in topics for k in t.get("free_keywords", [])})
    if free:
        out.append(_or(free))
    return out


def _get(client: httpx.Client, params: dict) -> dict:
    # Long boolean searches are throttled; wait and retry when OpenAlex says so.
    for attempt in range(4):
        r = client.get(API, params=params, timeout=60)
        if r.status_code != 429 or attempt == 3:
            r.raise_for_status()
            return r.json()
        time.sleep(min(60, int(r.headers.get("Retry-After") or 10 * (attempt + 1))))
    raise AssertionError("unreachable")


def fetch_conferences(cfg: dict, today: dt.date, client: httpx.Client) -> dict[str, list[Paper]]:
    """Papers from the configured conferences (this year and next) whose title or abstract matches the
    topic keywords (see `_searches`). Papers shown before are dropped later by the seen-check, so what
    is new each day is whatever OpenAlex indexed since the last run."""
    confs = {c["openalex"]: c for c in cfg.get("conferences", [])}
    if not confs:
        return {}
    # Last year's proceedings only early in the year; next year's (AAAI-27 etc.) can appear from autumn.
    years = ([today.year - 1] if today.month <= 3 else []) + [today.year, today.year + 1]
    out: dict[str, dict[str, Paper]] = {c["name"]: {} for c in confs.values()}
    for n, search in enumerate(_searches(cfg)):
        filt = (f"primary_location.source.id:{'|'.join(confs)},"
                f"publication_year:{'|'.join(str(y) for y in years)},"
                f"title_and_abstract.search:{search}")
        # Plain page numbers: cursor paging needs an API key.
        for page in range(1, MAX_PAGES + 1):
            if n or page > 1:
                time.sleep(2)
            try:
                data = _get(client, _params(
                    filter=filt, page=page, **{"per-page": 200},
                    select="doi,id,title,publication_date,primary_location,authorships,abstract_inverted_index"))
            except httpx.HTTPError as e:  # keep what the other searches found
                print(f"  openalex: conference search {n + 1} failed ({str(e)[:80]})")
                break
            for w in data["results"]:
                src = ((w.get("primary_location") or {}).get("source") or {}).get("id", "").rsplit("/", 1)[-1]
                conf = confs.get(src)
                if conf is None or not w.get("title"):
                    continue
                doi = (w.get("doi") or "").lower().removeprefix("https://doi.org/")
                date = w.get("publication_date") or ""
                pid = f"doi:{doi}" if doi else f"openalex:{w['id'].rsplit('/', 1)[-1]}"
                out[conf["name"]][pid] = Paper(
                    id=pid,
                    title=clean(w["title"]),
                    url=f"https://doi.org/{doi}" if doi else (w["primary_location"].get("landing_page_url") or w["id"]),
                    venue=f"{conf['name']} {date[:4]}".strip(),
                    publisher="Conference",
                    date=date,
                    authors=[a["author"]["display_name"] for a in w.get("authorships", [])],
                    abstract=_rebuild(w["abstract_inverted_index"]) if w.get("abstract_inverted_index") else "",
                )
            if page * 200 >= data["meta"]["count"]:
                break
    return {name: list(papers.values()) for name, papers in out.items()}


def add_abstracts(papers: list[Paper], client: httpx.Client) -> int:
    missing = [p for p in papers if not p.abstract and p.id.startswith("doi:")]
    by_doi = {p.id[4:]: p for p in missing}
    filled = 0
    dois = list(by_doi)
    for i in range(0, len(dois), 50):
        chunk = dois[i:i + 50]
        params = _params(filter="doi:" + "|".join(chunk), select="doi,abstract_inverted_index", **{"per-page": 50})
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
