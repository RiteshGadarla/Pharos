# DRISHTA

A maritime event attribution engine. Built for Smart India Hackathon 2026, NTRO Problem Statement 26143.

An oil slick on satellite imagery is a crime scene with no timestamp and no suspect, and it is not where it started. DRISHTA detects a slick on Sentinel-1 SAR, rejects look-alikes using wind physics, runs an ensemble backward drift to produce an origin probability field over latitude, longitude and time, reconstructs AIS vessel traffic through that field, detects vessels whose AIS went dark over the origin window, confirms those dark vessels against unmatched ship targets in the same SAR scene, scores every vessel with an explicit weighted evidence model, logs a reason for every vessel it eliminates, evaluates the reconstructed discharge against MARPOL Annex I conditions, and exports a hash sealed evidence dossier carrying a Bharatiya Sakshya Adhiniyam Section 63 certificate.

The system does not report where a spill started. It reports the probability of every place and time it could have started, then asks which vessel's behaviour is best explained by that distribution.

Underneath that sits an architectural claim: **the drift kernel is a plug in**. An oil spill is instance one of a general problem shape, which is "given an observed effect at a known place and time, reconstruct the origin window and rank who was present in it, including vessels that were not broadcasting."

See [PLAN.md](PLAN.md) for the full build plan, data contracts, non-negotiables and phase order. That file is the source of truth for design decisions. Its section 0B lists what changed from the earlier SLICKTRACE plan and why.

## Quick start

**No dataset download is required.** Nothing here is blocked on a Copernicus account, an Earthdata login, a real AIS feed or a 40GB Zenodo archive. One SAR scene is committed to the repository as the staged sample image, and every other input the pipeline consumes is generated locally and deterministically by a single script.

```bash
git clone <this repo> && cd slicktrace
make setup     # venv, model weights, synthetic data, demo bundle, frontend deps
make sample    # process the staged sample SAR image, print the oil detections
make dev       # core service on :8000 and the operator console on :5173
```

The only thing `make setup` pulls over the network, beyond pip and npm packages, is the segmentation model's weights (about 205MB, from HuggingFace, no account and no API token). They are cached to `backend/data/models/` and loaded from disk afterwards, so every run after the first is fully offline.

This runs natively on Linux, macOS and Windows. Windows has no `make`, so the same steps run as plain Python and npm commands there, and `python scripts/dev.py` replaces `make dev` on every platform. See [Setup, per platform](#setup-per-platform).

### What you get without downloading anything

| | Where it comes from |
|---|---|
| One SAR scene with a real oil slick texture in it | Committed: `backend/data/fixtures/synthetic_scene.tif`, see [SAMPLE_SCENE.md](backend/data/fixtures/SAMPLE_SCENE.md) |
| Wind, currents, sea surface temperature | Generated: `backend/scripts/make_synthetic_data.py` |
| A cached backward drift ensemble | Generated: same script, from the two above |
| AIS vessel traffic, including the culprit and four hard negatives | Generated in memory every run, positioned against the origin field it is scored on |
| Coastline, MARPOL special areas, offshore installations | Committed placeholders, each file says so at the top of itself |
| Segmentation model weights | Downloaded once, `make fetch-model` |

What that costs you is stated plainly in [What is real and what is synthetic](#what-is-real-and-what-is-synthetic) rather than buried. Swapping in real data is a path change, not a code change: the AIS schema mirrors the MarineCadastre columns, and the forcing readers are OpenDrift's CF-generic readers, so real CMEMS and ERA5 files drop in where the fixtures sit.

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
    make_synthetic_data.py   one command, every synthetic input
    process_sample.py        one command, process the staged sample image
    seed_demo.py             the full pipeline, into the precomputed bundle
    run_validation.py        50 incidents and three ablations
    make_fixture_*.py        the individual generators, driven by make_synthetic_data.py
  data/fixtures/
    synthetic_scene.tif      the staged sample image, committed
    real_oil_texture/        the real CC BY 4.0 slick patch composited into it
frontend/        the operator console
```

`backend/validation/` being a sibling of `backend/services/` rather than a child is deliberate: it is what keeps measurement tools, Cerulean above all, out of the runtime path.

## Development

Only Postgres, PostGIS and TimescaleDB run in Docker, and only the ledger view needs them. `services/core`, `services/detection` and `validation` share one Python environment (`backend/requirements.txt`, `backend/.venv`) and run locally.

### Prerequisites

| | Version | Needed for |
|---|---|---|
| Python | 3.11 | everything backend. 3.12 and 3.13 are untested against this pinned dependency set, so 3.11 is the one to install |
| Node.js | 20.19+ or 22.12+ | the operator console. Vite 8 refuses to start below those |
| Docker | any recent | Postgres only, and only for the ledger view. Skip it and the rest still runs |
| Disk | about 2.5GB | 205MB model weights, roughly 1.5GB of Python wheels (TensorFlow dominates), the rest npm |

No GDAL, PROJ, NetCDF or Rust toolchain has to be installed separately, on any of the three platforms. Every one of the 186 packages in the resolved dependency tree is either pure Python or ships a prebuilt wheel for Linux x86_64 and arm64, macOS arm64 and Windows x86_64 on Python 3.11.

### Setup, per platform

The three steps are the same everywhere: build the Python environment, fetch the model weights, generate the synthetic data. `make setup` does all three plus the demo bundle and the frontend's `node_modules`, and skips whatever is already in place.

#### Linux

```bash
sudo apt install -y python3.11 python3.11-venv git make
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs

git clone <this repo> && cd slicktrace
make setup
```

On Fedora or RHEL, `sudo dnf install python3.11 git make nodejs`. On Arch, `sudo pacman -S python git make nodejs npm` (check `python --version` is 3.11).

#### macOS

```bash
brew install python@3.11 node git
# make ships with the Xcode command line tools: xcode-select --install

git clone <this repo> && cd slicktrace
make setup
```

Apple silicon is the exercised path. TensorFlow runs on CPU here, which is fine: the model is small and the demo bundle is precomputed once.

#### Windows

The project runs natively on Windows. There is no capability that only works under Linux: every one of the 186 packages in the resolved dependency tree is either pure Python or ships a Windows wheel for Python 3.11, including the three that usually cause trouble (TensorFlow, rasterio, and OpenDrift's `roaring-landmask`, which is a Rust extension but publishes an abi3 wheel). No compiler, no GDAL install, no conda.

What Windows genuinely does not have is `make` and `bash`, so the Makefile targets have to be run as the commands they wrap. `scripts/dev.py` replaces `make dev` on every platform.

Install [Python 3.11](https://www.python.org/downloads/) (any 3.11.x, and tick "Add python.exe to PATH") and [Node.js 22 LTS](https://nodejs.org/), then paste this in one block:

```powershell
git clone <this repo>
cd slicktrace\backend

py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt

# model weights, the one download
New-Item -ItemType Directory -Force -Path data\models\oil-spill-deeplab
.\.venv\Scripts\python -c "import shutil; from huggingface_hub import hf_hub_download; shutil.copy(hf_hub_download('sahilvishwa2108/oil-spill-deeplab','model.keras'), 'data/models/oil-spill-deeplab/model.keras')"

# synthetic data, then process the staged sample image
.\.venv\Scripts\python scripts\make_synthetic_data.py
.\.venv\Scripts\python scripts\process_sample.py

# the full pipeline and the demo bundle
$env:PYTHONPATH="."; .\.venv\Scripts\python scripts\seed_demo.py

cd ..\frontend
npm install
```

Then, from the repository root:

```powershell
python scripts\dev.py
```

Two things to expect during `pip install`, both harmless and both automatic:

- **pip pauses and backtracks on `tensorflow-io-gcs-filesystem`.** TensorFlow asks for `>=0.23.1`, and that package dropped Windows wheels after 0.31.0. pip walks back to 0.31.0, which does have a Python 3.11 Windows wheel and satisfies the constraint. Nothing to do, it just looks like a stall.
- **`awesome-slugify` builds from a source archive.** It publishes no wheel for any platform, but it is pure Python with no dependencies of its own, so setuptools handles it and no compiler is involved. It arrives via OpenDrift's oil database.

`uvloop` is skipped on Windows by its own environment marker, and uvicorn falls back to the standard asyncio loop. That is a small performance difference on a service that serves a precomputed JSON bundle, so it does not matter here.

##### Where Windows differs, precisely

| | Linux and macOS | Windows |
|---|---|---|
| Run both servers | `make dev` | `python scripts\dev.py` |
| Any other target | `make <target>` | the command in [Commands](#commands), run directly |
| venv interpreter | `backend/.venv/bin/python` | `backend\.venv\Scripts\python` |
| Set `PYTHONPATH` for a script | `PYTHONPATH=. python ...` | `$env:PYTHONPATH="."; python ...` |
| Copy the bundle to the frontend | done by `make seed-demo` | one `Copy-Item`, below |

`make seed-demo` also copies the bundle into `frontend\public\data\`, which the raw script does not, so do that by hand on this path:

```powershell
New-Item -ItemType Directory -Force -Path ..\frontend\public\data
Copy-Item data\precomputed\demo_bundle.json, data\precomputed\case_dossier.pdf, data\precomputed\scene_preview.png ..\frontend\public\data\
```

Neither `make_synthetic_data.py` nor `process_sample.py` needs `PYTHONPATH` set or a particular working directory: both put the backend directory on `sys.path` themselves, which is most of why they exist as single entry points. `seed_demo.py` and `run_validation.py` are older and still expect `backend\` as the working directory with it on `PYTHONPATH`, which is what the `$env:PYTHONPATH` prefix above is for.

**WSL2 is still worth considering**, not because native Windows is broken but because it gives you `make` and the bash tooling, so every command in this README works verbatim. `wsl --install -d Ubuntu`, then follow [Linux](#linux). Clone inside the WSL filesystem (`~/slicktrace`), not under `/mnt/c/`, or file IO will dominate every step.

### Generating the synthetic data

One script produces every input the pipeline consumes. It resolves the dependency order itself, since the cached origin field integrates through the currents and the offshore wind and cannot run before them.

```bash
cd backend

.venv/bin/python scripts/make_synthetic_data.py            # build whatever is missing
.venv/bin/python scripts/make_synthetic_data.py --force    # rebuild everything
.venv/bin/python scripts/make_synthetic_data.py --list     # show status, build nothing
.venv/bin/python scripts/make_synthetic_data.py --only currents,origin_field
```

or, from the repository root, `make synthetic` (a forced rebuild) and `make fixtures` (the old name, kept as an alias).

What it writes, in the order it writes it:

| Name | Output | What it is |
|---|---|---|
| `scene` | `data/fixtures/synthetic_scene.tif` | 512x512 calibrated sigma0 GeoTIFF, real oil texture composited into a synthetic sea. Already committed, so this only matters if you are changing it |
| `wind` | `data/fixtures/synthetic_wind.nc` | near-shore 10m wind with four speed zones, so all four wind gate verdicts are reachable from one fixture |
| `currents` | `data/fixtures/synthetic_currents.nc` | open-ocean surface currents and SST, with a real time axis rather than one snapshot repeated |
| `wind_offshore` | `data/fixtures/synthetic_wind_offshore.nc` | open-ocean 10m wind over the same domain, the ensemble's windage forcing |
| `origin_field` | `data/fixtures/synthetic_origin_field.nc` | a small cached backward ensemble, so the AIS and scoring tests do not each pay for a fresh OpenDrift run |

Everything is seeded from `config/pipeline.yaml`, so rebuilding reproduces the same output rather than drawing a new sample: on the pinned dependency set the regenerated files are byte identical. The synthetic AIS traffic is deliberately not written here: it is generated in memory on every run by `services/core/ais/synthetic.py`, positioned relative to the origin field it is about to be scored against, which is what keeps the vessels and the field from drifting out of agreement.

Apart from the staged sample scene, none of these outputs are committed. They are small, deterministic and fast to rebuild, so there is no reason to carry binary diffs in git history. The real oil texture PNGs under `data/fixtures/real_oil_texture/` stay committed, since they come from a real dataset rather than from a script.

### Processing the staged sample image

The smallest useful thing the system can be asked to do, and the fastest check that an install works. No database, no Docker, no frontend.

```bash
make sample
# or: cd backend && .venv/bin/python scripts/process_sample.py
```

That runs the real P2 path (render, tile, infer, stitch, polygonize) over `data/fixtures/synthetic_scene.tif`, prints each oil polygon with its mean class probability, pixel count, area and centroid, and writes `data/processed/sample_detections.geojson` in EPSG:4326.

Point it at your own scene with `--scene`:

```bash
.venv/bin/python scripts/process_sample.py --scene /path/to/your_scene.tif --scene-id MY-SCENE-001
```

Band 1 is read as VV and is expected to be calibrated sigma0 in linear power. A scene already in dB, or one still in raw DN, will be read as if it were linear power and will degrade the output silently rather than erroring. That trap is documented at the top of `services/detection/render.py`, which is the one place the conversion happens.

For the whole pipeline rather than just detection, `scripts/seed_demo.py` is the entry point. `process_sample.py` stops at detection on purpose, so that it stays fast enough to be a smoke test.

### Commands

Root level targets, each delegating into `backend/Makefile`.

| | |
|---|---|
| `make setup` | venv, model weights, synthetic data, demo bundle, frontend deps. Idempotent |
| `make venv` | build `backend/.venv` from `backend/requirements.txt` |
| `make synthetic` | regenerate every synthetic input |
| `make sample` | process the staged sample image through detection |
| `make seed-demo` | run the full pipeline, rebuild the demo bundle, the SAR basemap and the dossier |
| `make dev` | core service on :8000 and the frontend dev server on :5173, together. `python scripts/dev.py` does the same thing on any platform, and is the way to do it on Windows |
| `make run-core` | core service alone, http://localhost:8000 |
| `make run-detection` | detection service alone, http://localhost:8001 |
| `make up` / `make down` | start and stop Postgres, PostGIS and Timescale in Docker |
| `make test` | the test suite, building any missing synthetic data first |
| `make validate` | 50 incidents plus three ablations, into `data/processed/validation.md` |
| `make lint` | ruff over `services/core`, `services/detection` and `validation` |
| `make deck` | the four P-1 deck figures, from the precomputed demo bundle |

Copy `backend/.env.example` to `backend/.env` first. `POSTGRES_HOST` points at `localhost`, since the database is the only thing in Docker. Every credential in that file is optional for the offline path: `KAGGLE_API_TOKEN` is only needed to re-pull the real oil slick texture patch, and the chosen patch is already committed.

### Running the demo

From the repository root:

```bash
make setup   # skips whatever is already there
make dev     # core service (:8000) and the frontend dev server (:5173) together
```

Run `make seed-demo` directly to force a fresh regenerate of the demo bundle, the SAR basemap and the dossier after changing a fixture or a config file. It also copies all three into `frontend/public/data/`, the static fallback the frontend uses when the core service is not running, so the demo works with the network cable unplugged and no backend process at all.

For the case where the laptop cannot be trusted to keep two dev servers alive, `cd frontend && npm run build && npx vite preview` serves the production build with no backend at all. That is what the "DEMO MODE: OFFLINE" badge in the header refers to. Exercise this path once before the day, since it is the one with no moving parts. The one thing it cannot serve is the ledger view, which reads from the core service; that is stated on screen rather than failing silently.

Presenting order that matches how the pipeline actually runs: **Scene** (the SAR image, the detected slick, the wind gate that accepted it), **Origin** (the backward drift's probability field, scrubbing back from acquisition), then **Traffic** (every vessel, the dark period envelopes, the unmatched radar target, and the vessels eliminated far off scene). Open the elimination log when asked how a vessel was ruled out.

### When something goes wrong

| Symptom | Cause and fix |
|---|---|
| `FileNotFoundError: Segmentation model not found at data/models/...` | The weights were never downloaded. `make fetch-model`, or the PowerShell one-liner above. This is the only download the system needs |
| `scene not found: data/fixtures/synthetic_scene.tif` | The staged sample is missing from the clone. `python scripts/make_synthetic_data.py --only scene --force` rebuilds it byte for byte |
| `FileNotFoundError` on a `.nc` file during `seed-demo`, `test` or `validate` | The forcing fixtures were never generated. `make synthetic` |
| `ModuleNotFoundError: No module named 'services'` | Running a script from the wrong directory. `seed_demo.py`, `run_validation.py` and the `make_fixture_*.py` scripts expect `backend/` as the working directory with it on `PYTHONPATH`. `make_synthetic_data.py` and `process_sample.py` handle this themselves and can be run from anywhere |
| Vite exits with an engine or syntax error on startup | Node is too old. Vite 8 needs 20.19+ or 22.12+. `node --version` |
| `pip install` tries to compile something from source | Almost always a Python that is not 3.11. Check `.venv/bin/python --version` and rebuild the venv with 3.11 if it is not |
| The console loads but the ledger view is empty | Postgres is not up (`make up`), or the core service is not running. Every other view reads from the static bundle and works without either |
| The console shows the SAR scene but no detections or tracks | `frontend/public/data/` is stale or missing. `make seed-demo` rebuilds it and copies it across |
| `pip install` sits on `tensorflow-io-gcs-filesystem` for a long time on Windows | Expected. That package has no Windows wheel above 0.31.0, so pip is backtracking to one that does. It resolves on its own |
| `'make' is not recognized` on Windows | There is no `make` on Windows. Use `python scripts\\dev.py` to run the servers and the direct commands in [Commands](#commands) for everything else |
| `No Python environment at ...\\.venv\\Scripts\\python` from `dev.py` | The venv was never built, or was built somewhere other than `backend/.venv`. The error prints the exact command for your platform |

### Building the deck figures

```bash
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
