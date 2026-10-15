> One of two design passes of 15 Oct 2026, kept for its evidence. The design to follow is the merge in `docs/REBUILD.md`, "Next: one resolver over every record".

# The record resolver, designed from the data

Written 15 Oct 2026 from the build database of that morning (`car-research-nightly/data/car-research.sqlite`, read only) and the published snapshot. Every count below is from those files. The other designer's document covers the algorithm in general; this one says what the records actually carry, where the current four lookups go wrong and how often, and what the resolver has to be to fix that.

Terms used throughout, in plain words:

- **Record**: one thing one source said, as the parser read it: a line on a Carwow page, a lease on LeaseLoco, a used car on cinch, a row of EV Database, one of the owner's own entries.
- **CAP id / derivative**: CAP HPI's number for one exact version of a car on one price list: model, trim, battery, motor, packs. Carwow prints it; brokers print CAP's *name* for it ('150kW GT-Line S 81.4kWh 5dr Auto [Heat Pump]') but not the number.
- **Variant**: EV Database's unit: one battery and motor of a model over the model years it was sold, named like 'Kona Electric 65 kWh (MY24-25)'. It spans every trim.
- **Entity**: a real thing in the world that several records describe. The resolver's job is to decide which records describe the same thing.
- **Constraint**: a rule that two records must be the same thing (a hard join) or cannot be (a hard separation). Everything else is evidence that is weighed.

## 1. The records and what each carries

The compound the resolver builds from a record is the set of features below. A feature a source does not print is simply absent; absence never counts against a join.

| Source (records) | Make, model | CAP id | Trim words | Motor kW | Battery, as what | Drive | Seats | Years | Price | Brackets |
|---|---|---|---|---|---|---|---|---|---|---|
| Carwow registry, `carwow_model` (916 current derivatives, 164 models, 42 makes) | slug | 916 | from the CAP name | 891 | nominal, 894 in the name | words in the name only (xDrive, Quattro, AWD) | 44 bracketed | price-list date, 916 (2024 to 2026: when the list was issued, not when the car went on sale) | RRP 916 | 241 |
| Carwow specification, `carwow_specs` (918 rows) | printed | 918 | 918 | bhp 918 | nominal number 885; the engine text's kWh equals it in every row | 918 | 841 | price-list date | RRP 918 | none |
| Carwow deals page lines, `carwow_deals` (6,553 price spans; 6,502 carry the line) | printed | all | yes | in the engine text | in the engine text | words only | no | the line's price-list date | RRP | none. These lines are the only description of 832 of the 1,971 cars (old price lists). |
| EV Database index card, `evdb` (1,110 variants) | make and a free-text model that carries version words and model years: 'EV6 Long Range AWD', 'Model Y RWD (BYD 7C BLADE)', '(MY24-25)' | none | none | none on the card; 0-62 time on 1,110 | usable 1,110 | words in the name (RWD, AWD, 2WD) | 1,110 | on sale since 1,109, until 638, on sale now 457 | list price | none |
| EV Database car page, `evdb_cars` (288 read) | as the card | none | none | 288 | gross 288 and usable 288 | 288 | 288 | as the card | | |
| Kia tables, `kia_specs` (23 grade × powertrain rows) | printed | none | 23 | 17 | nominal gross (EV6 84, EV3 81.4 and 58.3) | 23 | 7 | none | none | none |
| Hyundai guides, `hyundai_specs` (20 grade rows) | printed | none | 20 | 10 | the guide's figure, per grade (Kona 65, Ioniq 5 63 and 84, Inster 42 and 49) | 8 | 6 | none | 10 | none |
| Hyundai configurator (122 configurations) | printed | none | yes | | nominal | | | none | 122 | packs by name |
| New Car Discount, `ncd` (219 offers under 114 names, 110 technical rows) | NCD's words, with the make before the model on Kia pages ('KIA EV6 ELECTRIC ESTATE') | the derivative page prints Carwow's CAP id (110 rows, keyed by it) | CAP name | 114 of 114 | nominal in the name | words | 9 | none | RRP on 328 of 390 spans | 48 |
| LeaseLoco (1,639 offers under 951 names) | its words | none | CAP name | 940 of 951 | 943 | words | 29 | none | none (lease rates only) | 392 |
| RRG (14), Kia dealers (15), cinch new (42), Carwow pastes (4) | free text | none | free text ('Kia EV6 'Air' 84.0kWh', 'Kia EV3 GT-Line') | some | some | some | | none | an on-the-road price on 11 of 16 RRG spans | rare |
| Hyundai offers (9) | printed | Hyundai's own CAP *code* ('HYKN00ADE5HE A 2'), which is not Carwow's id and matches nothing without the owner | | | 4 | | | | yes | |
| Carwow used, `carwow_used` (10,959 listings) | slug | none | 5,029 have text | 4,261 | 4,261 nominal | words | no | registration year 10,876 | asking price | 0 |
| cinch used (1,724) | printed | none | CAP name 1,724; a separate `trim` field, drive, seats and range are printed and not read | 1,608 | 1,602 | 1,724 (read) | printed, not read | year 1,724, registration 1,724 | asking | 189 |
| Motorpoint used (812) | printed | none | CAP name | 689 | 689 | words | | year 812; list price when new 812 | asking | 73 |
| The owner, `manual_seed` | | 17 of 19 cars tied to a CAP id by their decisions | | | nominal | | | model year | | packs |

Two facts about battery figures decide a lot below:

- A nominal figure (a CAP name, a Carwow number, a maker table, a broker's or a used car's text) is a *label*, not a measurement, and it is exact. Carwow's engine text and its number agree in every one of the 879 rows that print both; a broker's kWh equals the Carwow derivative's in 621 of 621 resolved rows. When the maker renames the pack the label changes: the Kona went 64 → 65, the EV6 77.4 → 84, the Born 58 → 59, and in each case EV Database lists the two as different variants with different years. So two nominal figures that differ by more than rounding (0.6 kWh) are two versions, not one pack restated. The current used-listing rule ('within 3 kWh') is what joins a 2021 Kona 64 to the 2023-on Kona 65.
- Against EV Database the comparison is between kinds. For the 644 cars tied to a variant that has a car page, Carwow's nominal equals EV Database's gross in 432, its usable in 141, neither in 71 (Mercedes EQA 70.5 against gross 69.7 and usable 66.5; Mach-E 91 against 98.7 and 88). So nominal is matched to a variant by a band (usable/nominal between 0.84 and 1.03, as `_battery_fit` already allows), never by closeness to an ideal ratio, which is the Kona failure.

Motor power is printed almost everywhere a battery is (CAP names 891 of 916, Carwow spec 918, maker tables, broker text, cinch and Motorpoint text, Carwow used text 4,261) and on 288 EV Database car pages; where the card has no kW its 0-62 time stands in: Carwow's 0-62 and EV Database's agree within 0.4 s on 385 of the 631 linked cars that print both, and among the 246 that disagree every example I read is a wrong link (an iX1 xDrive30 on the eDrive20 variant, an Ioniq 6 239 kW on the 2WD variant, a Smart #1 Premium on the Brabus, a BMW i5 eDrive40 on the M60, an EV9 Air on the GT). Of the 353 linked cars with a car page, 169 are on a variant whose motor differs by more than 5 kW. Power is a constraint the current variant pick ignores, and the data says it must not.

## 2. The entities

Four levels, from the data's own grain:

1. **Model**: a catalogue model (`models`, 890 electric, by Carwow slug). Body styles are separate models on Carwow (Q4 e-tron and Q4 e-tron Sportback, Enyaq and Enyaq Coupe, EV4 and EV4 Fastback) and they share CAP names: 94 CAP names appear under two model slugs (Q6 e-tron/Sportback 10, ID.7/Tourer 10, iX1/iX2 6, Capri/Explorer 6, e-3008/e-5008 6, Elroq/Enyaq 6), 13 of them at the same RRP. So the model is a constraint of its own; the CAP name alone never identifies a car.
2. **Version**: one model, one battery as the maker labels it, one motor, one drive, over the years it was sold. This is EV Database's variant where one is filed (865 variants file under 185 models; 328 on sale, 534 discontinued), and the same thing where none is: 50 models with cars have no variant filed (Enyaq 97 cars, Elroq 72, the two Q6 e-tron bodies 68, the two Minis 49), and 70 of the 245 unfiled cards are unfiled only because `facts.norm` drops the accented letter from 'Škoda' and 'Citroën'; 175 are models the catalogue does not carry (e-Niro, i-MiEV, Macan Electric under another name). A version also exists with no CAP id at all: 980 used listings name a battery no current derivative of their model carries (Mini 33 kWh 152, Mokka-e 50 kWh 133, Leaf 39 kWh 111, Polestar 2 78 kWh 94, Ioniq 5 73 and 58 kWh 116, Kona 39 kWh 34), and 174 Kona listings say 64 kWh.
3. **Derivative**: a CAP id: one trim of one version on one price list, with its packs (the brackets) and RRP. 1,952 in the build: 897 with a specification row, 223 registry only, 832 only from deals-page lines. Twins (several derivatives of one trim and powertrain) are 119 groups holding 285 derivatives; 116 groups have all-distinct RRPs and 115 differ only by their brackets. The price-list date on a derivative sits inside its variant's years for 969 of 1,021 linked cars, after the variant ended for 47 (the Kona pattern), before it for 5.
4. **Single car**: a used listing: one registration year, a registration mark on cinch (1,724), and the same car on two sites (the snapshot already folds these by registration, else year and mileage). It belongs to a version and, where its text names one, a trim: `trim-version`. It is never itself a derivative, because a derivative is a price-list entry and a 2021 car cannot be a 2026 list's.

How they relate: a version has many derivatives (one per trim and pack combination per price list) and many single cars; a derivative belongs to exactly one version; a model has versions in sequence and in parallel (two packs on sale at once: Ioniq 5 63 and 84). An EV Database variant is a version; a Carwow 'trim · engine' is a trim-version; the owner's used EV6 ('kia-ev6-77-gtlines-2024-used', 77.4 kWh, 2024) is a single car of the version EV6 77.4 kWh RWD MY22-24, trim GT-Line S.

What attaches where:

| Record | Attaches to |
|---|---|
| Carwow registry line, specification row, deals line, configurator page, NCD technical row, the owner's decisions naming a CAP id | the derivative (hard, by CAP id) |
| Hyundai configurator configuration | the derivative, by trim, battery and price as now |
| Broker price (NCD, LeaseLoco, RRG, dealers, cinch new) | the derivative its text and price single out; else the trim-version it names (see 4) |
| EV Database card and page | the version |
| Maker grade row | the trim-version when the row has one battery, the trim otherwise (as now) |
| Used listing | the trim-version (the trim from its text; the version from its kWh, kW, drive words and registration year) |
| Tests, surveys, recalls, reviews | the model, as now |

## 3. The constraints

Hard joins (two records are one entity):

- The same CAP id. 1,114 records resolve this way today plus 832 deals lines.
- The owner's decision 'this is that car' (56 rows of `trim_map.json`) and their cars (19). These override everything else, as now.
- The same registration mark on two sites, or the same model, year and mileage where a site prints no mark (the snapshot's `dedupe_listings` rule), for single cars.

Hard separations (two records are never one entity):

- **Different model.** The catalogue model from the slug, the printed name, or EV Database's text (accents stripped). A record whose model text fits two catalogue models (NCD's 'EV4 saloon', LeaseLoco's 'Q4 e-tron Sportback' against the prefix rule in `gold.model_agrees` that lets 'Q4 e-tron' match it) is a candidate for both; it is the price or a body word that settles it, and if nothing does the record stays at the make. Evidence: the 94 shared CAP names, and the 20 LeaseLoco conflicts where two 'twins' carry the identical CAP name; in every one of those I read the two are a car and its Sportback at different RRPs (110379 and 110402, 109400 and 109434).
- **Different fuel.** Any combustion word in a name (`parse.combustion`: 21 records) makes no entity in this app at all. The Astra Sports Tourer '1.2 Turbo 130' therefore has no derivative for the model's 55.4 kWh claim to land on.
- **Different motor.** Two kW figures more than 5 kW apart (Carwow bhp × 0.7457 against a CAP name or a car page agrees within that). Where one side has only a 0-62 time, more than 1.0 s apart.
- **Different battery label.** Two nominal figures more than 0.6 kWh apart. Against EV Database's usable figure, outside 0.84 to 1.03 of the nominal; against its gross, more than 0.6 apart.
- **Different drive**, where both say: Carwow's `drive` (918 and 1,586 cars), cinch's field, EV Database's car page, and the words AWD, 4WD, RWD, FWD, 2WD, Quattro, 4MOTION, xDrive, 'Dual Motor' in any text. 430 matched used listings today carry a drive word their car contradicts.
- **Different seat count**, where both print one (brackets, EV Database, cinch).
- **Years that do not meet.** A single car registered before a version went on sale is not that version; a derivative first seen (the `records` table, back to January 2025 through the committed history) after a version's last year is not that version. Today 1,306 used listings sit on a current derivative while registered before its version and an earlier variant of the model fits them (Tesla 796, BMW 202, Vauxhall 71, Peugeot 54); 47 cars have a price list dated after their variant ended.
- **A trim word missing.** Every word of a candidate's trim must appear in the text (today's gate), but the stop list must stop dropping words that name versions and drives: 'Long Range', 'Standard', 'AWD', 'RWD', 'Performance'. Today 452 listings whose text says 'Long Range' sit on a 'Standard' derivative (Tesla in every example I read, on 'Standard · RWD Auto') because those words are discarded before the gate.
- **A price that fits none.** A record's own price below every candidate's RRP by more than £250 or above by more than £1,500 (today's `_off_price`) breaks the derivative link; the record keeps its trim-version. RRG's EV6 'Air' at £52,835 (the GT-Line's price) and EV9 'Air' at £78,395 are the 5 cases.

Soft evidence, weighed only among candidates no hard rule separates:

- The record's own RRP equals one twin's within £10 (NCD: 57 rows settle this way; RRG 2).
- The bracket set of the text equals one twin's bracket set (seat counts aside). This settles 56 of the 229 conflicts outright; 153 have no twin with that bracket at all (LeaseLoco writes '[Tech Pack]' where the registry has '[Tech]', or the pack version is on an old price list the registry no longer prints), and those stay unplaced at derivative level.
- A CAP name another source's RRP pinned to a twin (today's `name` rule, 35 rows).
- A pack bracket against exactly two prices goes to the dearer, no bracket to the cheapest (74 and 234 rows today), unchanged.
- Between EV Database variants of one version that only years tell apart (the Kona 64 kWh MY20-21 and MY22-23; 600 same-battery overlapping pairs separated by 0-62 and name words, 299 by name words alone, 56 by nothing: Zoe Q90 twice, Model S P90D twice), the variant whose years contain the record's date; a derivative on sale now goes to the variant on sale now.

## 4. The reduction

Everything below runs over the whole record set in one pass; nothing depends on the order pages were read, because every tie falls by a stable key (CAP id, record key, newest price-list date) and never by position.

1. **Compounds.** Each record becomes its feature set from section 1: model (catalogue slug), CAP id, trim words, kW, nominal kWh or usable/gross kWh with the kind marked, drive, seats, a date (price-list date, first sighting, registration year, on-sale years), price, bracket set, fuel.
2. **Blocks.** Records are grouped by make, then by catalogue model, a record naming two models going into both blocks. Nothing outside a block is ever compared, so the cost is per model (the largest block today is the Audi Q6 e-tron pair, 68 derivatives once the two bodies are read together, and a few hundred records).
3. **Candidate links.** Within a block every pair of records that no hard separation forbids gets a link, labelled with the soft evidence it carries. In practice this is each text record (broker, used, EV Database, maker row) against each derivative and version, since derivatives already carry an id.
4. **Hard components.** The hard joins alone are followed first: every record naming a CAP id, every owner decision, every registration mark. Each connected set is one entity, and it cannot be split by anything later: if two records are hard-joined and a hard separation also holds between them, that is a data fault and the build logs it (none exist today).
5. **Versions.** Derivatives, EV Database variants and maker rows cluster into versions by the version features alone: model, battery (nominal against nominal exactly; nominal against usable by the band), kW, drive, seats, years. A derivative joins the one variant that survives; two surviving variants with the same battery are told apart by kW, then drive, then years, then 0-62; if two still survive the derivative belongs to the version but names no variant, and the car gets no EV Database figures rather than the wrong variant's. A version with no variant and no derivative is still made when single cars need it (the Kona 64 kWh, the Mini 33 kWh).
6. **Attaching text records.** A text record whose candidate links reach exactly one derivative takes it ('trim-powertrain', 342 today). One reaching several derivatives of one trim-version is settled by the soft evidence in the order of section 3; one that nothing settles attaches to the trim-version and lists the derivatives it may be, which today's build records as a conflict and shows on the Data page. A used listing always attaches to its trim-version; it takes a derivative id only when exactly one current derivative is that trim-version, which is what `used_key` does today.
7. **Fewest entities.** No record makes a new entity while an existing one can take it without breaking a hard rule; a new version or trim-version is made only when every existing one is forbidden. That is the whole of the 'smallest set that satisfies the constraints' idea, and it falls out of steps 4 to 6 without a search.
8. **Evidence.** Every attachment records its method and the constraints that decided it, as `trim_map` rows do now, so the Data page can still say why a lease sits on a car.

## 5. Where the four lookups and the claim levels go

- **CAP ids** (`build.derivatives`, `match`): unchanged, now step 4. `combustion` becomes the fuel constraint rather than a parser rule, so the names are still kept in the raws and `records`, and simply make no entity.
- **Broker text** (`resolve.choose`, `match.score`, `_candidates`, `_pin_pass`, `gold.model_agrees`): the gates become hard separations (section 3) with the stop list and the model prefix rule fixed; the twin rules become the soft evidence in the same order plus bracket-set equality; the pin pass stays as the first sub-pass. The 'conflict' status stays for records nothing settles.
- **EV Database variants** (`facts.pick_variant`, `_battery_fit`, `claims.resolve_car`'s second pass): deleted. The car's variant is its version's, found in step 5 by battery, kW, drive, seats and years. `facts.model_of` stays as the model block for variants, with accents stripped.
- **Used listings** (`snapshot.used_key`, `used_key_for_text`, the 15 Oct `on_sale_since` rule): the listing's trim-version comes from the resolver. `used_key` keeps its shape `model|trim|kWh` but the kWh is the version's label, so a 2021 'Ultimate 64kWh' keys as `hyundai/kona-electric|ultimate|64` and a 2025 'Ultimate 65kWh' as `|65`; the year rule is subsumed by the years constraint.
- **Claim levels** (`claims.LEVEL_ORDER`): `own, derivative, trim_battery, trim, engine, model, variant` becomes `own, derivative, trim_version, trim, version, model`. `trim_battery` is the trim-version with a proper key; `engine` (make, model, engine text) and `variant` are both the version, so a Carwow engine's numbers and EV Database's measurements sit at one level and disagree visibly where they do. `trim_subject`, `model_subject`, `pack_subject` and the equipment ranking are untouched. `from_evdb` adds its claims to `version:<key>` instead of `variant:<spec_key>`; `_maker_numbers` likewise.

What the snapshot and the app see (schema_version stays 7; every change is an added field):

- `cars.json`: `version` (the version key) and `version_name` (EV Database's name where a variant is linked, else the label the build made, 'Kona Electric 64 kWh'); `on_sale_since` and `evdb_url` as now, from the version. `used_key` as now in shape.
- `used_spans.json` and `used.json`: `used_key` as now in shape, with the version's kWh; `version` added; `car_id` as now (a derivative only when one current derivative is the trim-version).
- `sightings.json`: `car_id` as now. A record that attaches to a trim-version with several possible derivatives stays out, as a conflict, unless the owner takes the option in section 8.
- `details.json`: source labels change wording only.
- `data.json`: `resolution_methods` gains `bracket-set` and `version`; `unmapped_trims` as now.

## 6. The known failures

1. **Kona on variant 1423.** The five current Konas (CAP 103322 to 103326, 160 kW, '65kWh', price list 2026-10-01, first seen no earlier than January 2025, where the history starts) against the model's eight variants: the battery band leaves 1126, 1204, 1423 (usable 64.0) and 1830 (65.4); kW (car pages: 150 against 160) removes the three 64s; years remove them again (1423 ended 2023-06); 1830 is on sale. No ideal ratio is involved. The same mechanism moves the 93 cars that sit on a discontinued variant while an on-sale one fits (Ariya, Scenic, ID. Buzz, Mach-E, Renault 5) and the 47 whose price list postdates their variant.
2. **The 2021 'Ultimate 64kWh'.** Nominal 64 against the current derivatives' 65 is a different label, so no current derivative is a candidate; the version Kona 64 kWh is made from the variants 1204 and 1423 (one version: same battery, 150 kW, front drive, consecutive years; a 2021 registration fits either by month and the year alone does not say which, which the version level absorbs), and the listing keys as `hyundai/kona-electric|ultimate|64`. The 101 cars registered in 2023 with '64kWh' go the same way, which the date rule alone could not do (the new car went on sale 2023-07).
3. **Petrol versions.** The fuel constraint makes no entity for the 21 combustion names; nothing else changes. The claim at the model level (the Astra Sports Tourer Electric's 55.4 kWh) has no petrol derivative to land on.
4. **Gross and usable.** Nominal figures are labels and exact; EV Database's usable and gross are matched by kind. The EV6 77.4 (MY22-24, usable 74) and 84 (MY25-27, usable 80) are two versions with their own variants and years; the Ioniq 5 63 and 84 are two packs on sale together; the Kona's 65 matches 1830's usable 65.4 and gross 68.5 by the band.
5. **Twins.** RRP, then the bracket set (56 conflicts settle), then pins, then two-price bracket and base rules; three or more prices with a pack no twin names stay a conflict (153), and the '[No Heat Pump]' brackets (5 Inster derivatives; 14 broker labels) keep feeding `from_broker_labels` as now.
6. **Broker quirks.** NCD's make-first names are handled in the block (the make word is stripped before the model is read, as `_candidates` does now). Halliwell Jones's captions and RRG's copied lines are caught by the price constraint: a price that fits none of the text's derivatives leaves the record at its trim-version (5 today) rather than on the wrong car.

## 7. Verification

- **A before/after list.** A script (scratchpad, not the repo) that reads the current build's `trim_map` (3,109 rows), `used_listings.car_id` (3,968 set) and each car's `evdb_url` (1,056), runs the new resolver on the same records, and prints every record whose entity changed with both sides and the constraint that decided it. The expected movements, from the counts above: 47 + 93 cars change variant; about 1,306 used listings leave a current derivative for an earlier version (796 Tesla, 202 BMW); 430 used listings with a contradicting drive word move; 452 Tesla 'Long Range' listings leave 'Standard'; 56 LeaseLoco conflicts gain a derivative; 70 EV Database cards file under Škoda and Citroën models. Anything outside those buckets is a finding to read, not a pass.
- **Fixture tests through `tests.helpers.Raws`**, each from pages already in the raw store:
  - Kona: the EV Database index page (cards 1423 and 1830), the car pages for both, the Carwow specification page, the Hyundai guide; assert the four current derivatives link to 1830 and a 2021 cinch listing `cinch:f1ef1786-4f74-4fad-9c44-c3a50820a7d5` ('150kW Ultimate 64kWh 5dr Auto') keys as `|ultimate|64` with no car id.
  - Astra Sports Tourer Electric model page with CAP 111456 to 111458: no entity, no battery claim.
  - EV6: the registry, Kia's table (84), LeaseLoco's '166kW Air 77.4kWh' and '168kW Air 84kWh', EV Database's 1481 and 3028; assert two versions, each lease on its own.
  - Audi Q4 e-tron and Sportback model pages with 110379 and 110402 ('…S Line 5dr Auto [Tech]' at £56,495 and £58,395): a LeaseLoco row naming 'Q4 e-tron Sportback … [Tech]' goes to 110402 by model, not to a conflict.
  - RRG's EV6 page ('Air' at £52,835): the record keeps the trim-version and no derivative.
  - NCD's Kia listing page ('KIA EV3 ELECTRIC ESTATE 150kW Air 58.3kWh'): CAP 106391 by trim and powertrain.
  - Order: every test builds twice with the raw entries reversed and asserts the same tables.

## 8. Open questions for the owner

1. A broker price that fits several twins and nothing settles (153 LeaseLoco rows today): keep it off the app as now, or show it on the cheapest twin with the others listed on the sighting (`alternatives`, a new field)? I recommend the second: the price is real and the car page can say 'one of these three'.
2. Resale evidence by version. The app reads the model's used cars by registration year; with versions known it could read the car's own version first and fall back to the model, so a 2023 Kona 64 kWh would not price a 2023-on Kona 65. That is an app change; the pipeline would only add `version` to the spans.
3. cinch prints `trim`, `seats`, `driveType` and `rangeInMiles` per listing and NCD's derivative page prints Carwow's CAP id; the parsers keep only the drive and the id respectively. By the project's own rule those are bugs, and reading them removes guesswork for 1,724 and 219 records. Fix before or alongside the resolver?
4. The accent fix in `facts.norm` (70 EV Database cards, Škoda and Citroën) is one line and independent of everything else; ship it now?
5. Versions with no derivative (the Kona 64 kWh, 980 used listings in all): entities in the build, but should they appear as cars in the app's buy-used route, or only as the evidence behind current cars' resale?
