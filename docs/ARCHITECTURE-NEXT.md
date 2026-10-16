# Architecture, next

Designed, not built. Only what changes from `ARCHITECTURE.md` is here; everything else stays.
The owner's words behind it are in `DECISIONS.md`, "Matching".

## What it does

The same ETL, with a new way of deciding which car a record is. Today four separate lookups
each compare one record with one list, and get things wrong: every current Kona Electric is
tied to EV Database's page for the 2021-23 Kona, 2021 Konas count as the 2023-on car, and a
survey of the 15 Oct build found 169 cars on an EV Database variant with a different motor and
1,306 used cars counted as a version that went on sale after they were registered. Next, there
is one master list of every derivative and one filter that every record goes through.

## The flow

```
   raw store ──parse──▶ records ──normalise──▶ compounds ──filter──▶ cars ──▶ facts and prices ──▶ snapshot
                                                            ▲
                                       master list: every derivative Parkers lists,
                                       old generations included
```

## Data model

| Thing | What it is | Identity |
|---|---|---|
| Car | one derivative on the master list: make, model, generation (body and start year), trim, motor kW, battery kWh, packs, doors, on-sale dates, price when new | built from those details, so the same whichever source lists it first |
| Version | a model's battery, motor and drive over the years it was on sale (EV Database's variant, where it files one) | model, battery, motor, drive, years |
| Compound | the details read off any record: make, model, CAP id, CAP-style name, trim words, kW, kWh, drive, seats, a date (registration or price list), price, packs, fuel | the record |
| Link | a record tied to a car, or to a version or model when it can get no finer, with the details that decided it | the record |

Parkers replaces CAP as the master list because CAP's is licensed. Parkers lists every
generation's derivatives in CAP's wording, with their on-sale dates.

## Extract

- **Parkers** is added: its sitemaps weekly, then each derivative's page (4,027 read on 16 Oct;
  400 a night after that). Its records wait for the resolver and do not reach the app yet.
- **Two readers gain fields** the filter needs: cinch's per-listing trim, seats, drive and range,
  and the CAP id printed on New Car Discount's derivative pages.

## Transform

1. **Normalise** (built, and today's lookups read through it). One function reads every source's text: accents removed and case folded,
   punctuation treated alike ("GT-Line S" is "GT Line S"), units read into numbers, one list of
   make and model names, and one table expanding CAP's short descriptions into its long ones
   ("eDr40" is "eDrive40", "Qtro" is "quattro"). Words that separate versions ("Long Range",
   "AWD") are kept. A record whose CAP-style name equals a master entry's matches it before any
   normalising, and a test fails if two different names of one model normalise to the same key.
2. **Filter.** Within the record's model, every detail it gives rules out the entries it
   contradicts: a fuel that burns, a motor more than 5 kW away, a battery label more than 0.6 kWh
   away (EV Database's usable and gross figures compared by kind), another drive or seat count,
   a date outside the entry's on-sale dates, a trim word the entry lacks, a price no entry could
   have. A detail the record does not give rules nothing out.
3. **Decide.**
   - One entry left: the record is that car.
   - Several: the record's list price, then its pack names, narrow them. Any still left, it goes
     on the best spec of them, with the others named on it.
   - None: a record with its own trim and details (a Carwow derivative newer than Parkers' list)
     becomes a car. A record of text alone stays at its version or model and is listed for the
     owner.
4. **The CAP id** is the strongest detail: once one record with an id is placed, every record
   printing that id goes to the same car, unless a detail contradicts it, which is listed.
5. **EV Database** describes a version, so its figures go to every car of that version, below any
   source that speaks for the car itself.

Facts and prices are worked out as today, for the new cars.

## Load

The same files, with fields added: each car's version, and each used car's version. Car ids
change once, from CAP ids to the new ids.

## Costing

- **End value by version**: the median asking price, now, of used cars of the same version as
  old as the term, with between half and double the reader's mileage over it (9,000 to 36,000
  miles at 6,000 a year over three years). Fewer than 10 such cars, and every car of that age
  counts, and the app says so. The app shows how many cars a figure rests on and the mileage
  band.
- **Old versions are cars**: a 2021 Kona is "Kona Electric 64 kWh, Ultimate", costed on the
  used route.

## Running it

As today, with one step before the switch: a comparison lists every record whose car changes
against today's lookups, and the owner goes through it. The work is tickets T1 to T8 on
`BOARD.md`.
