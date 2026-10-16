# Sources

What each source gives us, what we leave and why, and what reading it costs. The rule this file
serves: no new source without a survey. Before a reader is written, list every page type the site
has, what each prints that a buyer could use, and the cost of reading it; then record here what
is read and what is left. Data on a page we already fetch and do not read is a bug, and goes on
`BOARD.md`.

| Source | What it gives | Pages a night |
|---|---|---|
| Carwow catalogue | every electric model on sale, the list the other Carwow readers work from | about 48 |
| Carwow model pages | every derivative's CAP id, name and list price; Carwow's review | about 249 |
| Carwow spec pages | per derivative: equipment, range, efficiency, 0-62, prices | about 219 |
| Carwow deals | best cash price per derivative, PCP prices, one example PCP per model | about 178 |
| Carwow configurator | options and packs per derivative, with prices | up to 250 |
| Carwow used | used stock: price, year, mileage, derivative | 700 to 1,240 |
| cinch | used stock with a finance quote each; new cars with a PCP and cash price | about 131 |
| Motorpoint | used and nearly-new stock with its lowest monthly | about 18 |
| New Car Discount | broker cash price per derivative, a PCP quote, tyre sizes | about 250 |
| LeaseLoco | best personal lease per derivative, and one in-stock deal | about 249 |
| RRG, Lloyd, Halliwell Jones | Kia dealers' PCP and lease examples | about 38 |
| Kia | grade tables: equipment, range, charging, towing, dimensions | 4 |
| Hyundai | national offers; the PDF price and spec guides; every orderable configuration | about 29 |
| EV Database | per variant: measured range, efficiency, charging, dimensions, on-sale dates | 1, and up to 60 car pages |
| Parkers | every generation's trims and derivatives, with on-sale dates and price when new | up to 400, sitemaps weekly |
| ADAC | test grades (ride, build quality, space), breakdown statistics, measurements of the car tested | up to 75 |
| What Car? | owners' reliability rating per model, the share that had a fault | 3 |
| DVSA | every UK safety recall | 1 file |
| NHTSA | every US safety recall, and which recall replaced which | 1 file a week |

## Carwow

**Catalogue.** Every electric model on sale and which page types it has. Nothing left.

**Model pages.** The registry of derivatives: CAP id, name, list price, price-list date. Also
Carwow's review: "What's good", "What's not so good", and every section by heading (back seats,
ride in town and on the motorway, interior, reliability) as Carwow wrote it, not scored. Left: the
review's FAQs, which repeat the numbers, and the petrol versions some electric models' pages list.

**Spec pages.** Per derivative, keyed by its CAP id: equipment, range, efficiency, 0-62, top
speed, power, drive, prices; model facts (seats, doors, boot, turning circle, wheelbase). A figure
printed as a range for the model ("350 - 1,330 L") is not given to any one derivative. Nothing
numeric left.

**Deals.** One card per derivative (list price, best cash price, PCP price, contribution and APR
footnotes) and one representative PCP example per model. The cash price is Carwow's best across
its dealers, so it is a lead, not a named dealer's offer. Left: named dealer offers, which need a
logged-in quote page.

**Configurator.** Every option and pack with its price, whether fitted, and what each pack
bundles; never-read pages first, then those older than a week. It gave no records from 12 to 14
Oct and 239 from 250 pages on 16 Oct with no change on our side (`BOARD.md`, T11). Left: colour
prices, and which options exclude others.

**Used.** Every car in a model's results, with price and year; about four come in full per page,
the rest are fetched one card at a time within a budget. The results come back in a different
order each time, so a car counts as gone only after a week unseen. Left: each car's own page
(registration, owners, equipment, warranty), about 6,900 pages for all of them.

## cinch

**Used.** Every listing for each make: price, year, mileage, the derivative text, registration,
drive, colour, and the full finance quote each carries (all reconcile). Also each listing's own
trim, seats, doors, body type and fuel (which marks the range-extender MX-30 and i3), its range in
miles with the test it comes from (WLTP, or NEDC on some older cars, which reads higher), and
whose stock it is (cinch's own, a marketplace dealer's or a partner's). Left: cinch's own update
stamps; the engine size and miles per gallon, which are blank or meaningless on an electric car;
the fields that are the same on every listing (automatic, used, published, available, no deposit
contribution); the second copies of the year, model and registration. Also left: the detail page
(keepers, service history, equipment, battery warranty), one per car.

**New.** A PCP quote from cinch's retail partner and the cash price per new car.

## Motorpoint

Every listing: price, year, mileage, derivative, list price when new, lowest monthly, warranty
left; cars not yet on the forecourt are marked. Left: the detail page (battery health,
registration, keepers, service and MOT history, equipment, full PCP and HP terms), one per car.

## New Car Discount

Each derivative's broker cash price and saving, and its PCP quote at the page's own defaults
(marked illustrative, as NCD says). From each derivative's technical table, the tyre and wheel
sizes, from which the build works out the sidewall height (106 cars on sale, all Hyundai and Kia);
ride is graded by ADAC instead, since the survey found sidewall does not decide it across models.
NCD prints the make before the model on Kia listings, and files one copy of the EV6 GT as a
diesel, which is skipped. Left, and a bug: NCD's prices are matched by their text, not by the CAP
id its pages print (`BOARD.md`, T5). Also left: the HP quote, and the rest of the technical table,
which other sources give.

## LeaseLoco

The best personal lease per derivative and profile (converted from ex-VAT), and the in-stock deal.
Left: the thousands of other deals per model, which load from an API not traced; the equipment
page per derivative; a technical block whose values are visibly out of place. A guessed model page
that 404s is not asked again for a week.

## Kia dealers

**RRG.** Every electric Kia offer, PCP and lease. RRG copies derivative lines between pages (the
EV6 "Air" at the GT-Line's price), so a price that fits no derivative its text names is recorded
as a conflict, not a car.

**Lloyd and Halliwell Jones.** Each offer page's PCP example. Halliwell Jones's captions are
often wrong, so its examples are named from the page heading; some of its printed monthlies do not
add up from its own figures, and the app marks them. Left: Kia's own offer pages (contributions
and grant per trim, the order window), a new source needing a survey.

## Kia

The grade tables: equipment, range, charging times, towing, dimensions, weights, the PV5's 5 and
7-seat tables and its row-by-row cabin room. Kia's tables call the cabin socket "Vehicle-to-Load
(V2L) Capability" and the charge-port adapter "... with Adapter"; elsewhere those words alone do
not say where the socket is, and an adapter or the charge port named anywhere in a line means the
outside socket. Left: torque, the battery pack table, CO2, track widths, service interval, the
PV5 7-seat's third-row room (no other car prints one). Kia prints no prices here, and its finance
quote service answers "No quote available" to everything.

## Hyundai

**Offers.** Each model's PCP and loan examples with the order window; the grant and the
example's paint are read so the figures reconcile.

**Guides.** Hyundai has no readable spec page, so its PDF price and spec guides are read: grade
equipment, the price table per powertrain, option prices, towing, range, charging, boot, weights,
warranty, and the Ioniq 6's head and leg room. Left: there is no Ioniq 3 guide.

**Configurator.** Every orderable configuration with its price and packs. Left: paint, wheel and
interior prices, delivery dates, and a PCP quote the site seems to offer but whose query is unknown.

## EV Database

**Index.** A card per variant: measured range, efficiency, battery, charging, weight, towing,
boot, price, seats, on-sale dates. Its heat pump says only "available", which covers standard and
option, so the app shows "std or opt" until a closer source says which. Left: the business lease
headline.

**Car pages.** Each variant's full page: dimensions, warranty, charge curve, V2L outlets,
availability. The site refuses quickly, so pages are read slowly (60 a night) and the reader rests
after refused nights. Left: grant notes, V2H, V2G and Plug & Charge.

## Parkers

Bauer's used-car valuation site, read since 16 Oct as the master list for the resolver (CAP's own
list is licensed). The sitemaps name every generation of every model with its body and start year,
each trim, each engine, and each derivative in CAP's wording with its packs: four requests. Each
electric derivative's page gives its on-sale dates, price when new, power, battery, range,
efficiency, dimensions, insurance group, charging times and equipment. All 4,027 were read on 16
Oct; then 400 a night, newest first. Parkers files body styles as generations of one model, unlike
Carwow, so its models need mapping (`BOARD.md`, T2). Its equipment is what a version had "at some
point during its production lifespan", weaker evidence than a maker's table. Left: cars for sale,
the used price range (a valuation, not a seller's price), reviews. Its robots file allows the spec
pages; its terms page did not render without a browser. Its records stay out of the app until the
resolver reads them.

## ADAC

Germany's motoring club tests about 100 cars a year on a fixed route and grades them on the German
school scale (0.6 best, 5.5 worst): the testers' judgement, not instrument readings. Read per
model with an electric test (124 catalogue models on 101 tests): the overall grade, comfort,
suspension, build quality, boot, rear space, the family score, and what was tested. From each test
PDF, ADAC's own measurements: tyres fitted, boot, turning circle, braking, noise at 130 km/h, range
and consumption on its cycle, DC charging 10 to 80%, width, weight, payload. From the range pages,
breakdown statistics: callouts per 1,000 cars by first-registration year, graded against cars of
that age, all powertrains of the model together, with the recurring defects in English. 25 pages
of each kind a night, each again after 90 days. ADAC's generations are wider than Carwow's models
and its names German, so some models read a sibling's test. Left: German prices and costs, the
maker's specification, Euro NCAP (EV Database gives it), the 2026 PDFs' interior measurements and
the charging table at 5 to 30 minutes.

## What Car?

The Reliability Survey: owners of cars up to five years old rate each model (39,332 owners, 225
models in 2026). Three articles a night: the electric cars and electric SUVs class tables and the
overall edition. Per model: rating, rank in class, common faults, and from the write-ups the share
of cars that had a fault, of repairs that cost nothing, and of faulty cars off the road over a
week. The newest article naming a model wins, and only models still on sale take a rating, so the
2018-2023 Kona's does not land on the current one. Left: the per-car lookup (needs a login) and
classes that rate few electric cars.

## DVSA

The UK recall service's "All recalls since 1992" file, downloaded nightly by the installed Chrome,
since the service blocks scripts and the owner decided to work around it (`DECISIONS.md`): nothing
faked, and a page asking a person to prove themselves is not answered. Every recall since 2012 is
laid over the models it names; a line naming an engine, or with its defect in parts an electric
car lacks, is left, since Hyundai's "Kona" covers petrol, hybrid and electric cars. A recall that
follows one whose fix did not hold says so. 141 of 249 models have one. Left: VIN ranges, the check
by registration, equipment recalls.

## NHTSA

The US recall register's complete file, weekly (15 MB): every vehicle recall of model year 2019
on, for the 96 catalogue models sold in the US (84 have one). It says when a recall replaces one
whose fix did not hold, which the UK register rarely does. Its open API was surveyed and left: it
answers only for a model name exactly as one recall spelled it. Left: older years, equipment and
tyre recalls, owners' complaints and investigations (each worth a survey), completion rates, the
VIN lookup.

## Surveyed and left

- **Price and finance:** Richmond's and cars2buy's sites block scripts; Arnold Clark is drawn by
  script; Auto Trader's monthlies are dealer-supplied or a broker's generic example; Zuto,
  MoneySuperMarket and Quotezone quote only after a credit application.
- **Reliability:** Which? withholds model names from non-members; Auto Express Driver Power ranks
  too few electric cars; the TÜV Report measures wear, not reliability, and its full table is paid.

## Still on the table

1. Used cars' own pages: registration and keepers (cinch, Motorpoint, Carwow), battery health
   (Motorpoint); one page per car.
2. Kia's own offer pages: the order window and per-trim contributions; four pages.
3. Other Kia and Hyundai dealer groups' offer pages (Snows, WJ King, Howards, Gravells), many on
   shared dealer-website platforms.
4. NCD's HP quote.
5. LeaseLoco's other deals, if its price API can be found.
