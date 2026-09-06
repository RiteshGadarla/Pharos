.PHONY: venv fetch-model ensure-fixtures fixtures ensure-demo-bundle up down run-core run-detection test test-core test-detection fetch-data seed-demo validate lint

venv:
	@if [ ! -d .venv ]; then python3.11 -m venv .venv; fi
	.venv/bin/pip install --upgrade pip -q
	.venv/bin/pip install -r requirements.txt

# Regenerates every .nc / .tif fixture from scripts/make_fixture_*.py.
# These aren't committed (see .gitignore): small, deterministic, fast to
# rebuild, so there's no reason to carry ~2.8MB of binary diffs in git
# history every time one changes. origin_field depends on currents and
# wind_offshore already being on disk, so it runs last.
fixtures:
	PYTHONPATH=. .venv/bin/python scripts/make_fixture_scene.py
	PYTHONPATH=. .venv/bin/python scripts/make_fixture_wind.py
	PYTHONPATH=. .venv/bin/python scripts/make_fixture_currents.py
	PYTHONPATH=. .venv/bin/python scripts/make_fixture_wind_offshore.py
	PYTHONPATH=. .venv/bin/python scripts/make_fixture_origin_field.py

# Builds whichever fixtures are missing, skips the rest. Run `make
# fixtures` directly to force a full regenerate (e.g. after editing a
# make_fixture_*.py script).
ensure-fixtures:
	@if [ -f data/fixtures/synthetic_scene.tif ] && [ -f data/fixtures/synthetic_wind.nc ] && \
	    [ -f data/fixtures/synthetic_currents.nc ] && [ -f data/fixtures/synthetic_wind_offshore.nc ] && \
	    [ -f data/fixtures/synthetic_origin_field.nc ]; then \
		echo "fixtures already present, skipping (run 'make fixtures' to regenerate)"; \
	else \
		$(MAKE) fixtures; \
	fi

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

# Builds the precomputed demo bundle only if it isn't already there.
# Run `make seed-demo` directly to force a fresh regenerate.
ensure-demo-bundle:
	@if [ -f data/precomputed/demo_bundle.json ] && [ -f data/precomputed/scene_preview.png ]; then \
		echo "demo bundle already present, skipping (run 'make seed-demo' to regenerate)"; \
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

seed-demo: ensure-fixtures
	PYTHONPATH=. .venv/bin/python scripts/seed_demo.py
	@mkdir -p ../frontend/public/data
	cp data/precomputed/demo_bundle.json ../frontend/public/data/demo_bundle.json
	cp data/precomputed/case_dossier.pdf ../frontend/public/data/case_dossier.pdf
	cp data/precomputed/scene_preview.png ../frontend/public/data/scene_preview.png
	@echo "copied to ../frontend/public/data/"

validate: ensure-fixtures
	PYTHONPATH=. .venv/bin/python scripts/run_validation.py

lint:
	.venv/bin/ruff check services/core services/detection validation
