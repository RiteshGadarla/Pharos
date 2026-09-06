# PLAN.md

Build plan for **DRISHTA**, a maritime event attribution engine.
Target: Smart India Hackathon 2026, NTRO Problem Statement 26143.
Read the whole file before writing any code.

This file supersedes the earlier SLICKTRACE plan. Section 0B lists what changed and why, so if you have prior context on SLICKTRACE, read 0B before anything else.

---

## 0. Mission in one paragraph

An oil slick seen on satellite imagery is a crime scene with no timestamp and no suspect. The slick is not where it started. This system detects a slick on Sentinel-1 SAR, rejects look-alikes using wind physics, runs an **ensemble backward drift** to produce an origin **probability field over latitude, longitude and time** (never a single point), reconstructs AIS vessel traffic through that field, detects vessels whose AIS went dark over the origin window, confirms those dark vessels against **unmatched ship targets in the same SAR scene**, scores every vessel with an explicit weighted evidence model, logs a reason for every vessel it eliminates, evaluates the reconstructed discharge against MARPOL Annex I conditions, and exports a hash sealed evidence dossier carrying a Bharatiya Sakshya Adhiniyam Section 63 certificate.

**The one sentence the product exists to support:** we do not say where the spill started, we say the probability of every place and time it could have started, then ask which vessel's behaviour is best explained by that distribution.

**The architectural claim underneath it:** the drift kernel is a plug in. Oil spill is instance one of a general problem shape, which is "given an observed effect at a known place and time, reconstruct the origin window and rank who was present in it, including vessels that were not broadcasting."

---

## 0A. Priority order, read this before planning your work

The deck is submitted before the prototype is judged. Therefore:

1. **P-1 (Deck Assets) comes before P0.** It produces four images with throwaway scripts and no infrastructure. It is one to two days of work and it unblocks the presentation. Do it first, do not skip it, and do not let it turn into the real pipeline.
2. Everything from P0 onward is the real build, in the order given in section 19.
3. If the schedule compresses, cut from the bottom of the priority list in section 19, never from the never cut list.

---

## 0B. What changed from the SLICKTRACE plan

If you have the old plan in context, these are the deltas. Everything not listed here carries over.

| # | Change | Why |
|---|---|---|
| 1 | Renamed to DRISHTA | Project rename |
| 2 | **New P-1 phase: deck assets first** | Presentation is submitted before the prototype is judged |
| 3 | **Drift kernel is pluggable**, `DriftKernel` protocol with OpenOil, Leeway and Null implementations | Makes the engine event agnostic, which is the differentiator with NTRO |
| 4 | **Three verdict classes**: ATTRIBUTED, RANKED, DARK_CONFIRMED | "No broadcasting suspect found" is a finding for an intelligence organisation, not a failure |
| 5 | **New stage: SAR ship target cross check** (section 11) and new factor **F8** | Converts dark vessel from an inference into an independent sensor observation. Highest value addition in this revision |
| 6 | **New factor F7, AIS integrity** | AIS is spoofable, not merely switchable. Pre empts the obvious objection |
| 7 | **New stage: EO corroboration** (section 7) | The PS says "SAR and EO imagery". SAR only was a literal gap against the PS wording |
| 8 | **New stage: MARPOL Annex I evaluation** (section 13) | Bridges detection to enforcement. Nobody else will do this |
| 9 | **New stage: offshore infrastructure overlap flag** (section 14) | Prevents blaming a ship for a platform leak. Mumbai High makes this real for Indian waters |
| 10 | **Dossier carries a BSA Section 63 Part A certificate** | Makes the output usable after it leaves the screen |
| 11 | **Primary evaluation corpus is the PS named Zenodo dataset** (Sigma0 in dB), with a five class set as secondary | The PS names it, and it is in the same radiometric space as our render chain, so it tests render and model together |
| 12 | **Cerulean added as an external validation oracle only** (section 17.2) | Third party agreement metric on detection, plus a source of unresolved Dark cases to attempt. Never in the runtime path |
| 13 | **Drift engine validated against real drifter trajectories** (section 17.3) | The one component where real ground truth actually exists |
| 14 | **Accumulating outputs: dark period ledger and AIS completeness record** (section 18) | The by product that outlives any single case |
| 15 | Synthetic AIS is explicitly authorised by the PS, quote recorded in config | Removes the largest perceived weakness. Rigour is still required, permission is not an excuse |

---

## 1. Non-negotiables

Read these as hard constraints, not preferences.

1. **The hindcast output is a probability field, never a point.** Any code path that reduces the origin to a single lat/lon before scoring is a bug. A centroid may be displayed for orientation, but must never enter the scoring math.
2. **Every eliminated vessel gets a logged reason string.** The elimination log is a first class output, not a debug artifact. The PS text explicitly asks for irrelevant traffic to be filtered out, so the filter has to be inspectable.
3. **Scoring is an explicit weighted evidence model with named factors, defined in a YAML config.** Do not train a classifier for attribution. There is no ground truth, and a black box cannot be defended to a jury or a court.
4. **AIS dark periods raise suspicion, they never drop a vessel.** A vessel that stops transmitting while inside the origin envelope is scored up. This is the inversion the whole idea rests on.
5. **Cerulean is never in the runtime path.** It appears only under `validation/`. Any import of the Cerulean client from `services/core` outside `validation/` is a bug. Write a test that asserts this.
6. **The demo must run with the network cable unplugged.** Every external dataset is downloaded ahead of time into `backend/data/`, and there is an offline fixture path for every stage.
7. **Determinism.** Every stochastic component takes a seed from config. Two runs of the demo produce identical numbers.
8. **Never surface an aggregate accuracy figure without the class name attached.** Specifically, never surface the HuggingFace model card's self reported 0.9668 anywhere: not the UI, not the README, not the dossier, not a slide.
9. **No em dashes in any user facing string, README, report text, or UI copy.**

---

## 2. Explicit non-goals

Do not build these. If you find yourself building one, stop.

- Training or fine tuning a segmentation model in the critical path. Detection uses a pretrained model (section 5). A fine tune is an optional stretch task at the very end.
- A classifier or neural net for attribution.
- Live satellite tasking, live CMEMS API calls at runtime, live Cerulean calls at runtime, or anything that needs credentials during the demo.
- Absolute slick age in hours. Ship a relative age band with stated reasoning.
- A legal verdict. The MARPOL layer (section 13) outputs a flag with its assumptions printed, never a determination of illegality.
- User authentication, multi tenancy, role management, deployment tooling beyond Docker Compose.
- Mobile responsiveness beyond the frontend not breaking. This is an operator console on a desktop.

---

## 3. Repository layout

```
drishta/
  README.md
  PLAN.md
  Makefile                      # delegates to backend/Makefile
  deck/                         # P-1 output, throwaway scripts and images
    scripts/
    figures/
  backend/
    Makefile
    docker-compose.yml          # Postgres/PostGIS/Timescale only
    requirements.txt            # one env for the whole backend
    .venv/                      # gitignored, `make venv` builds it
    pytest.ini
    .env.example
    config/
      scoring.yaml              # evidence factor weights, thresholds, verdict rules
      pipeline.yaml             # tiling, ensemble size, seeds, paths, kernel choice
      demo.yaml                 # the hero scenario definition
      marpol.yaml               # Annex I thresholds and assumptions
    data/                       # gitignored except .gitkeep and fixtures/
      raw/
      interim/
      processed/
      fixtures/                 # small committed samples for tests
      precomputed/              # demo artifacts
      models/
      cerulean/                 # cached validation pulls, offline after first fetch
    services/
      detection/                # TensorFlow
        app.py                  # FastAPI
        render.py               # SAR to model input rendering
        tiling.py
        infer.py
        polygonize.py
        ships.py                # ship class extraction, feeds section 11
        eval.py
      core/
        app.py                  # FastAPI, orchestration
        worker.py               # Celery
        gate/wind.py
        corroborate/optical.py
        characterize/geometry.py
        characterize/age.py
        drift/kernel.py         # DriftKernel protocol
        drift/openoil.py
        drift/leeway.py
        drift/null.py
        hindcast/ensemble.py
        hindcast/field.py
        ais/ingest.py
        ais/synthetic.py
        ais/tracks.py
        ais/darkgaps.py
        ais/integrity.py        # F7
        crosscheck/radar.py     # F8, section 11
        crosscheck/infrastructure.py
        scoring/factors.py
        scoring/engine.py
        scoring/eliminate.py
        scoring/verdict.py
        legal/marpol.py
        forecast/forward.py
        dossier/render.py
        dossier/bsa63.py
        ledger/dark.py          # section 18
        ledger/completeness.py  # section 18
        schemas.py              # pydantic models, the contracts in section 4
        db/models.py
        db/migrations/
    validation/                 # never imported by services/core
      harness.py
      cerulean_client.py
      cerulean_agreement.py
      drifter.py
    tests/
    scripts/
      fetch_data.sh
      seed_demo.py
      run_validation.py
  frontend/
    src/
    package.json
```

One Python environment for the whole backend (`backend/requirements.txt`, `backend/.venv`), covering `services/core`, `services/detection` and `validation`. Only Postgres/PostGIS/Timescale runs in Docker (`make up`); the services run locally against the shared venv (`make run-core`, `make run-detection`) against `localhost:5432`.

---

## 4. Data contracts

Define these as pydantic models in `backend/services/core/schemas.py` **before writing any stage**. Every stage reads and writes these. Stages communicate through the database and object paths, never through in memory coupling.

```python
class SceneMeta:
    scene_id: str              # e.g. S1A_IW_GRDH_...
    acquired_at: datetime      # UTC, from product metadata
    bbox: tuple[float,...]     # minlon, minlat, maxlon, maxlat
    crs: str
    source_path: str
    sensor: str                # "S1", "EOS04", ... see section 5A

class Detection:
    detection_id: str
    scene_id: str
    class_name: Literal["oil","look_alike","ship","wake","background"]
    geometry: dict             # GeoJSON Polygon, EPSG:4326
    mean_class_prob: float
    pixel_area: int

class ShipTarget:                       # NEW, section 11
    target_id: str
    scene_id: str
    centroid: tuple[float,float]
    pixel_area: int
    mean_backscatter_db: float
    matched_mmsi: str | None            # None means unmatched, i.e. dark
    match_distance_m: float | None
    match_confidence: float

class SlickFeatures:
    detection_id: str
    area_km2: float
    perimeter_km: float
    complexity_ratio: float    # P / (2 * sqrt(pi * A)), 1.0 is a circle
    major_axis_deg: float      # 0-180, from minimum rotated rectangle
    elongation: float
    mean_backscatter_db: float
    contrast_db: float
    age_band: Literal["fresh","intermediate","weathered"]
    age_reasoning: str

class GateResult:
    detection_id: str
    wind_speed_ms: float
    verdict: Literal["accept","downgrade","suppress"]
    reason: str

class OpticalCorroboration:             # NEW, section 7
    detection_id: str
    status: Literal["agree","disagree","no_coverage"]
    sensor: str | None
    acquired_at: datetime | None
    delta_hours: float | None
    reasoning: str

class OriginField:
    field_id: str
    detection_id: str
    path: str                  # NetCDF, dims (time, lat, lon), normalised to sum 1
    t_min: datetime
    t_max: datetime
    n_members: int
    seed: int
    kernel: str                # "openoil" | "leeway" | "null"

class AISTrack:
    mmsi: str
    vessel_type: str
    points: list[AISPoint]     # ts, lat, lon, sog, cog, heading
    dark_gaps: list[DarkGap]
    integrity_flags: list[IntegrityFlag]   # NEW

class DarkGap:
    start: datetime
    end: datetime
    duration_min: float
    entry_point: tuple[float,float]
    exit_point: tuple[float,float]
    envelope: dict             # GeoJSON Polygon, dead reckoned reachable set

class IntegrityFlag:                    # NEW, F7
    kind: Literal["no_imo","implied_speed","static_change","mmsi_reuse","position_jump"]
    at: datetime
    detail: str
    severity: float            # 0-1

class SuspectScore:
    mmsi: str
    total: float
    factors: dict[str, float]  # factor name -> contribution, must sum to total
    rank: int
    narrative: str
    radar_support: str | None  # ShipTarget.target_id if F8 fired

class Elimination:
    mmsi: str
    reason: str                # required, never empty
    rule: str                  # machine readable rule id

class MarpolAssessment:                 # NEW, section 13
    mmsi: str
    en_route: bool | None
    distance_to_land_nm: float | None
    in_special_area: bool | None
    est_discharge_l_per_nm: tuple[float,float] | None   # band, never a point
    flag: Literal["conditions_not_met","conditions_met","insufficient_data"]
    assumptions: list[str]     # printed verbatim in the dossier

class CaseVerdict:                      # NEW, section 12
    case_id: str
    verdict: Literal["ATTRIBUTED","RANKED","DARK_CONFIRMED"]
    reasoning: str
    top_suspects: list[str]              # mmsi, ordered
    unmatched_targets: list[str]         # ShipTarget ids, for DARK_CONFIRMED
    infrastructure_flag: bool
```

**Contract rules, write a test for each:**
- `SuspectScore.factors` sums to `SuspectScore.total` within 1e-6.
- `Elimination.reason` is never empty.
- `OriginField` NetCDF sums to 1.0 within 1e-6 and has a time dimension of length > 1.
- `MarpolAssessment.est_discharge_l_per_nm` is a band, never a scalar.

---

## 4A. Data acquisition

Two categories. **Blocking human actions** need a person and have approval latency. **Scripted** means `backend/scripts/fetch_data.sh` can pull it unattended once credentials exist.

### Blocking human actions, do these before writing code

1. **Register a NASA Earthdata account** at `urs.earthdata.nasa.gov`, then authorise ASF access. Free, immediate. Unlocks Sentinel-1.
2. **Register a Copernicus Marine account** at `marine.copernicus.eu`. Free. Unlocks ocean currents.
3. **Register a Copernicus Climate Data Store account**, accept the ERA5 licence terms on the dataset page, and save the API key to `~/.cdsapirc`. Licence acceptance is a separate click and a common silent failure. **ERA5 requests queue and can take hours.** Submit the demo region request on day one.
4. **Start the Zenodo download now.** Part I alone is roughly 40.7 GB compressed. See the dataset table below. This is the single longest lead item.
5. **Pick the hero incident** and record its date, bounding box and a source reference in `backend/config/demo.yaml`. Everything downstream keys off this. Candidate worth checking first: the scene id labelled INDIA in the public cerulean-cloud README, `S1A_IW_GRDH_1SDV_20210523T005625_20210523T005651_038008_047C68_FE94`. Verify its footprint and whether Cerulean holds slick records for it before committing.

### Datasets

| Data | Source | Auth | Notes |
|---|---|---|---|
| **Zenodo Sentinel-1 SAR Oil spill dataset, Parts I to III** | Zenodo DOIs 10.5281/zenodo.8346860, 8253899, 13761290 | none | **Primary evaluation corpus. Named in the PS.** Sigma0 in decibels, 2048x2048x2 TIFF, binary masks 2048x2048, foreground 1 and background 0. Part I is roughly 40.7 GB. Record the published MD5 per file in the manifest. |
| **Five class SAR oil spill dataset** (Krestenitis style) | research dataset, acquire manually | request | **Secondary corpus.** Classes: sea surface, oil spill, look alike, ship, land. Approximately 1112 images, fixed 1002/110 split. Required for the wind gate FP measurement and for the ships class used by section 11. The Zenodo set is binary and cannot provide either. |
| Segmentation model | HuggingFace `sahilvishwa2108/oil-spill-deeplab` | none | ~205 MB. Cache to `backend/data/models/` and load from disk. Verify the on disk extension on the Files tab: the card says `.keras`, a sibling repo of the same author ships `.h5`. |
| Sentinel-1 GRD | ASF DAAC via `asf_search` | Earthdata | ~1 GB per scene. Use ASF, not CDSE: CDSE serves original GRD products older than one year with deferred availability, and the hero scene will be older than a year. |
| Ocean currents | CMEMS Global Ocean Physics via `copernicusmarine subset` | Copernicus Marine | Fallback: HYCOM over OPeNDAP with `xarray.open_dataset`, no account. |
| Wind | ERA5 single levels, 10 m U and V, via `cdsapi` | CDS key | Fallback: NOAA GFS from the public S3 bucket, no auth. Verify archive coverage for the incident date first. |
| AIS reference statistics | MarineCadastre daily zips, `marinecadastre.gov/accessais` | none | **Named in the PS as the format authority.** Used only to fit lane, speed, type and dropout distributions, and to fix the schema. |
| Optical corroboration | Sentinel-2 L1C or Sentinel-3 OLCI | Copernicus | Only needs a coincidence search plus one scene. See section 7. |
| Coastline and land mask | Natural Earth or GSHHG | none | Land mask, tile skipping, and distance to nearest land for section 13. |
| Offshore infrastructure | public offshore platform point layer | none | Section 14. |
| Drifter trajectories | NOAA AOML Global Drifter Program | none | Section 17.3. |
| Cerulean slick records | `api.cerulean.skytruth.org`, OGC API Features (tipg) | none for the public read API | **Validation only.** Cache every response to `backend/data/cerulean/`. See section 17.2. |

### Sentinel-1 minimal working shape

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

### AIS, be precise about what is real

The PS states: *"Real AIS if available may be used else synthetic data can be prepared for the region of oil spill to demonstrate the functioning of the algorithm."* Record this sentence verbatim as a comment at the top of `backend/config/demo.yaml` and in the README.

Synthetic AIS is therefore permitted. It is not an excuse to be sloppy. MarineCadastre files are US waters and are **not** the demo data; they are the statistical source. Lane geometry, vessel type mix, speed distributions, ping intervals and dropout rates are fitted from real files and used to generate demo traffic, with only the incident injected. The database schema mirrors the MarineCadastre columns so a real ICG or DGLL feed drops in with no code change.

### Fetch script requirements

- Writes `backend/data/raw/MANIFEST.json` recording, per file, the source URL or dataset id, retrieval timestamp, byte size and SHA-256. The dossier provenance page reads from this manifest.
- Idempotent. Re running skips files already present with a matching hash.
- Resumable. Sentinel-1 scenes are large and hackathon wifi is not.
- `--offline` flag that verifies the manifest and exits without touching the network. This is the pre demo check.
- Credentials only from environment variables listed in `.env.example`.

---

## 5. Stage 1 and 2: detection

### Model

`sahilvishwa2108/oil-spill-deeplab` from HuggingFace. MIT licensed. DeepLabV3+, Keras/TensorFlow.

- Input `(256, 256, 3)`, RGB, values scaled to 0-1.
- Output `(256, 256, 5)`, classes in order **Background, Oil Spill, Ships, Look-alike, Wakes**.
- Download the weights once into `backend/data/models/` and load from disk so the demo works offline.

The **Ships** channel is not decoration. Section 11 depends on it.

### The rendering trap, handle this first

The model expects images rendered the way its training dataset rendered them, which is an 8 bit visual product, not calibrated SAR. Feeding raw DN or unclipped dB degrades output silently rather than erroring.

`render.py` must:
1. Read the Sentinel-1 GRD VV band.
2. Convert to dB: `10 * log10(DN**2 / calibration)` or `10 * log10(sigma0)` if already calibrated.
3. Clip to a fixed dB window, start with `[-35, 0]`, expose it in `pipeline.yaml`.
4. Linear stretch the clipped range to 0-255, uint8.
5. Replicate to 3 identical channels.

**Validation gate before proceeding, and it is different from the old plan.** The Zenodo corpus is already in Sigma0 dB, which is the same space step 2 produces. So it tests the render chain and the model together:

1. Take Zenodo dB images, run steps 3 to 5 only, feed the model, inspect masks against the provided binary ground truth.
2. Then run the full chain on a real Sentinel-1 GRD.
3. If step 1 passes and step 2 produces garbage, the fault is in steps 1 and 2 of the render, not the model. Tune the dB window. **Do not swap the model.**

Stretch, only after P3: the Zenodo images are 2 channel, almost certainly VV and VH. Dual pol improves look alike separation. Cerulean's production model uses VV only. If time allows after the honest IoU number exists, evaluate a dual pol variant and report the delta. Do not start here.

### Tiling

- Tile the scene into 256x256 with 48 px overlap.
- Predict per tile, keep the full 5 channel softmax.
- Stitch by **averaging softmax over overlaps**, then argmax at the end. Do not argmax per tile and stitch masks, that produces visible grid seams straight through slicks.
- Skip tiles more than 90 percent land or nodata using the coastline mask.

### Georeferencing

Carry the `rasterio` affine transform per tile. After stitching, vectorise the oil class with `rasterio.features.shapes`, reproject to EPSG:4326, simplify lightly, drop polygons below a minimum area from config. Emit `Detection` records.

### Evaluation, do not skip

`eval.py` computes **per class IoU and per class F1** on a held out split and prints a table. Run it on both corpora:

- **Zenodo (binary):** oil versus background IoU. This is the headline number and the one the PS's own dataset produces.
- **Five class set:** per class IoU including look alike and ship, since the Zenodo set cannot measure either.

On this taxonomy the background class dominates pixel counts, so an aggregate figure near 0.97 tells you almost nothing about oil class performance. Surface the numbers `eval.py` produces, with the class name attached, even if oil class IoU is 0.6.

---

## 5A. Sensor adapter

Wrap ingest behind a `SensorAdapter` protocol with `read_backscatter_db(path) -> np.ndarray` and `read_metadata(path) -> SceneMeta`. Implement `Sentinel1Adapter` fully. Add an `EOS04Adapter` stub that raises `NotImplementedError` with a docstring naming the expected input.

This is fifteen minutes of work and it is the difference between claiming sensor agnosticism and demonstrating it. `SceneMeta.sensor` carries through to the dossier provenance page.

---

## 6. Stage 3: wind physics gate

A USP component. It is model agnostic post processing, which is a stronger claim than a better backbone because it improves any detector.

Oil damps capillary waves, which is why it appears dark on SAR. That mechanism has a valid wind window:

- Below roughly 2-3 m/s there are not enough capillary waves for oil to damp, so the whole sea surface is dark and dark patches are meaningless.
- Above roughly 10-12 m/s wind mixes the slick into the water column and the contrast disappears.

`gate/wind.py`:
1. Load the 10 m wind field for the scene acquisition time from cached ERA5 or GFS NetCDF via `xarray`.
2. Interpolate U and V to each detection polygon centroid, compute speed.
3. Apply thresholds from `pipeline.yaml`:
   - speed < `wind_min_ms` -> `suppress`, reason names the low wind ambiguity
   - speed > `wind_max_ms` -> `suppress`, reason names slick breakup
   - within `[wind_min_ms, wind_min_ms + margin]` -> `downgrade`, confidence multiplier applied
   - otherwise -> `accept`
4. Emit a `GateResult` per detection. **Never delete suppressed detections**, mark them. The UI shows them greyed with the reason on hover.

**Measure this.** Use the five class corpus plus curated Cerulean negatives (section 17.2) to assemble a set with known look alikes and known slicks. Report false positives before the gate versus after. That number goes on the slide.

---

## 7. Stage 3b: optical corroboration

The PS says "SAR and EO imagery". This stage closes that gap. It does not need to be sophisticated.

`corroborate/optical.py`:
1. Search for a Sentinel-2 L1C or Sentinel-3 OLCI acquisition intersecting the detection footprint within `optical_window_hours` from config, default 6.
2. If none, emit `status="no_coverage"` with reasoning that states SAR is the primary sensor because it is all weather, day and night, and free of cloud dependence.
3. If one exists, compute a simple anomaly statistic over the detection polygon versus a surrounding sea reference ring, and emit `agree` or `disagree` with the statistic in the reasoning.

Three honest states. Do not overclaim optical detection. The value is that the PS requirement is met and the reasoning is inspectable.

---

## 8. Stage 4: characterisation

`characterize/geometry.py` computes the `SlickFeatures` fields. Straightforward shapely and numpy.

`characterize/age.py` produces a **relative age band only**, from a small explicit rule set combining contrast in dB and complexity ratio. Fresh slicks are high contrast and compact, weathered slicks are lower contrast and fragmented with high complexity ratio. Every band comes with an `age_reasoning` string naming the rule that fired.

Put this line in the README and the dossier verbatim: we tested whether absolute slick age in hours is recoverable from a single SAR acquisition, concluded it is not, and therefore report a relative band with the reasoning that produced it.

### The age band constrains the origin window, and that is what it is for

The band is not a label on a dossier page. It is the **only evidence in the system about when the discharge happened**, and it has to reach the scoring engine or the hindcast has no way to prefer one hour of the horizon over another.

The backward field answers "where could this oil have come from" at every hour out to the horizon, and it treats an origin 48 hours ago as exactly as plausible as one an hour ago. It cannot do otherwise: the drift physics has no opinion about when the oil entered the water. The slick's own contrast and complexity do, weakly. Oil spreads and its contrast against the sea falls as it weathers, so a compact high-contrast slick has spent less time on the surface than a fragmented low-contrast one.

`scoring/age_window.py` turns the band into a weight over the field's time axis, which **F1 and F2 apply per timestep** (they are the two factors that integrate over time; the rest are either time-agnostic or already scoped to when the vessel was in the field). Windows live in `config/scoring.yaml` under `age_origin_window`.

Three rules keep it honest, and each has a test:

1. **It is a band, never a point.** The non-goal on absolute age still stands and nothing here recovers it. The windows are wide, they deliberately overlap, and they are config so they can be argued with rather than buried in code.
2. **It tapers, it does not cut off.** The boundary between a compact slick and a spreading one is not sharp. A hard edge would score a discharge one hour outside the band as impossible.
3. **It downweights, it never eliminates.** The weight bottoms out at `floor_weight`, not zero, for the same reason F6 is capped. A vessel in the origin field at an implausible time scores lower; it does not disappear. A zero would erase its field integral outright, which is elimination by another name.

The test that matters is the symmetry one: a **fresh** slick must favour the vessel that was there recently, and a **weathered** slick must favour the vessel that was there long ago, on the same field and the same two vessels. If only the first holds, the feature is a recency prior wearing physics as a costume.

#### The band's edges are estimates too, and F9 has to say so

There is a fourth rule, added with F9, and it is the one most likely to be got wrong by anyone tightening this later.

Suppose the discharge really happened 14 hours before acquisition, and the slick's contrast and complexity put the band at 0 to 12 hours. The band is wrong, by two hours, which is well inside what radiometry can resolve. Every vessel that passed in those two extra hours is a live candidate, and a scoring rule that buries them has not been strict, it has treated a soft radiometric estimate as a hard boundary.

So **the penalty does not begin at the window edge.** `config/scoring.yaml` carries `temporal_consistency.band_uncertainty_hours`, and inside that margin of either edge a vessel is scored exactly as though it were inside the window, because on the evidence available it may well be. The margin is finite: it absorbs the band's own uncertainty, it does not widen the window without limit.

This is the same instinct as rule 2 (it tapers, it does not cut off) applied one level up. Rule 2 softens the weight at the edge. This softens *where the edge is*.

---

## 9. Stage 5: backward drift ensemble, the core artifact

### 9.1 The drift kernel protocol

Define in `drift/kernel.py`:

```python
class DriftKernel(Protocol):
    name: str
    def run_backward(self, seed_geometry, t0, horizon_hours,
                     forcing, params, seed) -> np.ndarray:
        """Returns array of shape (n_particles, n_steps, 3): lat, lon, t."""
    def run_forward(self, seed_geometry, t0, horizon_hours,
                    forcing, params, seed) -> np.ndarray: ...
```

Implementations:
- `drift/openoil.py`: OpenDrift with the OpenOil module. The default, used for slicks.
- `drift/leeway.py`: OpenDrift Leeway or OceanDrift, for drifting objects and debris.
- `drift/null.py`: returns the seed geometry unchanged at every timestep. Used for fixed position events. **Build this one, it is ten lines, and it is what proves the architecture is genuinely general.** Every downstream stage must run unchanged against it.

Kernel selection comes from `pipeline.yaml`. Adding a second demo scenario that swaps the kernel via config is a one line diff and it is the single most persuasive thing you can do on stage. Build the plumbing even if the second scenario is cut.

### 9.2 Ensemble construction

This is the contribution, not the drift model itself.

1. Seed particles uniformly inside the slick polygon, count from config.
2. Run `n_members` (default 30, reducible to 8 for the live demo) independent backward runs, each with perturbed forcing:
   - wind drift factor sampled around 0.03 (typical range 0.02 to 0.04)
   - current field perturbed with a spatially correlated noise term, magnitude from config
   - horizontal diffusivity sampled from config range
   - seed time jittered across the acquisition uncertainty
3. Every particle at every backward timestep contributes a sample `(lat, lon, t)`.

### 9.3 Field construction

`hindcast/field.py` converts those samples into `P(lat, lon, t)`:

- Bin onto a regular grid, resolution and time step from config.
- Smooth with a Gaussian kernel, bandwidth from config.
- Normalise so the field sums to 1 over the whole space time volume.
- Write to NetCDF with dims `(time, lat, lon)`, recording seed, kernel name, member count and forcing source in the attributes.

**Do not** collapse over time. The time axis is what makes the AIS scoring work.

Backward horizon default 48 hours, configurable. Note openly in the docs that uncertainty grows with horizon, and that a wide field producing a longer suspect list is an honest result and not a failure.

---

## 10. Stage 6: AIS reconstruction

### Storage

PostgreSQL with PostGIS and TimescaleDB. Hypertable on the ping timestamp, GiST index on position. Schema mirrors the MarineCadastre AIS CSV columns.

### Synthetic generator

`ais/synthetic.py`:

- Lane geometry taken from **real** shipping lane coordinates for the demo region.
- Vessel type mix and speed distributions sampled from **real** MarineCadastre statistics.
- Ping intervals and natural dropout rates sampled from real distributions, not a fixed cadence.
- Inject exactly one culprit: a vessel whose track crosses the high probability region, slows to a steady low speed, stops transmitting for a configurable dark period, and resumes on a different course.
- Inject at least **four** hard negatives:
  1. passes through the field at the wrong time
  2. has a dark gap far from the field
  3. spatially close throughout, constant transit speed, no dark gap
  4. **NEW:** has a dark gap overlapping the field but no corresponding unmatched radar target in the scene, so F8 does not fire for it

If the scoring engine cannot separate the culprit from all four, the engine is wrong. Negative 4 exists specifically to prove F8 discriminates rather than just rewarding darkness.

Everything is seeded and reproducible from `backend/config/demo.yaml`.

### The culprit goes at a PAST origin, and this is easy to get wrong

**The scenario must seed the discharge hours before acquisition, from the age band's origin window (section 8), never at the field's global peak.**

This was a real bug and it hid well. `field_peak` takes the argmax over the whole space-time volume, and the field is always most concentrated at acquisition because the ensemble members have not yet diverged: peak cell density falls monotonically as the hindcast runs backwards. So the global argmax can only ever land within a timestep of the satellite pass, whatever the horizon is. On the 48 hour demo field the culprit was seeded at -0.2h with a track spanning only -3.5h to +3.1h, and its field integral drew mass from just the final 1.2 hours. **Forty-one of the forty-eight reconstructed hours had no vessel positions in them at all.**

Everything downstream looked correct. The field was computed, normalised, rendered and scrubbable; the culprit ranked first; the tests passed. But the ranking was decided by which vessel was beside the slick when the satellite looked, which is the exact reasoning the project exists to replace, and no test could see it because every test asked whether the culprit won rather than *why*.

The fixes, all three needed together:

- `field_peak_at(field_ds, at_time)` slices first and takes the argmax second, so an origin can be placed genuinely in the past.
- `generate_demo_scenario(origin_lag_hours=..., acquired_at=...)` takes the lag from the slick's own age band, so the scenario is consistent with what the characterisation measured rather than with a number chosen to make the demo work.
- `extend_to` carries every vessel except `wrong_time` through to the end of the field's window at transit speed, so the fleet is still on screen at the acquisition instant instead of vanishing hours before the image the case is built on.

**Expect the margin to shrink as the origin goes deeper, and do not treat that as a regression.** On the fixture field rank 1 beats rank 2 by 17.99 with the origin at acquisition, 5.52 at -2h and 2.27 at -4h. A wider field genuinely admits more candidates. Uncertainty is the scoring surface (section 22); a demo whose margin does not move with the horizon is not measuring the horizon.

`wrong_time` is deliberately *not* extended and is deliberately left outside the window. With the age weighting in place it stops being a formality and becomes the negative that tests the timing evidence directly.

### Ship motion must be motion a ship can perform

**The synthetic tracks are sailed, not interpolated.** `ais/kinematics.py` integrates a vessel through its waypoints under a bounded rate of turn and a bounded rate of speed change, and the AIS pings are sampled from the resulting continuous track. That is the order the real world does it in: the vessel moves, and the transponder reports what it finds.

Placing waypoints and interpolating between them honours the waypoint schedule exactly, and no hull can. The demo's own tracks showed both failure modes:

- A hard negative turned 95 degrees with 84 of them inside a single seven minute ping interval, reporting a course sequence of `0, 0, 0, +11, +84, 0, 0, 0`. A real manoeuvre is a **plateau** of sustained rate of turn held across many reports, not a spike between two of them.
- The culprit went from 10.5 knots to 1.0 knots between consecutive pings. A laden merchant vessel reducing to a crawl takes ten to fifteen minutes and over a mile.

This is not cosmetic. **F4 scores sustained speed deviation and F5 scores course change**, so both were reading the shape of a corner in the fixture rather than the shape of a manoeuvre. A naive "is this rate of turn plausible" check passes anyway when the pings are far enough apart, which is how it survived: the sparse sampling averaged the corner into something that looked gradual. Check the course *sequence*, not the peak rate.

Figures, in `kinematics.py` so they can be argued with: rate of turn 0.20 deg/s laden tanker, 0.25 cargo, 0.60 fishing; acceleration 0.35 kn/min, deceleration 0.9 kn/min.

**Vessels wheel over before the mark, not at it.** A turning circle at 11 knots and 0.20 deg/s is about 1.3 km across, so a vessel steers into its turn `R tan(theta/2)` short of the waypoint. Sailing to the mark and turning afterwards puts the track through the corner and then swinging wide.

This constraint immediately exposed a scenario that was never physically possible. The culprit had been given a tight dogleg over the origin spanning 900 m, which is **narrower than the vessel's own turning circle**: sailed properly it wheels over before reaching the origin, misses it entirely, and scores a field integral of zero. The straight-line interpolation had been hiding an impossible manoeuvre.

**A discharge is a straight slow run, and the hard negatives are straight transits.** The realistic behaviour is also the better scenario: a vessel discharging holds its course and slows, which is precisely how a discharge streak comes to be elongated along the vessel's track, which is the geometry F3 exists to detect. The course change that F5 looks for is a separate, gentle manoeuvre well afterwards. The hard negatives used to be V shapes, in to the origin and back out on the reciprocal, which is a vessel sailing to a point and turning round. Traffic follows lanes, and lanes are straight.

### Track reconstruction

`ais/tracks.py`: group by MMSI, sort by time, interpolate positions between pings using great circle interpolation with SOG and COG, producing a continuous position function per vessel over the origin window.

### Dark gap detection

`ais/darkgaps.py`:

1. Find inter ping intervals longer than `dark_gap_min_minutes` (default 20, tuned against the observed dropout distribution so ordinary dropouts do not fire).
2. For each gap, build the **dead reckoned reachable envelope**: from the last known position, course and speed, propagate a cone widening with time, bounded by the vessel's plausible maximum speed, and close it against the first position after the gap. Represent as a polygon.
3. Emit `DarkGap` records. Do not exclude these vessels from anything.

### AIS integrity, F7

`ais/integrity.py` emits `IntegrityFlag` records:

- `no_imo`: MMSI present with no matching IMO number where the vessel class should carry one.
- `implied_speed`: implied speed between consecutive pings exceeds the vessel's plausible maximum.
- `static_change`: voyage or static data changes mid passage.
- `mmsi_reuse`: the same MMSI appears in two places within a physically impossible interval.
- `position_jump`: discontinuity inconsistent with reported COG and SOG.

Each carries a severity in 0 to 1. F7 aggregates them. This exists to answer "AIS can be spoofed, not just switched off" with a factor rather than a shrug.

---

## 11. Stage 6b: SAR ship target cross check

**This is the highest value addition in this revision. Build it before the frontend.**

It converts a dark vessel from an inference about missing data into an independent sensor observation.

`services/detection/ships.py`:
1. From the stitched softmax, extract the **Ships** class.
2. Connected components, filter by pixel area bounds from config to reject speckle.
3. Compute centroid, pixel area and mean backscatter per component.
4. Georeference to EPSG:4326.
5. Emit `ShipTarget` records with `matched_mmsi = None`.

`services/core/crosscheck/radar.py`:
1. For each `ShipTarget`, find AIS positions interpolated to the scene acquisition time.
2. Match within `radar_match_radius_m` from config, using a greedy nearest assignment with a distance cap. Record `match_distance_m` and a confidence.
3. Any `ShipTarget` left unmatched is a **radar observed dark vessel**: a hull Sentinel-1 photographed that AIS did not report.
4. For each unmatched target, test whether it falls inside any vessel's dead reckoned dark envelope, and whether it falls in a cell of the origin field with probability above `eps`.

Outputs feed two places: factor **F8**, and the `DARK_CONFIRMED` verdict in section 12.

Caveats to state in the docs and the dossier, because a jury will find them if you do not:
- Sentinel-1 ship detection at GRD resolution misses small vessels.
- Not every unmatched target is evasion. Vessels below AIS carriage requirements, fishing craft, and buoys all appear. Report the count of unmatched targets and their sizes; never assert that unmatched equals guilty.
- The match is at acquisition time only, which is a single instant. Say so.

---

## 12. Stage 7: evidence scoring and verdict

`scoring/factors.py` computes named factors, `scoring/engine.py` combines them, `scoring/eliminate.py` produces the elimination log, `scoring/verdict.py` assigns the case verdict. All weights and thresholds live in `backend/config/scoring.yaml` and are displayed in the UI and printed verbatim in the dossier.

### Factors

**F1, field integral.** The primary factor. For vessel `v`, integrate origin probability along its reconstructed track:

```
F_field(v) = sum over timesteps t of P(lat_v(t), lon_v(t), t) * w_age(t) * dt
```

Normalise across candidates to 0-1. This is what makes a vessel that lingered inside a broad uncertain cloud outrank a vessel that clipped a narrow peak, which distance to centroid ranking gets exactly backwards.

`w_age(t)` is the age band's origin window weight from section 8, and F2 carries the same term. Without it the sum treats every hour of the horizon as equally plausible, so a vessel is scored purely on *where* it was and never on *when*, and the ranking collapses towards whichever vessel was nearest the slick at acquisition. That is the proximity reasoning this system exists to replace, so the weight is not an enhancement to F1 but a condition of F1 meaning what it claims to.

**F2, dark overlap.** Fraction of the origin window during which the vessel was dark **and** its dead reckoned envelope overlapped non zero probability mass, weighted by the mass overlapped.

**F3, axis alignment.** A discharge streak is elongated along the vessel's track. Compare `SlickFeatures.major_axis_deg` against course over ground at the times the vessel was inside the field. Score angular agreement modulo 180 degrees.

**F4, speed anomaly.** Operational discharge is typically at a slow steady speed rather than transit speed. Score sustained deviation below the vessel's own median transit speed while inside the field.

**F5, course anomaly.** Deviation from the lane baseline, or a significant course change immediately after the origin window.

**F6, vessel plausibility.** A small prior by vessel type and size. Keep the weight low and the reasoning explicit. This factor **downweights, it never eliminates**, and that must be stated in the config comments and the docs.

**F7, AIS integrity.** Aggregated severity of `IntegrityFlag` records within the origin window.

**F8, radar confirmed dark.** Fires when an unmatched `ShipTarget` falls inside the vessel's dead reckoned dark envelope **and** in a field cell above `eps`. Scaled by the probability mass at that cell and by the match confidence. This should be one of the highest weighted factors, and the weight must be justified in a config comment.

**F9, temporal consistency.** How close the vessel's best opportunity to be the source sits to the origin window of section 8. For each vessel, find the hour at which origin probability along its track peaks, read off the **unweighted** field (sampling the age-weighted field would find the peak the age band had already decided it wanted, and F9 would be scoring its own assumption). Compare that hour against the window, allow for `band_uncertainty_hours`, and score the remainder on a Gaussian falloff.

F1 already carries `w_age(t)`, so the obvious objection is double counting. The answer is that they ask different questions. F1 integrates over space, so its timing term is invisible inside a spatial sum and a lot of mass at the wrong hour looks identical to a little mass at the right one. F9 marginalises space out entirely: two vessels whose opportunity peaked at the same hour score the same here regardless of how much mass either had. The redundancy is real but partial, and `seed_demo.py` reports how many survivors peak inside the window so it can be watched rather than assumed.

The separation also buys the thing section 22 is for. Timing used to be a weight nobody could see; as its own factor it becomes its own step in the case build, with its own bar, that a room can watch move the ranking and argue with.

Two bounds, both tested:

- **It saturates.** The combination section below records that an unbounded single factor penalty was a real bug here once. F9 bottoms out at the same logit floor as every other soft factor.
- **It cannot outvote the field.** Because it runs through a logit it swings both ways, so its full range is `weight * 5.89`. At a weight of 1.0 that came to 5.89 against the 5.5 that F1 and F2 can produce between them, which would have let a heuristic radiometric band overturn the origin field itself. The weight is 0.75 and `tests/test_temporal_consistency.py` holds the bound.

### Combination

Weighted sum in log odds space, weights from config, output normalised for display. Store every factor's contribution in `SuspectScore.factors`. Generate `narrative` by templating the top three contributing factors into plain sentences: plain language, active voice, no jargon.

### Elimination rules

Applied before scoring, each with a `rule` id and a human readable `reason`:

- `NO_TEMPORAL_OVERLAP`: the vessel had no position anywhere in the field's time range.
- `NO_SPATIAL_SUPPORT`: the track never entered a cell above `eps`, and no dark envelope overlapped one either.
- `INSUFFICIENT_TRACK`: fewer than N pings in the window, so the reconstruction is unreliable. Say so, do not silently drop.

Nothing else eliminates. Everything else downweights. Write reasons as sentences an investigator would accept, not error codes.

### Stage 3 shows the case being built, not the ranking that came out

**This is the strongest thing the project can put on screen, and it is available only because of non-negotiable 3.**

A ranked list is a result. The only things a room can do with a result are accept it or reject it, and every competing system produces one. Because the scoring is an explicit weighted model with named factors and no learned parameters, this one can be taken apart and reassembled in front of the room. A trained classifier cannot. `scoring/case_build.py` rebuilds the ranking through the real engine, one class of evidence at a time, in the order an investigator would gather it: who was present, who is ruled out and why, where they were, when they stopped reporting, how they behaved, what kind of vessel, what AIS says about itself, and last what a second independent sensor saw.

The independent sensor goes last deliberately, so the room can see how much of the case stands without it.

Two computed outputs matter more than the steps:

- **`stabilises_at_step`**, the earliest step after which the leader never changes again. A conclusion settled early and unmoved by everything after it is robust in a way a large final margin does not by itself demonstrate.
- **`decisive_factors`**, a leave-one-out ablation over the full evidence set. Empty is the strongest result available: there is no single factor you could disbelieve that would change who is ranked first. A non-empty list is not a failure to hide, it is the caveat the system owes the room, and it is shown in the same place with the same prominence. **A robustness claim that can only come out positive is marketing**, and a test asserts the negative case renders.

### The baselines are the closing argument

The rebuild shows how this system reached its answer. It does not, by itself, show the answer needed this system. So `naive_baselines` runs three simpler approaches on the same case, each named with what it has to assume:

| Baseline | Assumes | On the demo case |
|---|---|---|
| Nearest vessel when the satellite passed | That the oil is where it started | Same answer, but the nearest vessel is 64 km away and the runner-up is barely further: no discrimination at all |
| Nearest vessel to the origin field's centre | That the origin is a point | **Different answer.** This is ablation B made concrete on the case in front of the room |
| Any vessel that went dark | That going dark is itself incriminating | Three vessels went dark, so no single answer |

Collapsing the field to a point gets the wrong vessel. That single line is the whole argument for the probability field, and it is far more persuasive shown happening on the case being discussed than asserted in a table of fifty synthetic incidents.

Report agreement honestly when it happens, and show the margin to the runner-up alongside it. A baseline that picks the right vessel by half a kilometre out of sixty is not distinguishing between them, it is guessing and getting lucky, and crediting it with a discrimination it does not have would be the same overclaim in the other direction.

### Verdict assignment

`scoring/verdict.py` emits a `CaseVerdict`:

| Verdict | Condition | Meaning |
|---|---|---|
| `ATTRIBUTED` | Rank 1 score exceeds rank 2 by `dominance_margin` from config, and rank 1 was broadcasting throughout the origin window | One vessel dominates. Prosecutable evidence package. |
| `RANKED` | Multiple plausible candidates, no dominant one | Ordered list with reasons plus the full elimination log. Narrows the field for an investigator. |
| `DARK_CONFIRMED` | All broadcasting vessels eliminated or scored below `dark_floor`, **and** at least one unmatched `ShipTarget` sits inside the origin field above `eps` | A vessel absent from the AIS picture was present in the origin envelope. Radar saw a hull; AIS did not report it. |

`DARK_CONFIRMED` is not a failure state. Every competing system treats "no broadcasting suspect" as no result. For an intelligence organisation it is the finding. The dossier must render it as a positive result with the unmatched target's position, size and the origin probability at that cell.

---

## 13. Stage 7b: MARPOL Annex I evaluation

`legal/marpol.py`, thresholds in `backend/config/marpol.yaml`.

For the top ranked suspect, evaluate the Annex I conditions that are checkable from a reconstructed track:

| Condition | How | Source of the number |
|---|---|---|
| Proceeding en route | SOG above `en_route_min_sog` throughout the discharge window | AIS |
| Distance from nearest land | Minimum distance from track to the coastline layer, in nautical miles | Coastline layer |
| Inside a special area | Point in polygon against the special area layer | Static layer |
| Estimated discharge rate | Slick area multiplied by a stated thickness band gives a volume band, divided by track length inside the field gives litres per nautical mile as a **band** | Derived, assumptions printed |

Relevant thresholds, in `marpol.yaml` with a comment citing the regulation: machinery space discharge requires the ship to be en route, more than 12 nautical miles from nearest land, oil content not exceeding 15 ppm. Cargo area discharge from a tanker requires being outside a special area, more than 50 nautical miles from nearest land, en route, at an instantaneous rate not exceeding 30 litres per nautical mile.

Output a `MarpolAssessment` with `flag` in `conditions_not_met`, `conditions_met` or `insufficient_data`, and an `assumptions` list printed verbatim in the dossier.

**Hard rule.** This layer never outputs a determination of illegality. It reports which conditions the reconstructed behaviour appears not to satisfy, with the assumptions attached. Oil content in ppm is not observable from satellite, so `conditions_met` can never be asserted on that basis and the code must not attempt it.

---

## 14. Stage 7c: infrastructure overlap flag

`crosscheck/infrastructure.py`.

If the origin probability field places more than `infrastructure_mass_threshold` of its mass within `infrastructure_radius_m` of a known fixed offshore installation, set `CaseVerdict.infrastructure_flag` and emit a statement: *the origin envelope includes fixed infrastructure at position P, so vessel attribution alone may be incomplete.*

Do not eliminate any vessel. Do not accuse the installation. Report it.

Cost is a static point layer plus one spatial query. Value is that it answers "what if it was a rig, not a ship" with a click, and it demonstrates that you considered the failure mode where the system is confidently wrong.

---

## 15. Stage 8: forward forecast and dossier

`forecast/forward.py`: same kernel, positive time step, seeded from the current slick, horizon from config. Cheap, and it is a second deliverable, but it is the first thing to cut if time runs out.

**Built, with three decisions worth recording.**

**It emits a normalised probability field, not a time stepped GeoJSON.** The plan called for GeoJSON, and the field is the better product: it is the same `(time, lat, lon)` structure the backward hindcast produces, so it reuses `hindcast/field.py` unchanged, renders through the frontend's existing raster path, and carries uncertainty rather than a hard contour that a responder would read as a boundary. Direction is a parameter of `run_ensemble`, not a separate code path, so the forward and backward runs share the seed particles and the sampled member physics and therefore meet exactly at the acquisition instant.

**The forecast is never an input to attribution, and that is enforced rather than stated.** The two fields have identical dims and dtype, so a substitution would score silently and wrongly, in the direction of blaming a vessel for drift that happened after the evidence was recorded. `OriginField.direction` and the field's NetCDF attrs record which way time ran, `forecast/forward.py:assert_not_scoring_input` refuses a forward field, and `scoring/engine.py:score_vessels` calls it on entry.

**The horizon that gets reported is the horizon that was run.** A drift kernel that runs out of forcing data stops quietly and simply returns fewer steps: the forcing fixtures originally covered 6 hours past acquisition, so a config asking for 24 produced 6 and said nothing. `run_forecast` records `requested_horizon_hours` against `achieved_horizon_hours` and sets `horizon_truncated`, and the fixtures now cover the horizon. Note that the reported horizon is the median span of a single ensemble member, not the span of the binned time axis (which holds bin centres and can run a step long) and not the pooled span of all members (which includes the seed time jitter). Both of those overstate it.

`dossier/render.py`: ReportLab PDF, one case per file:

- **Cover:** case id, generation timestamp UTC, verdict class, and the statement that the output is ranked evidence for a human investigator and is not an automated accusation.
- **Scene:** id, acquisition time, sensor (from `SceneMeta.sensor`), footprint map.
- **Detection:** mask overlay image, per class IoU as measured by `eval.py` with class names attached, gate verdict and reason, optical corroboration status.
- **Slick:** geometry table, age band with reasoning.
- **Origin:** probability field snapshots at three time slices, ensemble size, seed, drift kernel name, forcing source and version.
- **Radar cross check:** ship targets found, matched and unmatched counts, unmatched target positions, with the stated caveats from section 11.
- **Suspects:** ranked table, then one page per top 3 vessel with the factor breakdown as a bar chart and the narrative.
- **Eliminations:** full table of MMSI and reason.
- **MARPOL assessment:** flag, condition by condition table, assumptions verbatim.
- **Provenance:** SHA-256 of every input artifact, the model identifier and version, the scoring config contents verbatim, and the git commit hash.
- **Certificate:** see below.

`dossier/bsa63.py`: generate the Bharatiya Sakshya Adhiniyam, 2023 Section 63 Schedule Part A fields pre filled, including the SHA-256 hash of the dossier and of each input artifact, with the hash function named. Part B is left blank for an expert signature, because that is what the statute requires. Render as the final page.

Do not claim the document is admissible. Claim that it is formatted to carry the information the certificate requires, and leave the signatures to humans. The provenance page and the certificate together are the point: they make this a case file rather than a dashboard.

---

## 16. Stage 9: frontend

React, Vite, TypeScript, MapLibre GL with deck.gl overlays. deck.gl because the origin field is tens of thousands of cells and the AIS layer is thousands of track segments, and a naive Leaflet implementation will stutter during the demo.

### Design direction

Not a generic dark dashboard with an acid accent. Take the direction from the **nautical chart**: chart paper linework, condensed annotation type, monospaced coordinates, graticule rules carrying real graticule values.

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
--radar:      #7FB2C4   /* unmatched radar targets, and only those */
--forecast:   #B08CC7   /* the forward forecast field, and only that */
--current:    #3E7A93   /* surface current arrows */
--wind:       #8FA98C   /* 10 m wind arrows */
```

`--current` and `--wind` were added with the forcing layer. Both are context the case is drawn on rather than findings on it, so they sit in the chart's own register and never borrow an evidence colour. They are two tokens rather than one because wind and current are frequently on screen together and often oppose each other, and form alone (barb versus arrow) does not survive a projector.

`--forecast` was added with the forward forecast and is deliberately off the chart palette. The backward origin field is drawn in `--oil` because it is a claim about where observed oil came from. The forecast is a claim about the future, it is never evidence, and it must not be able to borrow the authority of the colour the observed slick is drawn in. A prediction should not look like a measurement.

Type: **IBM Plex Sans Condensed** for headings and map annotation. **Inter** for body. **IBM Plex Mono** for all coordinates, timestamps, MMSI numbers and factor values. Never set a coordinate or an MMSI in a proportional face.

Probability field ramp: single hue, transparent at zero mass through to `--oil` at peak. Do not use a rainbow ramp, it makes uncertainty look like structure.

### Signature element

**One time scrubber drives everything.** Dragging it simultaneously moves the origin probability field through its time axis, advances every AIS track to that instant, and updates the suspect ranking live. Build it first and build it well, and keep every other interaction quiet.

### The three stage sequence

The console is entered through three ordered stages, each answering one question. Everything on screen at once behind toggles is the right tool for an operator who already knows what they are looking at, and the wrong one for a room seeing it for the first time: arriving together it reads as decoration, arriving in order it reads as an argument.

| Stage | Question | On screen | Scrubber |
|---|---|---|---|
| 1. Acquisition | What did the satellite actually see? | SAR scene, detection polygons, gate verdicts, slick characterisation | None. A single acquisition instant, and a time control there would imply the image is a movie. |
| 2. Drift | Where did it come from, and where is it going? | Both drift fields, `--oil` backward and `--forecast` forward, with the acquisition instant marked on the axis | The full axis, backward horizon through acquisition to the forecast horizon |
| 3. Attribution | Which vessel was in the origin field when it mattered? | The full operator console: tracks, dark envelopes, radar targets, ranking, elimination log, verdict | The backward half only. The ranking reads the origin field, so scrubbing into the forecast would show a ranking against a field that produced none of it. |

Rules, and they matter more than the sequence itself:

- **Every stage is directly reachable**, by click and by number key. A guided path that traps the presenter is worse than no path: during questions the room jumps straight to the drift or the attribution.
- **A stage sets the layers, it does not lock them.** The toggles stay live inside every stage, so any layer can be pulled forward if the room asks for it.
- **Nothing a stage hides is also uncomputed.** Every stage reads the same precomputed bundle. A stage decides what is on screen and what the caption claims, never what ran.
- **Captions are generated from the bundle's own numbers**, never written as prose about what the demo would show. If the ensemble runs at 8 members the caption says 8.
- **One time axis spans both fields.** They are two grids with two time coordinates; the frontend merges them into one ordered set of frames where each frame names the field that owns it. Nothing is interpolated between them and no instant is drawn by both: the origin field owns every instant up to acquisition, the forecast owns every instant after.
- **The acquisition marker sits on the acquisition instant, not on the nearest frame.** A frame is a time bin and its timestamp is the bin centre, so no frame lands exactly on the satellite pass. The marker is interpolated onto the true instant, and a frame within half a bin of it reads as "at acquisition" rather than printing a half bin offset as though the field resolved that finely.

### The attribution view has to explain itself

Stage 3 is the stage that fails hardest without help. It carries tracks, dashed segments, reachable envelopes, radar targets, a probability field and a ranked list at once, and drawn without annotation the honest reaction is "I see lines and circles". Four things fix that, and none of them is a colour choice.

**Say what each mark means, not what it is called.** The legend carries a sentence per mark, keyed to the layers actually switched on, with the sample drawn in the same treatment the map uses. A swatch captioned "eliminated" names the thing without explaining it. "Ruled out by a stated rule, hover the track for the written reason" explains it.

**Distinguish observed from reconstructed, everywhere, in every channel.** A solid line is a position the vessel broadcast; a dashed line is one nobody recorded and this system inferred. A filled marker is a reported position, a hollow one is a vessel that is dark at that instant. The dead-reckoned path is drawn in `--paper` rather than the vessel's own colour, because it is an annotation on the chart rather than a measurement on it. This distinction is the most important thing on the map and it must never be carried by a single cue.

**Label the map so it connects to the panel.** Every vessel carries its rank and MMSI on the chart and a heading arrow from its own reported course. Without the label the ranked list and the tracks are two unconnected displays and the room has to be told which is which out loud. Without the heading a line between two points is equally a vessel arriving and one leaving, and which of those it is decides the case.

**Make clicking a vessel do something.** Selecting one dims the rest hard rather than merely highlighting the chosen one, draws only that vessel's envelope, and opens a card with its whole story in the order the question gets asked: who is it, what did it do, when was it not looking, and only then what the scoring made of that. The score comes last on purpose, because leading with a number invites the room to argue with the number instead of with the behaviour that produced it.

### Forcing is drawn, and therefore has to be real

Wind and current arrows and a sea and air temperature readout answer the question the drift stage raises and never otherwise addresses: why does the origin field lean that way. Because the water was going that way, at that speed, at that time.

Drawing the forcing forced a fixture problem into the open. The current field was one steady-state snapshot repeated across all 91 timesteps and the wind was `np.full`, a single number for every cell at every hour. Both were defensible while nothing looked at them, since the ensemble spread comes from perturbing the forcing per member rather than from the field evolving. Neither survives being drawn: a frozen field animates into arrows that never move, which is decorative physics wearing a provenance chip, and PLAN.md 16A's rule is that every moving thing on screen must be real data. The fixtures now carry an M2 tide and a breathing gyre, a synoptic wind gradient with a slow veer and a diurnal cycle, and sea and air temperature. All small, all physical, all named in the file's own attributes.

Three rules govern the display:

- **Subsample, never resample.** Every arrow is a value that exists in the forcing file at that grid point and that timestep. A smoothed field would put numbers on screen that no dataset ever held, under a chip naming the dataset.
- **Crop to the case before spending the grid budget.** The fixture covers two degrees and the case occupies a fraction of it. Spending the budget on the empty majority left six arrows across the view with 22 km between them; cropping first buys 5.6 km spacing for the same payload.
- **An arrow may never outrun its own cell.** Length is capped at the grid spacing and centred on the grid point, and the wind layer is staggered half a cell off the current layer. Sized off the viewport instead, arrows overlapped their neighbours and the field read as scribble; drawn from a shared origin, an opposing wind and current fused into a single mark pointing both ways.

### Views

1. **Scene view.** SAR basemap, detection polygons, suppressed detections greyed with the gate reason on hover, **unmatched radar targets marked in `--radar`**.
2. **Origin view.** Probability field with the time scrubber, ensemble member spaghetti toggleable underneath.
2a. **Drift view.** The one camera that has to hold the backward origin envelope and the forward forecast at once, which reach in opposite directions from the slick. Kept separate from the origin view rather than widening it: the forecast can run a long way downstream, and framing it in every view would shrink the field the attribution actually rests on.
3. **Traffic view.** AIS tracks, dark gaps drawn as dashed segments with their reachable envelope as a translucent polygon. Make the dashed gap visually distinct at a glance.
4. **Suspects panel.** Ranked list, each row expanding to the factor bar chart and the narrative. Verdict class shown as a chip at the top.
5. **Elimination log.** A plain scrollable table of MMSI and reason. Deliberately unglamorous. Its job is to look like a record.
6. **Dossier button.** Downloads the PDF.

Copy rules: active voice, sentence case, buttons name what happens. Empty and error states say what happened and what to do, and never apologise. No em dashes.

---

## 16A. Visualization, fluid dynamics and motion

The pitch is judged in a room, on a projector, in a few minutes. A correct pipeline that renders as static polygons loses to a weaker pipeline that shows the ocean moving. Engineering work with acceptance criteria, not decoration.

### The one rule that governs everything here

**Every moving thing on screen must be real data.** The particles are the actual OpenDrift ensemble particles. The flow field is the actual CMEMS current and ERA5 wind vectors. The cloud is the actual normalised probability field. Add an on screen provenance chip next to every animated layer naming its source and version. That chip converts eye candy into evidence.

### Libraries

- `deck.gl` for all GPU layers on top of MapLibre GL.
- `luma.gl` shader access for the flow field, through a deck.gl custom layer.
- `@deck.gl/layers` TripsLayer for animated tracks, PathLayer for static, ScatterplotLayer for particles.
- `d3-scale` and `d3-interpolate` for ramps and eased timelines.
- `framer-motion` for panel and list transitions only, never map content.
- No Three.js.

### Layer 1: ambient flow field

GPU particle advection driven by your real forcing data.

1. Encode the current field (U, V) for the active timestep into an RGBA float texture, U in red, V in green, ranges as uniforms.
2. Hold particle positions in a second texture. Each frame a fragment shader samples the flow texture bilinearly, advects by `velocity * dt * speed_scale`, writes the new position.
3. Draw into an accumulation framebuffer that is faded rather than cleared, producing trails. Trail persistence is the knob that makes this read as fluid. Expose it in a dev panel.
4. Respawn a small random fraction of particles each frame to prevent pooling in convergence zones.
5. Swap the flow texture when the scrubber crosses into a new forcing timestep.

Tuning for a projector: particle count 60k to 120k, measured not guessed. Trails in `--graticule` at low alpha. If a viewer notices the flow before the slick, turn it down. Speed scale exaggerated deliberately, with the true factor in the provenance chip.

Acceptance test: with all overlays hidden, the map alone shows eddies and coastal shear matching a matplotlib quiver plot of the same NetCDF timestep. If not, the shader has a bug, most likely a texture flip or a normalisation error.

### Layer 2: the rewind, this is the demo

A single play button on the origin view runs a choreographed sequence backwards from acquisition. Implement as an explicit timeline in `frontend/src/sequence/rewind.ts` with named beats and eased transitions, durations in a config object so you can retime during rehearsal.

| Beat | Duration | What happens |
|---|---|---|
| 0. Hold | 3 s | SAR scene, slick in `--oil`, ambient flow underneath. Title chip: scene id and acquisition time. |
| 1. Dissolve | 3 s | The slick polygon dissolves into its seeded particles, same footprint, so the eye reads it as the same object. |
| 2. Rewind | 12 s | Time runs backwards. Particles advect backwards along the real ensemble tracks, spreading as members diverge. Clock counts backwards in UTC. Spaghetti fades in faintly behind. |
| 3. Bloom | 4 s | Particles fade, the probability field blooms in their place. Caption: not a point, a probability over space and time. |
| 4. Traffic | 6 s | Every AIS track in the window draws on with a TripsLayer trail, all in `--muted`. The screen deliberately clutters. Counter reads the vessel count. |
| 5. Elimination | 8 s | Vessels grey to `--cleared` and drop out in waves grouped by rule, the rule name appearing as each wave clears, counter ticking down. This is the PS requirement made visible. Give it real time. |
| 6. Dark gap | 5 s | Survivors thin. The rank 1 vessel's dark period renders as a dashed segment with its envelope expanding as a translucent cone over the probability cloud. |
| 6b. Radar | 4 s | **NEW.** The unmatched `ShipTarget` fades in inside the envelope in `--radar`, with a one line caption naming the scene it came from. This is the beat that closes the argument. |
| 7. Verdict | 4 s | Camera eases to the overlap. Suspect panel slides in with factor bars animating from zero, verdict chip appearing last. Dossier button pulses once. |

Rules:
- **Scrubbable and interruptible.** Any click pauses it and hands control back. A sequence that traps the presenter is worse than no sequence.
- Every beat reachable directly from the normal UI. The sequence is a guided path through the real product, never a separate mode with fake state.
- Captions in IBM Plex Sans Condensed, lower left, one line, sentence case, stating facts rather than selling.
- Keyboard shortcut to jump to any beat by number. During Q&A you will want beat 5 or 6b instantly.

### Layer 3: the space time prism

deck.gl in 3D with the vertical axis as **time**, not elevation.

- Ground plane at the origin window's earliest time, camera pitched around 50 degrees.
- Each vessel track a 3D polyline rising through the cube, PathLayer with z from timestamp.
- The origin field as stacked translucent slices forming a lens shaped volume.
- The culprit's track visibly passes **through** the volume. Innocents pass beside or above. `--suspect` and `--muted`.
- Dark gaps as gaps in the polyline with the envelope as a widening cone.

Label the vertical axis in UTC with at least three ticks. Provide a one key toggle back to 2D. Build after the rewind works. Cuttable; the rewind is not.

### Layer 4: motion in the panels

- Suspect factor bars animate from zero on expand, 400 ms, ease out.
- Elimination log rows enter with a short fade only. It should look like a record filling up, not a feed.
- Headline counters count up over 300 ms, no longer.
- Nothing loops idly.

### Performance and projector reality

- Target 60 fps at 1920x1080. Measure with the deck.gl stats overlay, keep a dev flag for frame time.
- Test on the actual presenting laptop, on battery, with an external display attached.
- Projectors crush contrast and thin lines. Line widths at least 2 px, treat anything under 30 percent alpha as invisible, check the palette on a real projector. Prefer raising line weight over saturation.
- Precompute everything the sequence needs into `backend/data/precomputed/hero_sequence.json`, loaded once at startup. No network, no worker jobs, no database queries during the animation.
- Respect `prefers-reduced-motion` by disabling ambient flow and shortening transitions, while keeping the rewind available on explicit click.

### The fallback you must build

Record a clean screen capture of the full rewind and the space time view as an MP4, commit it to the repo, keep it on the presenting laptop and in the slide deck. Build it the night before, not the morning of.

### Acceptance criteria

1. Ambient flow visually matches a matplotlib quiver plot of the same NetCDF timestep.
2. The rewind runs start to finish at 60 fps with no network access.
3. The sequence pauses, scrubs and resumes at any point, every beat keyboard reachable.
4. Particle positions during the rewind are the actual ensemble particle positions, verified in a test against the OpenDrift output arrays.
5. Every animated layer carries a provenance chip.
6. The MP4 fallback exists and plays.

---

## 17. Validation

Three independent validation tracks. They answer different questions and you need all three.

### 17.1 Internal consistency, the synthetic harness

`validation/harness.py`:

1. Generate 50 synthetic incidents from `demo.yaml` with varied lane density, dark gap presence, backward horizon and wind conditions, each with a known culprit MMSI.
2. Run the full pipeline from stage 5 onward on each.
3. Report **rank-1 accuracy**, **rank-3 accuracy**, mean rank of the true culprit, and a breakdown by traffic density.
4. Run three ablations:
   - **A:** `F2` (dark overlap) zeroed.
   - **B:** `F1` replaced by distance to the field centroid.
   - **C:** `F8` (radar confirmed) zeroed.

Ablations A and B are the two strongest numbers in the deck because they prove the two headline USP claims quantitatively. C proves the third.

Print the table to stdout and write it to `backend/data/processed/validation.md`. State plainly in the output that this measures internal consistency of the scoring model, not real world accuracy, and that validation against a documented prosecuted incident is the next step.

### 17.2 External agreement on detection, Cerulean

`validation/cerulean_client.py` and `validation/cerulean_agreement.py`. **Validation only. Never imported by `services/core`.**

The Cerulean public read API is an OGC API Features service served by `tipg` at `api.cerulean.skytruth.org`, and the tipg service does not require the Bearer key that the other cerulean-cloud services need. The repository is Apache-2.0.

1. Enumerate `/collections` first and record the actual collection names. Do not hardcode names guessed from documentation.
2. Query items with `bbox` and `datetime` filters, requesting GeoJSON.
3. Cache every response to `backend/data/cerulean/` with a hash in the manifest. After the first fetch, the harness runs offline.
4. Filter to records where the validation and human confidence fields indicate expert review, so you compare against reviewed polygons rather than raw model output.
5. For each shared Sentinel-1 scene id, download the GRD from ASF, run DRISHTA detection, and compute IoU against the Cerulean polygon.
6. Write an agreement table into `validation.md`.

Report as **agreement with an independent production system**, never as accuracy. Cerulean is another model with human review on some records, not ground truth. State the operating point difference: their production model runs on Sentinel-1 VV scaled to 80 m resolution with 512x512 tiles for global throughput; you run at full GRD resolution on a single scene.

Second use, higher value: pull records where their source category is **Dark**, meaning their vessel association could not resolve a broadcasting source, and run DRISHTA's stages 5 through 8 on one. Their vessel association considers only long linear detections and nearby broadcasting vessels, and their AIS carries a delay of up to 72 hours, so Dark records are exactly the gap DRISHTA targets. Resolving one is the strongest single result available to this project. Attempt it once P8 works.

Credit SkyTruth on the validation page and in the dossier provenance section.

### 17.3 Physical validation of the drift engine, drifters

`validation/drifter.py`. This is the only component where real ground truth exists, so use it.

1. Pull Global Drifter Program trajectories intersecting a region and period for which you already hold forcing data.
2. Take a drifter position at time `t1`. Run the backward ensemble from it with a 24 to 48 hour horizon.
3. Check whether the drifter's actual known position at `t0` falls inside the resulting probability field, and at what probability quantile.
4. Report containment rate across N drifter segments, and the median quantile of the true position.

This directly answers "your hindcast is unvalidated" with a real number. There is Indian precedent for the method: INCOIS and the Indian Coast Guard conducted a Surface Velocity Program drifter experiment at Mumbai High to evaluate their operational oil spill trajectory model. Cite it.

Note honestly that a drifter is not oil: no weathering, no wind drift factor uncertainty from surface film. Report it as validation of the advection and diffusion core, not of the oil model.

---

## 18. Accumulating outputs

Two tables that grow across runs, independent of any single case. They are cheap because every stage already computes their inputs.

`ledger/dark.py`, table `dark_period_ledger`: one row per `DarkGap` ever detected. MMSI, start, end, duration, entry point, exit point, resumed course, scene id, and whether an unmatched `ShipTarget` fell inside the envelope. Independent of whether oil was involved.

`ledger/completeness.py`, table `ais_completeness`: one row per processed scene. Scene id, acquisition time, footprint, count of `ShipTarget` records, count matched, count unmatched, size distribution of unmatched targets.

Expose both as read only endpoints and one plain table view in the frontend. Do not build analytics on top of them. The value is that they exist and accumulate.

State in the README what they are for, in one sentence each, and do not editorialise beyond that: the dark period ledger records AIS denial behaviour over time, and the completeness table measures, per scene, how much of the AIS picture the radar image does not corroborate.

---

## 19. Build order and priority

Each phase has an acceptance test that must pass before moving on.

### P-1: deck assets, do this first

No infrastructure. Throwaway scripts in `deck/scripts/`, images to `deck/figures/`. Pure Python and matplotlib. No React, no database, no Docker, no FastAPI. Target one to two days.

| Image | How | Acceptance |
|---|---|---|
| 1. Slick on SAR | One Zenodo image, render dB to grayscale, overlay the provided ground truth mask in `--oil`. Your detector does not need to work yet. | A publishable figure |
| 2. **Origin probability field** | OpenDrift OpenOil, 8 backward members, seed inside that polygon, dump particle positions, bin to a grid, plot as a heatmap with three time slices side by side. | **The money image. Protect this one above all others.** If nothing else in P-1 gets done, this must. |
| 3. AIS over the field | 12 synthetic tracks, 1 culprit, 3 hard negatives, plotted over image 2, culprit's dark gap dashed with a widening envelope polygon. | Culprit visibly distinguishable |
| 4. Scoring table | Plain terminal table: MMSI, total, five factor columns, rank. Below it the elimination list with a written reason per vessel. Screenshot the terminal. | Terminal output reads as real in a way a mockup never does |

Do not let P-1 become the real pipeline. Throw the scripts away after the deck ships.

### P0 onward: the real build

| Phase | Deliverable | Acceptance test |
|---|---|---|
| P0 | Repo, Docker Compose (Postgres+PostGIS+Timescale only), backend venv, Makefile targets | `make up` then `make test` passes on an empty suite |
| P1 | Schemas in `schemas.py` | Contract tests: factors sum to total, JSON round trips, all four rules in section 4 |
| P2 | Detection service: sensor adapter, render, tile, infer, stitch, polygonize | Given a GeoTIFF, returns a GeoJSON FeatureCollection of oil polygons with correct geographic coordinates |
| P3 | `eval.py` per class IoU on both corpora | Table printed with a real number attached to the oil class, on Zenodo and on the five class set |
| P3a | Cerulean agreement harness | Agreement table for N scenes written to `validation.md`, cached offline |
| P4 | Wind gate | Every detection carries a verdict and a reason. Measured FP reduction on the curated set |
| P4a | Optical corroboration | Three states emitted correctly, including `no_coverage` |
| P5 | Characterisation | `SlickFeatures` populated, age band with reasoning |
| P6 | Drift kernel protocol, backward ensemble, field | NetCDF written, sums to 1, real time dimension, seed and kernel recorded. Null kernel runs end to end. |
| P6a | Drifter validation | Containment rate reported across N drifter segments |
| P7 | AIS ingest, synthetic generator, tracks, dark gaps, integrity flags | Culprit plus four hard negatives generated, dark gaps detected with envelopes, F7 flags fire on injected anomalies |
| P7a | **SAR ship target extraction and radar cross check** | Unmatched targets identified in a scene, matched targets correctly associated to AIS |
| P8 | Scoring engine, elimination log, verdict classes | Culprit is rank 1 on the demo scenario, all four hard negatives below it, every eliminated vessel has a reason, all three verdict classes reachable from crafted fixtures |
| P8a | MARPOL layer and infrastructure flag | Assessment emitted with band not scalar, assumptions listed, flag raised on a crafted overlap |
| P9 | Frontend shell, map, layers, **time scrubber first** | Scrubbing updates field, tracks and ranking together at interactive frame rate |
| P9a | Ambient flow shader | Visual structure matches a matplotlib quiver plot of the same timestep |
| P9b | Rewind sequence | All 8 beats at 60 fps offline, pausable, scrubbable, keyboard reachable |
| P10 | Dossier PDF with provenance and BSA s.63 page | Generates with a full provenance page and a populated certificate |
| P11 | Validation harness, 50 incidents plus 3 ablations | Table written to `validation.md` |
| P11a | Cerulean Dark case attempt | One Dark record run through stages 5 to 8, result documented honestly whatever it is |
| P12 | Dark period ledger and completeness table | Both accumulate across two runs, exposed read only |
| P13 | Space time prism | Culprit track visibly passes through the probability volume, time axis labelled in UTC |
| P14 | Second drift kernel demo scenario | One config diff swaps OpenOil for Leeway and the full pipeline runs |
| P15 | Forward forecast view | Normalised forward field rendered beside the origin field on one time axis, labelled as a forecast, refused by the scoring engine. Built ahead of P13 and P14 because the three stage sequence needs it: stage 2 is where the drift picture is made, and half a drift picture is a weaker argument than a whole one. |
| P16 | Demo hardening: precompute bundle, seed script, offline mode, MP4 fallback, rehearsal on the presenting laptop | Full demo runs with the network disabled, MP4 plays |

**If time runs short, cut in this order:** P15, then P14, then P13, then P12, then dossier styling (keep the content), then P3a, then P6a, then P3 breadth (fewer images, keep the number honest), then ensemble size (30 down to 8).

**Never cut:** the wind gate, dark gap detection, the radar cross check (P7a), the elimination log, the verdict classes, the ablation numbers, the rewind sequence, and the MP4 fallback. The first five are the differentiation and the last two are how it reaches the room.

---

## 20. Precomputation and demo safety

`backend/scripts/seed_demo.py` produces into `backend/data/precomputed/`:

- Two fully preprocessed Sentinel-1 scenes, terrain corrected and rendered.
- Cached wind and current NetCDF subsets for the demo region and window.
- The full 30 member ensemble field for the hero scene.
- The generated synthetic AIS for the hero scenario.
- Extracted `ShipTarget` records including the unmatched one.
- The generated dossier PDF.
- `hero_sequence.json`: per frame ensemble particle positions, probability field slices, AIS track vertices, unmatched target positions, elimination waves in order, and beat timings. The animation must never query the database or a worker while playing.
- The MP4 screen capture.

The application starts in `DEMO_MODE=offline` and serves these without touching the network or running the heavy ensemble. A separate visible button runs a **reduced live** hindcast at 8 members with a shorter horizon, so you can prove it genuinely computes rather than replaying a video. Rehearse both paths.

---

## 21. Testing requirements

- Contract tests on every schema, including the four rules in section 4.
- A golden file test on the stitching logic, so a refactor cannot silently reintroduce grid seams.
- A test that the origin field normalises to 1 and retains its time dimension.
- **A test that a vessel with a dark gap overlapping the field scores strictly higher than an identical vessel without one.** This guards the central claim of the project.
- **A test that a vessel with a dark gap plus a corresponding unmatched radar target scores strictly higher than an identical vessel with the dark gap alone.** This guards F8 and separates it from merely rewarding darkness.
- A test that every eliminated vessel has a non empty reason string.
- A test that all three verdict classes are reachable from crafted fixtures, and that `DARK_CONFIRMED` requires both conditions.
- **A test that no module under `services/` imports anything from `validation/cerulean_client.py`.** This enforces non negotiable 5.
- A test that the null drift kernel produces a field on which every downstream stage runs unchanged.
- A test that `MarpolAssessment.est_discharge_l_per_nm` is a band and never a scalar.
- A test that the rewind sequence's particle frames match the OpenDrift output arrays for a sampled set of frames.
- A test that `hero_sequence.json` is self contained: loading it with the database stopped still renders every beat.
- End to end smoke test on committed fixtures, run in CI and by `make test`.

---

## 22. Things a jury will attack, and what the code must show

Build so each is answered by clicking something, not by talking.

| Objection | Answer | What you click |
|---|---|---|
| "This is an off the shelf model plus OpenDrift." | The contribution is stages 3, 6, 6b and 7, and here are four numbers. | Gate FP reduction, ablations A, B and C |
| "Your attribution is unvalidated." | Internally, across 50 incidents. The drift engine separately, against real drifters. Neither is real world attribution accuracy and we say so. | `validation.md`, drifter containment rate |
| "Your AIS is synthetic." | The PS permits it, in these words. Only the incident is invented, and the schema is the MarineCadastre format the PS names. | The PS quote in `demo.yaml`, the schema |
| "You could accuse an innocent ship." | The system never accuses. Ranked with a printed factor breakdown, vessel type only downweights, and the cover states it is evidence for a human investigator. | Dossier cover, factor bars, `scoring.yaml` on screen |
| "AIS can be spoofed, not just switched off." | Factor F7. And independently, radar saw a hull where AIS reported nothing. | F7 breakdown, the unmatched target |
| "Unmatched radar target does not mean guilty." | Correct. We report count, size and position, with the stated limitations, and it is one factor among eight. | The radar caveat page in the dossier |
| "48 hour backward drift is too uncertain." | That is the design premise. Uncertainty is the scoring surface. | Drag the scrubber backwards |
| "How is this different from Cerulean?" | It has no drift model, so it never computes an origin. It evaluates broadcasting vessels only, with AIS delayed up to 72 hours, and files unresolved cases as Dark. Resolving those is what we built. | Beat 6b, and the P11a result |
| "What if it was a platform, not a ship?" | Flagged explicitly, and we do not blame a vessel by default. | The infrastructure flag |
| "What happens after your screen?" | A hash sealed dossier with a pre filled Section 63 certificate. | Download the PDF, open the provenance page |
| "What else could this do?" | The drift kernel is a plug in. Same engine, different kernel. | Run the P14 scenario |

---

## 23. First tasks, in order

1. **Start the Zenodo Part I download now.** It is roughly 40.7 GB and it is the longest lead item in the project.
2. **Register the three accounts** in section 4A and submit the ERA5 request for the demo region today. It queues.
3. **Build P-1 image 2**, the origin probability field. One OpenDrift script, no infrastructure. This is the image the deck is built around and it is the fastest proof to yourself that the core idea works.
4. **Finish P-1**, ship the deck.
5. Scaffold P0 and P1. Do not write pipeline code before the schemas exist.
6. Download the model, confirm the actual file format on the HuggingFace Files tab, load it, and run it on Zenodo samples through render steps 3 to 5. Confirm sane masks. **This gate blocks everything downstream.**
7. Write `eval.py` and produce the honest per class IoU numbers on both corpora.

Report back after task 3 with the field image, after task 6 with the observed masks, and after task 7 with the IoU tables, before proceeding to P4.
