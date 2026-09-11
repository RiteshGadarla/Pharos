.PHONY: setup dev venv up down run-core run-detection test test-core test-detection fetch-data synthetic fixtures sample seed-demo validate deck lint

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
#
# scripts/dev.sh is the POSIX implementation and stays the one this
# target execs, since it is the exercised path. scripts/dev.py is the
# same two commands with cross-platform process handling, and is how
# Windows (which has neither make nor bash) runs the pair.
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

# The single synthetic data generator: SAR scene, wind, currents,
# offshore wind, cached origin field. DRISHTA downloads no dataset, so
# this is where every input it consumes comes from.
synthetic:
	$(MAKE) -C backend synthetic

# Back-compat alias for `synthetic`.
fixtures:
	$(MAKE) -C backend synthetic

# Processes the staged sample SAR image through detection. The fastest
# check that an install works.
sample:
	$(MAKE) -C backend sample

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
