.PHONY: setup dev venv up down run-core run-detection test test-core test-detection fetch-data fixtures seed-demo validate deck lint

# Installs everything needed to run the demo, skipping anything already
# in place: backend venv, the segmentation model, the fixture data, the
# precomputed demo bundle, and frontend node_modules.
setup:
	$(MAKE) -C backend venv
	$(MAKE) -C backend fetch-model
	$(MAKE) -C backend ensure-fixtures
	$(MAKE) -C backend ensure-demo-bundle
	@if [ -d frontend/node_modules ]; then \
		echo "frontend/node_modules already present, skipping npm install"; \
	else \
		cd frontend && npm install; \
	fi

# Runs the core service (http://localhost:8000) and the frontend dev
# server (http://localhost:5173) together. Ctrl+C stops both.
dev:
	@exec bash scripts/dev.sh

venv:
	$(MAKE) -C backend venv

up:
	$(MAKE) -C backend up

down:
	$(MAKE) -C backend down

run-core:
	$(MAKE) -C backend run-core

run-detection:
	$(MAKE) -C backend run-detection

test:
	$(MAKE) -C backend test

test-core:
	$(MAKE) -C backend test-core

test-detection:
	$(MAKE) -C backend test-detection

fetch-data:
	$(MAKE) -C backend fetch-data

fixtures:
	$(MAKE) -C backend fixtures

seed-demo:
	$(MAKE) -C backend seed-demo

validate:
	$(MAKE) -C backend validate

# The four P-1 deck figures, from the precomputed demo bundle.
# Throwaway scripts, see deck/README.md.
deck:
	backend/.venv/bin/python deck/scripts/make_figures.py

lint:
	$(MAKE) -C backend lint
