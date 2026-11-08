"""Accepted-paper lists that NeurIPS, ICML and ICLR publish on their conference websites.

The lists carry titles and authors but no abstracts, so these papers are screened and scored on the
title. Each list is fetched whole every day; papers shown before are dropped by the seen-check, so a
conference's papers appear once, on the day its list goes online.
"""
from __future__ import annotations

import datetime as dt

import httpx

from feed.models import Paper, clean


def fetch(pl: dict, today: dt.date, client: httpx.Client) -> list[Paper]:
    # This year's list, plus last year's early in the year (it may only just be complete).
    years = ([today.year - 1] if today.month <= 3 else []) + [today.year]
    out = []
    for year in years:
        r = client.get(pl["url"].format(year=year), timeout=120)
        if r.status_code == 404:  # not published yet
            continue
        r.raise_for_status()
        for x in r.json().get("results", []):
            title = clean(x.get("name") or "")
            if not title:
                continue
            url = x.get("paper_url") or ""
            if not url.startswith("http"):
                url = str(r.url.copy_with(path=x.get("virtualsite_url") or "/", query=None))
            out.append(Paper(
                id=f"{pl['name'].lower()}:{year}:{x['uid']}",
                title=title,
                url=url,
                venue=f"{pl['name']} {year}" + (" (oral)" if x.get("eventtype") == "Oral" else ""),
                publisher="Conference",
                date=today.isoformat(),
                authors=[a.get("fullname", "") for a in x.get("authors") or []],
            ))
    return out
