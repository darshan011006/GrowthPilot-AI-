# GrowthPilot AI — common commands. Run `make help`.
SHELL := /bin/bash
PY := backend/.venv/bin/python
# Node 24 from Homebrew is keg-only; put it first on PATH if present.
NODE_ENV_PATH := PATH="/opt/homebrew/opt/node@24/bin:$$PATH"

.PHONY: help start setup env demo dev backend frontend worker migrate test test-backend lint build e2e reset-demo clean

help:
	@echo "make start      One command for a fresh clone: install, configure, demo login, run (start here)"
	@echo "make setup      Install backend (venv) and frontend (npm) dependencies"
	@echo "make env        Create .env with fresh secret keys (never overwrites)"
	@echo "make demo       Create a demo login and load the fictional demo brand"
	@echo "make dev        Run API (:8000) + web app (:3000) with the in-process worker"
	@echo "make test       Backend tests + lint, frontend lint + type-check"
	@echo "make build      Production build of the frontend"
	@echo "make e2e        Browser end-to-end test of the demo flow (needs: make dev running)"
	@echo "make migrate    Apply database migrations"
	@echo "make worker     Run the background worker as a separate process"

start:
	./scripts/start.sh

setup:
	test -d backend/.venv || python3 -m venv backend/.venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e "backend[dev]"
	cd frontend && $(NODE_ENV_PATH) npm ci

env:
	cd backend && .venv/bin/python -m growthpilot init-env

demo:
	cd backend && .venv/bin/python -m growthpilot demo-setup

migrate:
	cd backend && .venv/bin/python -m growthpilot migrate

dev:
	./scripts/dev.sh

backend:
	cd backend && .venv/bin/python -m growthpilot serve --reload

frontend:
	cd frontend && $(NODE_ENV_PATH) npm run dev

worker:
	cd backend && RUN_WORKER_IN_PROCESS=false .venv/bin/python -m growthpilot worker

test: test-backend lint

test-backend:
	cd backend && .venv/bin/python -m pytest -q

lint:
	cd backend && .venv/bin/ruff check growthpilot tests migrations
	cd frontend && $(NODE_ENV_PATH) npx eslint src && $(NODE_ENV_PATH) npx next typegen && $(NODE_ENV_PATH) npx tsc --noEmit

build:
	cd frontend && $(NODE_ENV_PATH) npm run build

e2e:
	cd backend && .venv/bin/python ../scripts/e2e_demo.py

clean:
	rm -rf frontend/.next backend/.pytest_cache backend/.ruff_cache
