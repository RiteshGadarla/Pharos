# SLICKTRACE

Oil spill attribution pipeline built for Smart India Hackathon, NTRO Problem Statement 26143.

An oil slick on satellite imagery is not where it started. SLICKTRACE detects a slick on Sentinel-1 SAR, rejects look-alikes using wind physics, runs an ensemble backward drift to produce an origin probability field over latitude, longitude and time, reconstructs AIS vessel traffic through that field, detects vessels whose AIS went dark over the origin window, scores every vessel with an explicit weighted evidence model, logs a reason for every vessel it eliminates, and exports a hashed evidence dossier.

The system does not report where a spill started. It reports the probability of every place and time it could have started, then asks which vessel's behaviour is best explained by that distribution.

See [PLAN.md](PLAN.md) for the full build plan, data contracts, non-negotiables and phase order. That file is the source of truth for design decisions.

## Status

Build in progress, phase by phase, per the acceptance tests in PLAN.md section 14.

- [x] P0: repo scaffold, Docker Compose, Makefile targets
- [x] P1: data contracts in `backend/services/core/schemas.py`, contract tests
- [x] P2: detection service (render, tile, infer, stitch, polygonize)
- [ ] P3: evaluation, honest per-class IoU (deferred, blocked on the labeled dataset, see PLAN.md section 4A item 4)
- [x] P4: wind physics gate, synthetic FP-reduction measurement
- [x] P5: characterisation, SlickFeatures geometry and relative age band
- [x] P6: backward drift ensemble (real OpenDrift/OpenOil) and origin probability field
- [x] P7: AIS reconstruction, synthetic generator, track interpolation, dark gaps
- [x] P8: scoring engine and elimination log
- [x] `backend/scripts/seed_demo.py`: runs the full pipeline once, offline, on the committed fixtures (detection through scoring) and writes `backend/data/precomputed/demo_bundle.json`. `services/core/app.py` serves it at `GET /api/demo`. Not the full PLAN.md section 15 precompute bundle (no real Sentinel-1 scenes, no `hero_sequence.json` for the rewind sequence), but a real end-to-end run, not fabricated data.
- [~] P9: frontend shell, map, layers, time scrubber. Built as a functional MVP, not the full section 12/12A spec: MapLibre + deck.gl map (chart-paper style, no external tiles, works offline), a single time scrubber that drives the origin probability field and every AIS track together, detections with wind-gate verdicts, dark-gap envelopes, a suspects panel with animated factor bars and narrative, and a plain elimination log table. Suspect ranking itself is the static, already-scored result (not recomputed per scrub tick), so the P9 acceptance test ("scrubbing updates field, tracks and ranking together") is only partly met. Demo-facing additions on top of that MVP:
  - **SAR basemap.** `backend/services/core/preview.py` warps the scene's VV band to EPSG:4326 and stretches it for display, and the map draws it under everything as a deck.gl `BitmapLayer`, so detection polygons sit on the image they came from instead of over blank water. It is a display product on a sea-anchored dB stretch, not the calibrated data the model saw; the stretch it used is on screen in the provenance chip and in `scene.preview.note`. Served at `GET /api/scene_preview.png`, with a static copy for the offline path.
  - **Three view presets** (Scene, Origin, Traffic), named for the views in PLAN.md section 12. The case spans two orders of magnitude (a 5 km slick, a 100 km reachable envelope, an eliminated vessel 250 km out), so no single camera shows it all. Origin is the default.
  - **Origin field as a filtered raster** rather than one polygon per grid cell, so a probability density stops reading as a mosaic of 1 km squares. The texture's texels are the field's own cells and its bounds are the field's own footprint, so the geometry is unchanged; only the display interpolation between cell centres is new.
  - **Verdict card and scene evidence panel.** The rank-1 vessel, its dark period, its margin over rank 2, and the wind-gate verdict, age band and slick geometry, all with their stated reasoning. These answer the two questions a room asks first ("how do you know that is oil and not a look-alike", "how old is it") without having to open the dossier.
  - **Scrubber** opens at the acquisition time and plays *backwards* from it, which is the signature interaction in PLAN.md section 12. It reads its position relative to acquisition ("48h 14m before acquisition"), not just an absolute UTC stamp, and ticks once per forcing timestep so it shows the resolution of the field it drives.
  - **Origin spread readout**, in kilometres, beside the scrubber. The field's colour ramp is normalised per timestep rather than across the whole volume, because the same probability mass covers steadily more ground as the hindcast runs back and its peak density falls by over an order of magnitude; normalised globally the early field renders as almost nothing, which reads as "there is nothing here" rather than "little is known here". Per-timestep normalisation keeps the shape readable but hides that density drop, so the spread is stated as a number instead of left to be inferred from how faint a blob looks on a projector.

### The origin field has to visibly bloom, and it did not

The interaction the product is built around is scrubbing back from acquisition and watching the origin probability field expand as the hindcast runs out of knowledge. Measured, it was not doing that: the field's spread went 3.07 km at acquisition to 3.27 km six hours back, a 7% change over the whole window. The cloud drifted; it never grew. Four separate causes, all real, none of them cosmetic:

1. **`seed_demo.py` overrode the configured hindcast down to 8 members over a 6 hour horizon** for speed. Over 6 hours the ensemble barely diverges. The demo precompute now runs `config/pipeline.yaml` as written, 30 members over 48 hours, which the committed forcing fixtures already cover (they span 66 hours). It costs about 2 minutes for a step that runs once.
2. **The ensemble held surface current error fixed across every member** while sampling wind drift, diffusivity and seed time. That asserted the current was known exactly, which for a surface slick is the wrong thing to be certain about. It is now sampled per member over 0.05 to 0.15 m/s, the range CMEMS surface currents validate against drifters at. Horizontal diffusivity was left at 1 to 10 m²/s, which is what Okubo's diffusion diagram gives at the 1 to 10 km scale a slick drifts over: it was *not* inflated to make the cloud bigger.
3. **The smoothing kernel was wider than the thing it was smoothing.** A 0.02 degree bandwidth is about 2.2 km, against a true particle spread near acquisition of roughly 0.2 km, so the kernel was manufacturing an order of magnitude more uncertainty than the ensemble produced and pinning the field to a floor it could never go below. Now 0.008 degrees.
4. **The synthetic AIS scenario scaled its geometry off the field's grid span but fixed its leg duration at one hour**, so a wider field silently accelerated every vessel. At a 48 hour horizon they exceeded 35 knots. Leg duration is now derived from the geometry at a plausible 11 knot transit speed, and the "spatially close" hard negative is placed relative to the field's actual spread rather than its grid extent, so it stays inside the probability mass instead of being eliminated for having none.

Together: the particle spread now runs 0.2 km at acquisition to 5.5 km two days back, and the rendered field 1.2 km to 5.4 km, a 4.4x bloom that is monotonic across the window.

### Two scoring bugs the longer horizon exposed

Both were latent, and both were only visible once the field's time window got much longer than a vessel track:

- **F5 (course anomaly) sampled the vessel's course at the field window's own edges.** With a 48 hour window and a 5 hour track those edges are nowhere near the vessel, so it returned its "could not compute" sentinel of 0.0 for every vessel. It now samples the ends of the overlap between the track and the window.
- **0.0 is not a neutral value in log-odds space.** With `LOGIT_EPS = 1e-6`, `logit(0)` is -13.8, so any factor that legitimately found nothing contributed a penalty large enough to bury every real signal the other factors found. A vessel that simply never slowed down scored `logit(0)` on F4 and picked up -13.8 on that alone, which was enough to rank the wrong vessel first on the fixture field. The clamp is now 0.05, bounding any single factor to about a 19:1 likelihood ratio, and factors that genuinely cannot be computed return 0.5, which contributes nothing.

The narrative templater also had a related honesty problem: it described any positive contribution in words, so a `field_integral` contribution of 0.0004 was read out as "its track passes through the highest-probability part of the origin field". It now ignores contributions below 0.05 and falls back to saying no single factor stands out.

The 50-incident validation harness still reports 100% rank-1 accuracy on the baseline and both ablations after these changes.
- [x] P10: dossier PDF. `backend/services/core/dossier/render.py`, built from the same bundle the frontend reads. Cover, scene footprint, detection table (states plainly that per-class IoU is not available, P3 is deferred, rather than reporting a substitute number), slick characterisation, three origin-field time snapshots, ranked suspects with factor-contribution bar charts and narrative, the full elimination log, and a provenance page (SHA-256 of every input artifact, the git commit, `config/scoring.yaml` verbatim). Served at `GET /api/dossier`; the frontend's "Download dossier" button uses it, falling back to a static copy for the fully offline path.
- [x] P11: validation harness. `backend/services/core/validation/harness.py` and `backend/scripts/run_validation.py`. Runs 50 synthetic incidents stratified across a few independently-run backward ensembles, traffic density and dark-gap presence, and reports rank-1/rank-3 accuracy, mean rank, and a breakdown by traffic density, plus the two ablations (F2 zeroed, F1 replaced by distance to the field's centroid) to `backend/data/processed/validation.md`. Reported honestly, including a case where the aggregate ablation numbers moved the opposite of the expected direction on this run, with the underlying mechanism isolated separately (a purpose-built right-place-wrong-time decoy vessel) rather than smoothed over. States plainly that this measures internal consistency, not real-world accuracy.
- [ ] P9a (GPU ambient flow shader), P9b (choreographed rewind sequence), P12 (3D space-time prism): not started, see PLAN.md section 14.

P2 was validated against a fixture scene (`backend/scripts/make_fixture_scene.py`, `backend/data/fixtures/synthetic_scene.tif`), not a real Sentinel-1 product, since Sentinel-1 access is blocked on the Earthdata account (PLAN.md section 4A). Swap in a real scene once that account exists; the pipeline itself does not change. The fixture's own slick is no longer hand-drawn: it composites real Sentinel-1A oil-spill backscatter and speckle texture from a CC BY 4.0 dataset (Persian Gulf, not the Arabian Sea) into the synthetic background, with the oil/sea contrast scaled up from the source patch's own value to clear the detector's confidence threshold. See `backend/data/fixtures/real_oil_texture/ATTRIBUTION.md` for the source, license and exactly what was changed.

The demo's own incident (`backend/config/demo.yaml`) is a deliberately illustrative scenario, not a re-investigation of a specific real, already-resolved spill: its `source_reference` grounds *why this matters* in real, documented, unattributed Eastern Arabian Sea pollution (peer-reviewed literature, journalism on tarballs from unreported discharges, and a real Indian Coast Guard smuggling interception off Mumbai), while the date, bounding box and outcome stay clearly synthetic.

`backend/data/fixtures/*.nc` and `*.tif` are not committed (regeneratable, deterministic, no reason to carry binary diffs in git history): run `make fixtures` to build them from `backend/scripts/make_fixture_*.py`, or just `make test` / `make setup`, which both build whatever's missing first. The real oil-texture PNGs under `backend/data/fixtures/real_oil_texture/` stay committed, since those aren't scripted, they're pulled from a real dataset.

## Repository layout

The project is split into `backend/` (the Python services, tests, scripts, config and data) and `frontend/` (the operator console UI). See PLAN.md section 3 for the full layout.

## Development

Only Postgres/PostGIS/Timescale runs in Docker. `services/core` and `services/detection` share one Python environment (`backend/requirements.txt`, `backend/.venv`) and run locally.

```
make venv           # build backend/.venv from backend/requirements.txt
make up              # start Postgres/PostGIS/Timescale in Docker
make run-core         # run services/core locally, http://localhost:8000
make run-detection    # run services/detection locally, http://localhost:8001
make test             # run the test suite locally
```

These root-level targets delegate into `backend/Makefile`. Run them directly from `backend/` if you prefer. Copy `backend/.env.example` to `backend/.env` first; `POSTGRES_HOST` points at `localhost` since the database is the only thing in Docker. `KAGGLE_API_TOKEN` there is only needed to re-pull the real oil-slick texture patch (`.venv/bin/kaggle datasets download bitsandlayers/sar-oil-spill-segmentation-dataset-sos`); the chosen patch is already committed under `backend/data/fixtures/real_oil_texture/`, so this isn't needed for normal development.

Absolute slick age in hours cannot be estimated reliably from a single SAR acquisition. This system reports a relative age band and states its reasoning, never a number in hours.

Every eliminated vessel carries a non-empty reason. Vessel type and class never eliminate a vessel, they only downweight its score.

### Frontend (demo UI)

From the repo root:

```
make setup   # backend venv, model download, demo bundle, frontend node_modules -- skips whatever is already there
make dev     # runs the core service (:8000) and the frontend dev server (:5173) together, Ctrl+C stops both
```

`make setup` is idempotent: safe to re-run, only does the parts that are missing. Run `make seed-demo` directly (not `setup`) to force a fresh regenerate of the demo bundle, the SAR basemap PNG and the dossier PDF after changing a fixture or `config/scoring.yaml`; it also copies all three into `frontend/public/data/`, the static fallback the frontend uses when the core service isn't running, so the demo also works with the network cable unplugged and no backend process at all.

### Running it on demo day

`make dev` is the normal path. For the case where the laptop cannot be trusted to keep two dev servers alive, `cd frontend && npm run build && npx vite preview` serves the production build with no backend at all: the bundle, the basemap and the dossier all load from `frontend/public/data/`, which is what the "DEMO MODE: OFFLINE" badge in the header refers to. This path is worth exercising once before the day, since it is the one that has no moving parts.

Presenting order that matches how the pipeline actually runs: **Scene** (the SAR image, the detected slick on it, and the wind gate that accepted it), **Origin** (the backward drift's probability field, scrubbing back from acquisition), then **Traffic** (every vessel, the dark period envelopes, and the vessels eliminated far off scene). The elimination log tab is the tab to open when asked how a vessel was ruled out.

Run `make validate` to run the 50-incident validation harness and write `backend/data/processed/validation.md` (takes under a minute; it runs a handful of real backward ensembles).
