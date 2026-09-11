# Build status

Phase by phase, what is built, what is partial and what is not started. Phases are from [PLAN.md](../PLAN.md) section 19, which is the source of truth for the phase order itself.

[← Back to the README](../README.md)

---

**Legend.** `[x]` built and tested, `[~]` partial with the gap named, `[ ]` not started or blocked.

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


## What the open items are blocked on

| Item | Blocked on |
|---|---|
| P3 per class IoU | The labeled evaluation corpora in PLAN.md section 4A. `services/detection/eval.py` raises rather than reporting a substitute number |
| P3a, P11a Cerulean | No scenes pulled yet. The client and the agreement metric are written and cache offline |
| P6a drifter validation | No Global Drifter Program trajectories pulled yet. `backend/validation/drifter.py` is written |
| P9a, P9b, P13 visual layers | Not started. The console MVP works without them, see [ARCHITECTURE.md](ARCHITECTURE.md#the-operator-console) |

None of these block running the system. See [SETUP.md](SETUP.md).
