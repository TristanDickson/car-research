"""car-research data pipeline.

providers (discover → fetch → parse)  →  SQLite medallion  →  static snapshot

  Bronze  artifacts     every fetched body, content-addressed (sha256), superseded chain
  Silver  source_rows   source-shaped rows per artifact
  Gold    cars · deals · requirements   canonical entities (JSON payload + indexed columns)

`python -m pipeline refresh` runs every provider and writes the snapshot the SPA reads.
Same shape as etf-tool / bolthole, without Postgres or a worker: the data is tiny.
"""
