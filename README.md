# car-research

A persistent platform for evaluating cars and car deals: which car is right for us, what a car
is intrinsically worth, and what a given deal (PCP, PCH, used, cash) actually costs once the
headline numbers are unpicked.

**Live site:** https://tristandickson.github.io/car-research/ (after the one-time Pages setting,
see *Deploy*).

## Why this exists

Our Ioniq 5 PCP ends on **10 December 2026**. Rather than repeat the "walk into a dealer and
react to the monthly figure" process, this repo:

1. Captures **what we need from a car** as structured, weighted requirements
   (`docs/requirements.md`, `data/seed/requirements.json`).
2. Keeps **every car and every offer** we look at as dated, sourced observations with their
   source page as evidence, and normalises each onto one footing (`model/deal_math.py`).
   An offer not seen for a fortnight goes stale and drops out of the summaries, so "current"
   is a property of the data, not a label.
3. Serves it as a fast **single-page app** on GitHub Pages that loads the whole dataset into the
   browser's IndexedDB and lets us filter, sort and compare (`web/`).
4. Will estimate how **intrinsically good value** a car is: a model of the real base cost to
   build and ship a car from its spec, as a yardstick independent of marketing. Not started.

### The PCP obfuscation problem

Three things move independently and sellers shuffle value between them: the **vehicle price**
(list, dealer discount, government grant), the **finance support** (APR, manufacturer
contribution) and the **GFV** the lender underwrites. A low APR is worthless if the car's price
under that finance is £3-5k above the best cash price elsewhere. A high monthly can be cheap
money with a pessimistic balloon. Examples already in the data:

- Kia EV3 GT-Line S: nominal 3.9% PCP, but **~8.5% effective** against a £37,263 broker cash
  price because the PCP's net vehicle price is £3,692 higher.
- Hyundai Kona Ultimate: Richmond's 2.9% PCP looks like "only £287 more than cash", until a
  £26,966 outright price appears elsewhere and it becomes a **£6,871 premium at ~11%**.
- Hyundai Ioniq 3: cheapest car on the list, worst finance (8.9%, £5,533 interest on £27k).
  Right car, wrong campaign. Buy it cash or wait for a 0-3% campaign.
- Hyundai Ioniq 5: 0% plus £3,000 contribution, yet £652/month because the GFV is now 40% of
  price versus ~55% on our 2022 deal.

So every deal is normalised to **£0 deposit, total cost over the term, and measured against the
best confirmed like-for-like cash price**. The GFV is treated as a floor, not a forecast.
Full rules in `docs/research-notes.md`; the generated comparison is `docs/deal-comparison.md`.

## Where we are (6 Oct 2026)

| Car | Role | Route | Status |
| --- | --- | --- | --- |
| Kia PV5 Elite 7-seat | The car Tristan actually wants: 7 seats, dual powered sliding doors, V2L, Ioniq 5 footprint | PCP 3.9%, ~£699/month £0 down, GFV £18,662 | Over my partner's £400 ceiling. Decide by pricing the delta vs the best ≤£400 car. |
| Hyundai Ioniq 3 Ultimate EV Pack | Rational compact: 300mi, V2L, heat pump, 1,800mm wide | **Cash £27,445.** PCP is 8.9%, don't | Brand new model, no owner corpus. Test drive. |
| Kia EV2 GT-Line S + heat pump | Better-equipped Ioniq 3 rival, 257mi | Cash lead £29,666; lease ~£427 effective | Broker price unconfirmed for December. |
| Hyundai Kona Ultimate | Safe fallback | Richmond PCP £547; **£26,966 outright lead** | Confirm the cash lead is like-for-like. |
| Hyundai Ioniq 5 84kWh Premium | Known quantity, best charging | PCP 0% + £3k, £652/month | Good structure only if we expect equity. |
| Hyundai Inster 02 + Tech Pack | Cheap control | PCP 0% + £3k, £325/month | 4 seats, 223mi. |
| Used 2024 Kia EV6 GT-Line S | Most car per pound | £26,995, 27.8k miles | Still 1,890mm wide. |

Test-drive shortlist: Ioniq 3 Ultimate EV Pack and PV5 Elite 7-seat, Inster as the control.

## How it fits together

```
data/seed/*.json ─────────────┐
data/pastes/carwow/*.txt ─────┼─▶ pipeline (Python) ─▶ SQLite ─▶ web/public/data/*.json (committed)
live scrapers (5 sites) ──────┘     bronze/silver/gold           offers = latest sighting + maths + freshness
data/history/observations.jsonl ┘   trim map resolves each       push main ─▶ Pages ─▶ SPA
   (committed sighting log,         source's trim naming         SPA loads JSON into IndexedDB
    replayed so CI needs no network)
```

Details, the snapshot contract and the decisions are in `docs/ARCHITECTURE.md`.

## Where the prices come from

| Provider | What it reads | What it yields | Offline? |
| --- | --- | --- | --- |
| `manual_seed` | `data/seed/*.json` | cars, requirements, trim map, 29 hand-captured offers | yes |
| `carwow_paste` | `data/pastes/carwow/*.txt` | dealer PCP quotes from the logged-in Carwow account (4 so far) | yes |
| `carwow_deals` | carwow.co.uk public `<make>/<model>/deals` pages | Carwow's best cash price per derivative (CAP id), Kia's separate "PCP finance" price, the model-level representative PCP example | scrapes |
| `hyundai_offers` | hyundai.com/uk per-model offer pages | Hyundai Finance's full national PCP example per model (deposit, contribution, APR, GFV, validity dates) | scrapes |
| `ncd` | new-car-discount.com model listings | broker all-in cash price per derivative | scrapes |
| `leaseloco` | leaseloco.com model pages | best personal-lease deal per derivative and profile, VAT added | scrapes |
| `rrg` | rrg-group.com Kia PV5 offers | the dealer's PCP example for the PV5 7-seat | scrapes |

Every scrape is an observation: the body is kept (Bronze), parsed (Silver), resolved to one of
our 19 trims through the trim map and written as a sighting (Gold). Re-seeing the same price
extends the sighting; a changed price is a new row; a price not seen for 14 days is stale and
drops out of the best-price summaries. Kia's own quote widget currently returns "No quote
available" for every car, so Kia Finance examples are hand-captured for now; Richmond and
cars2buy block automated reads and stay as pastes.

## Trends

Every sighting is kept, so prices are a history, not a number: one row per distinct
price with the span of dates it was seen over. The app draws them on three levels:

- **Pick cards**: a 90-day sparkline of the best outright price with "down £x over 30
  days" and how long it has sat at the current price.
- **Car page → Price over time**: outright prices by source and advertised monthly
  payments by offer as step lines through their sightings, with a crosshair that reads
  every line at a date, the list-after-grant line for reference, and the same data as
  a table underneath.
- **Trends page**: a movers table (best price, discount against list, change over the
  window, days at this price) and one small chart per car on a shared axis.

The nightly scrape adds a point per car per day. Older points come from two places:
the hand-captured offers and Carwow quotes keep their original dates, and `pipeline
backfill` folds dated captures of the scraped pages from the Wayback Machine into the
same history (`.github/workflows/backfill.yml`, dispatched by hand). Coverage there is
sparse and uneven: a probe found roughly one capture every few months for the Carwow
Kona and EV6 pages and Hyundai's Ioniq 5 offer page, next to nothing for the newer
models, and nothing for LeaseLoco or RRG. It gives waypoints (what Carwow's Kona price
was in January, May and August), not a daily line. There is no other public source of
historical UK car prices for these pages; the nightly scrape is the trend.

## Repo layout

```
pipeline/               Python package: providers, SQLite medallion, snapshot exporter, history, CLI
  providers/            manual_seed, carwow_paste, and the live scrapers (carwow_deals, hyundai_offers, ncd, leaseloco, rrg)
                        http.py (polite fetch: UA, per-host delay, retry) and parse.py (money/pct/text/key helpers)
  services/snapshot.py  Gold → web/public/data: offers with metrics + freshness, requirement checks, data page
  history.py            offer_observations ⇄ data/history/observations.jsonl (so CI and a fresh clone replay the past)
model/deal_math.py      PCP / PCH / cash normalisation (pinned by tests/test_deal_math.py)
data/seed/              hand-captured cars (19), offers (29), requirements, trim map (50 mapped, the rest ignored on purpose)
data/pastes/            pasted source pages, one file each (carwow: 4, richmond: 2)
data/history/           the committed sighting log, appended by every refresh
web/                    Next.js static SPA: pick, compare, cars, car detail with price board, offers, requirements, data
  public/data/          the committed snapshot the SPA reads
docs/                   requirements, research notes, architecture, generated deal table,
  transcripts/          raw source conversations (contact details redacted)
tests/                  Python unit tests; tests/fixtures holds one real page per scraper
.github/workflows/      pages-deploy, web-ci, pipeline-ci (offline replay; fails if the snapshot is stale), scrape (nightly), backfill (Wayback, by hand)
```

## Working on it

```
make snapshot      # run every provider (live scrape) → SQLite → data/history + web/public/data
make snapshot-offline   # same without the network: seed + pastes + replayed history
make test          # python unittest + web lint/typecheck/vitest
make web-dev       # http://localhost:3001
python3 -m pipeline deal-table > docs/deal-comparison.md
python3 -m pipeline trims        # anything scraped that is not yet in the trim map
python3 -m pipeline backfill --since 2025-01-01   # Wayback captures → history (needs a network archive.org will talk to)
```

Python ≥ 3.11 with no third-party packages; Node 22 (`cd web && npm install`).

**Nightly:** `.github/workflows/scrape.yml` runs every provider at 03:17 UTC, commits
`data/history`, `web/public/data` and `docs/deal-comparison.md` when anything changed, and
redeploys the app. A site that changes its layout shows up as a provider with 0 records in the
run and its offers going stale a fortnight later; fix the parser against a fresh fixture.

**To add a Carwow quote:** copy the dealer-offer page text from your logged-in browser into
`data/pastes/carwow/<date>_<dealid>.txt`, first line `# captured_at: 2026-10-07T09:00:00Z`,
then `make snapshot-offline`. If the trim is new, `python3 -m pipeline trims` tells you what to
add to `data/seed/trim_map.json`. Re-pasting the same offer on a later date records a new
sighting (and any price change) rather than overwriting.

**To add any other offer or a car:** edit `data/seed/deals.json` or `cars.json` following the
existing entries (every offer has `captured_at`, `status`, `verification`, a `source`, and prices
net of discount and grant), run `make snapshot-offline`, commit the seed and the regenerated
snapshot together. CI rejects a seed change without its snapshot, and rejects unmapped trims.

**When a scraper meets a new derivative:** `python3 -m pipeline trims` prints it with the label
as the site printed it. Add a row to `data/seed/trim_map.json` with the `car_id` it is, or with
`"status": "ignored"` and a note if it is a derivative we do not track (wrong pack, no heat
pump, 5-seat). Nothing is ever attached to a guessed car.

## Deploy

Push to `main` deploys via `.github/workflows/pages-deploy.yml`. One-time settings in the GitHub
repo: **Settings → Pages → Source = "GitHub Actions"**, and the `github-pages` environment must
allow `main` to deploy. Enabling Pages creates that environment with a branch rule naming whatever
branch was the default at the time, and changing the default branch later does not update it, so
add `main` under Settings → Environments → github-pages → Deployment branches and tags. A deploy
rejected by that rule fails in two seconds with no runner and no logs.

## Data conventions

- **`vehicle_price`** is the net price after dealer discount *and* government grant, before any
  manufacturer finance contribution and before the customer deposit: what you would pay in cash
  from that seller.
- **`amount_of_credit`** = vehicle price minus deposit minus contribution.
- Every offer sighting carries `captured_at`, `status` as the source implied it (live / expired /
  lead / illustrative / derived / campaign / historical) and `verification` (pasted / cited /
  derived / user). The exported `freshness.state` adds `gone` and auto-expires on `valid_to`.
  Anything ChatGPT sourced is *cited* until we re-verify it.
- Cars carry `heat_pump` and `internal_v2l` as standard / pack / option / none / unknown, with
  `packs_required` naming the pack. These two fields drive most trim decisions.

## Context log

- **2026-10-06** Trends: sparklines on the Pick cards, price-over-time charts on the car
  page, a Trends page with movers and small multiples. Sighting merge generalised so
  backfilled (older) captures extend, start or split spans correctly. Wayback Machine
  backfill as a capability on every live provider plus a dispatchable workflow.
- **2026-10-06** Live scrapers: Carwow public deals pages, Hyundai UK offer pages, New Car
  Discount, LeaseLoco and RRG, each pinned to a real captured page in `tests/fixtures`. Sightings
  are logged to `data/history/observations.jsonl` and replayed so CI and fresh clones need no
  network. Nightly scrape workflow. 80 offers across 19 trims after the first live run; the trim
  map carries 50 mapped derivatives and ~150 deliberately ignored ones.
- **2026-10-06** Offers became observations: offer keys, sighting history, freshness (stale after
  14 days, gone, auto-expiry), a trim map with an unmapped queue, and a Carwow paste provider
  with the four real pages from the transcript as fixtures. SPA gained Offers and Data pages.

- **2026-10-06** Built the platform: pipeline (SQLite medallion, snapshot export), Next.js SPA
  with IndexedDB, Pages deploy and CI. Imported the 4-6 Oct ChatGPT conversation into
  `docs/transcripts/`, distilled requirements and research notes, captured 19 cars and 33 deals.
- **2026-10-06** Project started. Current car is a Hyundai Ioniq 5 on a 36-month 0% PCP,
  £0 deposit, ~£540/month, ending 10 Dec 2026.

## Next steps

1. Confirm the cash leads are like-for-like and available for December using the enquiry
   script in `docs/research-notes.md`; the scraped NCD and Carwow prices are leads, not quotes.
2. Get the Ioniq 3 Premium EV Pack GFV so a ~£400 PCP alternative can be priced properly.
3. Kia Finance examples: the `kiaofferscalculator.co.uk` quote API answers "No quote available"
   for every parameter set today (the live widget too); revisit, else keep hand-capturing.
4. Richmond paste parser (two pages saved under `data/pastes/richmond/`), and a used-market
   provider once a source that allows automated reads is found.
5. Intrinsic-value model: start with £/kWh, £/mile of range and £/kg against segment, then
   residual-value evidence from used listings.
