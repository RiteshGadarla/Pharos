"""The case study endpoints in services/core/app.py.

GET /api/cases serves the index scripts/seed_demo.py writes, and
/api/demo, /api/scene_preview.png and /api/dossier take ?case=<id>. With
no parameter each behaves exactly as it did before the registry existed.
An unknown id is a 404 that names the valid ids and the make target that
builds them, and no query string ever reaches a filesystem path: the path
is built from the index's own copy of the id.
"""

import json

import pytest
from fastapi.testclient import TestClient

from services.core import app as app_module

CASE_IDS = ["arabian-sea-discharge", "monsoon-high-wind"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    precomputed = tmp_path / "precomputed"
    cases_dir = precomputed / "cases"
    for cid in CASE_IDS:
        d = cases_dir / cid
        d.mkdir(parents=True)
        (d / "demo_bundle.json").write_text(json.dumps({"case_id": cid, "origin_field": {}, "scene": {}}))
        (d / "scene_preview.png").write_bytes(b"\x89PNG\r\n\x1a\n" + cid.encode())
        (d / "case_dossier.pdf").write_bytes(b"%PDF-1.4 " + cid.encode())
    (precomputed / "demo_bundle.json").write_text(json.dumps({"case_id": "legacy", "origin_field": {}, "scene": {}}))
    (precomputed / "scene_preview.png").write_bytes(b"\x89PNG\r\n\x1a\nlegacy")
    (precomputed / "case_dossier.pdf").write_bytes(b"%PDF-1.4 legacy")
    index = {
        "default_case": CASE_IDS[0],
        "generated_at": "2026-09-15T00:00:00+00:00",
        "cases": [{"id": cid, "bundle_url": f"/data/cases/{cid}/demo_bundle.json"} for cid in CASE_IDS],
    }
    (precomputed / "cases.json").write_text(json.dumps(index))

    monkeypatch.setattr(app_module, "DEMO_BUNDLE_PATH", str(precomputed / "demo_bundle.json"))
    monkeypatch.setattr(app_module, "SCENE_PREVIEW_PATH", str(precomputed / "scene_preview.png"))
    monkeypatch.setattr(app_module, "DOSSIER_PATH", str(precomputed / "case_dossier.pdf"))
    monkeypatch.setattr(app_module, "CASES_INDEX_PATH", str(precomputed / "cases.json"))
    monkeypatch.setattr(app_module, "CASES_DIR", str(cases_dir))
    return TestClient(app_module.app)


def test_cases_index_is_served(client):
    body = client.get("/api/cases").json()
    assert body["default_case"] == "arabian-sea-discharge"
    assert [c["id"] for c in body["cases"]] == CASE_IDS


def test_demo_with_a_case_serves_that_case(client):
    for cid in CASE_IDS:
        response = client.get("/api/demo", params={"case": cid})
        assert response.status_code == 200
        assert response.json()["case_id"] == cid


def test_demo_without_a_case_behaves_as_before(client):
    assert client.get("/api/demo").json()["case_id"] == "legacy"
    assert client.get("/api/scene_preview.png").content.endswith(b"legacy")
    assert client.get("/api/dossier").content.endswith(b"legacy")


def test_scene_preview_and_dossier_follow_the_case(client):
    preview = client.get("/api/scene_preview.png", params={"case": "monsoon-high-wind"})
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content.endswith(b"monsoon-high-wind")

    dossier = client.get("/api/dossier", params={"case": "monsoon-high-wind"})
    assert dossier.status_code == 200
    assert dossier.headers["content-type"] == "application/pdf"
    assert dossier.content.endswith(b"monsoon-high-wind")
    assert client.head("/api/dossier", params={"case": "monsoon-high-wind"}).status_code == 200


def test_unknown_case_is_a_404_naming_the_valid_ids_and_the_build_target(client):
    for route in ("/api/demo", "/api/scene_preview.png", "/api/dossier"):
        response = client.get(route, params={"case": "no-such-case"})
        assert response.status_code == 404
        detail = response.json()["detail"]
        for cid in CASE_IDS:
            assert cid in detail
        assert "make seed-demo" in detail
        assert "make seed-case" in detail


@pytest.mark.parametrize("hostile", ["../demo_bundle.json", "..", "arabian-sea-discharge/../../x", "/etc/passwd", ""])
def test_a_query_string_never_becomes_a_path(client, hostile):
    response = client.get("/api/demo", params={"case": hostile})
    assert response.status_code == 404


def test_missing_index_is_a_404_with_the_build_hint(client, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "CASES_INDEX_PATH", str(tmp_path / "absent.json"))
    response = client.get("/api/cases")
    assert response.status_code == 404
    assert "make seed-demo" in response.json()["detail"]
    # And a case query with no index at all is still refused, not guessed at.
    assert client.get("/api/demo", params={"case": "arabian-sea-discharge"}).status_code == 404


def test_the_inspector_route_is_still_mounted():
    paths = {getattr(r, "path", "") for r in app_module.app.routes}
    assert any("inspect" in p for p in paths)
