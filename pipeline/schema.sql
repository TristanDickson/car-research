-- Bronze: every fetched body, content-addressed. One row per distinct body per
-- (source, capability, target); a newer body supersedes the previous one.
CREATE TABLE IF NOT EXISTS artifacts (
  id            INTEGER PRIMARY KEY,
  source        TEXT NOT NULL,
  capability    TEXT NOT NULL,
  target        TEXT NOT NULL,
  url           TEXT,
  sha256        TEXT NOT NULL,
  content_type  TEXT,
  status_code   INTEGER,
  body          BLOB NOT NULL,
  fetched_at    TEXT NOT NULL,
  parser_version TEXT,
  superseded_by INTEGER REFERENCES artifacts(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_artifacts_key_sha ON artifacts(source, capability, target, sha256);
CREATE INDEX IF NOT EXISTS ix_artifacts_key ON artifacts(source, capability, target, fetched_at);

-- Silver: source-shaped rows, one per parsed record, keyed to the artifact they came from.
CREATE TABLE IF NOT EXISTS source_rows (
  id          INTEGER PRIMARY KEY,
  artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
  source      TEXT NOT NULL,
  kind        TEXT NOT NULL,          -- car | deal | requirements
  source_key  TEXT NOT NULL,          -- the record's id within the source
  row         TEXT NOT NULL,          -- JSON
  parsed_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_source_rows_key ON source_rows(source, kind, source_key);
CREATE INDEX IF NOT EXISTS ix_source_rows_artifact ON source_rows(artifact_id);

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
  source         TEXT NOT NULL,       -- provider that wrote the row
  artifact_id    INTEGER REFERENCES artifacts(id),
  updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deals (
  id              TEXT PRIMARY KEY,
  car_id          TEXT NOT NULL REFERENCES cars(id),
  captured_at     TEXT,
  finance_type    TEXT NOT NULL,      -- pcp | pch | cash | campaign
  status          TEXT NOT NULL,
  verification    TEXT,
  seller_source   TEXT,               -- the deal's own "source" (Carwow, Richmond, ...)
  vehicle_price   REAL,
  monthly_payment REAL,
  apr             REAL,
  gfv             REAL,
  payload         TEXT NOT NULL,
  source          TEXT NOT NULL,      -- provider that wrote the row
  artifact_id     INTEGER REFERENCES artifacts(id),
  updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_deals_car ON deals(car_id);
CREATE INDEX IF NOT EXISTS ix_deals_type_status ON deals(finance_type, status);

CREATE TABLE IF NOT EXISTS requirements (
  id          INTEGER PRIMARY KEY CHECK (id = 1),
  as_of       TEXT,
  payload     TEXT NOT NULL,
  source      TEXT NOT NULL,
  artifact_id INTEGER REFERENCES artifacts(id),
  updated_at  TEXT NOT NULL
);

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
  error       TEXT
);
