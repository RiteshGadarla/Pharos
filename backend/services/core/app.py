"""FastAPI orchestration for core. See PLAN.md section 20: the app must
start in DEMO_MODE=offline and serve the precomputed demo bundle with no
network access and no live pipeline run.

The offline demo bundle, the scene basemap, the dossier and the two
accumulating ledgers (PLAN.md section 18) are wired up. A "reduced live"
hindcast endpoint (PLAN.md section 20) is a later addition, not part of
this pass.
"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from services.core.ledger import completeness as completeness_ledger
from services.core.ledger import dark as dark_ledger

app = FastAPI(title="drishta-core")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD"],
    allow_headers=["*"],
)

DEMO_BUNDLE_PATH = "data/precomputed/demo_bundle.json"
DOSSIER_PATH = "data/precomputed/case_dossier.pdf"
SCENE_PREVIEW_PATH = "data/precomputed/scene_preview.png"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "core"}


@app.get("/api/ledger/dark")
def dark_period_ledger() -> dict:
    """The dark period ledger (PLAN.md section 18): one row per DarkGap
    ever detected, accumulating across runs, independent of whether oil
    was involved in any given case.

    Read only, and deliberately without analytics on top. It records AIS
    denial behaviour over time; that it exists and accumulates is the
    whole value."""
    rows = dark_ledger.read_rows()
    return {
        "description": "One row per dark period ever detected. Records AIS denial behaviour over time.",
        "n_rows": len(rows),
        "rows": rows,
    }


@app.get("/api/ledger/completeness")
def ais_completeness_ledger() -> dict:
    """The AIS completeness record (PLAN.md section 18): one row per
    processed scene, measuring how much of the AIS picture the radar
    image does not corroborate.

    Read only, no analytics. A single scene's unmatched count means
    little; accumulated over a region and a year it is a measurement of
    AIS coverage that nobody currently has."""
    rows = completeness_ledger.read_rows()
    return {
        "description": (
            "One row per processed scene. Measures, per scene, how much of the AIS picture "
            "the radar image does not corroborate."
        ),
        "n_rows": len(rows),
        "rows": rows,
    }


@app.get("/api/demo")
def demo_bundle() -> dict:
    """The single self-contained demo bundle the frontend loads at
    startup: scene, detections, gate verdicts, slick features, origin
    field, AIS tracks, eliminations and suspect scores. Built offline by
    scripts/seed_demo.py, never computed live."""
    if not os.path.exists(DEMO_BUNDLE_PATH):
        raise HTTPException(
            status_code=404,
            detail="Demo bundle not built yet. Run: make seed-demo",
        )
    with open(DEMO_BUNDLE_PATH) as f:
        return json.load(f)


@app.api_route("/api/scene_preview.png", methods=["GET", "HEAD"])
def scene_preview() -> FileResponse:
    """The SAR scene warped to EPSG:4326 and stretched for display, used
    as the map basemap so detections sit on the image they came from.
    Its lon/lat bounds are in the demo bundle under scene.preview.
    Display product only, see services/core/preview.py."""
    if not os.path.exists(SCENE_PREVIEW_PATH):
        raise HTTPException(
            status_code=404,
            detail="Scene preview not built yet. Run: make seed-demo",
        )
    return FileResponse(SCENE_PREVIEW_PATH, media_type="image/png")


@app.api_route("/api/dossier", methods=["GET", "HEAD"])
def dossier() -> FileResponse:
    """The case dossier PDF (PLAN.md section 15): cover with the verdict
    class, scene, detection with optical corroboration, characterisation,
    origin field, radar cross check, suspects, elimination log, MARPOL
    assessment, infrastructure flag, a provenance page with file hashes,
    the git commit and the scoring config verbatim, and a pre-filled
    Bharatiya Sakshya Adhiniyam s.63 Part A certificate. Built offline by
    scripts/seed_demo.py from the same bundle GET /api/demo serves."""
    if not os.path.exists(DOSSIER_PATH):
        raise HTTPException(
            status_code=404,
            detail="Dossier not built yet. Run: make seed-demo",
        )
    return FileResponse(DOSSIER_PATH, media_type="application/pdf", filename="drishta_case_dossier.pdf")
