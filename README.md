# car-research

A persistent platform for evaluating cars and car deals: which car is right for us, what a car
is intrinsically worth, and what a given deal (PCP, PCH, used, cash) actually costs once the
headline numbers are unpicked.

## Why this exists

Our Ioniq 5 PCP ends on **10 December 2026**. Rather than repeat the "walk into a dealer and
react to the monthly figure" process, the aim is to build something reusable that:

1. Captures **what we need from a car** as structured, weighted requirements
   (`docs/requirements.md`, `data/seed/requirements.json`).
2. Estimates how **intrinsically good value** a car is. Working assumption: there is a real
   base cost to design, build and ship a car that manufacturers price against. A model that
   approximates that cost from spec (segment, battery kWh, power, size, equipment, platform
   sharing, volume) gives a yardstick for "what should this cost?" independent of marketing.
3. Decomposes **deals** into a true cost of ownership so that PCP, PCH, used and outright
   purchase can be compared on the same footing (`model/deal_math.py`).

### The PCP obfuscation problem

Three things move independently and sellers shuffle value between them: the **vehicle price**
(list, dealer discount, government grant), the **finance support** (APR, manufacturer
contribution) and the **GFV** the lender underwrites. A low APR is worthless if the car's price
under that finance is £3-5k above the best cash price elsewhere. A high monthly can be cheap
money with a pessimistic balloon. Examples we have already hit:

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
Full rules in `docs/research-notes.md`.

## Where we are (6 Oct 2026)

| Car | Role | Route | Status |
| --- | --- | --- | --- |
| Kia PV5 Elite 7-seat | The car Tristan actually wants: 7 seats, dual powered sliding doors, V2L, Ioniq 5 footprint | PCP 3.9%, ~£699/month £0 down, GFV £18,662 | Over Patricia's £400 ceiling. Decide by pricing the delta vs the best ≤£400 car. |
| Hyundai Ioniq 3 Ultimate EV Pack | Rational compact: 300mi, V2L, heat pump, 1,800mm wide | **Cash £27,445.** PCP is 8.9%, don't | Brand new model, no owner corpus. Test drive. |
| Kia EV2 GT-Line S + heat pump | Better-equipped Ioniq 3 rival, 257mi | Cash lead £29,666; lease ~£427 effective | Broker price unconfirmed for December. |
| Hyundai Kona Ultimate | Safe fallback | Richmond PCP £547; **£26,966 outright lead** | Confirm the cash lead is like-for-like. |
| Hyundai Ioniq 5 84kWh Premium | Known quantity, best charging | PCP 0% + £3k, £652/month | Good structure only if we expect equity. |
| Hyundai Inster 02 + Tech Pack | Cheap control | PCP 0% + £3k, £325/month | 4 seats, 223mi. |
| Used 2024 Kia EV6 GT-Line S | Most car per pound | £26,995, 27.8k miles | Still 1,890mm wide. |

Test-drive shortlist: Ioniq 3 Ultimate EV Pack and PV5 Elite 7-seat, Inster as the control.
The normalised comparison of every captured deal is in `docs/deal-comparison.md`.

## Repo layout

```
README.md
docs/
  requirements.md         what we need, quoting basis, budget, wants
  research-notes.md       decision rules, market context, spec gotchas, shortlist, tools, open questions
  deal-comparison.md      generated table of every deal, normalised (do not edit)
  transcripts/            raw source conversations (contact details redacted)
data/
  seed/cars.json          hand-captured car/trim specs (19 so far)
  seed/deals.json         hand-captured deals, dated and sourced (33 so far)
  seed/requirements.json  machine-readable requirements
model/
  deal_math.py            PCP / PCH / cash normalisation; solves monthlies, implied APR, premium vs cash
```

Planned, not yet built: `scrapers/` (batch collectors for Carwow, Cars2buy, LeaseLoco, broker
listings, manufacturer offer pages), `data/car-research.sqlite` (the source of truth the
scrapers populate), an export step, and `web/` (the SPA).

## Running the model

```
python3 model/deal_math.py                      # markdown tables
python3 model/deal_math.py --json               # machine-readable, for the export step
python3 model/deal_math.py > docs/deal-comparison.md
```

Standard library only. Conventions: payments at months 1..n, balloon at n+1, APR as an
effective annual rate. It reproduces Carwow's representative examples to within pennies and
flags any deal whose implied APR disagrees with the stated one.

## Data conventions

- **`vehicle_price`** is the net price after dealer discount *and* government grant, before any
  manufacturer finance contribution and before the customer deposit. That is what you would
  pay in cash from that seller.
- **`amount_of_credit`** = vehicle price minus deposit minus contribution.
- Every deal carries `captured_at`, `status` (live / expired / lead / illustrative / derived /
  campaign / historical) and `verification` (pasted / cited / derived / user). Anything
  ChatGPT sourced is *cited* until we re-verify it.
- Cars carry `heat_pump` and `internal_v2l` as standard / pack / option / none, with
  `packs_required` naming the pack. These two fields drive most of the trim decisions.
- Data snapshots are committed, so the git history is the price history.

## Architecture (target)

Same pattern as my other data-exploration projects (`bolthole`, `etf-analyzer`,
`wine-and-cheese`):

```
scrapers / importers (batch, run on the dev machine)
        |
        v
local SQLite database -- source of truth, committed to the repo
        |
        v
export step -> static JSON in web/public, with derived deal metrics precomputed
        |
        v
SPA on GitHub Pages -> on load, bulk-imports into an in-browser DB (sql.js / IndexedDB)
                       for fast client-side filtering and comparison
```

Batch, not live: GitHub Pages serves static files and the SPA never scrapes. Finance maths is
computed once at export time so the browser does not need its own copy.

## Context log

- **2026-10-06** Imported the 4-6 Oct ChatGPT conversation (85 messages) into
  `docs/transcripts/`, distilled requirements and research notes, captured 19 cars and 33
  deals as seed data, and wrote the deal normalisation model. Phone number and email were
  redacted from the transcript because this repo is public.
- **2026-10-06** Project started. Current car is a Hyundai Ioniq 5 on a 36-month 0% PCP,
  £0 deposit, ~£540/month, ending 10 Dec 2026.

## Next steps

1. Confirm the three cash leads are like-for-like and available for December (Kona Ultimate
   £26,966, EV2 £29,666, EV3 £37,263) using the enquiry script in `docs/research-notes.md`.
2. Get the Ioniq 3 Premium EV Pack GFV so a ~£400 PCP alternative can be priced properly.
3. Decide the SPA stack (mirror the reference repos once they are accessible) and set up
   SQLite + export + GitHub Pages deploy.
4. First scrapers: Carwow dealer offers (full PCP representative examples), Cars2buy
   derivative prices, manufacturer offer pages for campaign terms.
5. Intrinsic-value model: start with £/kWh, £/mile of range and £/kg against segment, then
   residual-value evidence from used listings.
