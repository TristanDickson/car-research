# car-research: notes for an agent

A household's EV decision tool: a Python pipeline scrapes UK car prices and specs into SQLite,
commits the history, and exports a JSON snapshot that a static Next.js app (GitHub Pages) loads
into IndexedDB. The decision is due before the current car's PCP ends on 10 Dec 2026.

Read first: `README.md` (why, sources, how to work on it, next steps, context log, newest
first), then `docs/ARCHITECTURE.md` (layers, snapshot contract, the claim store, the app).
What the household needs from a car: `docs/requirements.md`; deal rules: `docs/research-notes.md`.

## Commands

```
make snapshot-offline   # rebuild the DB from data/history and write web/public/data (~15 s, no network)
make test               # python unittest + web lint, typecheck, vitest
make web-dev            # http://localhost:3001
python3 -m pipeline run <provider>       # one live provider into the local DB
python3 -m pipeline reparse --only <p>   # re-run parsers over stored pages, no network
python3 -m pipeline trims                # broker derivatives that resolved to no car
```

Python ≥ 3.11, standard library only. Node 22. `hyundai_specs` needs `pdftotext` or `pypdf`.

## Rules

- `data/history/*.jsonl` and `web/public/data/*.json` are generated. Never edit them by hand:
  change code or `data/seed/`, run `make snapshot-offline`, and commit code, history and
  snapshot together. `pipeline-ci` rebuilds the snapshot from the committed history and fails
  if the committed one differs, so a snapshot must be exactly what the history reproduces.
- After an offline refresh, discard the `last_seen_at` churn in
  `data/history/resolutions.jsonl` (`git checkout -- data/history/resolutions.jsonl`) unless the
  change was meant to touch resolutions.
- Facts about a car are claims (`pipeline/services/claims.py`), resolved at export from what
  the history holds. Never write a fact onto a car record as a side effect of a live run:
  nothing in the history carries car records, so a replay would not reproduce it.
- Every scraper has a real captured page in `tests/fixtures/` and a test against it. A layout
  change is fixed against a fresh fixture, not by guessing.
- A new car field: add it to `NUMBERS` (and the source that says it) in `claims.py`, to
  `SnapshotCar` in `web/src/lib/types.ts`, and one line in `web/src/lib/fields.ts`, which
  makes it a Cars-table column, a search bound and a car-page row. A new equipment flag goes
  in `pipeline/services/features.py` and appears in the app by itself.
- A new provider: a module in `pipeline/providers/`, registered in `providers/__init__.py`
  (order matters), with a fixture and a test. If it reads many pages, give it a per-run cap or
  a freshness rotation (see `evdb_cars`, `carwow_options`): the nightly job has 180 minutes.
- Pushing to `main` deploys the site. The nightly scrape (`.github/workflows/scrape.yml`,
  03:17 UTC, ~90 minutes) commits data to `main`; it copes with `main` moving under it.
- Done means: Python tests and web lint/typecheck/vitest pass locally, and `pipeline-ci`,
  `web-ci` and the Pages deploy are green on the pushed commit. Wait for `pipeline-ci`; it is
  the check that catches a snapshot the history does not reproduce.

## The owner's preferences

- Keep it simple. Saved searches replaced a requirements editor, stars and a shortlist
  because those were concepts that did little; propose before adding a new concept.
- Be exact about coverage: say how many cars have a field, not that it is "comprehensive".
- Audi, BMW, Mercedes and Skoda maker spec tables are deferred until one of their cars is
  shortlisted.

## Known limits

- EV Database rate-limits hard outside GitHub's runners; its car pages come from the nightly.
- Hyundai UK has no spec page readable without a browser; `hyundai_specs` reads the PDF
  guides and `hyundai_configurator` the configurator's GraphQL endpoint.
- The Kia Finance quote API answers "No quote available"; Kia finance examples are captured
  by hand.
