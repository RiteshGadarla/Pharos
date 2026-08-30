# SLICKTRACE

Oil spill attribution pipeline built for Smart India Hackathon, NTRO Problem Statement 26143.

An oil slick on satellite imagery is not where it started. SLICKTRACE detects a slick on Sentinel-1 SAR, rejects look-alikes using wind physics, runs an ensemble backward drift to produce an origin probability field over latitude, longitude and time, reconstructs AIS vessel traffic through that field, detects vessels whose AIS went dark over the origin window, scores every vessel with an explicit weighted evidence model, logs a reason for every vessel it eliminates, and exports a hashed evidence dossier.

The system does not report where a spill started. It reports the probability of every place and time it could have started, then asks which vessel's behaviour is best explained by that distribution.

See [PLAN.md](PLAN.md) for the full build plan, data contracts, non-negotiables and phase order. That file is the source of truth for design decisions.

## Status

Build in progress, phase by phase, per the acceptance tests in PLAN.md section 14.

- [x] P0: repo scaffold, Docker Compose, Makefile targets
- [x] P1: data contracts in `services/core/schemas.py`, contract tests
- [ ] P2: detection service
- [ ] P3: evaluation, honest per-class IoU
- [ ] P4 onward: see PLAN.md section 14

## Repository layout

See PLAN.md section 3 for the full layout and rationale for the two-environment split (`services/detection` for TensorFlow, `services/core` for everything else).

## Development

```
make up      # start Postgres/PostGIS/Timescale and both services
make test    # run the test suite
```

Absolute slick age in hours cannot be estimated reliably from a single SAR acquisition. This system reports a relative age band and states its reasoning, never a number in hours.

Every eliminated vessel carries a non-empty reason. Vessel type and class never eliminate a vessel, they only downweight its score.
