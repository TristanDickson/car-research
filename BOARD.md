# Board

Every piece of work the owner has asked for that has not landed, and every decision still owed,
as tickets. The design is in `docs/ARCHITECTURE-NEXT.md` and the owner's words in
`docs/DECISIONS.md`; this file tracks only what is to be done and where it stands. The same
convention as the owner's other boards (SpaceTS, parasitic-feudalism), kept short.

- **Status** is one of: open, needs ruling, in progress, landed `<sha>`, held `<branch>`, or
  struck `<date>`. Only the owner strikes a ticket or rules on one.
- **A new ask** goes on the board with the next number before work starts. Numbers are never
  reused.
- **A commit that implements a ticket** carries a `Ticket: T<n>` trailer, and the ticket's status
  is updated in the same push, checked against the code.

| Ticket | What | Status |
|---|---|---|
| T1 | One normaliser for every source's text | landed `d12bbc8` |
| T2 | Carwow's models mapped to Parkers' models and generations | landed `3a438fb` |
| T3 | The resolver: every record filtered against the master list | open |
| T4 | cinch: read each used listing's trim, seats and range fields | landed `2ac6965` |
| T5 | NCD: match NCD's prices by the CAP id its pages print | landed `ec160a1` |
| T6 | End value by version, within a wide mileage band | open |
| T7 | A price that fits several cars goes on the best spec | open |
| T8 | Old versions are cars | open |
| T9 | Clear `data/seed` and `data/pastes` down to a file of default settings | landed `598e1ac` |
| T10 | `docs/SOURCES.md` in the same short form as the architecture docs | landed `de6de05` |
| T11 | Find out why Carwow's configurator reader recovered on 16 Oct | landed `8d2dc54` |
| T12 | Carwow used: no household models fetched ahead of the rest | landed `b1df4e8` |
| T13 | A code change goes live in one push with the snapshot it needs | landed `982525e` |
| T14 | The parse cache keyed by source, so a change to one reader re-reads only its pages | landed `5cfdb17` |

## T1. One normaliser for every source's text

Accents out and case folded, punctuation alike, units read into numbers, one alias list for makes
and models, and a table expanding CAP's short descriptions ("eDr40", "Qtro", "Black Ed",
"Comf+"). It fixes the name matching that drops the accent in "Škoda" and "Citroën", which
leaves 70 EV Database records attached to no car. An exact CAP-name match is taken before any
normalising, and a test fails if two
different names of one model normalise to the same key. Owner: "We should use a standard parser
for car listings, e.g. to remove accents"; "be careful not to let the parser fuck up exact matches
on CAP dervied strings".

Landed 16 Oct. Every reader and matcher reads names through one module; an exact CAP name match is
taken first. Against the same pages, with T5: 3,664 offers on a car (3,502 before), 253 records the rules
could not place (331), 1,312 cars with an EV Database variant (1,068), and every Škoda and 24 of 28
Citroën EV Database records on a car. Most of the 160 lease records that gained or changed a car
were on the other body style (Sportback, Touring, Coupé, Tourer). Among 4,539 Carwow and Parkers
names the only collisions are five Enyaq names that differ only in "KW" and "kW". What got worse
is for T3, below. Left: EV Database's DS records (10) still reach no car. Its make is now read as
DS, but it prints "N°8" and "DS 3 E-Tense" where the catalogue has "No 8" and "3 E-Tense", so "N°"
wants reading as "No" and a model name its make's name at the start, both for every source.

## T2. Carwow's models mapped to Parkers'

Parkers files body styles as generations of one model (the Q4 e-tron Sportback is a generation of
the Q4 e-tron); 534 of the 1,587 cars on sale on 16 Oct found no Parkers model by name.

Landed 17 Oct, derived by every build: a Carwow model goes on the Parkers model whose name reads
alike and whose derivatives share the most names with Carwow's list, and on the generations its
name prints (Sportback, Touring, N) or no other Carwow model claims. 229 of 250 Carwow models are
placed, holding 1,534 of 1,601 cars on sale; 5 are ambiguous and 16 unplaced, most because Parkers
has no model of that name (the Ioniq 3 because Parkers files 5 of its 11 derivatives under the
Ioniq 5 N). The Data page lists them first, with why, for the owner. Placed on the name alone, and
worth a look there: the CLA Shooting Brake, i5 Touring, i3 (both generations), Vivaro-e, DS No 7
and AMG GT Four-door. No record's car changes until T3 uses the map.

## T3. The resolver

As `docs/ARCHITECTURE-NEXT.md`, "Transform": Parkers' derivatives as the master list, a car's id
built from its details, the filter and the decide rules, the CAP id as the strongest detail, EV
Database's figures to every car of its version. A comparison listing every record whose car
changes against today's lookups is gone through with the owner before the switch. It supersedes
the battery patch held on `hold/evdb-battery-fit-two-readings`.

It places the makers' configurator rows as well. Today they are matched only against Carwow's
registry, so three Ioniq 3 Ultimate derivatives that only Carwow's deals page names (with the
Design Pack, the Comfort and Design Packs, and the EV and Design Packs) get no packs from
Hyundai's configurator. Since T9 they show no heat pump and no cabin socket, where Hyundai's
configurator has the EV Pack fitted on one and offered on the other two.

Since T1, where the text no longer splits two price lists' copies of a derivative by their
spelling ("Qtro Perf" and "Quattro Performance"), the scoring rules cannot choose: 8 LeaseLoco
leases (Audi Q4 and Q6, Polestar 4) and a used Polestar 4 are left as conflicts, and the Lexus RZ
450e lease goes on the cheaper copy. Two Volvo EX30 "Twin Motor Performance Black Edition" leases
went on the plain trim, because "twin motor" now scores as engine words. Six used Enyaqs no longer
count as the current car, since EV Database now gives the Enyaq an on-sale date of April 2026.

## T4. cinch: trim, seats and range per listing

Every cinch used listing has separate fields for trim, seats and range. We read the combined
variant text, year, mileage, registration and drive; trim and seats are dropped, and range is kept
only as badge text. These are exactly the details the matching needs, for 1,724 listings.

Landed 16 Oct: trim, seats, doors, body, fuel (which marks the range extenders), range in miles
with its test (WLTP, or NEDC on 17 older cars), and whose stock it is. 1,612 listings carry them;
the 194 without are committed history from before 10 Oct. Today's matching reads only the
derivative text, so no listing moved; the trim field would place 68 listings whose text spells
the trim differently ("SM" for "Single motor"), which is for T3.

## T5. NCD: prices matched by the CAP id

Each car's page on New Car Discount prints Carwow's CAP id. We store it on NCD's spec rows, but
NCD's own prices are still matched by their text rather than by that id. That affects 219 offers.

Landed 16 Oct. All 105 PCP quotes are placed by their page's id; the cash prices take the id of
the page each listing row links to from the first nightly run of this code. Where the id and the
text disagree, the id wins: two Ioniq 5 63 kWh twins (Advance and Premium), where the text rule
had chosen the other twin by price, and the Ioniq 5 Ultimate AWD with the Tech and Zen Pack. The
Inster 71kW 02's cash price names an id Carwow does not list, so it will be left unplaced rather
than put on the No Heat Pump version. Five quotes the text could not place now have a car (Ioniq 5
Ultimate with the Tech Pack, Ioniq 5 N and Ioniq 6 N, each with and without the Vision Roof).

## T6. End value by version

The median asking price, now, of used cars of the same version as old as the term, with between
half and double the reader's mileage over it; under 10 such cars, every car of that age counts and
the app says so. Owner: "We take resale at say 3 years, the price of a 2023 Kona now"; "My idea
was a very wide band so we dont discard most of the evidence".

## T7. A price that fits several cars goes on the best spec

With the others it could be named on it. Owner: "list that lease against the worst spec or best
spec it applies to. Maybe best because investigating a price thats worse than it looks is
preferable to missing a price that's better than it looks".

## T8. Old versions are cars

A 2021 Kona is "Kona Electric 64 kWh, Ultimate", costed on the used route. Owner: "we definitely
need to differentiate between the kona v1 and v2"; "its fine to make them cars".

## T9. Clear `data/seed` and `data/pastes`

Ruled 16 Oct. Of the 19 cars and the trim map's 56 links: "i think these would also need to go,
yes?"; of the pasted pages: "Havent i already said this pipeline should be automated?"; the cited
and derived offers fail the rule that prices are authoritative. Keep only a small file of default settings (term, savings rate,
resale assumption, starting searches). Drop the 19 hand-typed cars (14 cited from ChatGPT; their
specs outrank every scraped source), the 29 offers (20 cited, 4 derived), the trim map (the first
pipeline's lookup table, 163 of its rows encoding that week's shortlist), the picks, and the
hand-copied pages in `data/pastes` (four Carwow dealer quotes of 5 Oct, three expired, and two
Richmond Hyundai pages of 4 Oct) with the paste reader and README's instructions for adding one,
since the pipeline is to be automated (`docs/DECISIONS.md`). The current car's PCP details in the
seed settings go too: nothing reads them. It does not wait for T3: with the hand-typed cars gone
as well, nothing is left for the trim map's links to deduplicate.

Landed 16 Oct. A build from the same pages has 1,983 cars (1,604 on sale), two fewer than before:
of the 19 hand-typed cars, 17 carry on as the Carwow car of the same CAP id, and the 2022 Ioniq 5
and a used EV6 have none until T8. 33 hand-typed offers and five that only the lookup table placed
are gone. 28 equipment values changed on 10 cars that were in both builds. The Inster 02's are
right by Hyundai's configurator, which offers the Tech Pack only on the heat-pump version, and the
EV2 GT-Line S's by Kia's table, which lists only the outside adapter. Four Kona Electrics lose the
outside socket, which only the hand-typed cars gave. The Ioniq 3's are the gap under T3.

## T10. `docs/SOURCES.md` in the short form

One short entry per source (what it gives us, what we leave and why, what reading it costs),
without code references. Owner: "I want this concise enough that I A HUMAN can collaborate on it".

## T11. Carwow's configurator reader recovered

It gave no records from 12 to 14 Oct, then 239 records from 250 pages on 16 Oct, with no code
change; the site's redirect is due a fresh survey.

Found 17 Oct: the reader never failed. It reads pages not read for a week, and counted the
committed history's copies of 8 Oct as read, so from 10 to 14 Oct only one page was due a night,
a Peugeot e-208 derivative that Carwow answers with its first step ("Choose the type of car"),
which has no options. On 16 Oct the 8 Oct copies passed a week and 250 pages were due; on 17 Oct
249 of 250 gave records. The history's copies are now all past a week, so that cannot recur. Of
472 derivatives read both before and after, 467 give the same options and packs and five differ
by a BMW pack Carwow renamed. A page without options is now named in the build log.

## T12. Carwow used: no household models first

The Carwow used reader fetches every card of eight models (the Ioniq 5, Kona Electric, Inster,
Ioniq 3, EV2, EV3, EV6 and PV5) each night outside its budget, and the rest within it. The app is
generic (`docs/DECISIONS.md`, "The app is generic"), so every model goes through the same budget.
After their first night the eight took 27 to 40 cards a night (12 to 16 Oct), so the budget grows
from 400 to 440 and Carwow is asked for as many cards as before.

## T13. A code change goes live with its snapshot

A change to the snapshot's layout and the snapshot built with it went up in two pushes on 16 Oct,
and the site showed its version-mismatch banner for the 12 minutes between them. The nightly
script takes a local commit, builds it from the pages already held, puts the snapshot on top and
pushes both at once. Proposed 16 Oct; owner: "yes".

## T14. The parse cache by source

One hash over every reader's code keys the parse cache, so a change to any reader re-reads all
12,751 stored pages: 534 seconds of a 12-minute build on 16 Oct. Keyed per source, on that reader's
code and the shared code it uses, a change to one reader re-reads only its own source's pages.
Proposed 16 Oct; owner, 17 Oct: "add T14".

Landed 17 Oct. Each source's key covers its reader, every module it imports and the PDF reader
where it uses one. On 14,201 stored pages: a build with nothing to re-read takes 162 seconds (720
before); a change to cinch's reader re-read its 408 pages; a change to the shared parsing code
re-read the 19 sources that use it. `CAR_RESEARCH_PARSE_CACHE` can put the cache on another drive.
