.PHONY: snapshot snapshot-offline test test-pipeline test-web web-dev web-build

# Run every provider (live scrapers included) into the local SQLite DB, append the
# sighting log and write the snapshot the SPA reads.
snapshot:
	python3 -m pipeline refresh --out web/public/data
	python3 -m pipeline deal-table > docs/deal-comparison.md

# Same without the network: seed + pastes + the committed history. What CI runs.
snapshot-offline:
	python3 -m pipeline refresh --offline --out web/public/data
	python3 -m pipeline deal-table > docs/deal-comparison.md

test: test-pipeline test-web

test-pipeline:
	python3 -m unittest discover -s tests -v

test-web:
	cd web && npm run lint && npm run typecheck && npm test

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build
