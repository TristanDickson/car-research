# The rebuild: raws first, matching re-derived

Agreed with the owner on 10 Oct 2026; built and switched over the same evening (status below). It comes before any new source. The pipeline as built does not follow the owner's design; this document
says how it differs, what it should become, and in what order to get there.

The template is the owner's other project, **bolthole** (`TristanDickson/bolthole`): read
its `docs/RESOLVER.md`, `docs/DATA_MODEL.md` and `docs/ACQUISITION.md` before starting.

## Status (10 Oct 2026, evening): built and switched over

Built on the branch `rebuild-raw-store` and merged into `main` (PR #1) the same evening. The plan
was two nights beside the GitHub scrape first; the owner said "we dont need to be so cautious.
Nobody is using this right now and we built it in a couple of days", so it merged at once. The
first snapshot from the new build was pushed from the raws already held; the laptop's job now
runs `main` at 03:17 and pushes.

- **The raw store** (`pipeline/raw.py`) at `D:\car-research-raw` on the owner's laptop
  (`CAR_RESEARCH_RAW`, set for the user). Asked where it should live, the owner answered "path
  is fine, go". D: is the second partition of the laptop's internal NVMe drive (317 GB free); C:
  had 19 GB free. Every fetch is kept: the body gzipped and named by its sha256, an append-only
  index line per fetch, a failed response too when the site answered, and each response a
  combined fetch was made of.
- **The migration.** All 60 committed versions of `data/history/*.jsonl` (6 to 10 Oct) are in
  the store as source `legacy`, byte-identical to git; `raw-migrate` adds new ones and nothing
  twice. They are read with the matching stripped (`pipeline/legacy.py`).
- **The build** (`pipeline/build.py`), from scratch every run, as in "The target" below. The
  car creation during ingestion, the history export and replay, and the 10 Oct stopgap are
  deleted, as listed under "What the rebuild deletes".
- **The scraper** keeps raws and nothing else; **the laptop's nightly job**
  (`scripts/nightly.ps1`), registered with Task Scheduler for 03:17 daily: it scrapes, builds,
  and pushes the snapshot to `main` (without `-Push` it would only log a comparison with main).
- **CI** (`pipeline-ci`): unit tests, which build from a raw store of the captured fixtures, and
  a build over the owner's files with an empty store. The GitHub scrape and backfill workflows
  and `data/history` are gone.

How the new build compares with the snapshot committed on 10 Oct (built from the same history,
`scripts/compare_snapshots.py`):

| | Offers | What happened |
| --- | --- | --- |
| identical spans | 2,818 | |
| the same prices and dates in fewer spans | 224 | the old merge left two touching spans at one price; the build folds them into one |
| on a different car | 30 | 13 were stale: the old pipeline's own current match already pointed elsewhere, but the history replayed the first match. 8 follow the twins' current prices (below). 5 broker names had no current match at all and now get one by the rules. 2 pick, between twins at one price, the one New Car Discount's RRP pinned. |
| no car now | 177 | in every one the old pipeline's own current rule also gives no car (165 are a pack named against three or more prices, a conflict); they kept a car only because the history replayed a match made before the twins were listed |

Every one of the 1,978 car ids is the same. About 490 derivatives that only a deals page prints
now carry the latest line that page printed, where the old pipeline kept the first one it ever
read (often an archived 2025 price list): their RRP and price-list date change, and with the
date, which EV Database variant describes them (about 30 cars). That moves the heat pump on 16
BMW iX1 derivatives from "option" (EV Database's 2023 to 2025 entry) to "none" (Carwow's
standard list, the 2026 entry saying nothing), and on two XPeng G6s from "option" to "standard".
Used listings that name a derivative the owner entered now sit on the owner's car rather than on
a hidden twin.

The first full run from the laptop (10 Oct, 18:11 to 19:35 local, 84 minutes): 1,341 fetches,
71 MB in the store with the legacy history. EV Database answered 55 car pages with one failure and
no throttling. Against main's snapshot, every difference is tonight's sightings: 1,317 offers' last
span now runs to tonight and 140 have a new price tonight; no offer's earlier history changed. The
run found three problems, fixed the same evening:

- Carwow returns its used stock in a different order on every request (tested: page 1 twice gives
  different cars, and no sort parameter steadies it), so paging samples the stock. The old fetch
  stopped at the first page that brought nothing new, which on the laptop listed 1,142 Carwow cars
  where GitHub's run that morning listed 1,776, and every car missing from the sample was marked
  sold. The fetch now pages until there is no next page (or three pages bring nothing new), and a
  Carwow used car counts as gone only after a week unseen. cinch and Motorpoint page through their
  APIs and keep the old rule.
- Hyundai's spec guides (PDFs) need poppler's `pdftotext`, which GitHub's runner had. The laptop
  had only xpdf's (from Git for Windows), which failed, and pypdf, which reads the tables
  differently (it loses the Vision Roof from the Ioniq 5 Ultimate's Zen Pack and so marks the roof
  standard). Poppler 26.09 is now in `%USERPROFILE%\tools` and `CAR_RESEARCH_PDFTOTEXT` points at
  it; with it the laptop reads all 20 Hyundai rows exactly as GitHub did. The reader's version is
  part of the parse cache's key.
- The comparison above is from this build; the review fixes below changed none of its numbers.

Next: check the first nightly push (11 Oct) in `D:\car-research-raw\logs\nightly\<date>.log`.

Open, for the owner: whether D: is backed up (Windows File History is not set up and no backup
program is installed in Program Files; a backup run from elsewhere would not show there; a weekly
copy to OneDrive or an external drive would do), and whether the laptop is on overnight (the job wakes it, and runs as soon as it can after a missed start, but only while
the owner is logged on).

Known limits of what is built:

- The owner's decisions are the 219 rows of `data/seed/trim_map.json`, read as before: a row with
  a car is "this is that car"; an "ignored" row does not stop the rules matching the record to a
  derivative (it marked "not one of the hand-curated cars" before every EV was covered). There
  are no merge or reject pairs yet; none were needed.
- A raw is what the parser reads, so a parser's inputs that came from elsewhere are kept with the
  fetch: cinch's and Motorpoint's targets carry the catalogue models they file listings under.
- An independent review found that concurrent writers could lose index lines, that a body
  written just before a crash could stay broken, that a combined fetch failing partway dropped the
  pages it had, and two places where reading order decided a result. All are fixed and tested.
- The legacy rows from before the rebuild cannot be re-parsed (no page was kept); only their
  matching is re-derived. Re-running the Wayback backfill on the laptop would fetch the archived
  pages as raws.

## The principle

**Only the raws are permanent.** Every response fetched from a site is kept, exactly as it
came, forever. Everything else (the parsed records, which records are the same car, the
facts about each car, the snapshot the app reads) is derived from the raws by a process
that can be re-run from scratch at any time, so a better parser or a better matcher fixes
the past as well as the future. The only other durable thing is the owner's own decisions
("this listing is that car", "these two are different", "ignore this one").

## How the current pipeline differs

| | The design | What exists today |
| --- | --- | --- |
| Raw pages | kept forever | fetched into a throwaway SQLite database (on the GitHub runner, every night) and lost when it ends |
| What is committed | nothing but code and the owner's decisions | `data/history/*.jsonl` (~30 MB): already-parsed records **with the car each was matched to**, plus the match decisions themselves (`resolutions.jsonl`) |
| Matching | a separate step over all records, re-run from scratch every time | done while each page is read (`runner._ingest` → `gold.resolve_car`), which also **creates car records as a side effect** (`gold.ensure_auto_car`, `gold.upsert_derivative`) |
| A rebuild | re-derives every match | replays the stored matches, so old mistakes come back; a better matcher only helps pages read from now on |
| The owner's own entries | one more source | special "hand-curated" cars that other records are matched onto |

The duplicate-car bug of 10 Oct (17 cars listed twice) came straight from this: matching
created a car record for a derivative the owner had already entered, and nothing later
re-derived it. The fix shipped that day (`gold.curated_owner`, `gold.prune_auto_cars`,
`snapshot.load_cars`) is a stopgap that the rebuild removes.

## Glossary: the code's words, in plain English

The owner does not use these terms; never use one with the owner without saying what it means.

| In the code | What it is |
| --- | --- |
| hand-curated car | one of the 19 cars typed into `data/seed/cars.json` on 6 Oct from the owner's ChatGPT research (the shortlist, with prices and notes) |
| generated car | a car record the pipeline creates for each Carwow derivative it reads |
| stub car | a generated car made from a single line (a deals page, Carwow's derivative list) with no spec page behind it |
| CAP id, derivative | CAP HPI's id for one exact version of a car: model, trim, battery, motor, packs, price list. Carwow, cinch and Motorpoint all print it; it is the natural key |
| trim map | which source's label is which car: the owner's 219 rows in `data/seed/trim_map.json` (56 "this is that car", 163 "ignore") plus the pipeline's own guesses stored in the database |
| sighting, observation | one price one source showed on one date |
| claims | what each source says about a field (width, heat pump...) and at what level (this derivative, this trim, this model); resolved to one value per field when the snapshot is written |

## The target

```
raw store (permanent, on the owner's laptop)
   every fetched response, content-addressed, with an index of what was fetched when
        │  parse (re-runnable; a parser fix re-parses everything)
source records: what each page said, source-shaped, no car ids
        │  resolve (pure, from scratch every run; reads the owner's decisions)
derivatives (keyed by CAP id) + which records belong to each, with method and evidence
        │  facts (the claim store, as today) and prices
snapshot (web/public/data, committed; the app is unchanged)
```

1. **Raw store.** A folder outside git on the laptop (bolthole uses
   `ARTIFACT_ROOT=/data/raw` with a filesystem backend; do the same, e.g.
   `CAR_RESEARCH_RAW=~/car-research-raw`). One gzipped file per distinct body, named by its
   sha256, plus an index of every fetch: source, capability, target, URL, fetched_at,
   status, sha256, content type. An unchanged page is stored once. The current `artifacts`
   table already has these columns; it is the store, minus being thrown away.
   Size: about 300 MB of pages a night (~80 MB gzipped) before de-duplication, so roughly
   30 GB a year at the current scope; the laptop's backup should cover the folder.
2. **Parse.** Each provider's `parse` already turns a body into source-shaped rows; keep
   that, drop everything after it that writes cars. Cache parsed records by
   (sha256, parser version) so a rebuild only re-parses what changed.
3. **Resolve.** One pure function over all source records:
   - a record that names a CAP id belongs to that derivative;
   - a record with only text (LeaseLoco, NCD, broker names) is matched to a derivative by
     the rules in `services/resolve.py` and `services/match.py` (kW, kWh, trim words, RRP,
     brackets), recording method and evidence;
   - the owner's decisions override: the 56 "mapped" and 163 "ignored" rows of
     `trim_map.json` become decisions on source records, alongside merge/reject pairs as in
     bolthole's `listing_pair_decision`;
   - no record ever creates a car; derivatives are the entities.
4. **The owner's own data is a source.** The 19 cars, 29 offers and the pasted quotes are
   records from a source called something like "Tristan" (prices they were quoted, facts they
   checked), resolved like any other. Whatever "the shortlist" needs to be (today the
   "Hand-curated" saved search) is a saved search or a list of derivative ids, not a
   different kind of car.
5. **Facts and snapshot.** The claim store (`services/claims.py`) and the snapshot export
   already work from records and levels; point them at the resolved derivatives. Keep the
   snapshot contract (`docs/ARCHITECTURE.md`, "Snapshot contract") so the app needs little
   or no change.

## Migration: the history is the only copy of the past

There are no raws for anything fetched before the rebuild. The committed
`data/history/*.jsonl` (observations since 6 Oct plus the Wayback backfill back to 2025,
specs, derivatives, catalogue, options, configurations, used stock) is all that remains.
Import it once into the raw store as a legacy source, **stripped of the matching**
(`car_id` on observations and specs, the whole of `resolutions.jsonl`), keeping what each
source said and when. After that, `data/history` stops being written and can leave the
repo.

## Operations after the rebuild

- **Scraping runs on the laptop** (cron or launchd), because that is where the raws live.
  The GitHub nightly scrape (`.github/workflows/scrape.yml`) is retired once the laptop
  runs; until then it keeps going and should be checked each morning.
- **Publishing:** the laptop rebuilds the snapshot and pushes `web/public/data`; the push
  deploys the site.
- **CI** cannot rebuild from raws it does not have. `pipeline-ci` becomes: unit tests, and
  a rebuild from the test fixtures; its "the committed snapshot is what the history
  reproduces" check goes, since the history goes.
- **EV Database** throttles some addresses hard (429 on most car pages from a cloud sandbox,
  none from GitHub's runners). How the laptop fares is unknown; `evdb_cars` already slows
  down on a 429 and stops after 25 minutes.

## What the rebuild deletes

Car creation during ingestion (`gold.ensure_auto_car`, `gold.upsert_derivative`'s car,
`services/autocars.py` as a writer), the pipeline's own trim-map rows and
`resolutions.jsonl`, the hand-curated/generated distinction and the stopgap of 10 Oct
(`gold.curated_owner`, the curated half of `gold.prune_auto_cars`, the filter in
`snapshot.load_cars`), the history export and replay (`history.py`, `cli._replay`,
`cli._write_history`), and the fold-in logic in `scrape.yml`.

## Queued behind the rebuild

These were found or agreed on 10 Oct and should be built on the new design.

### Real PCP quotes (the owner wants authoritative figures, never derived ones)

Only 74 of 1,978 cars have a current PCP figure: Carwow's public deals page prints one
worked example per model and only for 15 makes (no Kia). Sources that print complete,
real examples per derivative, checked on 10 Oct:

- **cinch new cars**: the same search API the used-stock reader calls,
  `https://search-api.snc-prod.aws.cinch.co.uk/new-cars?url=electric-fuel-type&channelId=CINCH`
  (or `url=<make>/electric-fuel-type`). Each listing carries a full quote from cinch's
  retail partner, Marshall Motor Group: `quoteType` ("pcp"), `quoteRegularPaymentInPence`,
  `quoteTermMonths`, `quoteApr`, `quoteDepositInPence`, `quoteResidualValueInPence` (the
  final payment), `quoteBalanceInPence` (credit), `quoteChargesInPence` (interest),
  `quoteAnnualMiles`, `quoteExcessMileage`, plus `price`, `variant` (CAP-style derivative
  text), `make`, `model`, `trim`, `site` (the Marshall branches), `inventoryType`
  (virtual = factory order). 21 electric listings on 10 Oct: BYD 13, Hyundai 5 (Inster,
  Kona, IONIQ 5, 6, 9), Nissan 2, Geely 1. No Kia. One page of 32; `pageNumber` exists.
- **Dealer groups' offer pages**, full worked examples in plain HTML, each with its own
  dealer contribution on top of the maker's:
  - Lloyd Motor Group, `https://www.lloydmotorgroup.com/Kia/Current-Offers/Kia-EV3-Deals/382`:
    "Kia EV3 'GT-Line' 150Kw 81.4Kwh Auto PCP Representative Example Monthly Payment £449.45
    Customer Deposit £4,499 Kia UK Deposit Contribution £2,000 Lloyd Kia Deposit
    Contribution £430 ... Optional Final Payment £18,469.34 ... Fixed Rate of Interest 2.01%".
  - Halliwell Jones, `https://www.halliwelljones.co.uk/kia/offers/ev3`: "Representative
    Example (PCP) Based on a Kia EV3 GT-Line. Monthly Payment £399.00, Term of Agreement 37
    Months, Customer Deposit £4,999.00, Kia UK Deposit contribution £2,000.00, Electric Car
    Grant £1,500.00, Dealer Contribution £955.00 ... Optional Final Payment £18,469.34 ...
    Representative APR 3.9%".
  - RRG (`pipeline/providers/rrg.py` reads its PV5 page): the EV3 page
    (`https://www.rrg-group.com/kia/new-car-offers/ev3/`) did not show its example in the
    HTML; look for where it loads from.
  - Other Kia/Hyundai groups print similar pages (Snows, WJ King, Howards, Gravells); many
    run on shared dealer-website platforms, so one parser may cover several.
- **Not usable**: Kia's own offer pages show only the headline ("3.9% APR, up to £3,000
  contribution"); the worked figures come from the quote API that answers "No quote
  available". Auto Trader's monthly figures are, by its own description, indicative (dealer
  supplied or a generic example from its broker, Zuto). What Car?'s Target PCP is indicative
  on a fixed basis. Zuto, MoneySuperMarket (Motiv) and Quotezone quote only after a credit
  application. The owner's logged-in Carwow dealer quotes stay as pastes
  (`data/pastes/carwow/`).

### Cars that look identical in the table

- About 388 derivatives Carwow no longer lists and nobody has priced for 14 days (old price
  lists, e.g. Kona Ultimates at £43,995 to £45,595 last priced in August 2025). Proposed:
  hidden by default, history kept.
- About 500 current derivatives share their displayed name with another (BMW iX1 xLine at
  £39,065 on the July 2026 price list beside three at £49k to £53k from March 2025; EV9
  "[7St]" vs "[6St]"). Proposed: label by what differs, the price-list date and Carwow's
  CAP name where known.
- The "used" route is per model: every derivative shows the model's cheapest used car of
  any age or trim, which usually wins "True £/mo" (every Kona showed "£37 used"). Proposed:
  count a used car towards a derivative only when it is that derivative, or at least the
  same trim and battery.

The owner has not yet answered the three proposals above; ask before building them.

### EV Database car pages

69 of 862 read by 10 Oct; the nightly reads 60 more (`evdb_cars`), the hand-curated
models' first. Width is known for 594 of 1,978 cars, DC peak for 269, Euro NCAP for 388 (10 Oct).
