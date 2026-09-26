"""FastAPI orchestration for core. See PLAN.md section 20: the app must
start in DEMO_MODE=offline and serve the precomputed demo bundle with no
network access and no live pipeline run.

The offline demo bundle, the scene basemap, the dossier and the two
accumulating ledgers (PLAN.md section 18) are wired up, for the default
case and, with ?case=<id>, for every case study in config/cases.yaml
(GET /api/cases lists them). A "reduced live"
hindcast endpoint (PLAN.md section 20) is a later addition, not part of
this pass.
"""

from __future__ import annotations

import json
import os
import re

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from services.core.inspect import router as inspect_router
from services.core.ledger import completeness as completeness_ledger
from services.core.ledger import dark as dark_ledger

app = FastAPI(title="pharos-core")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "POST"],
    allow_headers=["*"],
)

app.include_router(inspect_router)

DEMO_BUNDLE_PATH = "data/precomputed/demo_bundle.json"
DOSSIER_PATH = "data/precomputed/case_dossier.pdf"
SCENE_PREVIEW_PATH = "data/precomputed/scene_preview.png"

# The case study index and per-case outputs, written by
# scripts/seed_demo.py from config/cases.yaml. See PLAN.md section 20.
CASES_INDEX_PATH = "data/precomputed/cases.json"
CASES_DIR = "data/precomputed/cases"
BUILD_HINT = "Run: make seed-demo (every case) or make seed-case CASE=<id> (one case)"

# A case id is lowercase words joined by hyphens. Checked in addition to
# membership of the index, so nothing that reaches a filesystem path was
# ever free text from a query string.
_CASE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _read_cases_index() -> dict | None:
    if not os.path.exists(CASES_INDEX_PATH):
        return None
    with open(CASES_INDEX_PATH) as f:
        return json.load(f)


def _case_file(case: str | None, filename: str, legacy_path: str) -> str:
    """Where one case's output lives, or the single-bundle path when no
    case is asked for.

    The id is looked up in the index and the path is built from the
    index's own copy of it, never from the query string, and only after
    it has matched the id pattern. An id that is not in the index is a
    404 that names every valid id and how to build them.
    """
    if case is None:
        return legacy_path
    index = _read_cases_index()
    valid = [c.get("id") for c in (index or {}).get("cases", []) if isinstance(c.get("id"), str)]
    match = next((cid for cid in valid if cid == case), None)
    if match is None or not _CASE_ID.match(match):
        listing = ", ".join(valid) if valid else "none built yet"
        raise HTTPException(
            status_code=404,
            detail=f"Unknown case {case!r}. Valid case ids: {listing}. {BUILD_HINT}",
        )
    return os.path.join(CASES_DIR, match, filename)


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


@app.get("/api/cases")
def cases_index() -> dict:
    """The case study index: one entry per case with its title, verdict,
    gate verdict, wind and counts, all read back from the bundles the
    engine produced, plus the URLs of each case's bundle, basemap and
    dossier. Built offline by scripts/seed_demo.py."""
    index = _read_cases_index()
    if index is None:
        raise HTTPException(status_code=404, detail=f"Case index not built yet. {BUILD_HINT}")
    return index


@app.get("/api/demo")
def demo_bundle(case: str | None = Query(default=None)) -> dict:
    """The self-contained demo bundle the frontend loads: scene,
    detections, gate verdicts, slick features, origin field, AIS tracks,
    eliminations and suspect scores. Built offline by
    scripts/seed_demo.py, never computed live.

    With ?case=<id>, that case study's bundle. Without it, the default
    case, exactly as before the case registry existed."""
    path = _case_file(case, "demo_bundle.json", DEMO_BUNDLE_PATH)
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail=f"Demo bundle not built yet. {BUILD_HINT}" if case else "Demo bundle not built yet. Run: make seed-demo",
        )
    with open(path) as f:
        return json.load(f)


@app.api_route("/api/scene_preview.png", methods=["GET", "HEAD"])
def scene_preview(case: str | None = Query(default=None)) -> FileResponse:
    """The SAR scene warped to EPSG:4326 and stretched for display, used
    as the map basemap so detections sit on the image they came from.
    Its lon/lat bounds are in the demo bundle under scene.preview.
    Display product only, see services/core/preview.py. ?case=<id> picks
    a case study's scene."""
    path = _case_file(case, "scene_preview.png", SCENE_PREVIEW_PATH)
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail=f"Scene preview not built yet. {BUILD_HINT}" if case else "Scene preview not built yet. Run: make seed-demo",
        )
    return FileResponse(path, media_type="image/png")


@app.api_route("/api/dossier", methods=["GET", "HEAD"])
def dossier(case: str | None = Query(default=None)) -> FileResponse:
    """The case dossier PDF (PLAN.md section 15): cover with the verdict
    class, scene, detection with optical corroboration, characterisation,
    origin field, radar cross check, suspects, elimination log, MARPOL
    assessment, infrastructure flag, a provenance page with file hashes,
    the git commit and the scoring config verbatim, and a pre-filled
    Bharatiya Sakshya Adhiniyam s.63 Part A certificate. Built offline by
    scripts/seed_demo.py from the same bundle GET /api/demo serves.
    ?case=<id> picks a case study's dossier."""
    path = _case_file(case, "case_dossier.pdf", DOSSIER_PATH)
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail=f"Dossier not built yet. {BUILD_HINT}" if case else "Dossier not built yet. Run: make seed-demo",
        )
    filename = f"pharos_case_dossier_{case}.pdf" if case else "pharos_case_dossier.pdf"
    return FileResponse(path, media_type="application/pdf", filename=filename)
