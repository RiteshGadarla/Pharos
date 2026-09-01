.PHONY: venv up down run-core run-detection test test-core test-detection fetch-data seed-demo lint

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

seed-demo:
	$(MAKE) -C backend seed-demo

lint:
	$(MAKE) -C backend lint
