.PHONY: nightly build test test-pipeline test-web web-dev web-build

# The night's work, on the laptop that holds the raw store ($CAR_RESEARCH_RAW): new committed
# history into the store, scrape every live source into it, build from scratch, snapshot, deal table.
nightly:
	python3 -m pipeline nightly

# Build from scratch from what the raw store already holds (no network), then the snapshot and deal table.
build:
	python3 -m pipeline build --deal-table docs/deal-comparison.md

test: test-pipeline test-web

test-pipeline:
	python3 -m unittest discover -s tests -v

test-web:
	cd web && npm run lint && npm run typecheck && npm test

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build
