.PHONY: up down test test-core test-detection fetch-data seed-demo lint

up:
	$(MAKE) -C backend up

down:
	$(MAKE) -C backend down

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
