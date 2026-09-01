"""FastAPI orchestration for core. See PLAN.md section 15: the app must
start in DEMO_MODE=offline and serve the precomputed demo bundle with no
network access and no live pipeline run.

Only the offline demo bundle is wired up so far. A "reduced live" hindcast
endpoint (PLAN.md section 15) is a later addition, not part of this pass.
"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(title="slicktrace-core")

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
    """The case dossier PDF (PLAN.md section 11): cover, scene,
    detection, characterisation, origin field, suspects, elimination
    log and a provenance page with file hashes, the git commit and the
    scoring config verbatim. Built offline by scripts/seed_demo.py from
    the same bundle GET /api/demo serves."""
    if not os.path.exists(DOSSIER_PATH):
        raise HTTPException(
            status_code=404,
            detail="Dossier not built yet. Run: make seed-demo",
        )
    return FileResponse(DOSSIER_PATH, media_type="application/pdf", filename="slicktrace_case_dossier.pdf")
