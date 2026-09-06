# DRISHTA

A maritime event attribution engine. Built for Smart India Hackathon 2026, NTRO Problem Statement 26143.

An oil slick on satellite imagery is a crime scene with no timestamp and no suspect, and it is not where it started. DRISHTA detects a slick on Sentinel-1 SAR, rejects look-alikes using wind physics, runs an ensemble backward drift to produce an origin probability field over latitude, longitude and time, reconstructs AIS vessel traffic through that field, detects vessels whose AIS went dark over the origin window, confirms those dark vessels against unmatched ship targets in the same SAR scene, scores every vessel with an explicit weighted evidence model, logs a reason for every vessel it eliminates, evaluates the reconstructed discharge against MARPOL Annex I conditions, and exports a hash sealed evidence dossier carrying a Bharatiya Sakshya Adhiniyam Section 63 certificate.

The system does not report where a spill started. It reports the probability of every place and time it could have started, then asks which vessel's behaviour is best explained by that distribution.

Underneath that sits an architectural claim: **the drift kernel is a plug in**. An oil spill is instance one of a general problem shape, which is "given an observed effect at a known place and time, reconstruct the origin window and rank who was present in it, including vessels that were not broadcasting."

See [PLAN.md](PLAN.md) for the full build plan, data contracts, non-negotiables and phase order. That file is the source of truth for design decisions. Its section 0B lists what changed from the earlier SLICKTRACE plan and why.

## What is actually built

Phases are from PLAN.md section 19.

- [x] **P0** repo scaffold, Docker Compose, Makefile targets
- [x] **P1** data contracts in `backend/services/core/schemas.py`, contract tests for all four rules in PLAN.md section 4
- [x] **P2** detection service: sensor adapter, render, tile, infer, stitch, polygonize
- [ ] **P3** evaluation, honest per class IoU. Deferred, blocked on the labeled datasets (PLAN.md section 4A). `services/detection/eval.py` raises rather than reporting a substitute number, and the dossier states plainly that the number is not available
- [ ] **P3a** Cerulean agreement harness. The client and the agreement metric are written (`backend/validation/cerulean_client.py`, `cerulean_agreement.py`) and cache offline; no scenes have been pulled yet
- [x] **P4** wind physics gate, synthetic FP reduction measurement
- [x] **P4a** optical corroboration, three states emitted correctly including `no_coverage`
- [x] **P5** characterisation, `SlickFeatures` geometry and relative age band
- [x] **P6** drift kernel protocol, backward ensemble, origin probability field. OpenOil, Leeway and null kernels; the null kernel runs the whole pipeline end to end with no forcing data at all
- [ ] **P6a** drifter validation. `backend/validation/drifter.py` is written; no Global Drifter Program trajectories have been pulled yet
- [x] **P7** AIS ingest, synthetic generator, track reconstruction, dark gaps, integrity flags (F7)
- [x] **P7a** SAR ship target extraction and radar cross check (F8)
- [x] **P8** scoring engine, elimination log, three verdict classes
- [x] **P8a** MARPOL Annex I layer and offshore infrastructure flag
- [~] **P9** frontend shell, map, layers, time scrubber. A functional MVP, not the full section 16 and 16A spec, see below
- [ ] **P9a** ambient flow shader, **P9b** rewind sequence: not started
- [x] **P10** dossier PDF with provenance and the BSA s.63 certificate page
- [x] **P11** validation harness, 50 incidents and three ablations
- [ ] **P11a** Cerulean Dark case attempt: not started, blocked on P3a
- [x] **P12** dark period ledger and AIS completeness table, exposed read only
- [ ] **P13** space time prism, **P14** second drift kernel scenario, **P15** forward forecast view: not started
- [~] **P16** demo hardening: offline mode and the precompute bundle work; no MP4 fallback recorded yet
- [x] **P-1** deck assets, in `deck/`. Built after the pipeline rather than before it, see `deck/README.md` for what that changes

## What is real and what is synthetic

This matters more than the feature list, so it is stated plainly rather than buried.

**Real:** the detection model (`sahilvishwa2108/oil-spill-deeplab`, loaded from local disk), the drift physics (OpenDrift OpenOil), the ensemble construction, the field binning and normalisation, the wind gate thresholds and their physical justification, every scoring factor, every elimination rule, the verdict logic, the MARPOL condition checks, the hashing and the certificate. The slick texture in the fixture scene is real Sentinel-1A oil spill backscatter and speckle, composited from a CC BY 4.0 dataset (Persian Gulf, not the Arabian Sea). See `backend/data/fixtures/real_oil_texture/ATTRIBUTION.md`.

**Synthetic:** the SAR scene's geolocation, acquisition time and surrounding sea; the wind and current forcing fields; the AIS traffic; the SAR ship targets. The three static geographic layers (coastline, MARPOL special areas, offshore installations) are generalised placeholders, and each file says so at the top of itself.

**Why the AIS is synthetic, and why that is allowed.** The problem statement says, verbatim: *"Real AIS if available may be used else synthetic data can be prepared for the region of oil spill to demonstrate the functioning of the algorithm."* That sentence is recorded at the top of `backend/config/demo.yaml`. Permission is not an excuse to be sloppy: lane geometry, vessel type mix, speed distributions, ping intervals and dropout rates are meant to be fitted from real MarineCadastre statistics, the format authority the PS itself names, with only the incident injected. That fitting has not been done yet and the current distributions are documented placeholders. The database schema mirrors the MarineCadastre columns, so a real ICG or DGLL feed drops in with no code change.

**Not real anywhere:** an accuracy number for the detector. The HuggingFace model card's self reported 0.9668 F1 is not reproduced in the UI, the README, the dossier or any slide, because background pixels dominate this five class taxonomy and an aggregate figure says nothing about oil class performance. `eval.py` exists to produce the honest per class number and is blocked on the labeled datasets; until it runs, the dossier says the number is unavailable rather than substituting one.

## The pipeline, stage by stage

```
SAR scene
  -> sensor adapter          services/detection/sensors.py       (S1 implemented, EOS-04 a documented stub)
  -> render, tile, infer     services/detection/render|tiling|infer.py
  -> polygonize (oil)        services/detection/polygonize.py    -> Detection
  -> ship targets (hulls)    services/detection/ships.py         -> ShipTarget
  -> wind physics gate       services/core/gate/wind.py          -> GateResult
  -> optical corroboration   services/core/corroborate/optical.py -> OpticalCorroboration
  -> characterisation        services/core/characterize/         -> SlickFeatures
  -> backward drift ensemble services/core/drift/ + hindcast/    -> OriginField
  -> AIS reconstruction      services/core/ais/tracks|darkgaps.py -> AISTrack, DarkGap
  -> AIS integrity           services/core/ais/integrity.py      -> IntegrityFlag
  -> radar cross check       services/core/crosscheck/radar.py   -> matched / unmatched targets
  -> elimination             services/core/scoring/eliminate.py  -> Elimination
  -> scoring, F1 to F8       services/core/scoring/engine.py     -> SuspectScore
  -> verdict                 services/core/scoring/verdict.py    -> CaseVerdict
  -> MARPOL Annex I          services/core/legal/marpol.py       -> MarpolAssessment
  -> infrastructure flag     services/core/crosscheck/infrastructure.py
  -> ledgers                 services/core/ledger/               -> accumulating records
  -> dossier + certificate   services/core/dossier/              -> PDF
```

### The eight evidence factors

Weights and thresholds live in `backend/config/scoring.yaml`, are shown in the UI, and are printed verbatim in the dossier. No classifier is trained for attribution: there is no ground truth, and a black box cannot be defended in court.

| | Factor | What it measures |
|---|---|---|
| F1 | field integral | Origin probability integrated along the vessel's reconstructed track. Rewards a vessel that lingered inside a broad uncertain cloud over one that clipped a narrow peak, which distance to centroid ranking gets exactly backwards |
| F2 | dark overlap | How much origin probability mass the vessel's dead reckoned envelope covered while it was dark |
| F3 | axis alignment | Agreement, modulo 180 degrees, between the slick's major axis and the vessel's course |
| F4 | speed anomaly | Sustained slowing below the vessel's own median transit speed while inside the field |
| F5 | course anomaly | Course change across the vessel's passage through the origin window |
| F6 | vessel plausibility | A small prior by vessel type. **Downweights only. It never eliminates**, and its weight is kept low deliberately |
| F7 | AIS integrity | Aggregated severity of self report inconsistencies: missing IMO, implied speed beyond the plausible maximum, static data changing mid passage, MMSI reuse, position jumps. This answers "AIS can be spoofed, not just switched off" with a factor rather than a shrug |
| F8 | radar confirmed dark | An unmatched ship target from the SAR scene itself fell inside the vessel's dark envelope and in a live cell of the origin field. **The only factor backed by a second, independent sensor**, which is why its weight is the highest in the model |

### The three verdict classes

| Verdict | Condition | Meaning |
|---|---|---|
| `ATTRIBUTED` | Rank 1 beats rank 2 by the configured dominance margin, and was broadcasting throughout the origin window | One vessel dominates. A ranked evidence package for a human investigator |
| `RANKED` | Several plausible candidates, none dominant | An ordered list with reasons, plus the full elimination log. Narrows the field |
| `DARK_CONFIRMED` | Every broadcasting vessel eliminated or below the plausibility floor, **and** at least one unmatched ship target sits inside the origin field | A vessel absent from the AIS picture was present in the origin envelope. Radar saw a hull; AIS did not report it |

`DARK_CONFIRMED` is not a failure state. Every competing system files "no broadcasting suspect found" as no result. For an intelligence organisation, it is the finding.

### The radar cross check, and its limits

The cross check is the highest value addition in this revision, because it converts a dark vessel from an inference about missing data into an independent sensor observation. Its limits travel with it, in the docs, in the dossier and in the code:

- Sentinel-1 ship detection at GRD resolution misses small vessels.
- Not every unmatched target is evasion. Vessels below AIS carriage requirements, fishing craft and buoys all appear. The system reports the count, the size and the position of unmatched targets, and never asserts that unmatched equals guilty.
- The match is made at the acquisition instant only. That cuts both ways, and the code takes it seriously: an unmatched target is only attributed to a vessel that was dark at that same instant, never to one whose gap had already closed. Without that rule the check degenerates, because a dead reckoned envelope widens at the vessel's plausible maximum speed and after an hour it is larger than the whole origin field.

### What the MARPOL layer does and does not say

`services/core/legal/marpol.py` evaluates the Annex I conditions that are checkable from a reconstructed track: proceeding en route, distance from nearest land, whether the track entered a special area, and an estimated instantaneous discharge rate. The rate is always a band, never a single figure, and the schema enforces that: SAR sees that a damping film is present, never how thick it is.

This layer never outputs a determination of illegality. It reports which conditions the reconstructed behaviour appears not to satisfy, with its assumptions printed verbatim in the dossier. Oil content in parts per million is not observable from satellite, so no assessment can ever conclude that a discharge was permitted on that basis, and the code does not attempt it.

### What the certificate claims

The dossier's final page is a Bharatiya Sakshya Adhiniyam, 2023 Section 63 Schedule Part A certificate, pre filled from information the pipeline already carries, including the SHA-256 of every input artifact with the hash function named. Part B is left blank, because the statute requires it to be completed and signed by a person, and that is a human act rather than a software output.

The claim is that the document is formatted to carry the information the certificate requires. The claim is **not** that the document is admissible. Admissibility is decided by a court on the facts.

### Validation, three independent tracks

They answer different questions and all three are needed.

1. **Internal consistency** (`backend/validation/harness.py`, run with `make validate`). 50 synthetic incidents with a known injected culprit, stratified across field variant, traffic density and dark gap presence, plus three ablations: F2 zeroed, F1 replaced by distance to the field's centroid, and F8 zeroed. Written to `backend/data/processed/validation.md`. This measures internal consistency of the scoring model, not real world accuracy, and the report says so in its own text.
2. **External agreement on detection** (`backend/validation/cerulean_agreement.py`). IoU against Cerulean's reviewed slick polygons, reported as agreement with an independent production system and never as accuracy. Written; no scenes pulled yet.
3. **Physical validation of the drift engine** (`backend/validation/drifter.py`). Backward ensembles run from real NOAA Global Drifter Program positions, reporting containment rate and the quantile at which the true prior position landed. This is the only component where real ground truth exists. A drifter is not oil, so it validates the advection and diffusion core, not the oil model on top. Written; no trajectories pulled yet.

**Cerulean is never in the runtime path.** It lives only under `backend/validation/`, and `backend/tests/test_no_cerulean_in_services.py` enforces that by scanning the source tree.

## The frontend

`frontend/` is an operator console: MapLibre plus deck.gl, chart paper styling, no external tiles, works offline. What is built:

- A single time scrubber that drives the origin probability field and every AIS track together. It opens at the acquisition time and plays backwards from it, and reads its position relative to acquisition rather than as a bare UTC stamp.
- The SAR scene as a basemap, so detection polygons sit on the image they came from. It is a display product on a sea anchored dB stretch, not the calibrated data the model saw, and the stretch it used is on screen in the provenance chip.
- Detection polygons with their wind gate verdicts, suppressed detections greyed with the reason on hover.
- AIS tracks with dark gaps drawn dashed and their dead reckoned envelopes as translucent polygons.
- **Radar ship targets**: unmatched targets filled in `--radar`, matched targets hollow in the same colour. Both are drawn, because a cross check that matches nothing is a broken matcher rather than a fleet of dark vessels, and you cannot see the difference unless both are on screen.
- A verdict chip and card, a suspects panel with animated factor bars and narratives, a plain elimination log, and a plain ledger view.
- Three view presets (Scene, Origin, Traffic), because the case spans two orders of magnitude and no single camera shows it all.

Known gap against PLAN.md section 16: suspect ranking is the static already scored result rather than recomputed per scrub tick, so the P9 acceptance test is only partly met. Sections 16A layers 1 to 3 (ambient flow shader, rewind sequence, space time prism) are not started.

The origin field's colour ramp is normalised per timestep rather than across the whole volume, because the same probability mass covers steadily more ground as the hindcast runs back and its peak density falls by over an order of magnitude. Normalised globally the early field renders as almost nothing, which reads as "there is nothing here" rather than "little is known here". Per timestep normalisation keeps the shape readable but hides that density drop, so the spread is stated as a number in kilometres beside the scrubber instead of being left to be inferred from how faint a blob looks on a projector.

## Repository layout

```
PLAN.md          the source of truth for design decisions
deck/            P-1 deck figures and the throwaway scripts that build them
backend/
  config/        scoring.yaml, pipeline.yaml, demo.yaml, marpol.yaml
  services/      core/ and detection/, one shared venv
  validation/    a sibling of services/, never imported by it
  tests/
  scripts/
frontend/        the operator console
```

`backend/validation/` being a sibling of `backend/services/` rather than a child is deliberate: it is what keeps measurement tools, Cerulean above all, out of the runtime path.

## Development

Only Postgres, PostGIS and TimescaleDB run in Docker. `services/core`, `services/detection` and `validation` share one Python environment (`backend/requirements.txt`, `backend/.venv`) and run locally.

```
make venv           # build backend/.venv from backend/requirements.txt
make up             # start Postgres/PostGIS/Timescale in Docker
make run-core       # run services/core locally, http://localhost:8000
make run-detection  # run services/detection locally, http://localhost:8001
make test           # run the test suite locally
make validate       # 50 incidents plus three ablations -> data/processed/validation.md
```

These root level targets delegate into `backend/Makefile`. Copy `backend/.env.example` to `backend/.env` first; `POSTGRES_HOST` points at `localhost` since the database is the only thing in Docker. `KAGGLE_API_TOKEN` there is only needed to re-pull the real oil slick texture patch; the chosen patch is already committed, so it is not needed for normal development.

`backend/data/fixtures/*.nc` and `*.tif` are not committed, since they are regeneratable and deterministic. Run `make fixtures` to build them, or just `make test` or `make setup`, which both build whatever is missing first. The real oil texture PNGs stay committed, since they are pulled from a real dataset rather than scripted.

### Running the demo

From the repository root:

```
make setup   # venv, model download, demo bundle, frontend node_modules; skips whatever is already there
make dev     # core service (:8000) and the frontend dev server (:5173) together
```

`make setup` is idempotent. Run `make seed-demo` directly to force a fresh regenerate of the demo bundle, the SAR basemap and the dossier after changing a fixture or a config file; it also copies all three into `frontend/public/data/`, the static fallback the frontend uses when the core service is not running, so the demo works with the network cable unplugged and no backend process at all.

For the case where the laptop cannot be trusted to keep two dev servers alive, `cd frontend && npm run build && npx vite preview` serves the production build with no backend at all. That is what the "DEMO MODE: OFFLINE" badge in the header refers to. Exercise this path once before the day, since it is the one with no moving parts. The one thing it cannot serve is the ledger view, which reads from the core service; that is stated on screen rather than failing silently.

Presenting order that matches how the pipeline actually runs: **Scene** (the SAR image, the detected slick, the wind gate that accepted it), **Origin** (the backward drift's probability field, scrubbing back from acquisition), then **Traffic** (every vessel, the dark period envelopes, the unmatched radar target, and the vessels eliminated far off scene). Open the elimination log when asked how a vessel was ruled out.

### Building the deck figures

```
backend/.venv/bin/python deck/scripts/make_figures.py
```

Writes four figures to `deck/figures/` from the precomputed demo bundle. See `deck/README.md`.

## Statements this system makes about itself

These are load bearing. They are in the code, the dossier and the UI, not just here.

- Absolute slick age in hours cannot be estimated reliably from a single SAR acquisition. We tested whether it is recoverable, concluded it is not, and therefore report a relative band with the reasoning that produced it, never a number in hours.
- The hindcast output is a probability field, never a point. A centroid may be displayed for orientation but never enters the scoring math.
- Every eliminated vessel carries a non empty reason. Vessel type and class never eliminate a vessel, they only downweight its score.
- Dark periods raise suspicion. They never drop a vessel.
- The output is ranked evidence for a human investigator. It is not an automated accusation.
- Every stochastic component takes its seed from configuration. Two runs of the demo produce identical numbers.
