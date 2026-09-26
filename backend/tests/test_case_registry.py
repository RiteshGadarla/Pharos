"""The case study registry, config/cases.yaml, and the index built from it.

Two properties matter more than the rest. The default case is still the
hero case the deck and the single-bundle console were built on. And a
case's outcome is never typed into config: the index's verdict, gate
verdict, wind and counts are read back from the bundle the engine wrote,
so a test here feeds a bundle that disagrees with the case's design
intent and checks that the bundle wins.
"""

import os
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

import case_registry  # noqa: E402

EM_DASH = chr(0x2014)


@pytest.fixture(scope="module")
def registry():
    return case_registry.load_registry()


def test_four_cases_with_the_hero_case_as_default(registry):
    ids = case_registry.case_ids(registry)
    assert len(ids) == 4
    assert registry["default_case"] == "arabian-sea-discharge"
    hero = case_registry.get_case(registry, "arabian-sea-discharge")
    # deck/scripts/make_figures.py and the dossier key off this id.
    assert hero["case_id"] == "PHAROS-DEMO-0001"
    assert hero["scene"] == "committed"


def test_the_cases_cover_every_verdict_class_by_design(registry):
    intended = {c.get("intended_verdict") for c in registry["cases"]}
    assert {"ATTRIBUTED", "RANKED", "DARK_CONFIRMED"} <= intended


def test_ids_and_case_ids_are_unique_and_path_safe(registry):
    ids = case_registry.case_ids(registry)
    assert len(set(ids)) == len(ids)
    assert all(case_registry.CASE_ID_PATTERN.match(i) for i in ids)
    case_ids = [c["case_id"] for c in registry["cases"]]
    assert len(set(case_ids)) == len(case_ids)


def test_user_facing_text_has_no_em_dashes(registry):
    with open(os.path.join(BACKEND, case_registry.CASES_CONFIG), encoding="utf-8") as f:
        assert EM_DASH not in f.read()


def test_default_case_keeps_the_original_fixture_paths(registry):
    hero = case_registry.get_case(registry, registry["default_case"])
    paths = case_registry.paths_for(registry, hero)
    assert paths.scene == "data/fixtures/synthetic_scene.tif"
    assert paths.wind == "data/fixtures/synthetic_wind_offshore.nc"
    assert paths.currents == "data/fixtures/synthetic_currents.nc"
    other = next(c for c in registry["cases"] if c["id"] != registry["default_case"])
    other_paths = case_registry.paths_for(registry, other)
    assert other["id"] in other_paths.wind and other_paths.wind != paths.wind


def test_every_case_parameter_block_is_accepted_by_its_generator(registry):
    import synthetic_metocean as met

    for case in registry["cases"]:
        forcing = case.get("forcing", {})
        met._from_dict(met.WindRegime, forcing.get("wind"))
        met._from_dict(met.CurrentRegime, forcing.get("currents"))


def test_unknown_case_is_refused(registry):
    with pytest.raises(KeyError, match="Valid"):
        case_registry.get_case(registry, "no-such-case")


def test_index_entry_reads_the_outcome_from_the_bundle_not_the_config(registry):
    import seed_demo

    case = case_registry.get_case(registry, "arabian-sea-discharge")
    bundle = {
        "case_id": "PHAROS-DEMO-0001",
        "primary_detection_id": "d1",
        "detections": [
            {"detection_id": "d1", "gate": {"wind_speed_ms": 3.04, "verdict": "downgrade"}},
            {"detection_id": "d2", "gate": {"wind_speed_ms": 12.0, "verdict": "suppress"}},
        ],
        "scene": {"acquired_at": "2026-01-15T02:30:00"},
        # Deliberately not the case's intended verdict.
        "verdict": {"verdict": "RANKED"},
        "vessels": [{}] * 7,
        "suspects": [{}] * 2,
        "eliminations": [{}] * 5,
        "culprit_mmsi": None,
    }
    entry = seed_demo.case_summary(registry, case, bundle)
    assert entry["verdict"] == "RANKED" != case["intended_verdict"]
    assert entry["gate_verdict"] == "downgrade"
    assert entry["wind_ms"] == 3.0
    assert (entry["n_vessels"], entry["n_suspects"], entry["n_eliminated"]) == (7, 2, 5)
    assert entry["culprit_mmsi"] is None
    assert "1 of 2 detections suppressed" in entry["wind_summary"]
    assert entry["bundle_url"] == "/data/cases/arabian-sea-discharge/demo_bundle.json"
    assert EM_DASH not in entry["wind_summary"] + entry["subtitle"]


def test_primary_detection_is_the_largest_the_gate_kept():
    import seed_demo
    from services.core.schemas import Detection, GateResult

    def det(i, area):
        geom = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}
        return Detection(detection_id=i, scene_id="s", class_name="oil", geometry=geom, mean_class_prob=0.9, pixel_area=area)

    dets = [det("big", 2000), det("mid", 1500)]
    gates = {
        "big": GateResult(detection_id="big", wind_speed_ms=11.6, verdict="suppress", reason="high"),
        "mid": GateResult(detection_id="mid", wind_speed_ms=10.3, verdict="accept", reason="ok"),
    }
    assert seed_demo.select_primary(dets, gates).detection_id == "mid"
    all_suppressed = {k: g.model_copy(update={"verdict": "suppress"}) for k, g in gates.items()}
    assert seed_demo.select_primary(dets, all_suppressed).detection_id == "big"
