# PLAN.md

Build plan for **SLICKTRACE**, an oil spill attribution pipeline.
Target: Smart India Hackathon, NTRO Problem Statement 26143.
Read the whole file before writing any code.

---

## 0. Mission in one paragraph

An oil slick seen on satellite imagery is a crime scene with no timestamp and no suspect. The slick is not where it started. This system detects a slick on Sentinel-1 SAR, rejects look-alikes using wind physics, runs an **ensemble backward drift** to produce an origin **probability field over latitude, longitude and time** (never a single point), reconstructs AIS vessel traffic through that field, detects vessels whose AIS went dark over the origin window, scores every vessel with an explicit weighted evidence model, logs a reason for every vessel it eliminates, and exports a hashed evidence dossier.

**The one sentence the product exists to support:** we do not say where the spill started, we say the probability of every place and time it could have started, then ask which vessel's behaviour is best explained by that distribution.

---

## 1. Non-negotiables

Read these as hard constraints, not preferences.

1. **The hindcast output is a probability field, never a point.** Any code path that reduces the origin to a single lat/lon before scoring is a bug. A centroid may be displayed for orientation, but must never enter the scoring math.
2. **Every eliminated vessel gets a logged reason string.** The elimination log is a first-class output, not a debug artifact. The PS text explicitly asks for irrelevant traffic to be filtered out, so the filter has to be inspectable.
3. **Scoring is an explicit weighted evidence model with named factors, defined in a YAML config.** Do not train a classifier for attribution. There is no ground truth, and a black box cannot be defended to a jury or a court.
4. **AIS dark periods raise suspicion, they never drop a vessel.** A vessel that stops transmitting while inside the origin envelope is scored up. This is the inversion the whole idea rests on.
5. **The demo must run with the network cable unplugged.** Every external dataset is downloaded ahead of time into `backend/data/`, and there is an offline fixture path for every stage.
6. **Determinism.** Every stochastic component takes a seed from config. Two runs of the demo produce identical numbers.
7. **No em dashes in any user-facing string, README, report text, or UI copy.**

---

## 2. Explicit non-goals

Do not build these. If you find yourself building one, stop.

- Training or fine-tuning a segmentation model in the critical path. Detection uses a pretrained model (section 5). A fine-tune is an optional stretch task at the very end.
- A classifier or neural net for attribution.
- Live satellite tasking, live CMEMS API calls at runtime, or anything that needs credentials during the demo.
- Absolute slick age in hours. Ship a relative age band with stated reasoning. An absolute number is unsupportable and will be attacked.
- User authentication, multi-tenancy, role management, deployment tooling beyond Docker Compose.
- Mobile responsiveness beyond the frontend not breaking. This is an operator console on a desktop.

---

## 3. Repository layout

```
slicktrace/
  README.md
  PLAN.md
  Makefile                  # delegates to backend/Makefile
  backend/
    Makefile
    docker-compose.yml       # Postgres/PostGIS/Timescale only, see below
    requirements.txt          # one env for the whole backend
    .venv/                    # gitignored, `make venv` builds it
    pytest.ini
    .env.example
    config/
      scoring.yaml            # evidence factor weights, thresholds
      pipeline.yaml            # tiling, ensemble size, seeds, paths
      demo.yaml                # the hero scenario definition
    data/                     # gitignored except .gitkeep and fixtures/
      raw/                    # Sentinel-1 GRD, NetCDF forcing, AIS CSV
      interim/
      processed/
      fixtures/               # small committed samples for tests
      precomputed/            # demo artifacts, committed if small enough
    services/
      detection/              # TensorFlow
        app.py                # FastAPI
        render.py             # SAR to model-input rendering
        tiling.py
        infer.py
        polygonize.py
        eval.py
      core/                   # everything else
        app.py                # FastAPI, orchestration
        worker.py             # Celery
        gate/wind.py
        characterize/geometry.py
        characterize/age.py
        hindcast/ensemble.py
        hindcast/field.py
        ais/ingest.py
        ais/synthetic.py
        ais/tracks.py
        ais/darkgaps.py
        scoring/factors.py
        scoring/engine.py
        scoring/eliminate.py
        forecast/forward.py
        dossier/render.py
        validation/harness.py
        schemas.py            # pydantic models, the contracts in section 4
        db/models.py
        db/migrations/
    tests/
    scripts/
      fetch_data.sh
      seed_demo.py
      run_validation.py
  frontend/
    src/
    package.json
```

One Python environment for the whole backend (`backend/requirements.txt`, `backend/.venv`), covering both `services/core` and `services/detection`. Only Postgres/PostGIS/Timescale runs in Docker (`make up`); `services/core` and `services/detection` run locally against the shared venv (`make run-core`, `make run-detection`), against `localhost:5432` for the database.

---

## 4. Data contracts

Define these as pydantic models in `backend/services/core/schemas.py` **before writing any stage**. Every stage reads and writes these. Stages communicate through the database and object paths, never through in-memory coupling.

```python
class SceneMeta:
    scene_id: str              # e.g. S1A_IW_GRDH_...
    acquired_at: datetime      # UTC, from product metadata
    bbox: tuple[float,...]     # minlon, minlat, maxlon, maxlat
    crs: str
    source_path: str

class Detection:
    detection_id: str
    scene_id: str
    class_name: Literal["oil","look_alike","ship","wake","background"]
    geometry: dict             # GeoJSON Polygon, EPSG:4326
    mean_class_prob: float
    pixel_area: int

class SlickFeatures:
    detection_id: str
    area_km2: float
    perimeter_km: float
    complexity_ratio: float    # P / (2 * sqrt(pi * A)), 1.0 is a circle
    major_axis_deg: float      # 0-180, from minimum rotated rectangle
    elongation: float          # major / minor
    mean_backscatter_db: float
    contrast_db: float         # slick mean minus local sea mean
    age_band: Literal["fresh","intermediate","weathered"]
    age_reasoning: str         # human readable, goes in the dossier

class GateResult:
    detection_id: str
    wind_speed_ms: float
    verdict: Literal["accept","downgrade","suppress"]
    reason: str

class OriginField:
    field_id: str
    detection_id: str
    path: str                  # NetCDF, dims (time, lat, lon), normalised to sum 1
    t_min: datetime
    t_max: datetime
    n_members: int
    seed: int

class AISTrack:
    mmsi: str
    vessel_type: str
    points: list[AISPoint]     # ts, lat, lon, sog, cog, heading
    dark_gaps: list[DarkGap]

class DarkGap:
    start: datetime
    end: datetime
    duration_min: float
    entry_point: tuple[float,float]
    exit_point: tuple[float,float]
    envelope: dict             # GeoJSON Polygon, dead-reckoned reachable set

class SuspectScore:
    mmsi: str
    total: float
    factors: dict[str, float]  # factor name -> contribution, must sum to total
    rank: int
    narrative: str             # one paragraph, generated from factors

class Elimination:
    mmsi: str
    reason: str                # required, never empty
    rule: str                  # machine readable rule id
```

**Contract rule:** `SuspectScore.factors` must sum to `SuspectScore.total` within 1e-6. Write a test for this. It is what makes the score auditable.

---

## 4A. Data acquisition: what is automatic and what a human must do first

Two categories. **Blocking human actions** must be done by a person before any script works, because they involve account creation and approval latency. **Scripted** means `backend/scripts/fetch_data.sh` can pull it unattended once credentials exist.

### Blocking human actions, do these before writing code

1. **Register a NASA Earthdata account** at `urs.earthdata.nasa.gov`, then authorise ASF access. Free, immediate. This unlocks Sentinel-1.
2. **Register a Copernicus Marine account** at `marine.copernicus.eu`. Free. This unlocks ocean currents.
3. **Register a Copernicus Climate Data Store account**, accept the ERA5 licence terms on the dataset page, and save the API key to `~/.cdsapirc`. The licence acceptance is a separate click from registration and is a common silent failure. **ERA5 requests queue and can take hours**, so submit the demo region request on day one, not on build day.
4. **Obtain the oil spill segmentation dataset.** The 5-class dataset matching the model taxonomy is distributed by request or through a mirror, so it cannot be scripted blind. Get the actual download link in hand before starting P2, because P3 (the honest IoU number) is blocked on it.
5. **Pick the hero incident** and record its date, bounding box and a source reference in `backend/config/demo.yaml`. Everything downstream keys off this.

### Scripted, once credentials exist

| Data | Source | Auth | Tool | Size | Notes |
|---|---|---|---|---|---|
| Segmentation model | HuggingFace `sahilvishwa2108/oil-spill-deeplab` | none | `huggingface_hub.hf_hub_download` | ~205 MB | Cache to `backend/data/models/`, load from disk so the demo is offline |
| Sentinel-1 GRD | ASF DAAC | Earthdata login | `asf_search` | ~1 GB per scene | Preferred route, see below |
| Ocean currents | CMEMS Global Ocean Physics | Copernicus Marine login | `copernicusmarine subset` | tens of MB subsetted | Subset by bbox and time, no volume quota |
| Wind | ERA5 single levels, 10 m U and V | CDS API key | `cdsapi` | small when subsetted | Queue delay, request early |
| AIS reference statistics | MarineCadastre daily zips | none | plain HTTP | ~100 MB per day file | Used only to fit lane, speed, type and dropout distributions |
| Coastline and land mask | Natural Earth or GSHHG | none | plain HTTP | small | For the land mask and tile skipping |

### Sentinel-1 route, read this before choosing

Use **ASF, not CDSE**, for the hero scene. ASF distributes all Sentinel-1 products through the ASF DAAC, searchable and downloadable programmatically with `asf_search`, and serves the full archive without a staging step.

The CDSE catch: original Sentinel-1 GRD products older than one year are served with deferred availability, while the COG_SAFE archive is available immediately. Your hero incident will almost certainly be older than a year, so on CDSE you would either wait for a deferred order to be staged or work from the COG form. Neither is a good thing to discover the night before. Keep CDSE as a fallback only.

Minimal working shape:

```python
import asf_search as asf
session = asf.ASFSession().auth_with_creds(user, password)
results = asf.search(
    platform=asf.PLATFORM.SENTINEL1,
    processingLevel=[asf.PRODUCT_TYPE.GRD_HD],
    intersectsWith=wkt_aoi,
    start=t0, end=t1,
)
results.download(path="data/raw/s1", session=session)
```

### Forcing data, with no-auth fallbacks

The plan's primary sources need accounts. Both have credential-free alternatives, and it is worth wiring the fallback as a config switch so a credential problem on the day cannot stop the build.

- **Currents.** Primary: `copernicusmarine subset` with bbox, time range and the surface velocity variables. The toolbox subsets remotely to NetCDF or Zarr without a volume quota, and reads credentials from `COPERNICUSMARINE_SERVICE_USERNAME` and `COPERNICUSMARINE_SERVICE_PASSWORD` or a credentials file, so it works unattended in Docker. Fallback: HYCOM over OPeNDAP, opened directly with `xarray.open_dataset`, no account at all, coarser but adequate for a demo.
- **Wind.** Primary: ERA5 via `cdsapi`, subset to the bbox and window. Fallback: NOAA GFS analysis from the public S3 bucket, no auth, but verify the archive covers your incident date before relying on it. Whichever you use, the source name and version string goes into the provenance chip and the dossier, so record it in the fetch script output rather than hardcoding it in the UI.

### AIS, be precise about what is real

MarineCadastre files are US waters. You are demonstrating over Indian waters, so they are **not** the demo data. They are the statistical source: lane geometry, vessel type mix, speed distributions, ping intervals and dropout rates are fitted from real files and then used to generate the demo traffic, with only the incident injected. The database schema mirrors the MarineCadastre columns so a real ICG or satellite AIS feed drops in with no code change.

`backend/scripts/fetch_data.sh` must write a `backend/data/raw/MANIFEST.json` recording, for every file, the source URL or dataset id, the retrieval timestamp, the byte size and the SHA-256. The dossier provenance page reads from this manifest, so the fetch step is part of the evidence chain, not a setup chore.

### Fetch script requirements

- Idempotent. Re-running skips files already present with a matching hash.
- Resumable. Sentinel-1 scenes are large and hackathon wifi is not.
- `--offline` flag that verifies the manifest and exits without touching the network, used as the pre-demo check.
- Credentials only from environment variables listed in `.env.example`, never hardcoded, never committed.

---

## 5. Stage 1 and 2: detection

### Model

Use `sahilvishwa2108/oil-spill-deeplab` from HuggingFace. MIT licensed. DeepLabV3+, Keras/TensorFlow.

- Input: `(256, 256, 3)`, RGB, values scaled to 0-1.
- Output: `(256, 256, 5)`, classes in order **Background, Oil Spill, Ships, Look-alike, Wakes**.
- Load with `keras.saving.load_model("hf://sahilvishwa2108/oil-spill-deeplab")`, or download the weights file once into `backend/data/models/` and load from disk so the demo works offline. **Do the offline version.**
- Verify the on-disk file extension on the Files tab before writing the loader. The model card says `.keras`, a sibling repo of the same author ships `.h5`. Handle whichever is actually there.

### The rendering trap, handle this first

The model expects images rendered the way its training dataset rendered them, which is an 8-bit visual product, not calibrated SAR. Feeding raw DN values or unclipped dB will degrade output silently rather than erroring.

`render.py` must:
1. Read the Sentinel-1 GRD VV band.
2. Convert to dB: `10 * log10(DN**2 / calibration)` or `10 * log10(sigma0)` if already calibrated.
3. Clip to a fixed dB window, start with `[-35, 0]`, expose it in `pipeline.yaml`.
4. Linear stretch the clipped range to 0-255, uint8.
5. Replicate to 3 identical channels.

**Validation gate before proceeding:** run the model on a handful of images from the original public oil spill segmentation dataset and confirm the masks are sensible. Only then run it on your own rendered Sentinel-1 scene. If your own scene produces garbage after this check passes, the rendering parameters are wrong, not the model. Tune the dB window, do not swap the model.

### Tiling

- Tile the scene into 256x256 with 48 px overlap.
- Predict per tile, keep the full 5-channel softmax.
- Stitch by **averaging softmax over overlaps**, then argmax at the end. Do not argmax per tile and stitch masks, that produces visible grid seams straight through slicks.
- Skip tiles that are more than 90 percent land or nodata, using a coastline mask, for speed.

### Georeferencing

Carry the `rasterio` affine transform per tile. After stitching, vectorise the oil class with `rasterio.features.shapes`, reproject to EPSG:4326, simplify lightly, drop polygons below a minimum area from config. Emit `Detection` records.

### Evaluation, do not skip

`eval.py` computes **per-class IoU and per-class F1** on a held-out split, and prints a table.

The model card reports 0.9668 F1, self-reported, with no split stated and no per-class breakdown. On this class taxonomy the background class dominates pixel counts, so a near-0.97 overall figure tells you almost nothing about oil-class performance, where published work on comparable data sits far lower. **Never surface 0.9668 in the UI, the README, the dossier, or any slide.** Surface the numbers `eval.py` produces, with the class name attached, even if oil-class IoU is 0.6.

---

## 6. Stage 3: wind physics gate

This is a USP component. It is model-agnostic post-processing, which is a stronger claim than a better backbone, because it improves any detector.

Oil damps capillary waves, which is why it appears dark on SAR. That mechanism has a valid wind window:

- Below roughly 2-3 m/s there are not enough capillary waves for oil to damp, so the whole sea surface is dark and dark patches are meaningless.
- Above roughly 10-12 m/s wind mixes the slick into the water column and the contrast disappears, so a dark patch is unlikely to be oil.

`gate/wind.py`:
1. Load the 10 m wind field for the scene acquisition time from cached ERA5 or GFS NetCDF via `xarray`.
2. Interpolate U and V to each detection polygon centroid, compute speed.
3. Apply thresholds from `pipeline.yaml`:
   - speed < `wind_min_ms` -> `suppress`, reason names the low-wind ambiguity
   - speed > `wind_max_ms` -> `suppress`, reason names slick breakup
   - within `[wind_min_ms, wind_min_ms + margin]` -> `downgrade`, confidence multiplier applied
   - otherwise -> `accept`
4. Emit a `GateResult` per detection. **Never delete the suppressed detections**, mark them. The UI shows them greyed with the reason on hover, which is what makes the gate visible to a jury instead of invisible.

**Measure this.** Assemble a small set of scenes containing known look-alikes and known slicks, and report false positives before the gate versus after. That number goes on the slide, not the model card's number.

---

## 7. Stage 4: characterisation

`characterize/geometry.py` computes the `SlickFeatures` fields. All straightforward shapely and numpy, no cleverness needed.

`characterize/age.py` produces a **relative age band only**, from a small explicit rule set combining contrast in dB and complexity ratio. Fresh slicks are high contrast and compact, weathered slicks are lower contrast and fragmented with high complexity ratio. Every band comes with an `age_reasoning` string that states the rule that fired.

Put this line in the README and the dossier verbatim: absolute slick age in hours cannot be estimated reliably from a single SAR acquisition, so this system reports a relative band and states its reasoning.

---

## 8. Stage 5: backward drift ensemble, the core artifact

`hindcast/ensemble.py` uses **OpenDrift with the OpenOil backend**, run with a negative time step.

Ensemble construction, this is the contribution, not the drift model itself:

1. Seed particles uniformly inside the slick polygon, count from config.
2. Run `n_members` (default 30, reducible to 8 for the live demo) independent backward runs, each with perturbed forcing:
   - wind drift factor sampled around 0.03 (typical range 0.02 to 0.04)
   - current field perturbed with a spatially correlated noise term, magnitude from config
   - horizontal diffusivity sampled from config range
   - seed time jittered across the acquisition uncertainty
3. Every particle at every backward timestep contributes a sample `(lat, lon, t)`.

`hindcast/field.py` converts those samples into `P(lat, lon, t)`:

- Bin onto a regular grid, resolution and time step from config.
- Smooth with a Gaussian kernel, bandwidth from config.
- Normalise so the field sums to 1 over the whole space-time volume.
- Write to NetCDF with dims `(time, lat, lon)`, and record the seed in the attributes.

**Do not** collapse over time. The time axis is what makes the AIS scoring work. A vessel is suspicious for being in the right place *at the right time*, and the field carries both jointly.

Backward horizon default 48 hours, configurable. Note openly in the docs that uncertainty grows with horizon, and that a wide field producing a longer suspect list is an honest result and not a failure.

---

## 9. Stage 6: AIS reconstruction

### Storage

PostgreSQL with PostGIS and TimescaleDB. Hypertable on the ping timestamp, GiST index on position. Schema mirrors the MarineCadastre AIS CSV columns so real feeds drop in without a code change. This matters for the Q&A answer about synthetic data, so keep the schema faithful.

### Synthetic generator

`ais/synthetic.py`. The demo uses synthetic AIS, so it has to be defensibly synthetic:

- Lane geometry taken from **real** shipping lane coordinates for the demo region.
- Vessel type mix and speed distributions sampled from **real** MarineCadastre statistics.
- Ping intervals and natural dropout rates sampled from real distributions, not a fixed cadence.
- Then inject exactly one culprit: a vessel whose track crosses the high-probability region of the origin field, slows to a steady low speed, stops transmitting for a configurable dark period, and resumes on a different course.
- Also inject at least three **hard negatives**: a vessel that passes through the field at the wrong time, a vessel with a dark gap far from the field, and a vessel spatially close throughout but at constant transit speed with no dark gap. If the scoring engine cannot separate the culprit from these three, the engine is wrong.

Everything is seeded and reproducible from `backend/config/demo.yaml`.

### Track reconstruction

`ais/tracks.py`: group by MMSI, sort by time, interpolate positions between pings using great circle interpolation with SOG and COG, produce a continuous position function per vessel over the origin window.

### Dark gap detection

`ais/darkgaps.py`, a USP component:

1. Find inter-ping intervals longer than `dark_gap_min_minutes` (default 20, configurable, tuned against the observed dropout distribution so ordinary dropouts do not fire).
2. For each gap, build the **dead reckoned reachable envelope**: from the last known position, course and speed, propagate a cone that widens with time, bounded by the vessel's plausible maximum speed, and close it against the first position after the gap. Represent it as a polygon.
3. Emit `DarkGap` records. Do not exclude these vessels from anything. They feed a scoring factor.

---

## 10. Stage 7: evidence scoring, the USP

`scoring/factors.py` computes named factors, `scoring/engine.py` combines them, `scoring/eliminate.py` produces the elimination log. All weights and thresholds live in `backend/config/scoring.yaml` and are displayed in the UI and printed in the dossier.

### Factors

**F1, field integral.** The primary factor. For vessel `v`, integrate the origin probability along its reconstructed track:

```
F_field(v) = sum over timesteps t of P(lat_v(t), lon_v(t), t) * dt
```

Normalise across all candidate vessels to 0-1. This is what makes a vessel that lingered inside a broad uncertain cloud outrank a vessel that clipped a narrow peak, which distance-to-centroid ranking gets exactly backwards.

**F2, dark overlap.** The fraction of the origin window during which the vessel was dark **and** its dead-reckoned envelope overlapped non-zero probability mass, weighted by the mass it overlapped. This is the factor that inverts the baseline's blind spot.

**F3, axis alignment.** A discharge streak is elongated along the vessel's track. Compare `SlickFeatures.major_axis_deg` against the vessel's course over ground at the times it was inside the field. Score the angular agreement, modulo 180 degrees. This is strong, cheap, physically motivated evidence and almost nobody else will implement it.

**F4, speed anomaly.** Operational discharge is typically done at a slow steady speed rather than at transit speed. Score a sustained deviation below the vessel's own median transit speed while inside the field.

**F5, course anomaly.** Deviation from the lane baseline, or a significant course change immediately after the origin window.

**F6, vessel plausibility.** A small prior by vessel type and size. Keep the weight low and the reasoning explicit. This factor **downweights**, it never eliminates, and that must be stated in the config comments and the docs, because attributing pollution by vessel class alone is exactly the kind of shortcut a jury should attack.

### Combination

Weighted sum in log-odds space, weights from config, output normalised for display. Store every factor's contribution in `SuspectScore.factors`. Generate `narrative` by templating the top three contributing factors into plain sentences. The narrative is what the operator reads, so write it in plain language, active voice, no jargon.

### Elimination rules

Applied before scoring, each with a `rule` id and a human readable `reason`:

- `NO_TEMPORAL_OVERLAP`: the vessel had no position anywhere in the field's time range.
- `NO_SPATIAL_SUPPORT`: the track never entered a cell with probability above `eps`, and no dark envelope overlapped one either.
- `INSUFFICIENT_TRACK`: fewer than N pings in the window, so the reconstruction is unreliable. Say so, do not silently drop.

Nothing else eliminates. Everything else downweights. Write the elimination reasons as sentences an investigator would accept, not as error codes.

---

## 11. Stage 8: forward forecast and dossier

`forecast/forward.py`: same OpenDrift setup, positive time step, seeded from the current slick, horizon from config. Output a time-stepped GeoJSON for the response-planning view. This is a second deliverable for free and takes almost no extra code, so do it, but it is the first thing to cut if time runs out.

`dossier/render.py`: ReportLab PDF, one case per file. Contents:

- Cover: case id, generation timestamp UTC, and the statement that the output is ranked evidence for a human investigator and is not an automated accusation.
- Scene: id, acquisition time, sensor, footprint map.
- Detection: mask overlay image, per-class IoU of the model as measured by `eval.py`, gate verdict and reason.
- Slick: geometry table, age band with its reasoning.
- Origin: probability field snapshots at three time slices, ensemble size, seed, forcing data source and version.
- Suspects: ranked table, then one page per top-3 vessel with the factor breakdown as a bar chart and the narrative.
- Eliminations: full table of MMSI and reason.
- Provenance: SHA-256 of every input artifact, the model identifier and version, the scoring config contents verbatim, and the git commit hash.

The provenance page is the point. It is what makes this a case file rather than a dashboard.

---

## 12. Stage 9: frontend

React, Vite, TypeScript, MapLibre GL with deck.gl overlays. deck.gl because the origin field is tens of thousands of cells and the AIS layer is thousands of track segments, and a naive Leaflet implementation will stutter during the demo.

### Design direction

Not a generic dark dashboard with an acid accent. The subject has its own visual world, the **nautical chart**, so take the direction from there: chart-paper linework, condensed annotation type, monospaced coordinates, graticule rules that carry real graticule values.

Tokens, use exactly these:

```
--ink:        #0A1E29   /* deep chart water, page background */
--panel:      #102C3A   /* raised surfaces */
--graticule:  #2E5567   /* rules, grid, borders */
--paper:      #E9E3D2   /* primary text, chart paper cream */
--muted:      #90A5AF   /* secondary text */
--oil:        #F2A03D   /* the slick, and only the slick */
--suspect:    #D6455E   /* rank 1 vessel, and only that */
--cleared:    #4E7C6B   /* eliminated vessels */
```

Type: **IBM Plex Sans Condensed** for headings and map annotation, which is how real charts label features. **Inter** for body. **IBM Plex Mono** for all coordinates, timestamps, MMSI numbers and factor values, so numeric columns align. Never set a coordinate or an MMSI in a proportional face.

Probability field ramp: single-hue, transparent at zero mass through to `--oil` at peak. Do not use a rainbow ramp, it makes uncertainty look like structure.

### Signature element

**One time scrubber drives everything.** Dragging it simultaneously moves the origin probability field through its time axis, advances every AIS track to that instant, and updates the suspect ranking live. Scrub backwards from the acquisition and watch the cloud expand while the suspect list shrinks to three. That single interaction is the spine of the product. Build it first and build it well, and keep every other interaction quiet.

Section 12A below specifies the motion and fluid dynamics layer that sits on top of it. Read it as part of this section, not as an optional extra.

### Views

1. **Scene view.** SAR basemap, detection polygons, suppressed detections greyed with the gate reason on hover.
2. **Origin view.** Probability field with the time scrubber, ensemble member spaghetti toggleable underneath.
3. **Traffic view.** AIS tracks, dark gaps drawn as dashed segments with their reachable envelope as a translucent polygon. Make the dashed gap visually distinct at a glance, this is the thing you point at on stage.
4. **Suspects panel.** Ranked list, each row expanding to the factor bar chart and the narrative.
5. **Elimination log.** A plain scrollable table of MMSI and reason. Deliberately unglamorous. Its job is to look like a record, not a visualisation.
6. **Dossier button.** Downloads the PDF.

Copy rules: active voice, sentence case, buttons name what happens. Empty and error states say what happened and what to do, and never apologise. No em dashes.

---

## 12A. Visualization, fluid dynamics and motion

This section exists because the pitch is judged in a room, on a projector, in a few minutes. A correct pipeline that renders as static polygons loses to a weaker pipeline that shows the ocean moving. Treat this as engineering work with acceptance criteria, not decoration.

### The one rule that governs everything here

**Every moving thing on screen must be real data.** The particles are the actual OpenDrift ensemble particles. The flow field is the actual CMEMS current and ERA5 wind vectors. The cloud is the actual normalised probability field. Nothing is a decorative noise function dressed up as physics.

Why this matters practically: a jury member will ask "is that a real simulation or an animation?" The answer has to be "those are the 30 ensemble members, here is the seed, here is the NetCDF." If any of it is fake, one honest answer destroys the whole pitch, and if you lie about it you deserve to lose. Add an on-screen data provenance chip next to every animated layer, showing the source (`CMEMS GLOBAL_ANALYSISFORECAST_PHY`, `ERA5 10m`, `ensemble n=30, seed=...`). That chip converts eye candy into evidence.

### Libraries

- `deck.gl` for all GPU layers, on top of MapLibre GL.
- `luma.gl` shader access for the flow field layer, reached through a deck.gl custom layer.
- `@deck.gl/layers` TripsLayer for animated vessel tracks, PathLayer for static, ScatterplotLayer for particles, ColumnLayer or a custom layer for the space-time view.
- `d3-scale` and `d3-interpolate` for colour ramps and eased timelines. No charting library on the map.
- `framer-motion` for panel and list transitions only, never for map content.
- No Three.js. deck.gl already gives you the 3D camera and it composites with the map correctly.

### Layer 1: ambient flow field, the fluid dynamics look

This is the classic GPU particle advection technique, driven by your real forcing data rather than a synthetic noise field.

1. At load, encode the current field (U, V) for the active timestep into an RGBA float texture, U in red, V in green, with the min and max ranges passed as uniforms.
2. Hold particle positions in a second texture. Each frame, a fragment shader reads each particle position, samples the flow texture bilinearly, advects the particle by `velocity * dt * speed_scale`, and writes the new position.
3. Draw particles into an accumulation framebuffer that is faded rather than cleared each frame, which produces streaking trails. Trail persistence is the single knob that makes this read as fluid rather than as confetti, so expose it in the UI dev panel and tune it visually.
4. Respawn a small random fraction of particles each frame to prevent them all pooling in convergence zones.
5. The flow texture swaps when the time scrubber crosses into a new forcing timestep, so the ambient flow genuinely changes with time.

Tuning for a projector, not for your laptop:

- Particle count 60k to 120k. Measure the frame time, do not guess.
- Trails in `--graticule` at low alpha, near invisible individually. The field should read as texture, not as a foreground element. If a viewer notices the flow field before they notice the slick, turn it down.
- Speed scale slow. Real currents are around 0.1 to 1 m/s and a literal mapping looks static, so exaggerate deliberately and put the true speed scale factor in the provenance chip. Do not silently exaggerate.

Acceptance test: with the slick and all overlays hidden, the map alone should show recognisable eddies and coastal shear that match the source NetCDF when you plot it in matplotlib. If the visual structure does not match the raw data plot, the shader has a bug, most likely a texture flip or a normalisation error.

### Layer 2: the rewind, this is the demo

A single play button on the origin view runs a choreographed sequence backwards from the acquisition time. Implement it as an explicit timeline in one module, `frontend/src/sequence/rewind.ts`, with named beats and eased transitions, not as a pile of independent animations.

Beats, roughly 45 seconds total, every duration in a config object so you can retime it during rehearsal:

| Beat | Duration | What happens |
|---|---|---|
| 0. Hold | 3 s | SAR scene, slick polygon in `--oil`, ambient flow running underneath. Title chip: scene id and acquisition time. |
| 1. Dissolve | 3 s | The slick polygon dissolves into its seeded particles. Polygon opacity to 0, particle opacity to 1, same footprint, so the eye reads it as the same object. |
| 2. Rewind | 12 s | Time runs backwards. Particles advect backwards along the real ensemble tracks, spreading and separating as members diverge. Clock in the corner counts backwards in UTC. Ensemble spaghetti fades in faintly behind the particles. |
| 3. Bloom | 4 s | Particles fade, the probability field blooms in their place as a smooth density. This is the visual statement that the answer is a distribution, so let it breathe. Caption appears: not a point, a probability over space and time. |
| 4. Traffic | 6 s | Every AIS track in the window draws itself on with a TripsLayer trail, all in `--muted`. The screen deliberately becomes cluttered. Counter reads the vessel count. |
| 5. Elimination | 8 s | Vessels grey to `--cleared` and drop out in waves, grouped by elimination rule, with the rule name appearing as each wave clears and the counter ticking down. This beat is the PS requirement made visible, so give it real time. |
| 6. Dark gap | 5 s | Survivors thin to three. The rank-1 vessel's dark period renders as a dashed segment with its dead-reckoned envelope expanding as a translucent cone, drawn directly over the probability cloud. |
| 7. Verdict | 4 s | Camera eases to the overlap region. Suspect panel slides in with the factor breakdown bars animating from zero. Dossier button pulses once. |

Rules for the sequence:

- It must be **scrubbable and interruptible**. Any click pauses it and hands control back. A sequence that traps the presenter is worse than no sequence, because Q&A always interrupts.
- Every beat is also reachable directly from the normal UI. The sequence is a guided path through the real product, never a separate mode with its own fake state.
- Captions are set in IBM Plex Sans Condensed, lower left, one line each, sentence case, and they state facts rather than sell.
- Build a keyboard shortcut to jump to any beat by number. During Q&A you will want beat 5 or 6 instantly.

### Layer 3: the space-time prism

The distinctive view, and the one that makes the joint space-time argument legible in a single frame. Use deck.gl in 3D with the vertical axis as **time**, not elevation.

- Ground plane at the origin window's earliest time, camera pitched around 50 degrees.
- Each vessel track becomes a 3D polyline rising through the cube as time advances, using PathLayer with z from timestamp.
- The origin probability field renders as stacked translucent slices, one per time bin, forming a lens-shaped volume where the high-mass region is.
- The culprit's track visibly passes **through** the volume. The innocents pass beside it or above it. Colour by `--suspect` and `--muted`.
- Dark gaps render as gaps in the polyline with the reachable envelope as a widening translucent cone rising through the cube.

One frame of this explains the entire idea without narration, which is exactly what a slide needs. Build it after the rewind sequence works. It is cuttable, the rewind is not.

Guard rails: label the vertical axis in UTC, clearly, at least three ticks. An unlabelled 3D view reads as a gimmick. Provide a one-key toggle back to 2D, because 3D is a liability during a detailed question.

### Layer 4: motion in the panels

- Suspect factor bars animate from zero on expand, 400 ms, ease-out. This is worth it because the eye reads the relative contributions from the growth.
- Elimination log rows enter with a short fade only. It should look like a record filling up, not a feed.
- Numbers count up rather than snapping, but only over 300 ms and only for the headline counters. Longer and it reads as padding.
- Nothing loops idly. Ambient loops on a dashboard read as screensaver.

### Performance and projector reality

- Target 60 fps at 1920x1080. Measure with the deck.gl stats overlay and keep a dev flag to display frame time.
- Test on the actual presenting laptop, on battery, with an external display attached. GPU behaviour changes on all three axes and discovering that on stage is fatal.
- Projectors crush contrast and thin lines. Set map line widths at least 2 px, treat anything below 30 percent alpha as invisible, and check the palette on a real projector before the event. Prefer raising line weight over raising saturation.
- Precompute everything the sequence needs into a single JSON or binary bundle at `backend/data/precomputed/hero_sequence.json`, loaded once at startup. No network calls, no worker jobs, no database queries during the animation.
- Respect `prefers-reduced-motion` by disabling the ambient flow and shortening transitions, while keeping the rewind available on explicit click. Accessibility and the demo are not in conflict here.

### The fallback that you must build

Record a clean screen capture of the full rewind sequence and the space-time view as an MP4, and commit it to the repo. Keep it on the presenting laptop and in the slide deck. Live demos fail at SIH for reasons that have nothing to do with your code, and a team that switches to a recording in four seconds looks prepared while a team debugging on stage loses the room. Build this the night before, not on the morning of.

### Acceptance criteria for this section

1. Ambient flow visually matches a matplotlib quiver plot of the same NetCDF timestep.
2. The rewind sequence runs start to finish at 60 fps with no network access.
3. The sequence can be paused, scrubbed and resumed at any point, and every beat is reachable by keyboard.
4. Particle positions during the rewind are the actual ensemble particle positions, verified by comparing a sampled frame against the OpenDrift output arrays in a test.
5. Every animated layer carries a provenance chip naming its data source.
6. The MP4 fallback exists and plays.

---

## 13. Stage 10: validation harness

`validation/harness.py`. There is no ground truth for attribution, so build your own:

1. Generate 50 synthetic incidents from `backend/config/demo.yaml` with varied lane density, dark gap presence, backward horizon and wind conditions, each with a known culprit MMSI.
2. Run the full pipeline from stage 5 onward on each.
3. Report **rank-1 accuracy**, **rank-3 accuracy**, mean rank of the true culprit, and a breakdown by traffic density.
4. Run an ablation: rerun with `F2` (dark overlap) zeroed, and with `F1` replaced by distance to the field centroid. Report the accuracy drop for each.

Those two ablation numbers are the strongest slide in the deck, because they prove the two USP claims quantitatively rather than asserting them. Print the table to stdout and write it to `backend/data/processed/validation.md`.

State plainly in the output that this measures internal consistency of the scoring model, not real-world accuracy, and that validation against a documented prosecuted incident is the next step. Do not let the harness print a claim it cannot support.

---

## 14. Build order and priority

Critical path first. Each phase has an acceptance test that must pass before moving on.

| Phase | Deliverable | Acceptance test |
|---|---|---|
| P0 | Repo, Docker Compose (Postgres+PostGIS+Timescale only), backend venv building, Makefile targets | `make up` then `make test` passes on an empty test suite |
| P1 | Schemas in `schemas.py` | Contract test: factors sum to total, round trips through JSON |
| P2 | Detection service: render, tile, infer, stitch, polygonize | Given a GeoTIFF, returns a GeoJSON FeatureCollection of oil polygons with correct geographic coordinates |
| P3 | `eval.py` per-class IoU table | Table printed with a real number attached to the oil class |
| P4 | Wind gate | Every detection carries a verdict and a reason. Measured FP reduction on the curated set |
| P5 | Characterisation | `SlickFeatures` populated, age band with reasoning |
| P6 | Backward ensemble and field | NetCDF written, sums to 1, has a real time dimension, seed recorded |
| P7 | AIS ingest, synthetic generator, track reconstruction, dark gaps | Culprit plus three hard negatives generated, dark gaps detected with envelopes |
| P8 | Scoring engine and elimination log | Culprit is rank 1 on the demo scenario, all three hard negatives are below it, every eliminated vessel has a reason |
| P9 | Frontend shell, map, layers, time scrubber first | Scrubbing updates field, tracks and ranking together at interactive frame rate |
| P9a | Ambient flow field shader (12A layer 1) | Visual structure matches a matplotlib quiver plot of the same NetCDF timestep |
| P9b | Rewind sequence (12A layer 2) | Runs all 7 beats at 60 fps offline, pausable and scrubbable, every beat keyboard reachable |
| P10 | Dossier PDF | Generates with a full provenance page |
| P11 | Validation harness, 50 incidents plus 2 ablations | Table written to `validation.md` |
| P12 | Space-time prism view (12A layer 3) | Culprit track visibly passes through the probability volume, time axis labelled in UTC |
| P13 | Forward forecast view | Time-stepped GeoJSON rendered |
| P14 | Demo hardening: precompute bundle, seed script, offline mode, MP4 fallback, rehearsal on the presenting laptop | Full demo runs with the network disabled, MP4 fallback plays |

**If time runs short, cut in this order:** P13, then the space-time prism (P12), then dossier styling (keep the content), then P3 breadth (evaluate on fewer images, keep the number honest), then ensemble size (30 members down to 8).

**Never cut:** the wind gate, dark gap detection, the elimination log, the ablation numbers, the rewind sequence, and the MP4 fallback. The first four are the differentiation and the last two are how the differentiation reaches the room. A prettier map without the first four is a losing pitch, and a correct pipeline that renders as static polygons is also a losing pitch.

---

## 15. Precomputation and demo safety

Before the demo, `backend/scripts/seed_demo.py` must produce and commit to `backend/data/precomputed/`:

- Two fully preprocessed Sentinel-1 scenes, already terrain corrected and rendered.
- Cached wind and current NetCDF subsets for the demo region and window.
- The full 30-member ensemble field for the hero scene.
- The generated synthetic AIS for the hero scenario.
- The generated dossier PDF.
- `hero_sequence.json`, the single bundle the rewind sequence loads: per-frame ensemble particle positions, probability field slices, AIS track vertices, elimination waves in order, and the beat timings. The animation must never query the database or a worker while it is playing.
- The MP4 screen capture of the full sequence.

The application must start in `DEMO_MODE=offline` and serve these without touching the network or running the heavy ensemble. A separate visible button runs a **reduced live** hindcast, 8 members and a shorter horizon, so you can prove it genuinely computes rather than replaying a video. Rehearse both paths.

---

## 16. Testing requirements

- Contract tests on every schema, including the factors-sum-to-total invariant.
- A golden-file test on the stitching logic, so a refactor cannot silently reintroduce grid seams.
- A test that the origin field normalises to 1 and retains its time dimension.
- A test that a vessel with a dark gap overlapping the field scores strictly higher than an identical vessel without one. This test guards the central claim of the project.
- A test that every eliminated vessel has a non-empty reason string.
- A test that the rewind sequence's particle frames match the OpenDrift output arrays for a sampled set of frames. This guards the rule that nothing on screen is decorative, which is the claim you make out loud during the demo.
- A test that `hero_sequence.json` is self-contained: loading it with the database stopped still renders every beat.
- End to end smoke test on the committed fixtures, run in CI and by `make test`.

---

## 17. Things a jury will attack, and what the code must be able to show

Build so that each of these can be answered by clicking something, not by talking:

- "This is just an off-the-shelf model plus OpenDrift." Show the gate's measured FP reduction, and the two ablation numbers. The contribution is stages 3, 6 and 7 and the numbers prove it.
- "Your attribution is unvalidated." Open `validation.md`, show rank-1 and rank-3 across 50 incidents, and state clearly that it measures internal consistency.
- "Your AIS is synthetic." Show the schema matching MarineCadastre columns exactly, and the config where lane geometry and dropout distributions come from real statistics with only the incident injected.
- "Dark vessel inference could accuse an innocent ship." Show the dossier cover statement, the factor breakdown, and the fact that vessel type never eliminates.
- "48 hour backward drift is too uncertain to be useful." Scrub the timeline and show the cloud widening. That is the design premise, the uncertainty is the scoring surface.

---

## 18. First three tasks

1. Scaffold P0 and P1. Do not write pipeline code before the schemas exist.
2. Download the model, confirm the actual file format on the HuggingFace Files tab, load it, and run it on samples from the original public dataset. Confirm sane masks. **This gate blocks everything downstream, do it before writing the tiling code.**
3. Write `eval.py` and produce the honest per-class IoU number. Everything after this is built on knowing what the detector actually does.

Report back after task 2 with the observed masks and after task 3 with the IoU table before proceeding to P4.
