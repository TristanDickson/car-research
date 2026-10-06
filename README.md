# car-research

A persistent platform for evaluating cars and car deals: which car is right for me, what a
car is intrinsically worth, and what a given deal (PCP, HP, used, cash) actually costs once
the headline numbers are unpicked.

## Why this exists

Our current PCP ends on **10 December 2026**. Rather than repeat the "walk into a dealer and
react to the monthly figure" process, the aim is to build something reusable that:

1. Captures **what I need from a car** as structured, weighted requirements (to be imported
   from the existing ChatGPT discussion; see *Context log* below).
2. Estimates how **intrinsically good value** a car is. Working assumption: there is a real
   base cost to design, build and ship a car that manufacturers price against. A model that
   approximates that cost from spec (segment, battery kWh, power, size, equipment, platform
   sharing, volume) gives a yardstick for "what should this cost?" independent of marketing.
3. Decomposes **deals** into a true cost of ownership so that PCP, HP, used and outright
   purchase can be compared on the same footing.

### The PCP obfuscation problem

PCP routinely quotes a *finance* price that differs from the *cash* price for the same car.
"0% APR" on a £43k dealer price is not free money if the same car can be bought outright for
less, or if the guaranteed future value (GFV) is set low so the monthlies look right. The
real cost of the credit is hidden in the gap between those prices and in the GFV.

To compare honestly, every deal gets normalised to:

- **Total paid over the term** (deposit + monthlies + fees + optional final payment)
- **Implied interest** vs. the best available cash price for the same car
- **Equity position at term end** (GFV vs. expected market value)
- **Cost per month of ownership** under the hand-back and buy-out scenarios

### Worked example: the current deal (Hyundai Ioniq 5)

| Item | Value |
| --- | --- |
| List price | £46,000 |
| Dealer / finance price | ~£43,000 |
| Deposit | £0 |
| APR | 0% |
| Monthly | £540 x 36 |
| Total of monthlies | £19,440 |
| Implied GFV (derived: £43,000 - £19,440) | ~£23,560 |

The derived GFV is the figure the deal only works at. If the car is worth more than ~£23.5k
in December the equity is real; if it is worth less, the 0% APR was partly paid for through
the GFV. Confirm against the actual finance agreement before relying on this.

## Options under consideration this time

- New car on PCP (as before)
- New car bought outright
- Second-hand car (dealer or private), outright or financed

## Architecture

Same pattern as my other data-exploration projects (`bolthole`, `etf-analyzer`,
`wine-and-cheese`):

```
scrapers / importers (batch, run on the dev machine)
        |
        v
local database (SQLite) -- source of truth, committed to the repo as data
        |
        v
export step -> static data files in the SPA's public dir
        |
        v
SPA on GitHub Pages -> on load, bulk-imports data into an in-browser DB
                       (sql.js / IndexedDB) for fast client-side filtering
```

Key properties:

- **Batch, not live.** Scrapes run locally and the resulting data is committed. GitHub Pages
  serves static files only, so the SPA never scrapes anything itself.
- **Data is versioned.** Every commit of the data files is a snapshot of the market on that
  date, which gives price history for free.
- **Fast browsing.** The browser loads the whole dataset once and queries it locally.

## Planned repo layout

```
data/           committed data snapshots (SQLite + exported JSON/CSV)
scrapers/       batch scripts that populate the local DB
model/          intrinsic value model and deal normalisation logic
web/            SPA (deployed to GitHub Pages)
docs/           requirements, decisions, research notes
```

## Data to capture

**Cars** (per model / trim / model year)
- Spec: body, segment, dimensions, boot, powertrain, battery kWh, WLTP range, power, charging
  speeds, equipment highlights, platform
- Pricing: list (OTR) price, typical dealer discount, used asking prices by age/mileage
- Running costs: efficiency, insurance group, VED, tyre sizes, servicing intervals
- Reliability and ownership signals where available

**Deals** (per offer, dated)
- Source, car, cash price, finance price, deposit, contributions, APR, term, monthly, GFV,
  fees, mileage allowance, excess mileage charge
- Derived: total paid, implied interest, equity at end, monthly cost of ownership

**Requirements** (mine)
- Weighted criteria and hard constraints, imported from the ChatGPT discussion

## Context log

- **2026-10-06** Project started. Current car is a Hyundai Ioniq 5 on a 36-month, 0% PCP
  ending 10 Dec 2026 (details above). ChatGPT conversation covering personal requirements and
  earlier research to be imported next.

## Status

Bootstrapping. No code yet; this README defines the intent and the shape of the platform.
