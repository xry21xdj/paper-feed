"""Journal papers via Crossref (by ISSN and the date the record was created).

Crossref is free and indexes new articles within a day or two, but IEEE and Elsevier deposit no
abstracts there, so `openalex.add_abstracts` fills the gaps afterwards where it can.
"""
from __future__ import annotations

import datetime as dt
import os

import httpx

from feed.models import Paper, clean

API = "https://api.crossref.org/journals/{issn}/works"
SKIP_TYPES = {"journal-issue", "component"}
SKIP_TITLES = ("editorial board", "erratum", "corrigendum", "correction to", "retraction",
               "table of contents", "front cover", "information for authors", "ieee transactions on")


def _date(item: dict) -> str:
    # Online date if deposited, else when the record was created; print/issue dates are often months ahead.
    for key in ("published-online", "created"):
        parts = item.get(key, {}).get("date-parts", [[None]])[0]
        if parts and parts[0]:
            y, m, d = (parts + [1, 1])[:3]
            return f"{y:04d}-{m:02d}-{d:02d}"
    return ""


def fetch_journal(journal: dict, since: dt.date, client: httpx.Client) -> list[Paper]:
    params = {"filter": f"from-created-date:{since.isoformat()},type:journal-article",
              "rows": 200, "select": "DOI,title,author,abstract,created,published-online,"
                                      "published-print,issued,URL,type"}
    mailto = os.environ.get("CROSSREF_MAILTO")
    if mailto:
        params["mailto"] = mailto
    r = client.get(API.format(issn=journal["issn"]), params=params, timeout=60)
    r.raise_for_status()
    out = []
    for it in r.json()["message"]["items"]:
        title = clean((it.get("title") or [""])[0])
        if not title or it.get("type") in SKIP_TYPES or title.lower().startswith(SKIP_TITLES):
            continue
        doi = it["DOI"].lower()
        out.append(Paper(
            id=f"doi:{doi}",
            title=title,
            url=f"https://doi.org/{doi}",
            venue=journal["name"],
            publisher=journal["publisher"],
            date=_date(it),
            authors=[" ".join(filter(None, [a.get("given"), a.get("family")])) for a in it.get("author", [])],
            abstract=clean(it.get("abstract")),
        ))
    return out
