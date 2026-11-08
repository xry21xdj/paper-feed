"""arXiv API: newest submissions in the configured categories that mention any topic keyword."""
from __future__ import annotations

import datetime as dt
import re
import time
import xml.etree.ElementTree as ET

import httpx

from feed.filter import all_keywords
from feed.models import Paper, clean

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
VENUES = ("NeurIPS", "ICML", "ICLR", "AAAI", "IJCAI", "KDD", "AAMAS", "ICAPS", "ACL", "EMNLP", "NAACL",
          "ITSC", "e-Energy", "CPAIOR", "WWW", "CDC", "ACC", "GECCO", "CIKM", "SIGSPATIAL", "ICCPS",
          "BuildSys", "AISTATS", "UAI", "COLM")
# "Accepted at ICLR 2026", "NeurIPS'25 camera-ready", ... but not workshop papers.
VENUE_RE = re.compile(r"\b(" + "|".join(re.escape(v) for v in VENUES) + r")\s*['’]?\s*((?:20)?\d\d)\b")


def venue_tag(comment: str) -> str:
    """Conference named in an arXiv comment, e.g. "ICLR 2026"; "" if none or a workshop."""
    if not comment or "workshop" in comment.lower():
        return ""
    m = VENUE_RE.search(comment)
    if not m:
        return ""
    year = m.group(2) if len(m.group(2)) == 4 else "20" + m.group(2)
    return f"{m.group(1)} {year}"


def _term(kw: str) -> str:
    kw = kw.replace('"', "")
    return f'abs:"{kw}"' if " " in kw or "-" in kw else f"abs:{kw}"


def fetch(cfg: dict, since: dt.date, client: httpx.Client) -> list[Paper]:
    cats = " OR ".join(f"cat:{c}" for c in cfg["arxiv"]["categories"])
    keywords = all_keywords(cfg)
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
            cat = e.find("x:primary_category", NS)
            venue = "arXiv " + (cat.get("term") if cat is not None else "")
            tag = venue_tag(" ".join(filter(None, [e.findtext("x:comment", "", NS),
                                                   e.findtext("x:journal_ref", "", NS)])))
            papers[arxiv_id] = Paper(
                id=f"arxiv:{arxiv_id}",
                title=clean(e.findtext("a:title", "", NS)),
                url=f"https://arxiv.org/abs/{arxiv_id}",
                venue=f"{venue} · {tag}" if tag else venue,
                publisher="arXiv",
                date=published,
                authors=[a.findtext("a:name", "", NS) for a in e.findall("a:author", NS)],
                abstract=clean(e.findtext("a:summary", "", NS)),
            )
    return list(papers.values())
