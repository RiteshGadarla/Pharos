.PHONY: up down test test-core test-detection fetch-data seed-demo lint

up:
	docker compose up -d --build

down:
	docker compose down

test: test-core test-detection

test-core:
	docker compose run --rm core pytest -q /app/tests /app/services/core

test-detection:
	docker compose run --rm detection pytest -q /app/tests /app/services/detection

fetch-data:
	bash scripts/fetch_data.sh

seed-demo:
	python3 scripts/seed_demo.py

lint:
	docker compose run --rm core ruff check services/core
