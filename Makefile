# quantlab developer targets.  `make help` lists them.

PY      ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PIP     := $(if $(shell command -v uv),uv pip install --python $(PY),$(PY) -m pip install)
BIN     := $(dir $(PY))
HOME_   ?= .quantlab
LAKE    ?= data/lake

.DEFAULT_GOAL := help
.PHONY: help install test test-fast test-console contract lint examples docs docs-serve dashboard console check clean

help:  ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  \033[1m%-13s\033[0m %s\n", $$1, $$2}'

install:  ## Python package with every extra, plus the console's npm dependencies
	$(PIP) -e ".[dashboard,equities,dev,docs]"
	cd console && npm ci

test:  ## the full pytest suite, including the example scripts
	$(PY) -m pytest

test-fast:  ## pytest without the slow example runs
	$(PY) -m pytest -m "not slow"

test-console:  ## strict TypeScript check and the Vitest suite
	cd console && npm run typecheck && npm test

contract:  ## write a research home with the Python CLI, then hold the Node console to its numbers
	@tmp=$$(mktemp -d) && export QUANTLAB_HOME=$$tmp QUANTLAB_LAKE=$$tmp/lake && \
	  $(BIN)quantlab fetch synthetic --bars 1500 >/dev/null && \
	  $(BIN)quantlab backtest sma_crossover --study contract --save "SMA default" >/dev/null && \
	  $(BIN)quantlab search bollinger_reversion --study contract --perm 5 >/dev/null && \
	  cd console && QUANTLAB_CLI=$(abspath $(BIN))/quantlab npm run -s test:contract

lint:  ## ruff over Python, strict tsc over TypeScript
	$(BIN)ruff check quantlab tests dashboard examples
	cd console && npm run -s typecheck

examples:  ## run the three example scripts offline
	for f in examples/0*.py; do echo "== $$f"; $(PY) $$f || exit 1; done

docs:  ## build the documentation site strictly (output in site/)
	$(BIN)mkdocs build --strict

docs-serve:  ## serve the documentation with live reload
	$(BIN)mkdocs serve

dashboard:  ## the Streamlit dashboard
	QUANTLAB_HOME=$(HOME_) QUANTLAB_LAKE=$(LAKE) $(BIN)streamlit run dashboard/app.py

console:  ## build and start the Node console on http://127.0.0.1:8787
	cd console && npm run -s build && \
	  QUANTLAB_HOME=$(abspath $(HOME_)) QUANTLAB_LAKE=$(abspath $(LAKE)) QUANTLAB_CLI=$(abspath $(BIN))/quantlab npm start

check: lint test test-console contract docs  ## everything CI runs

clean:  ## build outputs and caches (never data or research state)
	rm -rf site console/dist .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -not -path "./console/node_modules/*" -exec rm -rf {} +
