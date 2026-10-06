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

-- Silver: source-shaped rows, one per parsed record, keyed to the artifact they came from.
CREATE TABLE IF NOT EXISTS source_rows (
  id          INTEGER PRIMARY KEY,
  artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
  source      TEXT NOT NULL,
  kind        TEXT NOT NULL,          -- car | offer | requirements | trim_map
  source_key  TEXT NOT NULL,          -- the record's id within the source
  row         TEXT NOT NULL,          -- JSON, as parsed (source vocabulary)
  parsed_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_source_rows_key ON source_rows(source, kind, source_key);
CREATE INDEX IF NOT EXISTS ix_source_rows_artifact ON source_rows(artifact_id);

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
  observed_at     TEXT NOT NULL,      -- ISO date or datetime
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
