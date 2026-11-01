# paper-feed

A daily web page of new papers relevant to my research: electric-bus scheduling and charging, traffic
simulation and calibration, LLM agents for transport/OR, and transport-grid integration.

Every morning a GitHub Actions job:

1. fetches new papers from **arXiv** and from journals of **Elsevier, IEEE, INFORMS and Springer Nature**
   (via Crossref, with missing abstracts filled from OpenAlex);
2. drops papers already shown and applies a keyword + transport-anchor pre-filter;
3. asks **Claude Haiku** to score each candidate 0-10 against the research profile, with a one-line reason;
4. writes `data/daily/<date>.json` and rebuilds the static site in `docs/` (served by GitHub Pages).

## Tuning

Everything lives in [`config/profile.yaml`](config/profile.yaml): the research profile (the scoring rubric),
topic keywords, anchor terms, journal list (by ISSN) and the score threshold.

## Running locally

```sh
pip install -r requirements.txt
python -m feed.main --dry-run --days 7   # fetch + filter only, prints candidates
python -m feed.main --no-llm             # keyword scores, no API key needed
python -m feed.main                      # full run (needs ANTHROPIC_API_KEY)
python -m feed.main --build-only         # re-render docs/ after editing templates
```

## Setup on GitHub

- Secret `ANTHROPIC_API_KEY` (required). Optional: secret `OPENALEX_API_KEY` (free key, more abstract
  lookups per day), variable `CROSSREF_MAILTO` (Crossref "polite pool").
- Settings → Pages → Deploy from branch `main`, folder `/docs`.
- Actions → "Daily paper feed" → Run workflow for the first run (e.g. `days` = 7).

Cost: roughly 50-300 candidates a day on Claude Haiku 5.5, a few cents per day.
