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
  the store as the source `history` (first named "legacy"; renamed on 11 Oct, when the owner said
  "if its somehow used to build history it shouldnt be called legacy"), byte-identical to git;
  `raw-migrate` adds new ones and nothing twice. They are read with the matching stripped
  (`pipeline/history.py`). Every build reads them: they are the only copy of the 3,203 price spans
  from the Wayback backfill (back to 12 Jan 2025), of 899 offers last seen before 10 Oct, and
  until the weekly rotation re-reads them, of the configurator options.
- **The build** (`pipeline/build.py`), from scratch every run, as in "The target" below. The
  car creation during ingestion, the history export and replay, and the 10 Oct stopgap are
  deleted, as listed under "What the rebuild deletes".
- **The scraper** keeps raws and nothing else; **the laptop's nightly job**
  (`scripts/nightly.sh`, bash; scheduled for 03:17 daily by `scripts/install-nightly.sh`): it scrapes, builds,
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
71 MB in the store with the committed history. EV Database answered 55 car pages with one failure and
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
- The committed history's rows cannot be re-parsed (no page was kept); only their
  matching is re-derived. Re-running the Wayback backfill on the laptop would fetch the archived
  pages as raws.

## Next: one resolver over every record (designed 15-16 Oct 2026, not built)

Matching today is four separate lookups, one comparison each: a record printing a CAP id attaches
to it; a broker's text is matched to Carwow's derivatives by rules (`services/resolve.py`,
`match.py`); an EV Database page attaches to a car by a battery ratio (`facts.pick_variant`),
which tied every current Kona to the 2021-23 Kona's page; a used listing attaches to a trim by its
words and a battery within 3 kWh (`snapshot.used_key_for_text`), which counts 2021 Konas as the
2023-on car. A survey of the 15 Oct build (`docs/resolver/`) also found 169 of the 353 cars
linked to an EV Database page that gives the motor on a variant with a different motor, 1,306
used listings on a version that went on sale after they were registered, and 452 "Long Range"
listings on "Standard" derivatives.

### What the owner said (15-16 Oct 2026)

- On the matching: "From memory, i said i didnt know if we needed to go as complex as bolthole,
  because properties are inherently harder to match and i thought car variants could be done
  with a few explicit comparisons, but that appears nto to be the case." What they want: "an
  algorithm that builds compounds of features from each raw and compares recursively to reduce to
  the smallest possible set of entites that satisfies those constraints".
- On a golden record: "we have presumably a master record of every derivative and only need to
  match against it. Its our golden record." CAP's list is licensed (quote only), so it cannot be
  that record; Parkers' is the nearest free one (`docs/SOURCES.md`, "Parkers").
- On the CAP id: "i dont think CAP id becomes anything special beyond a very high priority match
  field".
- On text: "We should use a standard parser for car listings, e.g. to remove accents".
- On the two Konas: "we definitely need to differentiate between the kona v1 and v2"; on old
  versions with only used cars: "its fine to make them cars".
- On a price that fits several near-identical versions: "list that lease against the worst spec
  or best spec it applies to. Maybe best because investigating a price thats worse than it looks
  is preferable to missing a price that's better than it looks".
- On resale: "We take resale at say 3 years, the price of a 2023 Kona now", and on mileage: "My
  idea was a very wide band so we dont discard most of the evidence".
- On decisions the matching cannot make: "Isnt it easier to have a flow in the app to resolve them
  if they come up? (I don't think they will even come up for the same reason in 1.)"
- On the first Parkers read: "i dont even want to wait 4 nights if we dont have to" (all 4,083
  pages were read on 16 Oct).

### The design (Claude's, from the above, for the owner to correct)

**The master list is Parkers' derivatives.** Every electric derivative Parkers lists, old
generations included, with what its address and its page say: make, model, generation (body and
start year), trim (from the generation's own trim list), motor kW, battery kWh, packs (CAP's
brackets), doors, on-sale dates, price when new. These are the cars the app shows. A car's id is
built from those details, normalised (make, model, generation, trim, kW, kWh, packs), not from
whichever source listed it, so a derivative Carwow lists before Parkers does keeps its id when
Parkers adds it, and the owner's saved references keep working.

**Every other record is matched to it**, Carwow's included, after one shared normaliser has read
its text: accents out and case folded ("Škoda" is "skoda"); hyphens, dots and spaces alike ("GT-Line
S" is "GT Line S"); units to numbers (kWh, kW, bhp and PS); one alias list for makes and models;
and one table expanding CAP's short descriptions into its long ones ("eDr40" to "eDrive40",
"Qtro" to "quattro", "Black Ed" to "Black Edition", "Comf+" to "Comfort Plus"), which is how
Carwow abbreviates and Parkers does not. Words that separate versions ("Long Range", "AWD",
"Performance") are features, never dropped.

Within the record's model, each detail it gives rules out the entries it contradicts: a fuel that
burns; motors more than 5 kW apart; battery labels more than 0.6 kWh apart (makers' labels are
exact; against EV Database's usable figure by kind, 0.84 to 1.03 of the label, against its gross
within 0.6); a different drive or seat count; a registration or price-list date outside the
entry's on-sale dates; a trim word the entry lacks; a price no entry could have. A detail the
record does not give rules nothing out. Then:

- one entry left: the record is that car;
- several: the record's list price, then its pack names, narrow them; any still left, the record
  goes on the best spec of them, with the others named on it (the owner's rule);
- none: a record with its own trim and details (a Carwow derivative newer than Parkers' list)
  becomes a car under the same id formula; a text record stays at the most specific level its
  details reach (the version: model, battery, motor and years; else the model) and is listed on
  the Data page.

A CAP id is the strongest match field: once one record with that id is matched, every record
printing it goes to the same car, unless one of its details contradicts the car, which is then
listed for a look rather than forced. EV Database describes a version, not a trim, so its record
matches every Parkers derivative of that version and its figures go to all of them, below any
source that speaks for the derivative itself. The same used car on two sites is one car by its
registration mark.

That is the whole procedure: one filter for every source, against one list, with no record
creating a car except a structured derivative the list lacks. It needs no graph: the master list
is the set of entities, and the filter only decides which entry each record belongs to.

**Resale** is the median asking price, now, of used cars of the same version that are as old as
the term, with between half and double the miles the reader's own mileage gives (9,000 to 36,000
at 6,000 a year over three years); fewer than 10 such cars, and all of that age count and the app
says so. The app shows how many cars and which mileage band a figure rests on.

**Decisions.** The owner's 19 cars and 56 trim-map decisions name CAP ids today; each is mapped
once through its CAP id to the new car, and any that does not map is listed for them to check.
Anything the resolver cannot place goes on the Data page; the owner says what it is and Claude
records it (a fix-it flow in the app would need the static site to write back to the repo).

### Order of work

1. The Parkers reader: done 16 Oct (`providers/parkers.py`), its records kept out of the snapshot
   until the resolver reads them.
2. The shared normaliser, with the CAP token table, each rule tested on strings from captured
   pages.
3. The model mapping between Carwow's catalogue and Parkers' models and generations (Parkers files
   body styles as generations: the Q4 e-tron Sportback is `q4-e-tron/sportback-2021`).
4. The resolver, the id formula, and `python -m pipeline resolver-diff`, which lists every record
   whose car changes against today's lookups; reviewed with the owner before the switch.
5. In the app: resale by version within the mileage band; a price that fits several cars on the
   best spec, with the others named; old versions as cars.

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
Import it once into the raw store as a source of its own (`history`), **stripped of the matching**
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

Built on 11 Oct: `cinch_new` (cinch's new-car API) and `kia_dealers` (Lloyd Motor Group and
Halliwell Jones). Cars with a current PCP figure went from 74 to 94. RRG's EV3 page and the other
Kia and Hyundai groups below are still to do. The notes from 10 Oct follow.

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
  - RRG (`pipeline/providers/rrg.py`) reads every Kia EV offer page its index lists since 11 Oct.
    There is no EV3 offer: the EV3 URL returns the index page itself.
  - Other Kia/Hyundai groups print similar pages (Snows, WJ King, Howards, Gravells); many
    run on shared dealer-website platforms, so one parser may cover several.
- **Not usable for a quote**: Kia's own offer pages print no worked example (that comes from the
  quote API that answers "No quote available"), but the 11 Oct survey found they do print the
  contribution and grant per trim and the order window (EV3: 01.10.2026 to 15.12.2026), which
  nothing reads yet (`docs/SOURCES.md`). Auto Trader's monthly figures are, by its own description, indicative (dealer
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

Built on 11 Oct, when the owner asked for the data to be ready for someone to use the app: an
"On sale now" flag on every car that the default search uses (old price-list versions hidden by
default, history kept); a note on every car that shares its displayed name saying what differs;
and the buy-used route counting a used car only for a car of the same trim and battery.

### EV Database car pages

69 of 862 read by 10 Oct; the nightly reads 60 more (`evdb_cars`), the hand-curated
models' first. Width is known for 594 of 1,978 cars, DC peak for 269, Euro NCAP for 388 (10 Oct).
