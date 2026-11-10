PY ?= python3
SEED ?= 42
AS_OF ?= 2026-02-05

.PHONY: demo-ui serve dashboard uat audit install lint test generate warehouse reconcile grade check benchmark demo clean
install:
	$(PY) -m pip install -e ".[dev]"

lint:
	ruff check src tests && ruff format --check src tests

test:
	pytest

generate:
	$(PY) -m trueup generate --seed $(SEED) --days 30 --out data/world-$(SEED)

warehouse: generate
	$(PY) -m trueup split --world data/world-$(SEED) --out data/batches-$(SEED) --late-rate 0.05 --seed 1
	rm -f data/warehouse.duckdb
	$(PY) -m trueup ingest --db data/warehouse.duckdb data/batches-$(SEED)/*
	$(PY) -m trueup build --db data/warehouse.duckdb
	$(PY) -m trueup status --db data/warehouse.duckdb

reconcile: warehouse
	$(PY) -m trueup reconcile --db data/warehouse.duckdb --as-of $(AS_OF)

grade: reconcile
	$(PY) -m trueup grade --db data/warehouse.duckdb --world data/world-$(SEED) --floors benchmarks/floors.json --profile easy

check:
	$(PY) -m trueup check

benchmark:
	$(PY) -m trueup stability --profile hard --seeds 1 2 3 4 5 6 7 8 --days 60
	$(PY) -m trueup scale --profile hard --out benchmarks/results/scale-hard.json

demo: grade
	@echo "Demo ready: warehouse at data/warehouse.duckdb, scorecard above"

clean:
	rm -rf data .pytest_cache .ruff_cache

# --- product UI -----------------------------------------------------------------------
# Builds a 60-day demo world through the real pipeline (backfill), then you start the two servers.
demo-ui:
	rm -rf data/ui && mkdir -p data/ui
	$(PY) -m trueup generate --seed $(SEED) --days 60 --out data/ui/world
	$(PY) -m trueup split --world data/ui/world --out data/ui/batches --late-rate 0.05 --seed 1
	$(PY) -m trueup backfill --db data/ui/serve.duckdb --batches data/ui/batches --start 2026-01-01 --end 2026-03-04
	@echo "Now run:  make serve   (API, port 8000)   and   make dashboard   (UI, port 3000)"

serve:
	$(PY) -m trueup serve --db data/ui/serve.duckdb --port 8000

dashboard:
	cd dashboard && npm install && npm run build && npm run start -p 3000

# Browser acceptance tests mapped to docs/UAT.md scenario IDs (boots and stops its own servers)
uat:
	PY=$(PY) scripts/uat.sh

audit:
	pip-audit
	cd dashboard && npm audit --omit=dev
