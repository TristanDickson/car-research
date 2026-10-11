# Sources: what each one prints, what we read, what we leave

One section per source the nightly job reads. Each says which pages it fetches and how many a
night, what those pages print, what the parser keeps, and what it leaves out and why. The
surveys behind it were made on 11 Oct 2026 against the pages in the raw store and a few live
fetches; the figures quoted are from those pages.

The rule this file serves (CLAUDE.md): **no new source without a survey**. Before a parser is
written, list every page type the site has, everything each one prints that the household could
use, and the cost of reading it. Then write down here what is read and what is left, with the
reason. A survey that finds data on a page we already fetch and do not read is a bug report.

Request counts are a night's fetches, counting every response the raw store keeps (the parts of
a combined fetch included).

| Source | Site | Pages a night | Gives |
|---|---|---|---|
| `carwow_catalog` | carwow.co.uk sitemaps, `/<make>/electric` | about 48 | every EV model on sale, the list the other Carwow sources read |
| `carwow_deals` | `/<make>/<model>/deals` | about 178 | best cash price per CAP derivative, the PCP price, the card's contribution and APR, one representative PCP example per model |
| `carwow_model` | `/<make>/<model>` | about 249 | the derivative registry: every CAP id, its name and RRP |
| `carwow_specs` | `/<make>/<model>/specifications` | about 219 | per derivative: equipment, range, efficiency, 0-62, prices; model facts |
| `carwow_options` | `quotes.carwow.co.uk/car_configuration/choose-options` | rotation | options and packs per derivative; broken, see below |
| `carwow_used` | `quotes.carwow.co.uk/stock_cars/deal-cards`, `deal-card?id=` | about 700 to 1,240 | used stock with price, year, mileage, derivative |
| `cinch_new` | cinch new-car API | 2 | PCP and cash quotes per new car |
| `cinch_used` | cinch search API | about 129 | used stock with a full finance quote each |
| `motorpoint_used` | Motorpoint search JSON | about 18 | used stock with the lowest monthly |
| `ncd` | new-car-discount.com listings and `/fincalc` | about 250 | broker cash price per derivative and its PCP quote |
| `leaseloco` | leaseloco.com model pages | about 249 (154 are guessed pages that 404) | best personal lease per derivative and profile, and the in-stock deal |
| `rrg` | rrg-group.com Kia offers | about 15 | dealer PCP and lease examples for every Kia EV it advertises |
| `kia_dealers` | Lloyd Motor Group, Halliwell Jones | about 23 | dealer PCP examples for Kia EVs |
| `kia_specs` | kia.com specification pages | 4 | grade tables: equipment, range, charging, towing, dimensions |
| `hyundai_offers` | hyundai.com offer pages | 4 | Hyundai's national PCP and loan examples |
| `hyundai_specs` | Hyundai PDF price and spec guides | about 10 | grade equipment, the price table, the Technical pages |
| `hyundai_configurator` | Hyundai configurator GraphQL | about 15 | every orderable configuration with its price and packs |
| `evdb` | ev-database.org UK index | 1 | measured range, efficiency, charging, weight per variant; on-sale dates |
| `evdb_cars` | ev-database.org car pages | budgeted, resting after refusals | the variant's full page: dimensions, warranty, charging curve |

## Carwow

### carwow_catalog

Reads Carwow's model sitemaps and each make's `/<make>/electric` page to list every electric
model on sale, with which page types each model has. Prints no prices or specs; nothing is left.

### carwow_deals

`/<make>/<model>/deals` prints one card per CAP derivative: RRP, best cash price, a "PCP
Finance" price on some makes, "Monthly from" on others, and footnotes ("With finance deposit
contribution of £2,000", "Representative APR 3.9%"). Below the cards sits one representative
PCP example for the model (deposit, monthly, final payment, APR, mileage, RRP).

- **Read:** every card's prices and footnotes, the representative example in full.
- **The example's car:** matched by RRP; where two derivatives share an RRP (the Ioniq 5
  Advance 63 kWh model years, £40,695), by the card whose "Monthly from" is the example's
  payment. A tie that stays a tie is left unmatched.
- **Left:** nothing on the page. Named dealer offers need the logged-in quotes page.

### carwow_model

The model page lists every derivative with its CAP id, name, RRP and price-list version date.
It is the registry the build matches broker names against. It also prints the model's lease
headline, which `carwow_specs` reads. Nothing else is left.

### carwow_specs

`/<make>/<model>/specifications` prints a trim article per trim (standard equipment, the
trim's cheapest RRP and Carwow price, description, image) and an engines carousel with one
slide per derivative: its own breakdown (range, efficiency, 0-62, top speed, power, drive),
its own RRP and Carwow price, and a "Configure car" link carrying its CAP id. Model-level
facts follow (seats, doors, boot, turning circle, wheelbase, used-from, cash-from, the lease
headline "Monthly £336*" with its basis in a footnote).

- **Read:** each derivative's figures from its own slide, keyed by the CAP id in the slide.
  Keying by engine name gave 18 of 48 derivatives another's range (Kona N Line 319 miles for
  its printed 282) until 11 Oct.
- **Model ranges:** where the page prints a range ("5 - 7" seats, "350 - 1,330 L"), it is kept
  as `<field>_range` and no derivative gets a value from it. About 430 cars lost a turning
  circle and 400 a folded boot figure they had taken from such ranges; other sources fill them
  where they print the derivative's own.
- **Left:** nothing numeric.

### carwow_options

The configurator's options page carries the derivative's options, packs, colours with prices
and hex codes, and `option_rules` (which options exclude each other).

- **Broken:** the configurator now redirects to "Choose the type of car" for the pages tried
  since the raw store began, so the scrape yields nothing and retries nightly. The 1,040 option
  rows in the committed history predate it. Needs a fresh survey of the new flow.
- **Left even when it worked:** colour names and prices (only the count was kept), and the
  option rules.

### carwow_used

The model's used results (`stock_cars/deal-cards`, `per_page=200`, electric only) name every
car on the page in `data-stock-cars-v2--results-deal-ids-value`, with the total, and give price
and registration year for every car in `data-stock-cars-v2--results-ecommerce-items-value`. Only
about four sponsored cards per page come in full; the rest are placeholders filled from
`deal-card?id=<id>` (about 50 KB each: derivative, mileage, town, deal link).

- **Read:** every named car's price and year; its card where fetched (the household's eight
  models: every card new or a week old; the rest share 400 cards a night, never-fetched first).
  A car whose card was fetched on an earlier night keeps it, with tonight's price.
- **Until 11 Oct** only the sponsored cards were read: 1,317 of 8,204 stated cars, none for the
  EV3. Petrol and diesel cars were also kept (118, the Ford Focus among them).
- **Left:** the deal page itself (`/deals/<id>`, about 490 KB): registration, previous owners,
  colour, full equipment, warranty. One page per car; about 6,900 a night for everything.
- **Note:** 18 of the EV3's 48 "used" cars are ones Carwow marks New (pre-registered stock).
  They are listed but kept out of what a used car is worth.

## cinch

### cinch_new

cinch's new-car API returns PCP and cash offers per vehicle; the parser keeps both and records
whether the PCP's figures reconcile and whether a contribution had to be implied.

### cinch_used

The search API pages every listing for each make (`vehicleListings[]`), complete against its
`searchResultsCount`.

- **Read:** price, year, mileage, derivative, registration, and since 11 Oct the finance quote
  every listing carries (1,284 of 1,285): type, monthly, deposit, APR, payments, final payment,
  credit, charges, mileage, excess. All 1,238 kept quotes reconcile. Also colour, drive,
  discount, tags.
- **Left:** the detail page (about 46 KB a car): registered keepers, registration date, service
  history, keys, standard and optional equipment, HP beside PCP, battery warranty. 1,285 pages
  for all makes, 145 for Hyundai and Kia.

## Motorpoint

### motorpoint_used

The stock JSON pages every listing, complete against its count.

- **Read:** price, year, mileage, derivative, town, list price when new, and since 11 Oct the
  lowest monthly with its type, warranty months left, plate age code, previous price and
  discount, colour. The 66 "coming soon" cars (priced, not yet on the forecourt) are kept and
  marked.
- **Left:** the detail page (about 850 KB a car): battery health, registration (the parser's old
  claim that Motorpoint prints none is wrong), keepers, service and MOT history, previous prices,
  estimated market price, standard equipment, the full PCP and HP terms. 576 pages for all
  makes, 43 for Hyundai and Kia.

## New Car Discount

### ncd

Listing pages (`/car/<make>/<model>/<body>/all/all`) give one line per derivative: price and
stated saving. Each derivative's page shows a PCP panel whose figures come from
`POST /fincalc` (`{"ftype":"PCP","capcode":<derivative-id>,"advance":<price>,"mileage":10000,
"deposit":1000,"period":36,...}`); the same call with `"ftype":"HP"` gives hire purchase.

- **Read:** every listing line, and since 11 Oct each electric derivative's PCP quote at the
  page's own defaults (10,000 miles, £1,000 deposit, 36 months), marked illustrative as NCD
  says. The Ioniq 5 N Line returns £683.01 × 35, final payment £15,623.74, 7.9%.
- **Listings:** the EV6 range is under `/car/kia/ev6/4x4/all/all` as well as `/estate/`, added
  11 Oct. NCD prints the make before the model on Kia listings ("KIA EV6 ELECTRIC ESTATE");
  until 11 Oct no Kia line matched a car except through the owner's own decisions.
- **Listings added 11 Oct:** every other electric Hyundai and Kia on NCD's make pages (Ioniq 5 N,
  Ioniq 6 N, Ioniq 9, EV4 hatchback and saloon, EV5, EV9). The EV4 saloon is Carwow's EV4
  Fastback; NCD's RRP picks between the two bodies, which share trims and powertrains.
- **Left:** the HP quote (one more call a car).

## LeaseLoco

### leaseloco

Each model page's `__NEXT_DATA__` holds the best personal-lease deal per derivative and profile
(`originalBestDealList`, or the first page of search results), and one in-stock deal
(`originalInStockDealList`).

- **Read:** the best deals, converted from ex-VAT; since 11 Oct the in-stock deal under a key of
  its own (the Kona N Line in stock at £267.04 beside its factory-order best at £269.16). 68 of
  the 95 in-stock deals are already in the best lists and are marked there.
- **Left:** the other few thousand deals per model (the Ioniq 5 page counts 5,602) load from an
  API not traced; the `/config` page's equipment list (one fetch per derivative, about 55 for
  the household's models).
- **Guessed pages:** a model page that 404s is not asked again for a week.

## Kia dealers

### rrg

The Kia offers index (two pages, "19 Offers available") links one page per offer. Each prints a
representative PCP or lease example as labelled lines.

- **Read:** since 11 Oct every electric offer: EV2, EV4, EV5, EV6, EV9 and the PV5 pages, PCP
  and personal lease. There is no EV3 offer (its URL returns the index).
- **Names:** RRG copies derivative lines between pages; the EV6 example says "Air" at the
  GT-Line's £52,835. The on-the-road price goes with each record, and a text match whose price
  fits no derivative it names is recorded as a conflict instead of a car.

### kia_dealers

Lloyd Motor Group's and Halliwell Jones's Kia offer pages, each a representative PCP example.

- **Lloyd:** the heading before each example names its car.
- **Halliwell Jones:** an offer page's first example is its own; its heading names the car
  (the captions above examples are often wrong: an "EV3 Air" caption over the GT-Line's
  £39,455). The banner ("From only £499 p/m") is kept beside the example; the EV5 Storm's
  example prints £449, which its own credit, APR and final payment do not support.
- **Left:** Kia's own offer pages (`kia.com/uk/new-cars/offers/<model>/`): contributions per
  trim, the grant per trim, the order window (to 15 Dec 2026). Four pages; a new source, so it
  needs its own survey first.

## Kia

### kia_specs

`kia.com/uk/new-cars/<model>/specification/` prints grade tables for equipment and, per
powertrain or seat count, performance, charging, dimensions, weights and towing.

- **Read:** since 11 Oct also DC and AC charge times per charger, braked towing, the PV5's
  5-seat and 7-seat tables, the EV6's Wh/km as mi/kWh, cells that span several columns.
- **Left:** torque, the battery pack table (cells, voltage, weight), CO2, city range, track
  widths, service interval, the PV5's cabin dimensions. Kia prints no prices here.

## Hyundai

### hyundai_offers

Each model's offer page carries `data-js-options` JSON with a PCP and a Personal Motor Loan
example (cash price, up to three discounts, OTR, deposit, contribution, APR, monthly, final
payment), plus a Motability entry with no figures.

- **Read:** both examples since 11 Oct; the grant summed over the three discount slots (the
  Ioniq 3's £3,750 sits in the second); the example's paint from `extId` ("SAW-370", which is
  why the Inster's OTR is £370 above its cash price); whether the figures reconcile.

### hyundai_specs

Hyundai publishes no readable spec page, so this reads the PDF price and specification guides
(Inster, Kona, Ioniq 5, 6, 9) with poppler's `pdftotext`.

- **Read:** grade equipment, and since 11 Oct the price table per powertrain (OTR, insurance
  group, P11D, BIK), paint and option prices, and the Technical pages (towing, range, charging,
  boot, weights, warranty).
- **Left:** there is no Ioniq 3 guide (its downloads page 404s).

### hyundai_configurator

The configurator's GraphQL endpoint returns every orderable configuration with price, packs
and equipment. Since 11 Oct it includes the Ioniq 3 (20 configurations; Advance 42 kWh £22,245,
before the £3,750 grant).

- **Left:** paint, wheel and interior prices, delivery dates, and a per-configuration PCP quote
  the site appears to offer; the query for them is not known.

## EV Database

### evdb

The UK index prints a card per variant: measured range, efficiency, battery, charging, weight,
towing, boot, price, seats, and hidden availability dates.

- **Read:** since 11 Oct the hidden dates too: 635 of 1,105 cards are discontinued, and a
  variant's on-sale state now comes from them.
- **Left:** the BCH lease headline (business hire, of no use to the household).

### evdb_cars

Each variant's own page (dimensions, warranty, charge curve, V2L, availability). Read within a
nightly budget; the site refuses the laptop often, so it rests after refused nights
(`pipeline/providers/politeness.py`).

- **Left:** "Electric Car Grant applied £1,500", V2H/V2G and Plug & Charge are printed and not
  mapped.

## What is still on the table, by value

1. Detail pages for used cars: registration and keepers (cinch, Motorpoint, Carwow), battery
   health (Motorpoint). One page per car; 145 and 43 for Hyundai and Kia at cinch and
   Motorpoint.
2. Kia's own offer pages: the order window and per-trim contributions. Four pages.
3. NCD's HP quote.
4. Carwow's configurator, once its new flow is surveyed.
5. LeaseLoco's other deals per model, if its price API can be found.
