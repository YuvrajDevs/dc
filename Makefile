PY ?= python3
SEED ?= 42

.PHONY: install lint test generate demo clean
install:
	$(PY) -m pip install -e ".[dev]"

lint:
	ruff check src tests && ruff format --check src tests

test:
	pytest

generate:
	$(PY) -m tally generate --seed $(SEED) --days 30 --out data/world-$(SEED)

demo: generate
	@echo "Phase 1 demo: synthetic world written to data/world-$(SEED)"

clean:
	rm -rf data .pytest_cache .ruff_cache
