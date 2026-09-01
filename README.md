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
- [ ] P9 onward: see PLAN.md section 14

P2 was validated against a synthetic fixture scene (`backend/scripts/make_fixture_scene.py`, `backend/data/fixtures/synthetic_scene.tif`), not a real Sentinel-1 product, since Sentinel-1 access is blocked on the Earthdata account (PLAN.md section 4A). Swap in a real scene once that account exists; the pipeline itself does not change.

## Repository layout

The project is split into `backend/` (the Python services, tests, scripts, config and data) and `frontend/` (the operator console UI). See PLAN.md section 3 for the full layout and rationale for the two-environment split within the backend (`services/detection` for TensorFlow, `services/core` for everything else).

## Development

```
make up      # start Postgres/PostGIS/Timescale and both services
make test    # run the test suite
```

These root-level targets delegate into `backend/Makefile`. Run them directly from `backend/` if you prefer.

Absolute slick age in hours cannot be estimated reliably from a single SAR acquisition. This system reports a relative age band and states its reasoning, never a number in hours.

Every eliminated vessel carries a non-empty reason. Vessel type and class never eliminate a vessel, they only downweight its score.
