.PHONY: venv up down run-core run-detection test test-core test-detection fetch-data seed-demo lint

venv:
	python3.11 -m venv .venv
	.venv/bin/pip install --upgrade pip -q
	.venv/bin/pip install -r requirements.txt

up:
	docker compose up -d db

down:
	docker compose down

run-core:
	PYTHONPATH=. .venv/bin/uvicorn services.core.app:app --host 0.0.0.0 --port 8000 --reload

run-detection:
	PYTHONPATH=. .venv/bin/uvicorn services.detection.app:app --host 0.0.0.0 --port 8001 --reload

test: test-core test-detection

test-core:
	.venv/bin/pytest -q tests services/core

test-detection:
	.venv/bin/pytest -q services/detection

fetch-data:
	bash scripts/fetch_data.sh

seed-demo:
	.venv/bin/python scripts/seed_demo.py

lint:
	.venv/bin/ruff check services/core services/detection
