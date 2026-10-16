# Architecture

## What it does

Every night it collects what UK sellers and reference sites say about electric cars, keeps every
page it fetched, turns those pages into one set of facts per car and a price history, and
publishes the result as files that a static web app reads. The app then costs every deal under
the reader's own assumptions.

It is an ETL with one rule: only the fetched pages are kept. Everything between them and the
published files is rebuilt from scratch every night, so a better parser or matcher corrects the
past as well as the future. The only other thing that lasts is the owner's decisions. Until the
next step lands, the build also reads a set of cars, offers and a lookup table typed in by hand on
6 Oct, before any scraper existed; they go with it.

The next step, a new way of deciding which car a record is, is in `ARCHITECTURE-NEXT.md`.

## The flow

```
                 nightly                each build, from scratch
   sources ───────────────▶ raw store ─────────────────────────────────────────────▶ snapshot ──▶ app
   (sites,                  every page    parse      identify     facts and prices    (JSON files,  (costs every
    the owner's files)      kept forever ───────▶ records ───────▶ cars ──────────────▶  published)    deal in the
                                                                                                   browser)
```

## Data model

| Thing | What it is | Identity |
|---|---|---|
| Fetch | one response from one site: when, from where, its status and body | the body's content hash, plus the time |
| Record | one thing one source said, read from a fetch: an offer, a spec table, a used car for sale, a test grade, a recall | the source and a key stable at that source |
| Car | one exact version of a car on one price list (a CAP derivative), or a car the owner entered | the CAP id, or the owner's id |
| Claim | one source's statement of one fact about a car, at a level: this car, its trim, its trim and battery, its engine, its model, an EV Database variant | the fact, the level, the source |
| Fact | a car's value for a field: the strongest claim at the nearest level; where equally strong claims disagree, unknown, with both kept | car and field |
| Offer | one source's price for one car by one route (cash, PCP, lease) over the days it stayed the same, with the whole deal (deposit, term, APR, guaranteed future value) | the source's own key for the offer |
| Used car | one car for sale on a used site: asking price over time, registration year, mileage | the site's listing, and its registration mark across sites |

## Extract

- **Sources.** Prices come from Carwow (deals, configurator, used stock), the brokers and dealers
  (New Car Discount, LeaseLoco, RRG, the Kia dealer groups) and the used sites (cinch,
  Motorpoint). Specs come from Carwow, the makers' own tables and guides, EV Database and
  Parkers. Tests and reliability come from ADAC, What Car? and Carwow's reviews, and recalls from
  the UK and US registers. What each prints, what we read and what we leave: `SOURCES.md`.
- **Schedule.** One job a night on the owner's laptop. Sources with many pages read a budget a
  night, oldest pages first.
- **Every response is kept**, refusals included. A site that refuses is left alone for the rest
  of the night, rests for a growing number of nights, and comes back a few pages at a time. A
  page not fetched loses nothing: what earlier pages said still stands.
- **Two more sources** are read like the sites: the data committed before the raw store
  existed (6 to 10 Oct 2026, pages not kept, so only its matching is re-derived), and the owner's
  own files.

## Transform

1. **Parse.** Every stored page is read again by its source's parser each build. Results are
   cached by page and parser version, so changing a parser re-reads every page it ever fetched.
2. **Identify.** Each record is tied to a car, today by four separate lookups:
   - a record that prints a CAP id belongs to that derivative;
   - a broker's text is matched to Carwow's list of derivatives by rules (make, model, kW, kWh,
     trim words must agree; the record's own list price tells apart twins, derivatives of one
     trim that differ only by packs);
   - an EV Database variant is tied to a car by battery size and year;
   - a used car is tied to a trim by its trim words and a battery within 3 kWh.

   The 6 Oct lookup table overrides all four. A record none of them places is listed, never
   guessed. Petrol versions that electric models' pages also list are not cars.
3. **Facts.** Every source's statements become claims; each car's facts are resolved from them
   when the snapshot is written. A car's own source outranks its trim's, its trim's its model's.
   For equipment, a maker's table outranks a seller's list, and "not listed" counts only where
   the list is complete.
4. **Prices.** Each offer becomes a run of days at one price. An offer is current while its
   source showed it within the last 14 days, and gone after that.

## Load

The snapshot is a set of JSON files, rebuilt every night and committed to the repo, which
publishes the site. It holds facts only, never costs, because costs depend on the reader's
settings.

| File | Holds |
|---|---|
| cars | every car with its facts |
| details | per car, where each fact came from and what disagreed; per model, the long text its cars share (Carwow's review, the recall lines) |
| sightings | every offer's runs of days, with the whole deal |
| used | every used car's asking price over time |
| specs | every spec table read, per variant |
| models | the catalogue of every electric model |
| data | what each source did night by night, for the app's Data page |

Each night's commit is a dated copy of the market, which is the price history.

## Costing

The app costs every deal in the browser, so the reader's own settings (term, savings rate,
resale assumption) apply to everything at once.

- **The true monthly** puts every route on one footing: each payment discounted at the reader's
  savings rate, nothing paid down, the car's expected value at the end credited back, and what
  is left spread over the reader's term (37 months unless they change it). A lease pays
  rentals and gets nothing back. A PCP pays its payments and keeps the choice to buy at the
  guaranteed future value. Cash and used pay the price now and sell at the expected value.
- **Rules.** Compare total cost, never the monthly payment. The guaranteed future value is a
  floor, not a forecast. An APR means something only against the best like-for-like cash
  price. A quote whose own figures do not add up is shown but not ranked.
- **The end value** is the median asking price, now, of used cars of the same model as old as
  the term, scaled to the car's trim by its list price. A used car's own end value is its price
  scaled the same way from its own registration year. A figure resting on fewer than 10 used
  cars is marked "few cars", and a search can leave such figures out. Without used evidence the
  end value is the highest guaranteed future value grown at the savings rate, and failing that
  the reader's assumption (45% of list after 36 months unless they change it).
- **Deals of other lengths** are costed over the reader's term: a longer PCP is settled early,
  a shorter one's final payment is made and the car kept.
- **Cash against finance.** For each car the app shows the savings rate, and the resale price,
  at which its cheapest PCP and lease cost the same as its cheapest cash price.

Costs are worked out again whenever the snapshot, the reader's settings, the day or the costing
itself changes.

## Running it

- **The nightly job** fetches, builds and publishes. Its log is on the laptop, and is the first
  thing to read the morning after a change.
- **A code change goes live** by building from the pages already held and publishing, with no
  fetching.
- **Tests.** Every parser is tested on a real page captured from its site, and builds are
  tested over stored pages. CI runs the tests on every push, and the push publishes the site.
- **When a site changes its layout,** its source shows 0 records and its prices go stale a
  fortnight later. The parser is fixed against a freshly captured page, and the next build reads
  every stored page again with it.
