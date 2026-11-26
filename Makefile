# CampusPilot developer commands. Run `make help` to list them.
# Everything binds to 127.0.0.1 only.

API_DIR := apps/api
WEB_DIR := apps/web
PY      := $(API_DIR)/.venv/bin/python
API_PORT ?= 8000
WEB_PORT ?= 3000

.PHONY: help setup setup-api setup-web dev api web mock-dev test test-api test-web lint fmt \
        ingest ingest-dry reindex moodle-check acceptance screenshots e2e secrets-check tunnel-check

help:
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-15s %s\n",$$1,$$2}'

setup: setup-api setup-web ## Install backend (uv venv) and frontend (npm) dependencies

setup-api: ## Create apps/api/.venv with Python 3.12 and install the API
	cd $(API_DIR) && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e '.[dev]'

setup-web: ## Install web dependencies and the Playwright Chromium browser
	cd $(WEB_DIR) && npm install && npx playwright install chromium

dev: ## Start the API (port 8000) and the web UI (port 3000) together
	$(MAKE) -j2 api web

api: ## Start only the API on 127.0.0.1:8000
	cd $(API_DIR) && .venv/bin/uvicorn campuspilot.main:app --host 127.0.0.1 --port $(API_PORT) --reload

web: ## Start only the web UI on 127.0.0.1:3000
	cd $(WEB_DIR) && npm run dev -- --hostname 127.0.0.1 --port $(WEB_PORT)

mock-dev: ## Like `dev`, but with the scripted fake model (no tunnel needed)
	CAMPUSPILOT_MOCK_LLM=true $(MAKE) -j2 api web

test: test-api test-web ## Run every offline test and linter

test-api: ## pytest + ruff for the API
	cd $(API_DIR) && .venv/bin/pytest -q && .venv/bin/ruff check . ../../scripts

test-web: ## Lint, type-check, build and Playwright smoke test for the UI
	cd $(WEB_DIR) && npm run lint && npx tsc --noEmit && npm run build && npx playwright test

lint: ## ruff + eslint
	cd $(API_DIR) && .venv/bin/ruff check . ../../scripts
	cd $(WEB_DIR) && npm run lint

fmt: ## Auto-format Python code
	cd $(API_DIR) && .venv/bin/ruff format . ../../scripts && .venv/bin/ruff check --fix . ../../scripts

ingest: ## Fetch and index all approved sources (polite, slow on purpose)
	$(PY) scripts/ingest.py --all-approved

ingest-dry: ## Show what ingestion would fetch, without fetching
	$(PY) scripts/ingest.py --all-approved --dry-run

reindex: ## Rebuild chunks and the FTS5 index from saved raw files
	$(PY) scripts/reindex.py

moodle-check: ## Live read-only check of your Moodle token / iCal URL
	$(PY) scripts/moodle_check.py

acceptance: ## Live acceptance check against Gemma (needs the tunnel)
	$(PY) scripts/acceptance_check.py

e2e: ## Playwright smoke test only
	cd $(WEB_DIR) && npx playwright test

screenshots: ## Regenerate docs/screenshots with Playwright
	cd $(WEB_DIR) && SCREENSHOTS=1 npx playwright test --project=screenshots

tunnel-check: ## Is the model tunnel up?
	@curl -s -m 5 http://127.0.0.1:11500/api/tags >/dev/null && echo "tunnel: up" || echo "tunnel: DOWN (run: ssh -fN passpoli-llm)"

secrets-check: ## The §9 security sweep over tracked files
	@echo "Tracked secret-looking files:"; git ls-files | grep -Ei '\.env$$|\.db$$|data/raw|token|secret|id_ed25519' || echo "  none"
	@echo "Server IPs / tokens / keys in tracked files:"; git grep -nE '10[.]119[.]|wstoken[=]|BEGIN OPENSSH' -- . ':!MASTER_BUILD_PROMPT.md' || echo "  none"
