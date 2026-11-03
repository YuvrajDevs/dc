PY ?= python3
SEED ?= 42

.PHONY: install lint test generate warehouse demo clean
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

demo: warehouse
	@echo "Demo ready: warehouse at data/warehouse.duckdb"

clean:
	rm -rf data .pytest_cache .ruff_cache
