.PHONY: install run run-demo demo demo-assets test lint format docker-build docker-up docker-down

UV ?= uv
APP_HOST ?= 0.0.0.0
APP_PORT ?= 8000
BASE_URL ?= http://127.0.0.1:8000
AUDIO ?=
DEMO_RUNNER_TIMEOUT_SECONDS ?= 60

install:
	$(UV) sync --extra dev

run:
	$(UV) run uvicorn app.main:app --host $(APP_HOST) --port $(APP_PORT) --reload

run-demo:
	./scripts/run_demo.sh

demo-assets:
	./scripts/prepare_demo_assets.sh

test:
	$(UV) run pytest

lint:
	$(UV) run ruff check .

format:
	$(UV) run ruff format .

demo:
	$(UV) run local-voice-ai-demo $(AUDIO) --base-url $(BASE_URL) --timeout-seconds $(DEMO_RUNNER_TIMEOUT_SECONDS)

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down
