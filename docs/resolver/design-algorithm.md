> One of two design passes of 15 Oct 2026, kept for its evidence. The design to follow is the merge in `docs/REBUILD.md`, "Next: one resolver over every record".

# The record resolver: a design from the algorithm

This replaces the four separate one-comparison lookups (CAP id, broker text, EV Database battery,
used-listing trim) with one mechanism. The owner's words (15 Oct 2026): "an algorithm that builds
compounds of features from each raw and compares recursively to reduce to the smallest possible
set of entities that satisfies those constraints". This document says what that mechanism is, how
it gives the same answer whatever order pages were read in, what it costs on a nightly build, how
each decision is recorded so a reader can see why a price sits on a car, and how it slots into
`pipeline/build.py`. It is a design, not code; nothing in the repo changes with it.

One sentence of scope. Every car the app shows is still a CAP derivative (CAP HPI's id for one
exact version of a car, which Carwow, cinch and Motorpoint print) or a car the owner entered; the
resolver decides which records belong to which of those, and which EV Database variant, trim
line and model each sits under, by comparing every feature the records print rather than one.

## 1. The model

**A record** is one thing one source said, with a key that is stable at that source: an offer
(a LeaseLoco lease, a Carwow deals line, a dealer's PCP example), a Carwow specification row, a
registry line (Carwow's trims-and-prices table), a used listing, an EV Database variant (its
index card, and its own page when read), a maker's grade row (Kia's and Hyundai's tables), a car
the owner entered, a test or recall or review of a model. The build already holds every one of
them (`records`); the resolver reads them after parsing, every build, from scratch.

**A feature compound** is what the resolver reads off a record: a small set of named features,
each either unknown, a single value, a set of readings, or a range. The features, and who prints
them:

| Feature | What it is | Printed by |
| --- | --- | --- |
| make, model | the catalogue model; the resolver only ever compares records of one model, and that set is called a block | everyone, in their own spelling |
| fuel | bev, hybrid, range extender, petrol | a combustion marker in the name (`parse.combustion`), Carwow's spec `fuel` |
| pack | battery size in kWh, as a set of readings: nominal (gross), usable, or an unlabelled maker figure | Carwow spec and engine text, broker and used text, EV Database (usable on the card, nominal on the page), the owner |
| power | kW (bhp converted) | Carwow spec, broker and used text, EV Database page, the owner |
| drive | FWD, RWD, AWD | Carwow spec, "AWD" in names, EV Database page and variant name |
| seats | a count | Carwow spec, "[7 seat]" brackets, EV Database card |
| years | when this thing was on sale: a range, a point, or open-ended | EV Database (`year_from`, the "(MY22-23)" range in its name, the page's on-sale dates); Carwow (the price-list `version_date`, and the registry's configurator slug `kona-electric-2023`, which carries the generation year; `carwow_options` uses the slug for its URL and nothing reads the year); a used listing's registration year; the owner's `model_year` |
| trim words | the trim's words, stop words removed (`match.tokens`) | Carwow's trim, broker and used text, maker grades |
| brackets | CAP's bracket set ("[Heat Pump]", "[No Heat Pump]", "[7 seat]") | registry names, broker text |
| rrp | the list price | Carwow, NCD (price plus saving), dealers' on-the-road price |
| cap_name | CAP's derivative name, normalised | the registry, brokers, used listings |
| anchors | an identity: CAP id, EV Database variant id, VRM, catalogue slug | see below |

**An entity** is a group of records that are the same thing at some level. The levels, from
coarse to fine; every entity at one level has exactly one parent at the level above:

| Level | Entity | Identity (its anchor, when one exists) | Native records |
| --- | --- | --- | --- |
| L0 model | Hyundai Kona Electric | catalogue slug | tests, recalls, reviews, What Car? |
| L1 powertrain version | 65 kWh, 160 kW, FWD, on sale 2023-07 to now | EV Database variant id (`evdb:1830`) | EV Database card and page |
| L2 trim line | Ultimate, on that powertrain | none (formed by grouping) | maker grade rows |
| L3 derivative | Ultimate 65kWh on the Oct 2026 price list | CAP id (`carwow-cap:103325`) | Carwow spec, registry, deals lines, broker offers, the owner's cars |
| L4 individual car | one registered car | VRM (else listing key per site) | used listings, an owner's car marked `used: true` |

A record is placed at every level down to its native one, top down: first the block (L0), then
which powertrain version (L1), then which trim line (L2), then which derivative (L3), then, for
stock, which physical car (L4). A record that fits two children of a level equally stops at that
level, with the candidates recorded. The entity's own compound is the merge of its members':
readings intersect, ranges intersect, so an entity is at least as specific as any record in it.

"Car" for the app is unchanged: an L3 entity with a CAP id (`carwow-cap:<id>`), or an entry the
owner made (an L3 entity whose CAP id the owner named in `trim_map.json`, or an L4 entity when
`used: true`). L1 and L2 entities are not cars; they are the subjects the claim store already
speaks of as `engine`/`variant` and `trim`/`trim_battery`.

## 2. Constraints

**Must-link (hard, together whatever else is said):**
- two records naming the same anchor at that level: the same CAP id (a spec row, a registry line,
  a deals line, a cinch listing), the same EV Database variant id (card and page), the same VRM;
- the owner's `car_id` rows in `trim_map.json` (this source's key is that car);
- a new row kind, `same`, naming two records or a record and an entity (bolthole's merge pair).

**Cannot-link (hard, never together):**
- two different anchors at the same level: two CAP ids are two derivatives, two variant ids two
  powertrain versions. Note the level: two CAP ids can share one L1 parent;
- a contradiction on a hard feature: fuel; pack (section "Comparing a feature quoted two ways");
  power beyond 3% or 2 kW; drive; seats; years that do not overlap; a bracket set that differs
  where a twin with that bracket exists in the registry;
- the owner's `different` rows (bolthole's reject pair);
- the price gate: a record whose own price fits no derivative of the trim line its text names
  (below the cheapest by more than £250 or above the dearest by more than £1,500) does not link
  to that trim line on its caption. Dealers copy lines between pages (RRG's "Air" at the
  GT-Line's price); the price outranks the caption.

**Soft evidence** says "the same" without being conclusive on its own. It is tiered, strongest
first, per level; a tier is only consulted for records the stronger tiers left unplaced.

| Level | Tier | Evidence |
| --- | --- | --- |
| L1 | P1 | pack agrees (a reading within rounding) and years overlap, with no contradiction on power, drive, fuel or seats; among several, the one agreeing on more features (power, drive, variant words such as AWD, GT, Long Range) |
| L1 | P2 | pack compatible only (one figure could be the gross of the other's usable) and years overlap, when P1 found nothing |
| L2 | T1 | every word of the trim line's trim is in the text; the most specific line (most words) when several fit ("N Line S" over "N Line") |
| L3 | D1 | the record prints the CAP id |
| L3 | D2 | the CAP name equals a registry name (lower case, "GT-Line" and "GT Line" alike, seat brackets dropped) |
| L3 | D3 | the record's own RRP equals one twin's list price within £10 |
| L3 | D4 | another source's copy of the same CAP name was placed by D3 (the name group, below) |
| L3 | D5 | the bracket set equals one twin's |
| L3 | D6 | heuristics, recorded as such: a pack bracket against exactly two prices goes to the dearer; no bracket against several prices to the cheapest |
| L3 | D7 | identical prices: the version on the current price list |
| L4 | V1 | the same VRM on two sites |
| L4 | V2 | the same registration year and mileage where a site prints no VRM |

Today's final tiebreak "then the id" (`resolve._current_first`) is dropped: it is a guess. A tie
after D7 is recorded as ambiguous. The build on 14 Oct placed 9 rows by `version`; a few of them
will become ambiguous, and the diff in section 6 lists which.

**Comparing a feature quoted two ways.** Makers and Carwow print one battery figure without
saying whether it is gross or usable (Kia: EV6 "84 kWh" is gross, 80 usable; Hyundai: Kona
"65.4 kWh" is what EV Database calls usable, nominal 68.5). EV Database's index card prints
usable only; its page prints both. So the pack feature is a set of readings, and a single figure
`f` against a set `R`:
- **agrees** when `f` is within 1.0 kWh or 1.5% of any reading in `R` (65 against {64}: agrees;
  65.4 against {65.4, 68.5}: agrees; 84 against {80, 84}: agrees);
- **compatible, not corroborating** when `R` holds only a usable figure `u` and `0.86 ≤ u/f ≤
  0.99`, so `f` could be the gross of `u` (65.4 against {64}: 0.979, compatible; 84 against {80}:
  0.952, compatible). Two single figures compare the same way in either direction (77.4 against
  74: compatible);
- **contradicts** otherwise (84 against {60}: no).

Today's rule (`facts._battery_fit`) scores every pair by distance from a ratio of 0.93, which is
why 64/65.4 beat 65.4/65.4. Under this rule "agrees" outranks "compatible" (P1 before P2), and a
tie on the pack is broken by the other features, never by a ratio.

**Years.** An EV Database variant's range is the page's on-sale dates when the page was read;
else `year_from` to the end of the "(MYaa-bb)" range in its name, or open-ended when the name
has no range. A CAP derivative is on sale at its price-list date, and its generation starts at
the year in the registry's configurator slug (`kona-electric-2023`) when the slug has one. A used
listing is a point at its registration year. The owner's `model_year` 2027 is a point in 2026
to 2027 (model years run ahead of the calendar). Two ranges that do not overlap contradict; a
point outside a range contradicts; an unknown year is compatible with anything.

## 3. The algorithm

**Step 0, nodes.** Every record becomes a node with its compound. An offer key is one node: its
compound comes from its latest sighting's `car_ref`, and its RRP reading is the latest its page
printed (a page that printed the RRP once keeps it; today's `_pin_pass` reads every sighting for
the same reason). Records that share an anchor merge into one node before anything else (every
record naming CAP 103325 is one node; EV Database's card 1830 and page 1830 are one node), as do
the owner's `car_id` and `same` rows. A contradiction inside such a node (the spec row says 65,
the owner's entry says 77.4) is reported on the entity as a conflict and both readings are kept;
the claim store already shows disagreements per field.

**Step 1, blocking (L0).** One normaliser gives each node its catalogue model, replacing the three
that exist (`gold.model_agrees`, `facts.model_of`, `used_match.match_model`): exact name, then
the name without its electric suffix, then the alias table, then the longest catalogue name that
starts the text on a word boundary, with NCD's leading make stripped. A node with no model is
listed as such and goes no further. Everything after this runs inside one block.

**Step 2, one level at a time, inside the parent.** For level L, within one parent entity from
L-1, the nodes are that level's anchors and every node whose native level is L or deeper and
which reached this parent. The resolver compares each non-anchor node with each group (an anchor
with the members it has so far; or an unanchored group) and records a verdict per feature
(agrees, compatible, unknown, contradicts), then runs the tiers strongest first:

1. For every unplaced node, its candidate groups at this tier are the groups the tier's evidence
   points at and which are *legal* for it: no contradiction between the node's compound and the
   group's merged compound (which is the same as no contradiction with any member, bolthole's
   all-member gate), no `different` pair inside, no second anchor.
2. Exactly one legal candidate: the node joins it. Several: the node is deferred to the next
   tier. None: the next tier.
3. Candidates are computed against the groups *as they stood when the tier began*, and all of
   the tier's joins are applied together. If a group then holds two nodes that contradict each
   other (two broker rows with the same RRP but different bracket sets both joined one twin),
   every node that joined it this tier is taken back out and marked `conflict` at this tier. So
   a tier is a function of the state before it, and the order nodes are visited changes nothing.
4. After the last tier: a node with several corroborated candidates is `ambiguous` and stays at
   the parent with its candidates recorded; a node with compatible groups but no corroboration
   is `unplaced` at this level and stays at the parent too (compatible is not evidence, as in
   bolthole, where price agreement alone never merges); a node that contradicts every group forms
   an unanchored group of its own, which other such nodes may join on the same tiers.

Non-anchor nodes also join one another on the same tiers and under the same invariants: the
**name group** at L3 is every node in one trim line whose normalised CAP name is equal; a D3
placement of one member carries the others (D4); members placed on different twins by D3 break
the group, and both are recorded (today: "a name pinned to two twins pins neither"). Unanchored
L1 groups are nodes with equal fuel, power, pack reading and drive and overlapping years, which
is today's `engine` subject made explicit. L4 groups are physical cars across sites (today's
`snapshot.dedupe_listings`).

**Recursion.** A group formed at L becomes the parent for L+1 and its members are the nodes to
place there. The owner's "compares recursively" is this descent: the comparison at each level
uses the compound restricted to that level's features, with the parent chain already fixed, so
a used listing is first a Kona on the 64 kWh 2021-to-2023 powertrain, then an Ultimate, and
only then compared with derivatives, of which that powertrain has none on sale.

**The smallest set.** The set of entities the descent produces is the smallest that breaks no
constraint, in this sense: every node that any tier corroborates with exactly one legal group is
in that group, so no two groups could be merged without a contradiction or a lost corroboration,
and no node sits alone that the evidence places. Where the evidence is equal between two groups
the set is not made smaller by a guess; the node stays one level up, which is itself an entity
the app and the claim store can use. Because every exported car is a CAP id, the count of cars
is fixed by the anchors; the reduction's work is in which anchor each unanchored record belongs
to, and in which powertrain version and trim line each anchor sits under.

**Transitivity.** A corroborates B, B corroborates C, A cannot link C. Connected components over
corroboration would put all three together and break the constraint. Here, B's candidates at
the tier where it is corroborated are {A's group, C's group}; both are legal, so B is deferred,
and if no lower tier separates them B is `ambiguous` between A and C and stays at the parent. A
and C never meet. When B is an anchor (a CAP id) and A and C are two broker rows, A and C each
have one candidate, B's group, and whichever contradicts the group's merged compound after the
other joined is taken out by rule 3 and marked, symmetrically.

**Determinism and order independence.** Nodes, groups and candidates are identified by strings
(source and key, or the anchor id) and every iteration is over a sorted list; the tiers are
functions of the state before them; and no rule says "first" or "last". The output is a function
of the set of records and decisions. A test shuffles the records and reverses the raw store's
entry order and asserts the same placements (section 6).

**Cost.** The build on 15 Oct parsed 89,452 records in 7,269 fetches, in 140 s from the parse
cache (450 s cold). Sightings are not nodes; an offer key is. The nodes are about 3,500 offer
keys, 12,600 used listings, 2,400 spec rows (of which 1,106 EV Database cards and 123 pages),
911 registry lines, 1,952 CAP ids and the owner's 19 cars: roughly 20,000. A block is one model
(250 models), so at most a few hundred nodes against at most a dozen or two L1 anchors, then a
few dozen nodes against a dozen twins per trim line. That is on the order of a million compound
comparisons, each a few dictionary lookups; I estimate 5 to 20 s in CPython 3.12 (not measured).
The compound of a record is extracted once and memoised by record key; the build report gains a
`resolver` seconds figure so a regression is visible in the nightly log.

**Evidence, so the app and the owner can see why.** One `placements` row per node: source, kind,
key, label; the block; the entity at each level reached (`l1`, `l2`, `l3`, `l4`); the status
(`placed`, `ambiguous`, `unplaced`, `conflict`, `not-electric`, `no-model`); the tier that placed
it; the evidence as a list of `{feature, mine, theirs, verdict}` for the chosen group; for every
rejected candidate its first contradiction; the candidates when ambiguous; the decision applied
when the owner's. Per entity, its members with their tiers. The Data page's issues table reads
placements with no L3 (what `unmapped_trims` reads from `trim_map` today), the car page lists
what sits on the car and by which tier, and `python -m pipeline records <key>` prints the row.

## 4. Integration

**Where it runs.** `Build.finish()` today: `derivatives()`, `cars()`, `resolve()`, `trim_map()`,
`fold()`, `write_records()`. It becomes: `derivatives()` (unchanged in purpose: what describes
each CAP id, from its spec row, else the registry, else the newest deals line), then
`resolver.run(nodes, decisions, catalogue)` from a new `pipeline/services/resolver.py`, then
`cars()` (every L3 anchor whose L1 fuel is bev, plus the owner's cars), `placements()` (writes
the table), `fold()` reading each offer key's car from the placements, the `specs.car_id` and
`used_listings.car_id` updates likewise, then `write_records()`. The resolver runs after parsing
every build; it is not part of the parse cache, so `code_version` does not change.

**The four lookups.**

| Today | Becomes |
| --- | --- |
| `build.match()`: a record printing a CAP id attaches to that derivative; `autocars` makes one car per CAP id | the CAP id is the L3 anchor; must-link by id (D1). `autocars.from_spec`/`from_stub` stay as the description of an L3 anchor. `combustion()` stays as the fuel reader; the exclusion moves from a name rule in `derivatives()` to the fuel feature at L1 |
| `resolve.choose` + `match.score` + `gold.model_agrees` + `_candidates` + `_pin_pass`: broker text against the model's derivatives | the L0 normaliser, then T1 at L2 and D2 to D7 at L3. `match.tokens` stays as the trim-word reader; `resolve.choose`, `_pin_pass` and `_candidates` go. The price gate is the same numbers (`PRICE_BELOW_LIST`, `PRICE_ABOVE_LIST`) applied as a cannot-link, with the retry on price alone recorded as tier `price over caption` |
| `facts.pick_variant` + `_battery_fit`, called per car from `claims.resolve_car` | P1 and P2 at L1 place each CAP derivative under a variant once, from its compound (pack, power, drive, years, variant words); `resolve_car` reads the variant off the car's chain. `facts.model_of` folds into the L0 normaliser; `facts.py` goes |
| `snapshot.used_key` + `used_key_for_text`: a used listing to a trim and battery within 3 kWh | a used listing descends L1 (pack, power, years), L2 (trim words), L3 (CAP name or id when the site prints one), L4. Its `used_key` is its L2 entity's key; `used_key_for_text` goes; `dedupe_listings` is L4 |

**The claim levels.** `claims.LEVEL_ORDER` keeps its seven names and `resolve_equipment` and
`resolve_number` do not change. `_subjects(car)` stops recomputing subjects from the car's
fields and reads the chain: `own:<id>`; `derivative:<cap>`; `trim_battery` as the L2 trim with
the L1 pack figure (today's `store.trim_batteries` nearest-kWh search goes); `trim` as today;
`engine` as the L1 entity's key (anchored or not); `model`; `variant:<evdb spec key>` when the L1
entity is anchored. `from_evdb` keeps keying claims by variant spec key; `on_sale_since` on a car
comes from its L1 entity's years. Maker grade rows (`kia_specs`, `hyundai_specs`) are placed at
L2 by T1 and the pack reading, which is what the trim and trim-battery subjects already express.
Model-level sources attach at L0 through the one normaliser.

**What stays.** CAP ids as the anchors and the car ids (`carwow-cap:<id>`, the owner's ids);
offer keys and the spans; the raw store, parsing and the parse cache; the claim store's
resolution, kinds and ranks; `data/seed/trim_map.json` as the owner's decisions, with two new
row kinds (`same`, `different`) and the existing `ignored` rows kept as a label that does not
steer placement (as today).

**What the snapshot and the app see.** Car ids, `cars.json`, `sightings.json` `car_id`,
`details.json` `field_sources`: unchanged. `used_key` keeps the shape `model|trim|kWh`; the app
compares it for equality only (`Pricing.tsx`, `hooks.ts`), so where a model has two L1 entities
with the same rounded kWh (one pack across two generations) the key gains the generation's
start year, and the comment in `types.ts` says so. `data.json` `unmapped_trims` rows gain
optional `level` and `candidates`; `resolution_methods` counts tiers. All additive: no
`SCHEMA_VERSION` bump. One optional later step, section 7: an ambiguous offer carrying its L2
key so the app can show "a price for this trim, derivative not pinned".

**Database.** A `placements` table (columns above) in `schema.sql`; `trim_map` is written from it
with today's columns so `snapshot.unmapped_trims` and `resolution_methods` change little.

## 5. The known failures, walked

1. **Kona Electric on variant 1423 instead of 1830.** CAP 103325 ("160kW Ultimate 65kWh",
   price list 2026-10-01, configurator slug `kona-electric-2023`) has pack {65} (Carwow) and
   {65.4} (the owner's entry, must-linked by the owner's row), power 160 kW, years from 2023 and
   on sale 2026. Variant 1423: pack {64}, years 2021 to 2023 from "(MY22-23)". Variant 1830: pack
   {65.4, 68.5}, years 2023-07 to now from its page, power 160 kW, FWD. Years: 2026 is outside
   1423's range, a contradiction, so 1423 is not legal. 1830: pack agrees (65 against 65.4 within
   1.0; 65.4 exact), years overlap, power agrees: P1, placed. Had the Kona's page not been read,
   1423 is still excluded by years alone; had the name carried no range, pack "agrees" on 1830
   against "compatible" on 1423 still picks 1830 at P1.
2. **A 2021 "Ultimate 64kWh" counted as the 2023-on Ultimate 65.** The listing is a point at 2021
   with pack {64} and power 150 kW. At L1: 1830 starts 2023-07, a contradiction; 1423 agrees on
   pack and years: placed under 1423. At L2 it is the Ultimate line of that powertrain. At L3
   that line has no CAP derivative (every current Kona derivative sits under 1830), so the
   listing stops at L2 with `used_key` "hyundai/kona-electric|ultimate|64", which no car on sale
   carries. Where a site prints no kW and the year is missing, pack 64 against the current
   derivative's {65, 65.4} still agrees within 1.0, and the listing would reach the current line:
   that is the residual case, and section 6 counts how many listings lack both.
3. **Petrol versions as cars.** "1.2 Turbo 130 GS 5dr" on the Astra Sports Tourer Electric page
   and "1.0 EcoBoost Hybrid mHEV" on the Focus page read fuel petrol / hybrid from the name;
   "160kW Hybrid EV 19kWh" (Leapmotor) reads range extender. At L1 they contradict every bev
   variant and each forms an unanchored L1 group with fuel set; `cars()` exports only L3 anchors
   under a bev L1, so they are not cars, and they are listed as `not-electric` with the feature
   that said so. The 15 Oct name patch becomes the fuel reader rather than a special case in
   `derivatives()`. They take no battery from the model because the model-level claims apply to
   cars only.
4. **Gross or usable.** EV6 84 (Carwow) against variant 3028 {80} is compatible, against its
   page's {80, 84} agrees; the old EV6 77.4 against 1481 {74} is compatible, and the two are
   separated by years (3028 from 2024, 1481 from 2022) and, where the page was read, power. No
   ratio preference remains, so a maker's usable figure (Hyundai) and a maker's gross figure
   (Kia) are both handled by the same two-reading comparison.
5. **Twins.** One Carwow trim, several CAP ids with different RRPs: the twins are pairwise
   cannot-linked anchors in one L2 line. A broker row with an RRP goes by D3; with a bracket set
   that equals one twin's registry name by D5 ("[No Heat Pump]" against the bracketless twin is
   a contradiction, since the registry shows a twin with that bracket); without either, by the
   recorded heuristics D6 and D7; and a row that fits two twins after D7 is ambiguous and stays
   on the trim line with both named. The 161 `conflict` rows of 14 Oct (a pack against three or
   more prices, no RRP) stay unplaced at L2 with their candidates listed, as today but with a
   level the claim store can use.
6. **Broker quirks.** NCD's leading "KIA" is stripped by the L0 normaliser, as `_candidates`
   does today. A Halliwell Jones caption naming a trim at a price no derivative of that trim
   carries fails the price gate; the retry on price alone places it with tier `price over
   caption` when one derivative of the model has that price, else `conflict` with both the
   caption's candidates and the price's. RRG's "Air" at the GT-Line's £52,835 is the same path.

## 6. Verification and rollout

**Before/after, every link that changes.** A new command, `python -m pipeline resolver-diff`,
builds once and runs the old lookups and the new resolver over the same records, then prints
every record whose car differs (old car, new car, tier, the deciding feature), grouped by
cause, and the coverage counts before and after: offers on a car, used listings on a car, cars
with an EV Database variant, cars with width, with DC peak, with Euro NCAP. The counts matter
because P1's "ambiguous" is stricter than `pick_variant`'s year tiebreak: a model whose
variants differ only by drive, with no page read (the card prints no drive or power), loses its
variant until `evdb_cars` reads a page. The diff shows how many; `evdb_cars`' rotation should
read ambiguous candidates first (its priority list already exists).

**Fixture tests**, through `tests.helpers.Raws`, one per failure, with pages already in
`tests/fixtures`: the Kona specification page and the EV Database UK index (the Kona cards; if
the index fixture predates variant 1830, capture one card page), a cinch Hyundai page for the
2021 Ultimate, `carwow_used_ford_focus_petrol.html` and the Astra registry line, the Kia EV6
specification and index cards for gross against usable, `kia_dealer_hj_ev3_gt-line_offer.html`
and an RRG page for the caption cases, and a registry page with twins for D3 to D7. Two more
tests: the shuffle test (section 3) and one that a contradiction inside a must-link group is
reported, not resolved.

**Staging.** One `--build-only` run with the resolver beside the old lookups (`resolver-diff`),
the diff reviewed in this chat, then the switch on `main`; the owner's stance (11 Oct) is to ship
straight to `main`, so no nights in parallel. `resolve.py`, `match.score`, `facts.py` and
`used_key_for_text` are deleted in the commit after the switch, once the diff is not needed.

**What can go wrong.**
- Years read wrong for a variant whose name has no "(MY..)" range and whose page is unread: an
  open range is compatible with everything, so the fault is an under-separation (two variants
  tie, ambiguous), never a wrong placement. A range read too narrow would cannot-link wrongly;
  the diff's "cars with a variant" count would drop, which is the check.
- The one model normaliser filing a record under a different model than the three it replaces:
  every such change appears in the diff as a block change.
- D2 (CAP name equals a registry name) placing a broker row on an old price-list version with
  the same name: D7 prefers the current version, and two current versions with one name are
  ambiguous rather than guessed, so the failure mode is more ambiguous rows, not wrong cars.
- Cost above the estimate: the resolver's seconds are in the build report and the nightly log.
- The name group linking across trim lines through a sloppy normalisation: the group is
  confined to one L2 line by construction.

## 7. Open questions for the owner

1. An offer that fits two twins equally today shows on no car. Should it show on every
   derivative of its trim line, marked "derivative not pinned", which needs its L2 key on the
   span in `sightings.json`? I recommend yes, in a second step.
2. The decision rows: `{"same": ["ncd:<key>", "carwow-cap:103325"]}` and `{"different": [...]}`
   in `trim_map.json`, naming records by source and key or entities by id. Is that the form you
   want to write by hand, or a `python -m pipeline decide same <a> <b>` that writes it?
3. Broker rows that corroborate no CAP id but each other (two sites naming one derivative Carwow
   does not list) form an entity the app does not show. Keep them on the Data page only, or show
   them as cars without a CAP id? I recommend the Data page only, since prices must be on a
   listed derivative.
4. Dropping the id tiebreak turns a few `version` placements into ambiguous rows. Agree?
