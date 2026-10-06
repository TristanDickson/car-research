# Architecture

The same shape as `etf-tool` and `bolthole`, scaled to a dataset of tens of cars and
hundreds of deals: **scrape → resolve → app**, with only the *app* layer shipped to the
browser. No Postgres, no worker, no server mode. The data is tiny, so it is committed
on `main` and GitHub Pages serves it.

```
providers (discover → fetch → parse)       pipeline/providers/*      Python, stdlib
        │  Bronze  artifacts     every fetched body, sha256-addressed, supersede chain
        │  Silver  source_rows   one row per parsed record, keyed to its artifact
        ▼  Gold    cars · deals · requirements   canonical rows (JSON payload + indexed cols)
SQLite  data/car-research.sqlite            gitignored: a dev-machine artifact
        │
        ▼  export_snapshot()                 pipeline/services/snapshot.py
JSON    web/public/data/{manifest,cars,deals,requirements}.json   COMMITTED on main
        │                                    finance maths precomputed here (model/deal_math.py)
        ▼  push to main → Actions → next build (output: export) → Pages
SPA     web/                                 Next.js 16 App Router, Tailwind 4, react-query, Dexie
        │  on load: fetch manifest → if generated_at changed, bulk-load JSON into IndexedDB
        ▼  pages query IndexedDB (public tables) + the user's shortlist (private table)
```

## Mapping to the reference repos

| Concern | etf-tool / bolthole | car-research |
| --- | --- | --- |
| Providers | `app/crawlers/*`, `Provider` of `Capability` records with discover/fetch/parse | `pipeline/providers/*`, same records, synchronous |
| Bronze | `artifacts` in Postgres, content-addressed, `superseded_by` | `artifacts` in SQLite, same columns |
| Silver | `source_*` tables per source | one generic `source_rows` table (`source`, `kind`, `source_key`, JSON `row`) |
| Gold | `funds`, `assets`, … | `cars`, `deals`, `requirements` (JSON payload + indexed columns) |
| Export | `app.cli export-snapshot` → `services/snapshot.py`, `manifest.json` with `schema_version` | `python -m pipeline export-snapshot` → `pipeline/services/snapshot.py`, same manifest shape |
| Where data lives | squashed orphan `data` branch stitched in by the deploy workflow (100MB+) | committed on `main` under `web/public/data` (~60KB) |
| Static client | `lib/snapshot.ts` fetch + in-memory cache; Dexie for private data | `lib/snapshot.ts` fetch; `lib/db.ts` seeds **public** data into Dexie too and pages query it |
| Dual mode | `NEXT_PUBLIC_MODE=static` vs live FastAPI | static only |
| Deploy | `pages-deploy.yml`: Actions artifact, SPA 404 fallback, `.nojekyll` | same workflow, single checkout |
| CI | `frontend-ci.yml`, `pages-build-check.yml`, `backend-ci.yml` | `web-ci.yml`, `pipeline-ci.yml` (adds a snapshot-freshness check) |

## Snapshot contract (schema_version 1)

| File | Shape |
| --- | --- |
| `manifest.json` | `{schema_version, generated_at, counts:{cars,deals,cash_benchmarks}, runs:[…]}` |
| `cars.json` | array of car records as captured, plus `requirement_check` `{passes, failures[], unknown[]}` and `deal_summary` `{best_cash_price, best_pcp_monthly, best_pch_effective_monthly, …}` |
| `deals.json` | array of deal records as captured, plus `metrics` from `model/deal_math.py` |
| `requirements.json` | the requirements document verbatim |

Bump `SCHEMA_VERSION` in `pipeline/services/snapshot.py` and `SUPPORTED_SCHEMA_VERSION` in
`web/src/lib/snapshot.ts` together on any incompatible change; the banner warns on skew.

Files are written with `sort_keys` and `indent=1` so git diffs of the data are readable. Every
commit of `web/public/data` is a dated market snapshot, which is the price history.

## Finance maths lives in the pipeline

`model/deal_math.py` normalises PCP, PCH and cash deals: solves missing monthlies from APR, credit
and GFV; back-solves the implied APR as a check on the stated one; computes paid-if-handed-back,
paid-if-bought, cost of credit, effective monthly, and, against the lowest cash price captured
for the same car, the acquisition penalty, funding premium and effective annual rate. It runs once
at export time and the results ride in `deals[].metrics`, so the browser has no finance code to
drift. Conventions: payments at months 1..n, balloon at n+1, APR as an effective annual rate.
`tests/test_deal_math.py` pins it to the real Carwow quotes.

## Browser-side database

`web/src/lib/db.ts` opens `CarResearchDB` (Dexie):

- **public** `cars`, `deals`, `meta` — cleared and bulk-loaded from the snapshot whenever
  `manifest.generated_at` differs from the stored one. Seeding is memoised per session; a reload
  re-checks only the manifest.
- **private** `shortlist` — the user's picks. Never leaves the browser.

Pages use react-query hooks (`lib/hooks.ts`) over Dexie queries. The snapshot banner shows the
loaded generation and can re-check Pages for a newer one.

## Deploy

`.github/workflows/pages-deploy.yml` runs on push to `main`: `npm ci`, `next build` with
`NEXT_PUBLIC_BASE_PATH=/car-research`, copy `index.html` → `404.html` (SPA fallback for deep
links like `/cars/view?id=…`), `.nojekyll`, `upload-pages-artifact`, `deploy-pages`.

One-time repo setting: **Settings → Pages → Source = "GitHub Actions"**. Until then the deploy
step fails.

If the snapshot ever grows past a few MB (per-listing price history, scraped used-car markets),
move it off `main` onto a squashed orphan `data` branch exactly as `etf-tool/scripts/publish-data.sh`
does, and add the second checkout step to the deploy workflow.

## Local development

```
make snapshot        # python -m pipeline refresh --out web/public/data
make test            # python unittest + web lint/typecheck/vitest
make web-dev         # next dev on :3001, reads web/public/data
make web-build       # static export to web/out
python -m pipeline status | deal-table | run <provider> [--capability …] [--target …]
```

Python ≥ 3.11, stdlib only so far. Node 22.

## Adding a provider (scraper)

1. `pipeline/providers/<name>.py`: write `discover`, `fetch`, `parse`; wrap fetch with delay /
   retry middleware when it exists; declare `Capability(kinds=…)` and `Provider`.
2. Register it in `pipeline/providers/__init__.py`.
3. Emit `ParsedRecord(kind="deal" | "car", key=<stable id>, row=<dict in the seed schema>)`. A deal
   must reference an existing `car_id`; if the scraper discovers new trims it must emit the car
   too, in the same run.
4. `python -m pipeline run <name>` then `make snapshot`. The deal maths and requirement checks
   apply automatically.

Candidate first providers, in the order they pay off: Carwow dealer-offer pages (full PCP
representative examples), Cars2buy derivative price lists (cash benchmarks), manufacturer offer
pages (campaign terms), LeaseLoco (PCH).

## Decisions

- **SQLite, not Postgres.** Single user, tiny data, no concurrent writers. Stdlib only.
- **Data committed on `main`.** ~60KB. The orphan-branch machinery is documented above for later.
- **Next.js static export, not Vite.** Mirrors the two most recent reference repos so the layout,
  data client and deploy workflow are familiar. No server mode is built.
- **No Tremor.** Plain Tailwind tables; fewer dependencies, no React 19 / Tailwind 4 friction.
- **Finance maths in Python at export, not in the browser.** One implementation, pinned by tests.
- **Public data in IndexedDB as well as private.** Matches the "dump it all into a local DB on load"
  pattern; filtering and sorting stay instant and the app works offline after first load.
