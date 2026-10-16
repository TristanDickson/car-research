# Sources: what each one prints, what we read, what we leave

One section per source the nightly job reads. Each says which pages it fetches and how many a
night, what those pages print, what the parser keeps, and what it leaves out and why. The
surveys behind it were made on 11 Oct 2026 against the pages in the raw store and a few live
fetches (ADAC, What Car? and the other reliability sources on 13 Oct); the figures quoted are
from those pages.

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
| `adac` | adac.de car catalogue: the tested car's page, the range page; the test PDF | up to 75 (25 of each; a page every 90 days) | ADAC's Autotest grades per model (ride, build quality, space), its breakdown statistics, and its measurements of the car tested (tyres, boot, braking, noise, range, DC charging) |
| `whatcar` | whatcar.com Reliability Survey articles | 3 | owners' reliability rating per model, its place in its class and the common faults |
| `dvsa_recalls` | check-vehicle-recalls.service.gov.uk, "All recalls since 1992" | 1 (7.7 MB, downloaded by Chrome) | every UK safety recall: defect, remedy, build dates, cars affected |
| `nhtsa_recalls` | static.nhtsa.gov, `FLAT_RCL_POST_2010.zip` | 1 a week (15 MB) | every US safety recall: defect, remedy, model years, build dates, US vehicles affected, which recall replaced which |

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
- **Its number of payments:** the example prints its term ("36 months") but not how many
  monthly payments it has, and lenders differ: Hyundai's 36 months is 36 payments then the
  final one, Jeep's 35 then the final one in month 36. The count is whichever makes the
  example's total payable add up; the monthly is printed rounded up to the pound (£218 for
  £217.40). Until 12 Oct the term was read as the count: of the 108 examples held, 64 had one
  payment too many (54 at 36 months, 10 at 37), the committed history included (now corrected
  as it is read, `history.upgrade`).
- **Left:** nothing on the page. Named dealer offers need the logged-in quotes page.

### carwow_model

The model page lists every derivative with its CAP id, name, RRP and price-list version date.
It is the registry the build matches broker names against. It also prints the model's lease
headline, which `carwow_specs` reads, and Carwow's review of the model, which the survey of 11 Oct
missed.

- **Read since 14 Oct:** the review: its "What's good" and "What's not so good" lists, and every
  section by heading ("Space in the back seats", "In town", "On the motorway", "Interior style,
  infotainment and accessories", "Reliability and problems", ...), as text. All 249 model pages
  have one; 169 have a back-seat section, about 176 the ride sections, 183 a reliability one. The
  app shows the back seats, the ride, the interior and reliability on the car page, and the
  back-seat section's sentences about knees, thighs, the floor and the room as a field (162
  models): "the floor is relatively high up, so taller passengers have their legs angled
  awkwardly" (Ioniq 5). They are Carwow's words and are not scored, since they read both ways.
- **Left:** the review's FAQs, which repeat the numbers; and since 15 Oct the petrol versions
  some electric models' pages list beside the electric ones (the Ford Focus's "1.0 EcoBoost
  Hybrid mHEV", the Fiat 500 Convertible's "1.0 Mild Hybrid") and range extenders (Leapmotor's
  "Hybrid EV"), which had become cars in the app: `parse.combustion` names them, and
  `carwow_specs` leaves them too (the Astra Sports Tourer Electric page's "1.2 Turbo 130").

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
- **Listings:** the EV6 range is under `/car/kia/ev6/4x4/all/all`, added 11 Oct. NCD prints the
  make before the model on Kia listings ("KIA EV6 ELECTRIC ESTATE"); until 11 Oct no Kia line
  matched a car except through the owner's own decisions.
- **Left, on purpose:** `/car/kia/ev6/estate/all/all`, which holds only a second copy of the EV6
  GT filed as a diesel. Its vehicle code says diesel (`KIEV00G845ED` against the electric copy's
  `KIEV00G845EE`), NCD's finance quote answers "not found in residual database", and its £60,728
  sat £60 under the electric copy. Any electric car NCD files under another fuel is skipped.
- **Listings added 11 Oct:** every other electric Hyundai and Kia on NCD's make pages (Ioniq 5 N,
  Ioniq 6 N, Ioniq 9, EV4 hatchback and saloon, EV5, EV9). The EV4 saloon is Carwow's EV4
  Fastback; NCD's RRP picks between the two bodies, which share trims and powertrains.
- **Read since 13 Oct:** each derivative page prints CAP's technical data (`tech-name` /
  `tech-value` pairs) under its CAP id (hidden `derivative-code`, the id Carwow's registry
  uses: 111014 is the Ioniq 3 Premium EV Pack). The parser reads the pages back from the pcp
  fetch's stored parts and takes the front and rear tyre sizes and the wheel size; the build
  works out the front tyre's sidewall height (width × profile: 215/55 R17 is 118 mm). 106 of
  the 1,590 cars on sale have them, all Hyundai and Kia, the makes NCD lists.
- **Left:** the HP quote (one more call a car); the rest of the technical table (battery, WLTP
  range, charging, power, torque, 0-62, length, wheelbase, luggage, seats), which Carwow, EV
  Database and the makers already give.

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
  the household's models); the technical-data block, which is one per model page, for a
  derivative it does not name, with values visibly out of place ("Engine Power - PS: True",
  "0 to 60 mph (secs): False"), its tyre size among them.
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
  example prints £449, which its own credit, APR, final payment, total and banner do not
  support (they give about £500): the app marks it as not adding up. Elsewhere its printed
  monthly is a price point up to £1.30 under what its APR and total give (£399 for £400.12),
  and its total payable leaves out its own contribution and the grant.
- **Lloyd and RRG:** the total payable counts the government's Electric Car Grant (£3,750 or
  £1,500) as paid, RRG's EV4 example does not; either way the rest of the example agrees.
- **Left:** Kia's own offer pages (`kia.com/uk/new-cars/offers/<model>/`): contributions per
  trim, the grant per trim, the order window (to 15 Dec 2026). Four pages; a new source, so it
  needs its own survey first.

## Kia

### kia_specs

`kia.com/uk/new-cars/<model>/specification/` prints grade tables for equipment and, per
powertrain or seat count, performance, charging, dimensions, weights and towing.

- **Read:** since 11 Oct also DC and AC charge times per charger, braked towing, the PV5's
  5-seat and 7-seat tables, the EV6's Wh/km as mi/kWh, cells that span several columns. Since
  14 Oct the PV5's leg, head and shoulder room for the 1st and 2nd rows, per seat count (the
  only Kia page that prints them).
- **Left:** torque, the battery pack table (cells, voltage, weight), CO2, city range, track
  widths, service interval; the PV5 7-seat's 3rd-row room (no other car prints one, so it has no field yet);
  tyre sizes, which NCD's page gives per derivative. Kia prints no prices here.
- **V2L:** Kia's tables call the cabin socket "Vehicle-to-Load (V2L) Capability" and give the
  charge-port adapter its own "... with Adapter" row; the parser says so. Elsewhere those words
  alone do not place the socket (Carwow's line for a Cupra Born VZ), so they count only as V2L.
  A line that names an adapter or the charge port anywhere is the outside socket, whatever the
  word order: Carwow's configurator sells the VW group's "Adapter for V2L Charging (camping
  socket)", which until 14 Oct read as a cabin socket on 38 cars on sale. An outlet in the boot
  is inside the car.

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
  boot, weights, warranty). Since 14 Oct the Ioniq 6's 1st and 2nd row head room and 1st row
  leg room, per trim; no other guide prints interior space.
- **Left:** there is no Ioniq 3 guide (its downloads page 404s); tyre sizes, which NCD's page
  gives per derivative.

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
- **Heat pump:** the card says only "available" or "not available", and "available" covers
  standard and option. Since 14 Oct the car shows "std or opt" until its own page
  (`evdb_cars`) or a priced option says which; before, it showed "option".
- **Left:** the BCH lease headline (business hire, of no use to the household).

### evdb_cars

Each variant's own page (dimensions, warranty, charge curve, V2L, availability). Read within a
nightly budget; the site refuses the laptop often, so it rests after refused nights
(`pipeline/providers/politeness.py`).

- **Left:** "Electric Car Grant applied £1,500", V2H/V2G and Plug & Charge are printed and not
  mapped.

## ADAC

### adac

ADAC, Germany's motoring club, tests about 100 cars a year on a fixed procedure and grades them
on the German school scale (0.6 best, 5.5 worst). The grades are its testers' judgement on a set
route, calibrated between testers, not instrument readings. Surveyed 13 Oct 2026. Page types,
under `https://www.adac.de/rund-ums-fahrzeug/autokatalog/marken-modelle/`:

| Page | Prints | Cost |
|---|---|---|
| `<make>/<range>/<generation>/<car id>/`, a car's page | the page's data as JSON (`window.__APOLLO_STATE__`) in the plain HTML. On the tested car's page: the Autotest (date, the car tested, the overall grade, seven sections with their sub-grades, target-group scores, strengths and weaknesses, the PDF's path). On every car page: the model's breakdown statistics, every test of the generation (`rangeTests`), the maker's specification, German prices and running costs, Euro NCAP, the measured charging curve | one request, 0.6 to 1.3 MB |
| the test PDF (assets.adac.de) | the same grades, and ADAC's own measurements: boot, turning circle, the tyres fitted (size and brand), braking from 100 km/h, noise at 130 km/h, Ecotest range, DC 10-80% | one request, 1 to 1.7 MB |
| `<make>/<range>/`, a range page | generations and years; the breakdown statistics of the range's latest generation that has any; no tests | 310 to 350 KB |
| generation and make pages | generations, body styles and years; no tests | 550 to 620 KB |
| `sitemap-autokatalog.xml` | 20,101 car pages | 2.5 MB |
| the Autotest index | a search the browser fills from `/bff`, which robots.txt disallows | not usable |

Every request in the survey returned 200 (217 pages 2 s apart), with no challenge page.

- **Read:** the tested car's page for each catalogue model with an electric test. `TESTS` in
  `providers/adac.py` names it: the newest electric test in the newest ADAC generation the
  model belongs to, an N model taking only N tests and no other model one. 124 of the 188
  catalogue models have one, on 101 pages. The Autotest's overall grade, Komfort (comfort) and its Federung
  (suspension), Karosserie's Verarbeitung (build quality) and Kofferraum-Volumen (boot),
  Innenraum's Raumangebot hinten (rear space), the family score, and what was tested
  ("Kona Elektro (65 kWh) Prime-Paket, 12/2023"); the rest of the grades are kept in the row.
  The breakdown statistics: callouts in Germany per 1,000 cars of the model first registered in
  each year from 2016 to 2023, graded 1 (sehr gut) to 5 (mangelhaft) against that year's
  spread, all powertrains of the model together ("Hyundai Kona" counts the petrol and hybrid
  cars too), and the recurring defects, which the app shows in English ("Starterbatterie" is the
  12-volt battery, "Fahrzeugelektrik allgemein" general electrics; a name not yet translated is
  shown as printed). The app shows the latest year. A test page carries only
  its own generation's statistics, so the facelifted Ioniq 5's has none; the range page of each
  model's test (100 pages) carries the range's latest generation that has any (the Ioniq 5's
  first generation: 19.5 per 1,000 for 2023 cars, grade 5), and the build takes it over a test
  page's. Pages are read again after 90 days, 25 of each kind a night, never-read ones first
  and the household's models before the rest: a test never changes, and the statistics once a
  year (April).
- **Mapping:** ADAC's generation is wider than our model, so the A6 Sportback reads the A6
  Avant's test and the EV4 Fastback the hatchback's, and its names are German (Opel for
  Vauxhall, `mercedes-benz`). Seven tests the survey's electric filter let through were petrol
  or diesel and were taken out (Range Rover D350, CLA 180, B 250, two Mini Coopers). The page's
  `rangeTests` are kept with each row, so a newer electric test of the generation can be seen.
- **Read, the test PDF** (the `pdf` capability, added 14 Oct 2026): the PDF of each test the
  page rows name (`document`), one a test however many models read it, with poppler's
  pdftotext as `hyundai_specs` reads the Hyundai guides. It runs from the last build's rows, so a
  newly read test's PDF follows a night later; 25 a night, never-read first and the household's
  before the rest, again after 90 days, and as never read when a model's test changes. From the
  "ADAC Messwerte" block: the tyres the test car was on (size and brand), the boot seats up and
  folded to the roof, the turning circle (the larger of left and right), braking from 100 km/h,
  noise at 130 km/h, 60-100 km/h, the test cycle's consumption and range (Ecotest to 2025,
  "Autotest" from 2026; both include charging losses, and the app shows them in miles), the
  width with mirrors, and the weight and payload as tested. From the electric-drive page: the
  energy for a full charge from the socket, and ADAC's own DC charge from 10 to 80% (time and
  average power). The model's ride grade names the tyres it was given on. Two layouts were
  checked on nine PDFs from 2019 to 2026: to 2025 one line a measurement; from 2026 two columns
  with some labels wrapped onto a second line, one turning circle or a left/right pair, and a
  charge time as hh:mm. The 2019 i3 test has no electric-drive page, so no charging figures.
  A measurement is said only while the model's test page names the same test.
- **Left, in the PDF:** the boot folded to the window line, 80-120 km/h (2026 layout only) and
  the price as tested (German), which are kept in the row; the 5, 10, 20 and 30 minute charging
  table; the AC charging times; the 2026 layout's interior measurements (legroom and headroom by
  occupant height, interior width), which the older layout prints only as a drawing; the
  equipment list, which is the German car's; the costs; the text.
- **Left:** German prices,
  running costs and insurance; the maker's specification, which our UK sources give; the
  conclusion text; Euro NCAP, which EV Database gives.

## What Car?

### whatcar

What Car?'s Reliability Survey asks owners of cars up to five years old about faults, repair
costs and time off the road, and rates each model as a percentage (39,332 owners and 225 models
in 2026). Surveyed 13 Oct 2026.

- **Pages:** one article per class, each writing up the ten most and ten least reliable models
  and ending with a table that ranks every model in the class (electric cars n26158, 19 models;
  electric SUVs n26161, 27), and one article for each year's edition overall (n27337, the 2026
  survey, published 22 Sep 2026: its top 20 and bottom 10, every fuel). All in the plain HTML;
  each page repeats the article in a script, which is not read.
- **Read:** the three articles, every night (three requests). Per model: the rating, its rank
  and the class size, the list it is written up in, the years it covers, the common faults, and
  the article's publication dates. The class articles are re-published in place and still carry
  the 2025 survey (modified April 2026), so a model's rating comes from the newest article
  naming it: the ID.4 is 66.9% (2026) rather than 79.6% (2025). Only models still on sale
  ("2021-present") are applied, so the 2018-2023 Kona Electric's 92.8% does not land on the
  current car. Since 13 Oct also each write-up's figures: the share of repairs that cost the
  owner nothing ("Average repair cost: 90% £0, ..."), the share of faulty cars off the road for
  more than a week ("Typical time off road: 56% more than a week, ..."), and the share of cars
  that had a fault, which is only in the prose ("Overall, 42% of Ioniq 5s went wrong, compared
  with 30% of EV6s"; "Thirty-six percent of ID 4 owners had gripes, compared with 30% of people
  with Enyaqs"). A sentence that says cars went wrong or had a fault gives its share of the cars
  or owners in general, or of the entry's own model, to the entry; a share of another model in
  the article goes to that model when it has none of its own; a share of faulty cars is not one.
  The sentence is kept and shown as the figure's source. 42 entries of the three articles have
  one. A name rates its variants filed as models of their own (the Ioniq 5 rates the
  Ioniq 5 N, the MG 4 the MG4 Urban, which over-reaches); the overall article is matched only
  by exact name, since its Porsche Macan is the petrol one.
- **Left:** the per-car lookup by registration (needs a login); the other class articles, which
  rate few electric cars.

## DVSA

### dvsa_recalls

The Driver and Vehicle Standards Agency's recall service. Surveyed 13 Oct 2026. Its pages: a
question (vehicle recalls or equipment), a search by make and model, a check by registration, and
two downloads, "All recalls since 1992 (CSV)" and a data guide (DOC). The service answers a script
with a JavaScript check (Imperva) and a browser with the file; it has no robots.txt, and the
data.gov.uk entry for it has no files. The owner, 13 Oct: "I think we should work around the
block. This is a personal product not a commercial one", then "its just a government check
they're not really serious about". So the fetch asks the installed Chrome to download the file
(`scripts/fetch-with-chrome.mjs`: Chrome started normally with a profile of its own, about 15 s,
nothing faked; a page asking a person to prove themselves is not answered).

- **The file:** 17,744 rows, one per recall and model line, from 9 Jan 1992: launch date, recall
  number, make (as the importer names itself: 'VW', 'MERCEDES-BENZ CARS UK LTD'), the model as the
  maker wrote it ('IONIQ 5', 'KONA OS EV', 'Kona SX2 1.0 T GDI', 'PV5'), concern, defect, remedy,
  vehicles affected, the maker's reference, VIN and build ranges. A recall that follows one whose
  fix did not hold says so ("recall R/2023/154 has been incorrectly completed").
- **Read:** every row launched since 2012 whose make is not a lorry, bus, motorcycle or caravan
  maker (10,932 rows). The build lays them over the catalogue (`claims.recalls_by_model`): a line
  names the model of its make whose words begin it ('KONA OS EV' is the Kona Electric's), the
  longest such ('Ioniq 5 N' is the N's), or when none does, the models whose words it begins
  ('PV5' is the PV5 Passenger's); a make the importer files elsewhere is followed ('CUPRA BORN'
  under SEAT). A line that names an engine ('1.0 T GDI', 'HEV') or, not saying electric, has its
  defect in parts an electric car lacks (the gearbox, the fuel system) is left: Hyundai's 'Kona'
  covers petrol, hybrid and electric cars. Lines of one recall are combined per model. 141 of the
  249 catalogue models have a recall. The app shows the count, the latest, and each recall in a
  line on the car page; a recall that names an earlier one says "Follows R/..., a fix that did not
  hold" and the earlier "Followed by R/...".
- **Left:** the VIN ranges; the registration check (per car, for the reader); other equipment;
  older generations are not told apart from the current one (the build dates show which).

## NHTSA

### nhtsa_recalls

The US National Highway Traffic Safety Administration's recall register. Surveyed 14 Oct 2026. The
UK register rarely says when a recall replaces one whose fix did not hold; NHTSA's usually does
("This recall expands and replaces previous recall number 24V-204. Vehicles previously repaired
under recall 24V-204 will need to have the new remedy completed"). api.nhtsa.gov and
static.nhtsa.gov need no key and refused none of about 520 requests at five a second;
www.nhtsa.gov (the VIN lookup) answers a script with 403.

- **The open API, surveyed and left.** `products/vehicle/modelYears?issueType=r` (1949 to 2027),
  `products/vehicle/makes?modelYear=&issueType=r` (247 makes for 2024),
  `products/vehicle/models?modelYear=&make=&issueType=r` (the models with a recall that year) and
  `vehicles/models?make=&modelYear=` (every model, paged) list names; `recalls/recallsByVehicle?make=&model=&modelYear=`
  gives one row per recall: campaign number, report date (dd/mm/yyyy), component, summary,
  consequence, remedy, notes, park-it and park-outside advice, over-the-air flag, no vehicle count
  (400 and `Count: 0` for a name it does not know); `recalls/campaignNumber?campaignNumber=` gives
  the same with `PotentialNumberofUnitsAffected` and every make, model and year in the campaign.
  It cannot list a model's recalls: the model lists use product names the recalls do not
  ('MUSTANG MACH-E', where the recalls say 'MUSTANG MACH E'), and `recallsByVehicle` answers only
  for a name as one campaign wrote it ('EQS450' in 21V-931, 'EQS 450' in another). Asked by the
  model lists' names it returned nothing for the 2021 Mach-E and the 2022 EQS; asked by the file's
  names, nothing for the 2021 XC40BEV and 1 of the 13 recalls the file lists for the 2022 EQS 450.
  Reading it by name and model year would take about 535 requests and still miss these.
- **The file:** `FLAT_RCL_POST_2010.zip` (15 MB zipped, 311 MB of text, 245,855 lines, rebuilt
  daily; field guide `RCL.txt`): one tab-separated line per campaign, make, model, model year and
  component, with the maker's reference, build dates, US vehicles affected (the campaign's total),
  report and owner-letter dates, who started it, defect, consequence, remedy, notes, and the
  do-not-drive and park-outside advice. `FLAT_RCL_PRE_2010.zip` and the quarterly and annual
  completion reports sit beside it.
- **Read:** every vehicle recall of model year 2019 or later whose make and model name match a
  catalogue model sold in the US (`nhtsa_recalls.MODELS`: the make and the pattern its recall
  records follow, written from the API's model lists of 2019 to 2027 and the file's own names).
  366 campaigns. 96 of the 249 catalogue models are sold in the US; 84 of them have a recall; the
  other 12 (A6 and S6 Avant e-tron, iX3, Ioniq 6 N, EV3, Eletre, MX-30, GLC electric, Polestar 4
  and 4 SUV, Cayenne Electric, EX60) have patterns written from the product names, unconfirmed
  until a recall uses one. The Ioniq 5 N's recalls are filed under IONIQ 5, so the N reads IONIQ 5
  from model year 2025 (the Ioniq 6 N IONIQ 6 from 2026). The Lexus ES Electric and Range Rover
  Electric are filed under names their petrol and hybrid cars share, so they are not read and
  their card says so. The fetch is weekly (`FRESH_DAYS`); the build reads the file in about 10 s.
- **Links:** a sentence naming another recall says how: replaced by it, cars fixed under it need
  the fix again ("a fix that did not hold"), it replaces or supersedes it, or it expands it to
  more cars. 55 of the recalls read name another, 23 as a fix that did not hold. The app shows
  the count, the latest report date and each recall in a line on the car page; models not sold in
  the US say so. The lines add about 3 MB to `cars.json` (the UK lines are 5 MB).
- **Left:** equipment, tyre and child-seat recalls; model years before 2019; component part
  numbers; owners' complaints (`complaints/complaintsByVehicle`, 350 for the 2021 Mach-E) and the
  investigations a recall cites, each worth a survey of its own; the completion reports (the share
  of recalled cars fixed); the VIN lookup (per car, for the reader).

## Parkers

Surveyed 16 Oct 2026; not read yet. Bauer's used-car valuation site. The owner asked for "a
definitive list of trims"; CAP's is licensed (quote only, a subscriber id from Cap HPI), and
Parkers is the nearest free one: every generation of a model, each with its trims and every
derivative, old ones included, which a valuation site needs to price used cars.

- **Robots:** ordinary crawlers may read the spec pages (the file disallows only a used-car finance
  path, `_qs` query strings and `/purchase/`, and bans a list of named scraper programs). No
  crawl delay is set. The terms page came back as 2,709 characters with no text on automated use
  (probably drawn by script); not confirmed either way.

| Page | Prints | Cost |
|---|---|---|
| Sitemap, `sitemap.xml` and its `spec-1`, `spec-2`, `spec-3` files | every spec page's address: 136,599 across all fuels, of which 100,187 derivatives. The address names the model, the generation with its body and start year (`kona-electric/suv-2018`, `suv-2023`; body styles are generations: `q4-e-tron/sportback-2021`, `ioniq-5/n-2023`), each trim (`trim-ultimate`), each engine (`engine-160kw-65kwh-electric`) and each derivative in CAP's wording with its packs (`160kw-ultimate-65kwh-5dr-auto-[lux-pack]`) | 4 requests, 1.1 MB |
| Generation page, `<model>/<generation>/specs/` | the generation's years ("2018 - 2023"), its trims and engines | 1 a generation |
| Trim and engine pages | the derivatives of that trim or engine | 1 each; nothing the sitemap lacks |
| Derivative page, `<model>/<generation>/<derivative>/specs/` | its on-sale dates ("March 2021 - June 2023"); price when new (£39,900); a used price range (£11,398 - £19,038); battery, power, 0-60, efficiency, range, insurance group, road tax, length, width, weight, wheelbase, turning circle; charging times by charger; the standard equipment list (124 items for that Kona) and the options (23); cars for sale | about 180 KB each; about 4,000 electric derivatives |

- **Coverage:** 285 electric generations under 230 models by the sitemap's addresses (a derivative
  whose address names a kWh). Our 250 catalogue models are Carwow's, which treats body styles as
  models: 142 match a Parkers model by slug, and the rest are mostly body styles Parkers files as
  generations (the Q4 e-tron Sportback is `q4-e-tron/sportback-2021`) or names spelled apart
  (`junior-electric` against `junior`). Electric versions of mixed models are under their own
  model where Parkers makes one (`peugeot/e-208`). The first-generation Kona: trims SE, SE
  Connect, Premium, Premium SE and Ultimate, under two naming styles that are two eras (Premium
  SE "204PS auto 5d", December 2019 to January 2021; "150kW Ultimate 64kWh 5dr Auto", March 2021
  to June 2023), not duplicates.
- **Against Carwow's current trims:** the same for the Kona, EV3 and Ioniq 5, plus the older ones
  (Ioniq 5 SE Connect, Project 45, Ultimate Plus; EV6 Wave, Horizon). Its trim words need the
  shared normaliser like any source's: the Enyaq's battery sits in its trims (`80x-sportline`),
  the MG4's "-ev" (`se-ev`), and `standard-trim` is a placeholder, not a trim.
- **What it would be for:** the list of trims and derivatives, with their on-sale dates, that the
  resolver's car level lacks (`docs/REBUILD.md`, "Next: one resolver over every record"): every
  generation's trims as structured records, so a used 2021 Kona finds "Ultimate" under the
  64 kWh version, and a lease's or a listing's text joins a trim that a structured source names.
  The price when new gives an old derivative the list price the trim scaling needs. The
  equipment lists would give old cars their heat pump and cabin socket.
- **Left, and why:** cars for sale (the sites we already read print them); the used price range,
  which spans a derivative's years and mileages and is Parkers' valuation rather than a seller's
  price; reviews.
- **Cost of a read:** the sitemap weekly (4 requests). Derivative pages within a nightly budget
  and a freshness rotation, as `evdb_cars` does: about 4,000 pages, so about 20 nights at 200 a
  night for the first pass, then the new and changed ones.

## Reliability sources surveyed and left

Surveyed 13 Oct 2026 for evidence of how a model holds up in owners' hands.

- **Which?** (63,334 owners): the model names are withheld from non-members.
- **Auto Express Driver Power 2026:** an overall top 50 and a reliability top 10, which cover two
  of the household's candidates (Model 3, Model Y).
- **TÜV Report 2026:** the share of cars failing the German roadworthiness test on significant
  defects, which measures wear (brakes, suspension, lights) rather than reliability. Its 18-EV
  table is in a presentation PDF on a third-party site; the full table is in a paid booklet.

## What is still on the table, by value

1. Detail pages for used cars: registration and keepers (cinch, Motorpoint, Carwow), battery
   health (Motorpoint). One page per car; 145 and 43 for Hyundai and Kia at cinch and
   Motorpoint.
2. Kia's own offer pages: the order window and per-trim contributions. Four pages.
3. NCD's HP quote.
4. Carwow's configurator, once its new flow is surveyed.
5. LeaseLoco's other deals per model, if its price API can be found.
6. ADAC's test PDFs are read (14 Oct). Still in them: the 2026 layout's interior measurements
   (rear legroom and headroom by occupant height, interior width), and the charging table at
   5 to 30 minutes.
7. A new ADAC test of a generation is seen in `rangeTests` but read only once `TESTS` names it.
