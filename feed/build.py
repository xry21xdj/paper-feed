"""Render docs/ (GitHub Pages) from data/daily/*.json."""
from __future__ import annotations

import datetime as dt
import json
from email.utils import format_datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

PUBLISHER_KEYS = {"arXiv": "arxiv", "Elsevier": "elsevier", "IEEE": "ieee", "INFORMS": "informs",
                  "Springer Nature": "springer", "Conference": "conf"}


def _authors(names: list[str]) -> str:
    return ", ".join(names[:4]) + (" et al." if len(names) > 4 else "")


def _load_days(root: Path) -> list[dict]:
    files = sorted((root / "data" / "daily").glob("*.json"), reverse=True)
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def build_site(cfg: dict, root: Path) -> None:
    docs = root / "docs"
    (docs / "archive").mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                      autoescape=select_autoescape(["html", "xml"]), trim_blocks=True, lstrip_blocks=True)
    env.filters["authors"] = _authors
    env.filters["pubkey"] = lambda p: PUBLISHER_KEYS.get(p, "other")
    page = env.get_template("page.html")

    min_score = cfg["scoring"]["min_score"]
    days = _load_days(root)
    for d in days:
        d["shown"] = [p for p in d["papers"] if (p.get("score") or 0) >= min_score]
    archive = [{"date": d["date"], "n": len(d["shown"])} for d in days]
    topics = {k: t["label"] for k, t in cfg["topics"].items()}
    built = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    for i, d in enumerate(days):
        ctx = dict(site=cfg["site"], day=d, topics=topics, archive=archive, min_score=min_score,
                   built=built, is_latest=(i == 0))
        (docs / "archive" / f"{d['date']}.html").write_text(page.render(ctx, prefix="../"), encoding="utf-8")
        if i == 0:
            (docs / "index.html").write_text(page.render(ctx, prefix=""), encoding="utf-8")
    if not days:
        (docs / "index.html").write_text(page.render(
            site=cfg["site"], day=None, topics=topics, archive=[], min_score=min_score, built=built,
            is_latest=True, prefix=""), encoding="utf-8")

    items = [dict(p, day=d["date"]) for d in days[:7] for p in d["shown"]]
    for it in items:
        it["rfc822"] = format_datetime(dt.datetime.fromisoformat(it["day"]).replace(tzinfo=dt.timezone.utc))
    (docs / "feed.xml").write_text(env.get_template("feed.xml").render(site=cfg["site"], items=items, topics=topics),
                                   encoding="utf-8")
    (docs / ".nojekyll").write_text("")
    print(f"Built site: {len(days)} day(s), latest has {len(days[0]['shown']) if days else 0} papers shown")
