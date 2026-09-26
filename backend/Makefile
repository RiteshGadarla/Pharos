.PHONY: venv fetch-model ensure-fixtures synthetic fixtures sample ensure-demo-bundle up down run-core run-detection test test-core test-detection fetch-data seed-demo seed-case publish-cases validate lint

venv:
	@if [ ! -d .venv ]; then python3.11 -m venv .venv; fi
	.venv/bin/pip install --upgrade pip -q
	.venv/bin/pip install -r requirements.txt

# Regenerates every synthetic input from scratch: SAR scene, wind,
# currents, offshore wind, cached origin field, and each case study's
# scene, wind and currents (config/cases.yaml). One script rather than
# several, and it resolves the dependency order itself (origin_field
# integrates through currents and wind_offshore, so it runs after them).
#
# Pharos needs no downloaded dataset to run. This target is what makes
# that true, and it is the same script the README points Linux, macOS and
# Windows users at.
#
# Apart from the staged sample scene these outputs aren't committed (see
# .gitignore): small, deterministic and fast to rebuild, so there's no
# reason to carry binary diffs in git history every time one changes.
synthetic:
	.venv/bin/python scripts/make_synthetic_data.py --force

# Back-compat alias. `synthetic` is the name the README uses now.
fixtures: synthetic

# Builds whichever synthetic inputs are missing, skips the rest. Run
# `make synthetic` directly to force a full regenerate (e.g. after
# editing a make_fixture_*.py script).
ensure-fixtures:
	.venv/bin/python scripts/make_synthetic_data.py

# Processes the staged sample SAR image through detection and writes
# data/processed/sample_detections.geojson. The fastest check that an
# install works: no database, no Docker, no frontend, no dataset.
sample:
	.venv/bin/python scripts/process_sample.py

# Downloads the segmentation model (no auth needed) if it isn't already
# on disk. See PLAN.md section 4A.
fetch-model:
	@if [ -f data/models/oil-spill-deeplab/model.keras ]; then \
		echo "model already present at data/models/oil-spill-deeplab/model.keras, skipping"; \
	else \
		mkdir -p data/models/oil-spill-deeplab && \
		PYTHONPATH=. .venv/bin/python -c "\
import shutil; \
from huggingface_hub import hf_hub_download; \
p = hf_hub_download('sahilvishwa2108/oil-spill-deeplab', 'model.keras'); \
shutil.copy(p, 'data/models/oil-spill-deeplab/model.keras'); \
print('downloaded to data/models/oil-spill-deeplab/model.keras')"; \
	fi

# Builds the precomputed case bundles only if they aren't already there.
# Run `make seed-demo` directly to force a fresh regenerate.
ensure-demo-bundle:
	@if [ -f data/precomputed/demo_bundle.json ] && [ -f data/precomputed/scene_preview.png ] && [ -f data/precomputed/cases.json ]; then \
		echo "demo bundles already present, skipping (run 'make seed-demo' to regenerate)"; \
	else \
		$(MAKE) seed-demo; \
	fi

up:
	docker compose up -d db

down:
	docker compose down

run-core:
	PYTHONPATH=. .venv/bin/uvicorn services.core.app:app --host 0.0.0.0 --port 8000 --reload

run-detection:
	PYTHONPATH=. .venv/bin/uvicorn services.detection.app:app --host 0.0.0.0 --port 8001 --reload

test: ensure-fixtures test-core test-detection

test-core:
	.venv/bin/pytest -q tests services/core validation

test-detection:
	.venv/bin/pytest -q services/detection

fetch-data:
	bash scripts/fetch_data.sh

# Every case study in config/cases.yaml, then the case index, then a copy
# of all of it into the frontend's static data. The default case is also
# written to the original single-bundle paths. Each case runs the full
# 30 member ensemble, so this takes a while; see seed-case for one.
seed-demo: ensure-fixtures
	PYTHONPATH=. .venv/bin/python scripts/seed_demo.py --all
	$(MAKE) publish-cases

# One case: make seed-case CASE=monsoon-high-wind. The index is rebuilt
# from every bundle on disk, so other cases already built stay listed.
seed-case: ensure-fixtures
	@if [ -z "$(CASE)" ]; then echo "usage: make seed-case CASE=<id>, ids are in config/cases.yaml"; exit 2; fi
	PYTHONPATH=. .venv/bin/python scripts/seed_demo.py --case $(CASE)
	$(MAKE) publish-cases

# Copies cases.json, every indexed case's outputs and the default case's
# top-level files into ../frontend/public/data/, removing any case
# directory there that the index does not list.
publish-cases:
	PYTHONPATH=. .venv/bin/python scripts/publish_cases.py

validate: ensure-fixtures
	PYTHONPATH=. .venv/bin/python scripts/run_validation.py

lint:
	.venv/bin/ruff check services/core services/detection validation
