# Setup and running

How to install Pharos and run it on Linux, macOS and Windows, with no dataset download.

[← Back to the README](../README.md)

---

## What you need, and what you do not

**No dataset download is required.** One SAR scene is committed to the repository as the staged sample image, and every other input the pipeline consumes is generated locally by `backend/scripts/make_synthetic_data.py`. Nothing is blocked on a Copernicus account, an Earthdata login, a real AIS feed or a 40GB Zenodo archive. See [DATA.md](DATA.md) for exactly what is real and what is generated.

**One thing does download: the segmentation model's weights.** About 205MB from HuggingFace, no account and no API token. `make fetch-model` pulls them, `make setup` does it as part of the run, and they are cached to `backend/data/models/oil-spill-deeplab/model.keras` and loaded from disk afterwards. Every run after the first is fully offline, which is what makes the demo survive an unplugged network cable.

If the weights are missing, the pipeline fails with a `FileNotFoundError` naming the exact command to fix it rather than with a Keras error about file formats.

Only Postgres, PostGIS and TimescaleDB run in Docker, and only the ledger view needs them. `services/core`, `services/detection` and `validation` share one Python environment (`backend/requirements.txt`, `backend/.venv`) and run locally.

## Prerequisites

| | Version | Needed for |
|---|---|---|
| Python | 3.11 | everything backend. 3.12 and 3.13 are untested against this pinned dependency set, so 3.11 is the one to install |
| Node.js | 20.19+ or 22.12+ | the operator console. Vite 8 refuses to start below those |
| Docker | any recent | Postgres only, and only for the ledger view. Skip it and the rest still runs |
| Disk | about 2.5GB | 205MB model weights, roughly 1.5GB of Python wheels (TensorFlow dominates), the rest npm |

No GDAL, PROJ, NetCDF or Rust toolchain has to be installed separately, on any of the three platforms. Every one of the 186 packages in the resolved dependency tree is either pure Python or ships a prebuilt wheel for Linux x86_64 and arm64, macOS arm64 and Windows x86_64 on Python 3.11.

## Setup, per platform

The three steps are the same everywhere: build the Python environment, fetch the model weights, generate the synthetic data. `make setup` does all three plus the demo bundle and the frontend's `node_modules`, and skips whatever is already in place.

### Linux

```bash
sudo apt install -y python3.11 python3.11-venv git make
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs

git clone <this repo> pharos && cd pharos
make setup
```

On Fedora or RHEL, `sudo dnf install python3.11 git make nodejs`. On Arch, `sudo pacman -S python git make nodejs npm` (check `python --version` is 3.11).

### macOS

```bash
brew install python@3.11 node git
# make ships with the Xcode command line tools: xcode-select --install

git clone <this repo> pharos && cd pharos
make setup
```

Apple silicon is the exercised path. TensorFlow runs on CPU here, which is fine: the model is small and the demo bundle is precomputed once.

### Windows

The project runs natively on Windows. There is no capability that only works under Linux: every one of the 186 packages in the resolved dependency tree is either pure Python or ships a Windows wheel for Python 3.11, including the three that usually cause trouble (TensorFlow, rasterio, and OpenDrift's `roaring-landmask`, which is a Rust extension but publishes an abi3 wheel). No compiler, no GDAL install, no conda.

What Windows genuinely does not have is `make` and `bash`, so the Makefile targets have to be run as the commands they wrap. `scripts/dev.py` replaces `make dev` on every platform.

Install [Python 3.11](https://www.python.org/downloads/) (any 3.11.x, and tick "Add python.exe to PATH") and [Node.js 22 LTS](https://nodejs.org/), then paste this in one block:

```powershell
git clone <this repo> pharos
cd pharos\backend

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

#### Where Windows differs, precisely

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

**WSL2 is still worth considering**, not because native Windows is broken but because it gives you `make` and the bash tooling, so every command in this README works unchanged. `wsl --install -d Ubuntu`, then follow [Linux](#linux). Clone inside the WSL filesystem (`~/pharos`), not under `/mnt/c/`, or file IO will dominate every step.

## Generating the synthetic data

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

## Processing the staged sample image

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

## Commands

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

## Running the demo

From the repository root:

```bash
make setup   # skips whatever is already there
make dev     # core service (:8000) and the frontend dev server (:5173) together
```

Run `make seed-demo` directly to force a fresh regenerate of the demo bundle, the SAR basemap and the dossier after changing a fixture or a config file. It also copies all three into `frontend/public/data/`, the static fallback the frontend uses when the core service is not running, so the demo works with the network cable unplugged and no backend process at all.

For the case where the laptop cannot be trusted to keep two dev servers alive, `cd frontend && npm run build && npx vite preview` serves the production build with no backend at all. That is what the "DEMO MODE: OFFLINE" badge in the header refers to. Exercise this path once before the day, since it is the one with no moving parts. The one thing it cannot serve is the ledger view, which reads from the core service; that is stated on screen rather than failing silently.

Presenting order that matches how the pipeline actually runs: **Scene** (the SAR image, the detected slick, the wind gate that accepted it), **Origin** (the backward drift's probability field, scrubbing back from acquisition), then **Traffic** (every vessel, the dark period envelopes, the unmatched radar target, and the vessels eliminated far off scene). Open the elimination log when asked how a vessel was ruled out.

## When something goes wrong

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

## Building the deck figures

```bash
backend/.venv/bin/python deck/scripts/make_figures.py
```

Writes four figures to `deck/figures/` from the precomputed demo bundle. See `deck/README.md`.

