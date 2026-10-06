.PHONY: snapshot test test-pipeline test-web web-dev web-build

# Run every provider into the local SQLite DB and write the snapshot the SPA reads.
snapshot:
	python3 -m pipeline refresh --out web/public/data

test: test-pipeline test-web

test-pipeline:
	python3 -m unittest discover -s tests -v

test-web:
	cd web && npm run lint && npm run typecheck && npm test

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build
