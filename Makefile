PY ?= python3
SEED ?= 42
AS_OF ?= 2026-02-05

.PHONY: install lint test generate warehouse reconcile grade check benchmark demo clean
install:
	$(PY) -m pip install -e ".[dev]"

lint:
	ruff check src tests && ruff format --check src tests

test:
	pytest

generate:
	$(PY) -m tally generate --seed $(SEED) --days 30 --out data/world-$(SEED)

warehouse: generate
	$(PY) -m tally split --world data/world-$(SEED) --out data/batches-$(SEED) --late-rate 0.05 --seed 1
	rm -f data/warehouse.duckdb
	$(PY) -m tally ingest --db data/warehouse.duckdb data/batches-$(SEED)/*
	$(PY) -m tally build --db data/warehouse.duckdb
	$(PY) -m tally status --db data/warehouse.duckdb

reconcile: warehouse
	$(PY) -m tally reconcile --db data/warehouse.duckdb --as-of $(AS_OF)

grade: reconcile
	$(PY) -m tally grade --db data/warehouse.duckdb --world data/world-$(SEED) --floors benchmarks/floors.json --profile easy

check:
	$(PY) -m tally check

benchmark:
	$(PY) -m tally stability --profile hard --seeds 1 2 3 4 5 6 7 8 --days 60
	$(PY) -m tally scale --profile hard --out benchmarks/results/scale-hard.json

demo: grade
	@echo "Demo ready: warehouse at data/warehouse.duckdb, scorecard above"

clean:
	rm -rf data .pytest_cache .ruff_cache
