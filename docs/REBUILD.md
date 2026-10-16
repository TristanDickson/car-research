# The rebuild: raws first, matching re-derived

The owner's design, after their other project **bolthole** (`TristanDickson/bolthole`; its
`docs/RESOLVER.md`, `docs/DATA_MODEL.md` and `docs/ACQUISITION.md`): only the raw responses are
permanent, and everything else is re-derived from them by a build that runs from scratch
(`docs/DECISIONS.md`, "The raw store and the build"). How the system works now is in
`docs/ARCHITECTURE.md`. This file holds the rebuild's status and its next step.

## Status: live since 10 Oct 2026

Built on the branch `rebuild-raw-store` and merged into `main` (PR #1) on the evening of 10 Oct.
The laptop's job runs `main` at 03:17 and pushes the snapshot. The GitHub scrape, the backfill
workflow and the committed `data/history` are gone, and every committed version of that history
is in the raw store as the source `history`. Against the snapshot committed on 10 Oct, built from
the same history, every one of the 1,978 car ids stayed the same.

Parsing and matching are re-derived by every build, but the matching is still the four lookups
described below, not the owner's design. Replacing them is the next step.

## Next: one resolver over every record (designed 15-16 Oct 2026, not built)

Matching today is four separate lookups, one comparison each: a record printing a CAP id attaches
to it; a broker's text is matched to Carwow's derivatives by rules (`services/resolve.py`,
`match.py`); an EV Database page attaches to a car by a battery ratio (`facts.pick_variant`),
which tied every current Kona to the 2021-23 Kona's page; a used listing attaches to a trim by its
words and a battery within 3 kWh (`snapshot.used_key_for_text`), which counts 2021 Konas as the
2023-on car. A survey of the 15 Oct build also found 169 of the 353 cars linked to an EV Database
page that gives the motor on a variant with a different motor, 1,306 used listings on a version
that went on sale after they were registered, and 452 "Long Range" listings on "Standard"
derivatives. A patch to the battery comparison alone is held on the branch
`hold/evdb-battery-fit-two-readings`, since the resolver replaces it.

What the owner said, which this design follows, is in `docs/DECISIONS.md`, "Matching".

### The design (Claude's, from the owner's words, for the owner to correct)

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

## Glossary: the code's words, in plain English

The owner does not use these terms; never use one with the owner without saying what it means.

| In the code | What it is |
| --- | --- |
| raw store | the folder on the owner's laptop (`D:\car-research-raw`) that keeps every page fetched, exactly as it came |
| build | the run that reads every stored page from scratch and writes everything the app reads |
| hand-curated car | one of the 19 cars typed into `data/seed/cars.json` on 6 Oct from the owner's ChatGPT research (the shortlist, with prices and notes) |
| generated car | a car record the build makes for each CAP derivative a page names (`auto: true`) |
| stub car | a generated car made from a single line (a deals page, Carwow's derivative list) with no spec page behind it |
| CAP id, derivative | CAP HPI's id for one exact version of a car: model, trim, battery, motor, packs, price list. Carwow, cinch and Motorpoint all print it; it is the natural key |
| trim map | which source's label is which car: the owner's 219 rows in `data/seed/trim_map.json` (56 "this is that car", 163 "ignore") plus the build's own matches, stored in the database |
| sighting, observation | one price one source showed on one date |
| claims | what each source says about a field (width, heat pump...) and at what level (this derivative, this trim, this model); resolved to one value per field when the snapshot is written |
