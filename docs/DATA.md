# Data provenance

What is real in this system, what is synthetic, and why each choice was made. This matters more than the feature list, which is why it is a document rather than a footnote.

[← Back to the README](../README.md)

---

## What is real and what is synthetic

This matters more than the feature list, so it is stated plainly rather than buried.

**Real:** the detection model (`sahilvishwa2108/oil-spill-deeplab`, loaded from local disk), the drift physics (OpenDrift OpenOil), the ensemble construction, the field binning and normalisation, the wind gate thresholds and their physical justification, every scoring factor, every elimination rule, the verdict logic, the MARPOL condition checks, the hashing and the certificate. The slick texture in the fixture scene is real Sentinel-1A oil spill backscatter and speckle, composited from a CC BY 4.0 dataset (Persian Gulf, not the Arabian Sea). See `backend/data/fixtures/real_oil_texture/ATTRIBUTION.md`.

**Synthetic:** the SAR scene's geolocation, acquisition time and surrounding sea; the wind and current forcing fields; the AIS traffic; the SAR ship targets. The three static geographic layers (coastline, MARPOL special areas, offshore installations) are generalised placeholders, and each file says so at the top of itself.

**Why the AIS is synthetic, and why that is allowed.** The problem statement says: *"Real AIS if available may be used else synthetic data can be prepared for the region of oil spill to demonstrate the functioning of the algorithm."* That sentence is recorded at the top of `backend/config/demo.yaml`. Permission is not an excuse to be sloppy: lane geometry, vessel type mix, speed distributions, ping intervals and dropout rates are meant to be fitted from real MarineCadastre statistics, the format authority the PS itself names, with only the incident injected. That fitting has not been done yet and the current distributions are documented placeholders. The database schema mirrors the MarineCadastre columns, so a real ICG or DGLL feed drops in with no code change.

**Not real anywhere:** an accuracy number for the detector. The HuggingFace model card's self reported 0.9668 F1 is not reproduced in the UI, the README, the dossier or any slide, because background pixels dominate this five class taxonomy and an aggregate figure says nothing about oil class performance. `eval.py` exists to produce the honest per class number and is blocked on the labeled datasets; until it runs, the dossier says the number is unavailable rather than substituting one.


## The staged sample scene

`backend/data/fixtures/synthetic_scene.tif` is committed to the repository, the one exception to the rule that generated fixtures stay out of git. It exists so a fresh clone has a SAR scene to process before generating anything.

Full provenance, including the licence of the real oil texture composited into it and the exact rebuild command, is in [backend/data/fixtures/SAMPLE_SCENE.md](../backend/data/fixtures/SAMPLE_SCENE.md).

## Everything else is generated locally

| Input | Source | Real? |
|---|---|---|
| SAR scene geometry and sea | `scripts/make_synthetic_data.py` | No |
| Oil slick texture inside that scene | Deep-SAR SOS dataset, CC BY 4.0, Persian Gulf | Yes, the backscatter and speckle |
| 10m wind, near shore and offshore | `scripts/make_synthetic_data.py` | No |
| Surface currents and SST | `scripts/make_synthetic_data.py` | No |
| Cached backward ensemble | `scripts/make_synthetic_data.py`, from the two above | The physics is real, the forcing is not |
| AIS traffic | `services/core/ais/synthetic.py`, in memory each run | No |
| SAR ship targets | `services/core/ais/synthetic.py` | No |
| Coastline, MARPOL areas, installations | Committed generalised placeholders | No, and each file says so at the top of itself |
| Segmentation model weights | `sahilvishwa2108/oil-spill-deeplab`, downloaded once | Yes |

Every generator is seeded from `backend/config/pipeline.yaml`, so rebuilding reproduces the same output rather than drawing a new sample.

## Swapping in real data

This is a path change, not a code change. The interfaces were built for it:

- **AIS.** The database schema mirrors the MarineCadastre columns, the format authority the problem statement names, so a real ICG or DGLL feed drops in with no code change.
- **Forcing.** Wind and currents are read through OpenDrift's CF-generic NetCDF readers, so real CMEMS and ERA5 files drop in where the fixtures sit.
- **SAR.** `services/detection/sensors.py` is a sensor adapter. Sentinel-1 is implemented; EOS-04 is a documented stub.
- **Static layers.** Replace the three placeholder GeoJSON files with Natural Earth or GSHHG coastline and a real offshore platform layer.

`backend/scripts/fetch_data.sh` records exactly what a real fetch has to do, including the manifest and hashing contract, so whoever picks it up is not reverse engineering the requirement from the plan. See PLAN.md section 4A.
