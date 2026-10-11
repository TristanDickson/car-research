-- Bronze: every fetched body, content-addressed. One row per distinct body per
-- (source, capability, target); a newer body supersedes the previous one.
CREATE TABLE IF NOT EXISTS artifacts (
  id             INTEGER PRIMARY KEY,
  source         TEXT NOT NULL,
  capability     TEXT NOT NULL,
  target         TEXT NOT NULL,
  url            TEXT,
  sha256         TEXT NOT NULL,
  content_type   TEXT,
  status_code    INTEGER,
  body           BLOB NOT NULL,
  fetched_at     TEXT NOT NULL,
  parser_version TEXT,
  superseded_by  INTEGER REFERENCES artifacts(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_artifacts_key_sha ON artifacts(source, capability, target, sha256);
CREATE INDEX IF NOT EXISTS ix_artifacts_key ON artifacts(source, capability, target, fetched_at);

-- What each source said, and when: every record any parser distilled from a page (and every
-- row of the committed history, and the owner's files), as spans of unchanged content. One row
-- per source, kind, key, page and stretch of time over which the record read the same; the same
-- record seen again extends its row, a change starts a new one. A key missing from a later
-- page is not a record, so absence shows only as a row that stops. Built from scratch by
-- every build (pipeline/build.py); the tables below are the latest-state views of it.
CREATE TABLE IF NOT EXISTS records (
  id            INTEGER PRIMARY KEY,
  source        TEXT NOT NULL,        -- the provider (carwow_specs, ncd, manual_seed, ...)
  kind          TEXT NOT NULL,        -- model | spec | derivative | options | configuration | offer | used | car | trim_map | requirements
  record_key    TEXT NOT NULL,        -- the record's id within its source
  page          TEXT NOT NULL,        -- the target it was read from (one key can come from several pages, each saying part of it);
                                      -- '' for a committed history row, which merged what every page said
  first_seen_at TEXT NOT NULL,        -- '' for the owner's undated files
  last_seen_at  TEXT NOT NULL,
  sightings     INTEGER NOT NULL,     -- how many fetches said it
  origin        TEXT NOT NULL,        -- of the first sighting: live | wayback | history | owner
  first_fetch   TEXT,                 -- raw store fetch id (or the owner's file) of the first and last sightings
  last_fetch    TEXT,
  fingerprint   TEXT NOT NULL,        -- of the content, less the sighting's own date
  row           TEXT NOT NULL         -- JSON, as the parser emitted it (the first sighting's)
);
CREATE INDEX IF NOT EXISTS ix_records_key ON records(kind, record_key, first_seen_at);
CREATE INDEX IF NOT EXISTS ix_records_page ON records(source, page);
CREATE INDEX IF NOT EXISTS ix_records_source ON records(source, kind);

-- Run log: one row per provider/capability run.
CREATE TABLE IF NOT EXISTS runs (
  id          INTEGER PRIMARY KEY,
  source      TEXT NOT NULL,
  capability  TEXT NOT NULL,
  target      TEXT NOT NULL,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  status      TEXT NOT NULL,          -- running | ok | error
  artifacts   INTEGER DEFAULT 0,
  records     INTEGER DEFAULT 0,
  unmapped    INTEGER DEFAULT 0,      -- offers skipped because their trim is not in trim_map
  errors      INTEGER DEFAULT 0,      -- targets that failed to fetch or parse (run continues)
  error       TEXT
);

-- Gold: canonical entities. The full record lives in `payload` (JSON); the
-- columns are the fields worth indexing / querying in SQL.
CREATE TABLE IF NOT EXISTS cars (
  id             TEXT PRIMARY KEY,
  make           TEXT NOT NULL,
  model          TEXT NOT NULL,
  trim           TEXT,
  model_year     INTEGER,
  seats          INTEGER,
  battery_kwh    REAL,
  wltp_range_mi  REAL,
  width_mm       INTEGER,
  list_price_gbp REAL,
  grant_gbp      REAL,
  heat_pump      TEXT,
  internal_v2l   TEXT,
  payload        TEXT NOT NULL,
  source         TEXT NOT NULL,       -- provider that last wrote the row
  artifact_id    INTEGER REFERENCES artifacts(id),
  updated_at     TEXT NOT NULL
);

-- Identity: each source's own trim naming -> our car id. Scrapers add
-- 'unmapped' rows on a miss; a human promotes them to 'mapped' via the seed.
CREATE TABLE IF NOT EXISTS trim_map (
  source        TEXT NOT NULL,        -- the site (carwow, cars2buy, ...), not the provider
  source_key    TEXT NOT NULL,        -- normalised trim text or derivative code
  car_id        TEXT REFERENCES cars(id),
  status        TEXT NOT NULL,        -- mapped | unmapped | ignored
  label         TEXT,                 -- the trim as the source prints it
  example_url   TEXT,
  note          TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  PRIMARY KEY (source, source_key)
);

-- Offers are OBSERVED, not stored as mutable records: one row per offer key per
-- observation time. The current state of an offer is its latest observation;
-- present = 0 records a check that found the offer gone.
CREATE TABLE IF NOT EXISTS offer_observations (
  id              INTEGER PRIMARY KEY,
  offer_key       TEXT NOT NULL,
  car_id          TEXT NOT NULL REFERENCES cars(id),
  source          TEXT NOT NULL,      -- provider that observed it
  observed_at     TEXT NOT NULL,      -- first time this exact state was seen
  confirmed_at    TEXT,               -- last time the same state was seen again (unchanged re-sighting)
  present         INTEGER NOT NULL DEFAULT 1,
  finance_type    TEXT NOT NULL,      -- pcp | pch | cash | campaign
  status          TEXT NOT NULL,      -- what the source implied at the time
  verification    TEXT,
  seller          TEXT,
  vehicle_price   REAL,
  monthly_payment REAL,
  apr             REAL,
  gfv             REAL,
  fingerprint     TEXT,               -- hash of the price-bearing fields
  payload         TEXT NOT NULL,
  artifact_id     INTEGER REFERENCES artifacts(id),
  run_id          INTEGER REFERENCES runs(id),
  UNIQUE (offer_key, observed_at, source)
);
CREATE INDEX IF NOT EXISTS ix_obs_key ON offer_observations(offer_key, observed_at);
CREATE INDEX IF NOT EXISTS ix_obs_car ON offer_observations(car_id);

CREATE TABLE IF NOT EXISTS requirements (
  id          INTEGER PRIMARY KEY CHECK (id = 1),
  as_of       TEXT,
  payload     TEXT NOT NULL,
  source      TEXT NOT NULL,
  artifact_id INTEGER REFERENCES artifacts(id),
  updated_at  TEXT NOT NULL
);

-- One row per source variant (a Carwow CAP derivative, a Kia grade × powertrain):
-- the equipment list, canonical feature flags and numbers as the source prints
-- them. car_id is set when the trim map knows the variant; untracked variants
-- are kept so the Specs page can show every variant of a model.
CREATE TABLE IF NOT EXISTS specs (
  spec_key      TEXT PRIMARY KEY,
  source        TEXT NOT NULL,
  make          TEXT,
  model         TEXT,
  trim          TEXT,
  variant       TEXT,
  cap_id        TEXT,
  version_date  TEXT,
  car_id        TEXT REFERENCES cars(id),
  image_url     TEXT,
  fingerprint   TEXT,
  payload       TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  changed_at    TEXT,
  artifact_id   INTEGER REFERENCES artifacts(id),
  run_id        INTEGER REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS specs_car ON specs(car_id);
CREATE INDEX IF NOT EXISTS specs_model ON specs(make, model);

-- The catalogue: every model Carwow lists, with the flags discovery needs
-- (is it electric, does it have a deals page, a specifications page). Written
-- by the carwow_catalog provider; the Carwow and LeaseLoco scrapers discover
-- their targets from it, so a new EV on sale is picked up without a code change.
CREATE TABLE IF NOT EXISTS models (
  slug          TEXT PRIMARY KEY,     -- <make>/<model> as in the Carwow URL
  make          TEXT NOT NULL,        -- make slug
  model         TEXT NOT NULL,        -- model slug
  make_name     TEXT,                 -- as Carwow prints it ('Kia', 'BMW')
  model_name    TEXT,                 -- as Carwow prints it ('EV3', 'Ioniq 5')
  electric      INTEGER,              -- 1 = battery electric; NULL = not known to be
  has_deals     INTEGER,
  has_specs     INTEGER,
  source        TEXT NOT NULL,
  payload       TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  artifact_id   INTEGER REFERENCES artifacts(id),
  run_id        INTEGER REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS models_electric ON models(electric, has_deals, has_specs);

-- The derivative registry: every derivative of every model as Carwow's model
-- page prints it, by CAP name with its brackets ('[No Heat Pump]'), RRP and
-- version date. A derivative no spec page lists gets a stub car from here; the
-- brackets tell the facts overlay what the name says. Committed as
-- data/history/derivatives.jsonl.
CREATE TABLE IF NOT EXISTS derivatives (
  cap_id        TEXT PRIMARY KEY,
  make_slug     TEXT NOT NULL,
  model_slug    TEXT NOT NULL,
  name          TEXT NOT NULL,
  trim          TEXT,
  engine        TEXT,
  rrp           REAL,
  version_date  TEXT,
  payload       TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  artifact_id   INTEGER REFERENCES artifacts(id),
  run_id        INTEGER REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS derivatives_model ON derivatives(make_slug, model_slug);

-- What a derivative can be ordered with: Carwow's configurator options and
-- packs (name, price, the options a pack bundles), one row per derivative.
-- Committed as data/history/options.jsonl.
CREATE TABLE IF NOT EXISTS options (
  cap_id        TEXT PRIMARY KEY,
  payload       TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  artifact_id   INTEGER REFERENCES artifacts(id),
  run_id        INTEGER REFERENCES runs(id)
);

-- What the maker's own configurator will build: one row per orderable configuration
-- (Hyundai's FSC), with its price, the packages in that price, the packages offered
-- on that trim and powertrain, and the trim's standard equipment. Committed as
-- data/history/configurations.jsonl.
CREATE TABLE IF NOT EXISTS configurations (
  fsc           TEXT PRIMARY KEY,
  make_slug     TEXT NOT NULL,
  model_slug    TEXT NOT NULL,
  trim          TEXT,
  battery_kwh   REAL,
  price         REAL,
  payload       TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  artifact_id   INTEGER REFERENCES artifacts(id),
  run_id        INTEGER REFERENCES runs(id)
);

-- Backfill ledger: which pages the Wayback backfill has fully folded in (for a
-- given since / every-days), so a chunked run that stops at its time budget
-- continues from where it left off next time instead of re-querying the
-- archive for pages it has done. Committed as data/history/backfill.jsonl.
CREATE TABLE IF NOT EXISTS backfill_ledger (
  url        TEXT NOT NULL,
  since      TEXT NOT NULL,
  every_days INTEGER NOT NULL,
  source     TEXT,
  captures   INTEGER,
  done_at    TEXT NOT NULL,
  PRIMARY KEY (url, since, every_days)
);

-- Used stock: one row per used car a source lists for a model, as current
-- stock (first / last seen, present) rather than price history. car_id links
-- the listing to a derivative when its text names one; the residual value
-- the true-monthly needs is read per model and registration year.
CREATE TABLE IF NOT EXISTS used_listings (
  listing_key   TEXT PRIMARY KEY,
  source        TEXT NOT NULL,
  make          TEXT,
  make_slug     TEXT,
  model         TEXT,
  model_slug    TEXT,
  car_id        TEXT REFERENCES cars(id),
  price_gbp     REAL,
  year          INTEGER,
  mileage       INTEGER,
  present       INTEGER NOT NULL DEFAULT 1,
  payload       TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL,
  artifact_id   INTEGER REFERENCES artifacts(id),
  run_id        INTEGER REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS used_model ON used_listings(make_slug, model_slug, year);

-- A used listing's asking price over time, as spans like offer_observations:
-- one row per state, confirmed_at pushed on each unchanged re-sighting, a
-- present=0 row when it goes. The fact behind the used route's history and the
-- residual evidence as of any date.
CREATE TABLE IF NOT EXISTS used_observations (
  id            INTEGER PRIMARY KEY,
  listing_key   TEXT NOT NULL,
  source        TEXT NOT NULL,
  price_gbp     REAL,
  mileage       INTEGER,
  observed_at   TEXT NOT NULL,
  confirmed_at  TEXT,
  present       INTEGER NOT NULL DEFAULT 1,
  run_id        INTEGER REFERENCES runs(id),
  UNIQUE (listing_key, observed_at, source)
);
CREATE INDEX IF NOT EXISTS ix_uobs_key ON used_observations(listing_key, observed_at);
