"""arXiv API: newest submissions in the configured categories that mention any topic keyword."""
from __future__ import annotations

import datetime as dt
import time
import xml.etree.ElementTree as ET

import httpx

from feed.models import Paper, clean

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom"}


def _term(kw: str) -> str:
    kw = kw.replace('"', "")
    return f'abs:"{kw}"' if " " in kw or "-" in kw else f"abs:{kw}"


def fetch(cfg: dict, since: dt.date, client: httpx.Client) -> list[Paper]:
    cats = " OR ".join(f"cat:{c}" for c in cfg["arxiv"]["categories"])
    keywords = sorted({k for t in cfg["topics"].values() for k in t["keywords"]})
    # arXiv's query length is limited, so split the keywords into a few queries.
    chunks = [keywords[i:i + 15] for i in range(0, len(keywords), 15)]
    per_query = max(50, cfg["arxiv"]["max_results"] // len(chunks))

    papers: dict[str, Paper] = {}
    for n, chunk in enumerate(chunks):
        if n:
            time.sleep(3)  # arXiv asks for >= 3 s between calls
        query = f"({cats}) AND ({' OR '.join(_term(k) for k in chunk)})"
        params = {"search_query": query, "sortBy": "submittedDate", "sortOrder": "descending",
                  "max_results": per_query}
        r = client.get(API, params=params, timeout=60)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        for e in root.findall("a:entry", NS):
            published = e.findtext("a:published", "", NS)[:10]
            if not published or dt.date.fromisoformat(published) < since:
                continue
            abs_url = e.findtext("a:id", "", NS)
            arxiv_id = abs_url.rsplit("/abs/", 1)[-1].split("v")[0]
            papers[arxiv_id] = Paper(
                id=f"arxiv:{arxiv_id}",
                title=clean(e.findtext("a:title", "", NS)),
                url=f"https://arxiv.org/abs/{arxiv_id}",
                venue="arXiv " + (e.find("{http://arxiv.org/schemas/atom}primary_category").get("term")
                                  if e.find("{http://arxiv.org/schemas/atom}primary_category") is not None
                                  else ""),
                publisher="arXiv",
                date=published,
                authors=[a.findtext("a:name", "", NS) for a in e.findall("a:author", NS)],
                abstract=clean(e.findtext("a:summary", "", NS)),
            )
    return list(papers.values())
