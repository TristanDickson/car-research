# The owner's decisions

The owner's decisions in force, by topic, in their own words where the docs recorded them. Where
no words were recorded, the line says so. A decision a later one replaced
is not kept; git's history has the rest. The household's own buying notes (budget, timing, what
they want from a car) are in `docs/requirements.md` and are not decisions about the app.

## The app is generic

- 14 Oct 2026: "build a generic app for me to explore car prices and plan upgrades regardless of
  starting vehicle", and, asked whether the cabin socket was a must: "It could be a must or it
  could not be, the point of the app is to be flexible and able to trial out different
  requirements and preferences. I thought that was clear". Of a fixed width rule: "'narrower than the Ioniq 5' this is plain
  wrong as a requirment". So comparisons are against a car the reader chooses in Settings
  ("Compare every car with"), and requirements, the cabin socket and the heat pump included, are
  the reader's saved searches rather than rules in code.
- 14 Oct 2026, asking for chips that mix "and" and "or": "I'm pretty sure bolthole had variable
  boolean mixing logic".
- 13 Oct 2026, on figures worked out only in chat: "did you just do an equivalance to savings rate
  by hand without adding those features to the app? meaning if i ever wanted to pick based on this
  answer we'd have to do them all again?", and later the same day: "Are we pulling the what car
  survey into the app or are you making the same mistake of answering me and not making the
  response durable and general?" A figure quoted to the owner is one the app carries, made general
  for every car.
- 14 Oct 2026, on features discussed: "rear seat reading and any other features we've talked
  about are a yes if they're buildable".
- No words recorded: keep it simple. Saved searches replaced a requirements editor, stars and a
  shortlist (8 Oct) because those concepts did little; a new concept is proposed before it is
  built.

## Prices

- 10 Oct 2026, no words recorded: only authoritative prices, a figure a seller published or
  quoted, never a derived or estimated one.

## Sources and scraping

- 16 Oct 2026, on Parkers' first read: "i dont even want to wait 4 nights if we dont have to".
- 13 Oct 2026, on DVSA's recall service blocking scripts: "I think we should work around the
  block. This is a personal product not a commercial one", then "its just a government check
  they're not really serious about".
- 11 Oct 2026: "we should be tolerant of blocking and come up with strategies around it".
- 13 Oct 2026, asked whether disguising scripts as a person meant "not explicitly telling it
  you're a bot or doing something more drastic": "If its the first i think that's excusable for
  this purpose". So the readers send a browser's user agent and nothing more: no solved CAPTCHAs,
  no faked fingerprints.
- No words recorded: Audi, BMW, Mercedes and Skoda maker spec tables wait until one of their cars
  is shortlisted.

## Matching

The input to the resolver design in `docs/REBUILD.md`, "Next: one resolver over every record".

- On the matching: "From memory, i said i didnt know if we needed to go as complex as bolthole,
  because properties are inherently harder to match and i thought car variants could be done
  with a few explicit comparisons, but that appears nto to be the case." What they want: "an
  algorithm that builds compounds of features from each raw and compares recursively to reduce to
  the smallest possible set of entites that satisfies those constraints".
- On a golden record: "we have presumably a master record of every derivative and only need to
  match against it. Its our golden record." CAP's list is licensed (quote only), so it cannot be
  that record; Parkers' is the nearest free one (`docs/SOURCES.md`, "Parkers").
- On the CAP id: "i dont think CAP id becomes anything special beyond a very high priority match
  field".
- On text: "We should use a standard parser for car listings, e.g. to remove accents".
- On the two Konas: "we definitely need to differentiate between the kona v1 and v2"; on old
  versions with only used cars: "its fine to make them cars".
- On a price that fits several near-identical versions: "list that lease against the worst spec
  or best spec it applies to. Maybe best because investigating a price thats worse than it looks
  is preferable to missing a price that's better than it looks".
- On resale: "We take resale at say 3 years, the price of a 2023 Kona now", and on mileage: "My
  idea was a very wide band so we dont discard most of the evidence".
- On normalising text: "You should be careful not to let the parser fuck up exact matches on CAP
  dervied strings".
- On decisions the matching cannot make: "Isnt it easier to have a flow in the app to resolve them
  if they come up? (I don't think they will even come up for the same reason in 1.)"

All of these are from 15 and 16 Oct 2026.

## The raw store and the build

- 10 Oct 2026, no words recorded: the design is the owner's, after their project bolthole. Only
  the raw responses are permanent; parsing and matching are re-derived from scratch by every
  build; only the owner's own files and decisions persist (`docs/ARCHITECTURE.md`).
- 10 Oct 2026, asked where the raw store should live (`D:\car-research-raw`): "path is fine, go".
- 11 Oct 2026, on the committed history's source name: "if its somehow used to build history it
  shouldnt be called legacy". It is called `history`.

## How the work is done

- 10 Oct 2026, on switching to the rebuild without two nights beside the old scrape: "we dont need
  to be so cautious. Nobody is using this right now and we built it in a couple of days". Changes
  ship straight to `main` once tests and CI pass.
- 11 Oct 2026: "stop worrying about backup, this is a hobby project".
- 16 Oct 2026, on the docs: "Do we need this giant historical record of everything that happened,
  or do we just need the latest overall result of my decisions?" The docs hold the decisions in
  force and how things work now; git's commit messages are the history.
- 11 Oct 2026, of PowerShell scripts: "This is meant to be platform agnostic, we have git bash for
  a reason". Scripts are bash.
- No words recorded: talk to the owner in plain words, and say how many cars have a field rather
  than that coverage is complete.
