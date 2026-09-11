# Validation

Three independent tracks, answering three different questions. All three are needed, and none of them is an accuracy claim about the system as a whole.

[← Back to the README](../README.md)

---


They answer different questions and all three are needed.

1. **Internal consistency** (`backend/validation/harness.py`, run with `make validate`). 50 synthetic incidents with a known injected culprit, stratified across field variant, traffic density and dark gap presence, plus three ablations: F2 zeroed, F1 replaced by distance to the field's centroid, and F8 zeroed. Written to `backend/data/processed/validation.md`. This measures internal consistency of the scoring model, not real world accuracy, and the report says so in its own text.
2. **External agreement on detection** (`backend/validation/cerulean_agreement.py`). IoU against Cerulean's reviewed slick polygons, reported as agreement with an independent production system and never as accuracy. Written; no scenes pulled yet.
3. **Physical validation of the drift engine** (`backend/validation/drifter.py`). Backward ensembles run from real NOAA Global Drifter Program positions, reporting containment rate and the quantile at which the true prior position landed. This is the only component where real ground truth exists. A drifter is not oil, so it validates the advection and diffusion core, not the oil model on top. Written; no trajectories pulled yet.

**Cerulean is never in the runtime path.** It lives only under `backend/validation/`, and `backend/tests/test_no_cerulean_in_services.py` enforces that by scanning the source tree.


## Why three and not one

| Track | Question it answers | Ground truth exists? |
|---|---|---|
| Internal consistency | Does the scoring model separate a known injected culprit from hard negatives, and which factors carry that separation? | Yes, but synthetic and self generated. Proves consistency, not accuracy |
| Cerulean agreement | Does the detector outline the same water an independent production system outlines? | No. Cerulean is another model with partial human review, so this is agreement, never accuracy |
| Drifter validation | Does the backward ensemble contain where the object actually was? | Yes, real and external. The only place in the system where it does |

The ablations in track 1 exist because a scoring model that ranks the culprit first can still be doing it for the wrong reason. Zeroing F2, replacing F1 with distance to the field's centroid, and zeroing F8 each test whether a specific claim in the evidence model is load bearing or decorative. See [EVIDENCE_MODEL.md](EVIDENCE_MODEL.md).

## Running it

```bash
make validate    # 50 incidents plus three ablations -> backend/data/processed/validation.md
```

The report states in its own text that it measures internal consistency rather than real world accuracy. That sentence is not a disclaimer bolted on at the end; it is what the number means.
