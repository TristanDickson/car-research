# Architecture

The same shape as `etf-tool` and `bolthole`, scaled to a dataset of tens of cars and
hundreds of deals: **scrape → resolve → app**, with only the *app* layer shipped to the
browser. No Postgres, no worker, no server mode. The data is tiny, so it is committed
on `main` and GitHub Pages serves it.

```
providers (discover → fetch → parse)       pipeline/providers/*      Python, stdlib
   manual_seed     data/seed/*.json          cars, requirements, trim map, hand-captured offers
   carwow_paste    data/pastes/carwow/*.txt  Carwow offer pages copied out of a logged-in browser
   carwow_deals    carwow.co.uk (live)       best cash price per CAP derivative, Kia PCP-finance price, rep. example
   hyundai_offers  hyundai.com/uk (live)     Hyundai Finance national PCP example per model, with validity dates
   ncd             new-car-discount.com      broker all-in cash price per derivative
   leaseloco       leaseloco.com (live)      best personal lease per derivative/profile (ex-VAT → inc.)
   rrg             rrg-group.com (live)      dealer PCP example for the PV5 7-seat
        │  Bronze  artifacts            every fetched body, sha256-addressed, supersede chain
        │  Silver  source_rows          one row per parsed record, in the source's vocabulary
        │  Gold    cars                 canonical trims (hand-curated)
        │          trim_map             (site, trim-as-printed) → car_id; misses recorded as 'unmapped'
        │          offer_observations   one row per offer key per sighting (present / gone)
        ▼          requirements
SQLite  data/car-research.sqlite            gitignored: a dev-machine artifact
        │  ⇄ data/history/observations.jsonl  COMMITTED sighting log: every refresh appends, every
        │                                      run (CI, a fresh clone) replays it before scraping
        ▼  export_snapshot()                 pipeline/services/snapshot.py
JSON    web/public/data/{manifest,cars,offers,requirements,data}.json   COMMITTED on main
        │   offers = latest observation per key + finance maths + freshness (state, age, history)
        ▼  push to main → Actions → next build (output: export) → Pages
SPA     web/                                 Next.js 16 App Router, Tailwind 4, react-query, Dexie
        │  on load: fetch manifest → if generated_at changed, bulk-load JSON into IndexedDB
        ▼  pages query IndexedDB (public tables) + the user's shortlist (private table)
```

## Offers are observations

An offer is never edited in place. Each provider run records what it saw: one
`offer_observations` row per **offer key** per sighting, with `present = 0` when a check
found the offer gone. The offer key is stable per real-world offer (a Carwow deal id, a seed
id, later a dealer URL plus trim). The exporter derives, per key:

| Field | Meaning |
| --- | --- |
| `state` | `gone` if the latest sighting was a miss; `expired` if `valid_to` has passed or the source said so; otherwise the status the source implied (`live`, `lead`, `derived`, `illustrative`, `campaign`, `historical`) |
| `last_seen_at`, `age_days` | last positive sighting and its age at export time |
| `stale` | an active offer not seen for more than 14 days (`STALE_DAYS`) |
| `history` | every sighting with its price-bearing fields, so a price change is a diff, not an overwrite |

Only **current** offers (active state, not stale) feed a car's best-cash / best-PCP / best-PCH
summary. The SPA recomputes age and staleness from `last_seen_at` at view time, so an
un-refreshed deployment still greys out old offers. Re-running a provider over an unchanged
page is idempotent (same key, same observed time, same artifact).

## Trim map (the small resolution problem)

Every source names trims differently. A record that arrives with a `car_ref` (`{source, key}`)
is resolved through `trim_map`; the key is whatever is stable for that source: the CAP
derivative id on Carwow (`carwow-cap`), Hyundai's CAP code (`hyundai-cap`), or the derivative
text normalised by `parse.norm_key` (`ncd`, `leaseloco`, `rrg`: lower-case, `kwh` glued to its
number, parts joined by `|`). A miss leaves the record in Silver, records an `unmapped` row, and
counts on the run. `python -m pipeline trims` lists them (and fails CI); add the mapping to
`data/seed/trim_map.json` and re-run. Rows with `"status": "ignored"` are derivatives we have
looked at and chosen not to track (the 42kWh Ioniq 3, no-heat-pump Insters, 5-seat PV5s, AWD
Ioniq 5s): they resolve to nothing without counting as unmapped. Nothing is ever attached to a
guessed car.

## Backfill from the Wayback Machine

Each live provider has a second capability, `backfill`, built by
`providers/wayback.py::backfill_capability(base)`: discover asks the CDX index for
every 200 capture of the base capability's URLs since a date, thins them to one per
week and drops captures whose body digest matches the last one kept, and yields a
target per capture whose `observed_at` is the archive timestamp; fetch pulls the raw
page (`/web/<ts>id_/<url>`); parse is the base parser, which reads `observed_at` and
`original_url` off the target. The runner stores the archived body as a Bronze
artifact under the base provider, so a backfilled sighting is indistinguishable from a
live one apart from its date.

Gold's `_merge_sighting` makes out-of-order sightings safe: a sighting matching the
span before it extends that span; one matching the span after it moves that span's
start back; one bridging two matching spans merges them; a different price inside a
span splits the span at that point (the span was seen at its start and end, so those
become two rows). `refresh` skips `backfill`; `pipeline backfill` runs it, and
`.github/workflows/backfill.yml` runs that on a GitHub runner because archive.org
refuses connections from some cloud networks.

Coverage (probed 6 Oct 2026, with the archive partly offline): Carwow Kona and EV6
deals pages have 8–9 captures each since mid-2024, Hyundai's Ioniq 5 offer page 30,
New Car Discount's Kona and Ioniq 5 listings 3–4, the newer models (Ioniq 3, EV2, EV3,
PV5, Inster) 0–3, LeaseLoco and RRG none. Old captures of a page that has since been
redesigned parse to zero rows, which is harmless.

## Live scraping

`providers/http.py` is the one fetch path: a browser user agent, a per-host delay, two retries
on 429/5xx, and a `FetchError` the runner turns into a per-target failure (one dead page does
not sink a provider's run; the run records `errors` and the failing targets). Each live
provider is a `parse_page(text, …) -> rows` pure function with the real captured page in
`tests/fixtures/`, so a layout change fails `tests/test_providers.py` rather than writing
nonsense. Providers set `live=True`; `refresh --offline` skips them, which is what CI runs.

What each site gives, and the caveats carried into the offer rows:

- **Carwow deals pages** are server-rendered and public. Per derivative: RRP, Carwow's best
  cash price across its dealers (status `lead`, the named dealer needs the logged-in quotes
  page), and on Kia pages a separate *PCP Finance* price (the price if you take Kia's PCP, usually
  below cash: the row carries `pcp_finance_price` and the delta). One representative PCP example
  per model, matched to its derivative by RRP, status `illustrative`.
- **Hyundai UK offer pages** embed the complete PCP example as JSON (`data-js-options`): cash
  price, grant, OTR, deposit and contribution, APR and flat rate, GFV, interest, mileage, excess
  charge, and the order window in the T&Cs (`valid_from` / `valid_to`). Deposit is Hyundai's
  example (£3,500), not £0; the maths in the app normalises that.
- **New Car Discount** prints one all-in price per derivative, including the grant. The listing
  names the no-heat-pump and pack variants explicitly, which is how the trim map tells them apart.
- **LeaseLoco** ships deals in `__NEXT_DATA__` (`originalBestDealList`, or the first search
  page for models without a curated list). Prices are ex-VAT and are multiplied by 1.2; the key
  includes term, initial-months and mileage because the same car appears on several profiles.
- **RRG** is a plain-text representative example on a dealer page; the regex is pinned to the
  current wording.

Blocked or unavailable, and why they are not providers: Richmond Hyundai and Kia's used-car site
(Imperva, blocks headless Chromium too), cars2buy (Cloudflare), Arnold Clark (client-rendered),
EV Database (rate-limited), and Kia's own quote API (`kiaofferscalculator.co.uk`), which answers
"No quote available for parameters entered" for every parameter set, in the live widget as well.

## Carwow without an API

Carwow has no public API and blocks datacenter scraping, so Carwow offers come in as pasted
pages: copy the dealer-offer page text from the logged-in browser into
`data/pastes/carwow/<date>_<dealid>.txt` with a `# captured_at: <iso>` first line. The file is
the Bronze artifact; `carwow_paste` parses it (price, contribution, APR, GFV, mileage, the
car facts, the dealer) and reconciles the payment count against the page's own totals.
`tests/test_carwow_paste.py` pins the parser to the four real pages captured so far.

## Mapping to the reference repos

| Concern | etf-tool / bolthole | car-research |
| --- | --- | --- |
| Providers | `app/crawlers/*`, `Provider` of `Capability` records with discover/fetch/parse | `pipeline/providers/*`, same records, synchronous |
| Bronze | `artifacts` in Postgres, content-addressed, `superseded_by` | `artifacts` in SQLite, same columns |
| Silver | `source_*` tables per source | one generic `source_rows` table (`source`, `kind`, `source_key`, JSON `row`) |
| Gold | `funds`, `assets`, … | `cars`, `trim_map`, `offer_observations`, `requirements` (JSON payload + indexed columns) |
| Identity | bolthole's listing → property resolver | `trim_map`: a lookup table per source, with an unmapped queue |
| Export | `app.cli export-snapshot` → `services/snapshot.py`, `manifest.json` with `schema_version` | `python -m pipeline export-snapshot` → `pipeline/services/snapshot.py`, same manifest shape |
| Where data lives | squashed orphan `data` branch stitched in by the deploy workflow (100MB+) | committed on `main` under `web/public/data` (~60KB) |
| Static client | `lib/snapshot.ts` fetch + in-memory cache; Dexie for private data | `lib/snapshot.ts` fetch; `lib/db.ts` seeds **public** data into Dexie too and pages query it |
| Dual mode | `NEXT_PUBLIC_MODE=static` vs live FastAPI | static only |
| Deploy | `pages-deploy.yml`: Actions artifact, SPA 404 fallback, `.nojekyll` | same workflow, single checkout |
| CI | `frontend-ci.yml`, `pages-build-check.yml`, `backend-ci.yml` | `web-ci.yml`, `pipeline-ci.yml` (adds a snapshot-freshness check) |

## Snapshot contract (schema_version 2)

| File | Shape |
| --- | --- |
| `manifest.json` | `{schema_version, generated_at, counts:{cars,offers,observations,cash_benchmarks,unmapped_trims}, runs:[…]}` |
| `cars.json` | car records plus `requirement_check` `{passes, failures[], unknown[]}` and `deal_summary` (best current cash / PCP / PCH with the age of each) |
| `offers.json` | latest observation of each offer plus `metrics` (from `model/deal_math.py`) and `freshness` (state, stale, age, first/last seen, history) |
| `requirements.json` | the requirements document verbatim |
| `data.json` | providers, recent runs, unmapped trims, offer-state counts: the SPA's Data page |

`generated_at` can be pinned (`--generated-at`) so CI can rebuild the snapshot and diff it
against the committed one deterministically.

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

## Trends in the app

`web/src/lib/trends.ts` turns an offer's history into chart series: `offerSeries` joins
spans into a step line (a 'gone' breaks it), `dailyBest` takes the lowest covering span
per day with a current offer extended to today, `movement` reports the current run,
the first value and a windowed delta. `components/charts/LineChart.tsx` is a plain SVG
multi-line chart (2px lines, 8px end markers with a surface ring, hairline grid, legend
for two or more series, direct end-labels for up to four, crosshair tooltip reading
every series at the snapped date, arrow-key focus) and `Sparkline.tsx` the stat-tile
version. Colours are assigned by sorted offer id so a filter never repaints a line; the
palette was validated against the app's dark surface. Every chart has a table twin.

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

One-time repo settings: **Settings → Pages → Source = "GitHub Actions"** (until then the
deploy step fails with a 404), and the `github-pages` environment GitHub creates at that point
carries a deployment-branch rule naming the branch that was the default at the time. Changing
the default branch later does not update the rule. The workflow deploys from `main`, so add
`main` under Settings → Environments → github-pages → Deployment branches and tags. A run
rejected by that rule fails in two seconds with no runner and no logs.

`.github/workflows/scrape.yml` runs nightly (and on dispatch): `pipeline refresh` with the live
providers, commits `data/history`, `web/public/data` and `docs/deal-comparison.md` if anything
changed, then dispatches the Pages deploy (a push made with the workflow token does not trigger
other workflows by itself). `pipeline-ci.yml` runs `refresh --offline`: seed, pastes and the
replayed history, so the freshness diff is deterministic and needs no network.

If the snapshot ever grows past a few MB (per-listing price history, scraped used-car markets),
move it off `main` onto a squashed orphan `data` branch exactly as `etf-tool/scripts/publish-data.sh`
does, and add the second checkout step to the deploy workflow.

## Local development

```
make snapshot        # python -m pipeline refresh --out web/public/data   (live scrape)
make snapshot-offline  # same with --offline: seed + pastes + replayed history
make test            # python unittest + web lint/typecheck/vitest
make web-dev         # next dev on :3001, reads web/public/data
make web-build       # static export to web/out
python -m pipeline status | deal-table | run <provider> [--capability …] [--target …]
```

Python ≥ 3.11, stdlib only so far. Node 22.

## Adding a provider (scraper)

1. Save a real page into `tests/fixtures/` first and write `parse_page()` against it.
2. `pipeline/providers/<name>.py`: `discover` yields the targets (URL in `metadata`), `fetch`
   calls `http.fetch_url`, `parse` wraps `parse_page`; declare `Capability(kinds=("offer",))` and
   `Provider(live=True)`.
3. Register it in `pipeline/providers/__init__.py` (after `manual_seed`, which writes the cars
   and trim map everything else resolves against).
4. Emit `ParsedRecord(kind="offer", key=<offer key>, row=…)` with `offer_key`, `observed_at`,
   `present`, `finance_type`, `status`, `verification: "scraped"`, the price fields in the seed
   schema, and `car_ref: {source, key, label}` for the trim map to resolve.
5. `python -m pipeline run <name>`, then `python -m pipeline trims` to see what needs mapping or
   ignoring, then `make snapshot`. The deal maths, freshness and requirement checks apply
   automatically. Add a fixture test to `tests/test_providers.py`.

## Decisions

- **SQLite, not Postgres.** Single user, tiny data, no concurrent writers. Stdlib only.
- **Data committed on `main`.** ~60KB. The orphan-branch machinery is documented above for later.
- **Next.js static export, not Vite.** Mirrors the two most recent reference repos so the layout,
  data client and deploy workflow are familiar. No server mode is built.
- **No Tremor.** Plain Tailwind tables; fewer dependencies, no React 19 / Tailwind 4 friction.
- **Finance maths in Python at export, not in the browser.** One implementation, pinned by tests.
- **Public data in IndexedDB as well as private.** Matches the "dump it all into a local DB on load"
  pattern; filtering and sorting stay instant and the app works offline after first load.
