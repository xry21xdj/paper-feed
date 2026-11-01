"""Daily run: fetch -> dedupe -> keyword filter -> Claude scoring -> save -> build site.

    python -m feed.main              # normal daily run
    python -m feed.main --dry-run    # fetch and filter only; print counts, write nothing
    python -m feed.main --days 7     # wider fetch window (first run, catching up)
    python -m feed.main --no-llm     # keyword scores only
    python -m feed.main --build-only # re-render docs/ from data/
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import yaml

from feed import build, score
from feed.filter import KeywordFilter
from feed.models import Paper
from feed.sources import arxiv, crossref, openalex

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SEEN = DATA / "seen.json"
TZ = ZoneInfo("Australia/Sydney")
SEEN_KEEP_DAYS = 90


def load_cfg() -> dict:
    return yaml.safe_load((ROOT / "config" / "profile.yaml").read_text(encoding="utf-8"))


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())[:120]


def fetch_all(cfg: dict, since: dt.date) -> tuple[list[tuple[Paper, dict]], dict[str, int]]:
    """Returns (paper, journal config) pairs and per-source counts."""
    out: list[tuple[Paper, dict]] = []
    counts: dict[str, int] = {}
    headers = {"User-Agent": "paper-feed/1.0 (personal research feed)"}
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        try:
            got = arxiv.fetch(cfg, since, client)
            out += [(p, {}) for p in got]
            counts["arXiv"] = len(got)
        except (httpx.HTTPError, ValueError) as e:
            print(f"  arXiv failed: {e}")
            counts["arXiv"] = -1
        for j in cfg["journals"]:
            try:
                got = crossref.fetch_journal(j, since, client)
                out += [(p, j) for p in got]
                counts[j["name"]] = len(got)
            except (httpx.HTTPError, ValueError, KeyError) as e:
                print(f"  {j['name']} failed: {e}")
                counts[j["name"]] = -1
        filled = openalex.add_abstracts([p for p, _ in out], client)
        print(f"  openalex: filled {filled} missing abstracts")
    return out, counts


def run(args: argparse.Namespace) -> None:
    cfg = load_cfg()
    today = dt.datetime.now(TZ).date()
    since = today - dt.timedelta(days=args.days or cfg["fetch"]["days_back"])
    seen: dict[str, str] = json.loads(SEEN.read_text()) if SEEN.exists() else {}

    print(f"Fetching papers since {since} ...")
    fetched, counts = fetch_all(cfg, since)
    for name, n in counts.items():
        print(f"  {name:<48} {'FAILED' if n < 0 else n}")

    # Dedupe: by id, against earlier days, and journal versions of arXiv preprints (by title).
    kf = KeywordFilter(cfg)
    candidates: dict[str, Paper] = {}
    titles: set[str] = set()
    for p, journal in sorted(fetched, key=lambda x: x[0].publisher == "arXiv"):  # journals first
        nt = _norm_title(p.title)
        if p.id in seen or p.id in candidates or nt in titles:
            continue
        if kf.keep(p, gated=bool(journal.get("gated")), anchored=bool(journal.get("anchor"))):
            candidates[p.id] = p
            titles.add(nt)
    cands = sorted(candidates.values(), key=lambda p: -p.keyword_hits)[: cfg["fetch"]["max_candidates"]]
    print(f"{len(fetched)} fetched, {len(cands)} new candidates after keyword filter")

    if args.dry_run:
        for p in cands[:40]:
            print(f"  [{p.keyword_hits}] {','.join(p.topics):<14} {p.venue[:28]:<28} {p.title[:90]}")
        return

    if args.no_llm:
        score.keyword_scores(cands, cfg)
    else:
        score.llm_scores(cands, cfg)

    day_file = DATA / "daily" / f"{today}.json"
    day_file.parent.mkdir(parents=True, exist_ok=True)
    previous = [Paper.from_dict(d) for d in json.loads(day_file.read_text(encoding="utf-8"))["papers"]] \
        if day_file.exists() else []
    papers = {p.id: p for p in previous + cands}
    ordered = sorted(papers.values(), key=lambda p: (-(p.score or 0), p.publisher == "arXiv", p.title))
    day_file.write_text(json.dumps({
        "date": today.isoformat(),
        "fetched": len(fetched),
        "sources": counts,
        "papers": [p.to_dict() for p in ordered],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    for p in cands:
        seen[p.id] = today.isoformat()
    cutoff = (today - dt.timedelta(days=SEEN_KEEP_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    SEEN.write_text(json.dumps(seen, indent=0, sort_keys=True), encoding="utf-8")

    shown = sum(1 for p in ordered if (p.score or 0) >= cfg["scoring"]["min_score"])
    print(f"Saved {day_file.name}: {len(ordered)} scored, {shown} shown (score >= {cfg['scoring']['min_score']})")
    build.build_site(cfg, ROOT)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--build-only", action="store_true")
    args = ap.parse_args()
    if args.build_only:
        build.build_site(load_cfg(), ROOT)
    else:
        run(args)


if __name__ == "__main__":
    main()
