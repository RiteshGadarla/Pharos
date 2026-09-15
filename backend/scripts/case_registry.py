"""Reads config/cases.yaml and says where each case's inputs and outputs
live. Shared by make_synthetic_data.py (which builds each case's scene
and forcing) and seed_demo.py (which runs each case through the engine).

Paths are derived here and nowhere else, from a case id that has been
validated against the registry, so no caller joins free text into a
filesystem path.

The default case keeps the original fixture paths, so the tests, the
validation harness and the deck, which all read those paths, see the
same data the hero case is built from. Every other case gets its own
files beside them, suffixed with the case id, which the existing
.gitignore rules for data/fixtures/*.nc and *.tif already cover.
"""

from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass

import yaml

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_CONFIG = "config/cases.yaml"

COMMITTED_SCENE = "data/fixtures/synthetic_scene.tif"
DEFAULT_WIND = "data/fixtures/synthetic_wind_offshore.nc"
DEFAULT_CURRENTS = "data/fixtures/synthetic_currents.nc"

PRECOMPUTED_DIR = "data/precomputed"
CASES_INDEX = "data/precomputed/cases.json"

CASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REQUIRED_KEYS = ("id", "case_id", "title", "subtitle", "region", "acquired_at", "seed", "scene", "forcing", "ais")


@dataclass(frozen=True)
class CasePaths:
    scene: str
    wind: str
    currents: str
    out_dir: str
    bundle: str
    scene_preview: str
    dossier: str


def _path(rel: str) -> str:
    return os.path.join(BACKEND_DIR, rel)


def load_registry(path: str = CASES_CONFIG) -> dict:
    with open(_path(path) if not os.path.isabs(path) else path) as f:
        registry = yaml.safe_load(f)
    ids = []
    for case in registry.get("cases", []):
        missing = [k for k in REQUIRED_KEYS if k not in case]
        if missing:
            raise ValueError(f"case {case.get('id', '?')} is missing {', '.join(missing)}")
        if not CASE_ID_PATTERN.match(case["id"]):
            raise ValueError(f"case id {case['id']!r} must be lowercase words joined by hyphens")
        ids.append(case["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("case ids in config/cases.yaml must be unique")
    if registry.get("default_case") not in ids:
        raise ValueError("default_case must name one of the cases")
    return registry


def case_ids(registry: dict) -> list[str]:
    return [c["id"] for c in registry["cases"]]


def get_case(registry: dict, case_id: str) -> dict:
    for case in registry["cases"]:
        if case["id"] == case_id:
            return case
    raise KeyError(f"unknown case {case_id!r}. Valid: {', '.join(case_ids(registry))}")


def is_default(registry: dict, case: dict) -> bool:
    return case["id"] == registry["default_case"]


def acquired_at(case: dict) -> datetime.datetime:
    value = case["acquired_at"]
    if isinstance(value, datetime.datetime):
        return value.replace(tzinfo=None)
    return datetime.datetime.fromisoformat(str(value).replace("Z", "")).replace(tzinfo=None)


def paths_for(registry: dict, case: dict) -> CasePaths:
    cid = case["id"]
    assert CASE_ID_PATTERN.match(cid)
    default = is_default(registry, case)
    scene = COMMITTED_SCENE if case["scene"] == "committed" else f"data/fixtures/synthetic_scene__{cid}.tif"
    out_dir = f"{PRECOMPUTED_DIR}/cases/{cid}"
    return CasePaths(
        scene=scene,
        wind=DEFAULT_WIND if default else f"data/fixtures/synthetic_wind_offshore__{cid}.nc",
        currents=DEFAULT_CURRENTS if default else f"data/fixtures/synthetic_currents__{cid}.nc",
        out_dir=out_dir,
        bundle=f"{out_dir}/demo_bundle.json",
        scene_preview=f"{out_dir}/scene_preview.png",
        dossier=f"{out_dir}/case_dossier.pdf",
    )


def seeds(case: dict) -> dict[str, int]:
    """Every stochastic input of a case, derived from its one seed."""
    base = int(case["seed"])
    return {"ais": base, "wind": base + 1, "currents": base + 2, "background": base + 3}
