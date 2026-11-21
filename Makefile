UV ?= python -m uv
PY_SRC = core tests/core scripts/probe.py scripts/fetch_kit.py

test:
	$(UV) run pytest -q tests/core

lint:
	$(UV) run ruff check $(PY_SRC)
	$(UV) run ruff format --check $(PY_SRC)
	$(UV) run mypy $(PY_SRC)

run:
	DRY_RUN=0 $(UV) run python -m core.main

dry:
	DRY_RUN=1 DB_PATH=data/dry.db $(UV) run python -m core.main

kit:
	$(UV) run python scripts/fetch_kit.py

probe:
	$(UV) run python scripts/probe.py
