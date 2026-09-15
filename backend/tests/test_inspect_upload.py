"""Tests for the upload inspection endpoint, services/core/inspect.py.

The model is replaced by a small deterministic stand in for every test
but the last, so the suite does not load 214 MB of Keras. Everything
around it is real: multipart parsing, format sniffing, the render
choice, tiling, softmax stitching, vectorising and reprojection.

The two render path tests are the ones that matter. PLAN.md section 5's
rendering trap is silent: feed the model the wrong radiometry and it
still returns masks. So these tests do not stop at the path label, they
decode the preview (the model's actual input) and compare it pixel for
pixel with what that path must produce.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from rasterio.warp import transform_bounds
from shapely.geometry import box, shape

import services.core.inspect as inspect_module
from services.detection.render import render_geotiff

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCENE_PATH = BACKEND_DIR / "data" / "fixtures" / "synthetic_scene.tif"
MODEL_PATH = BACKEND_DIR / "data" / "models" / "oil-spill-deeplab" / "model.keras"
CLASSES = ["background", "oil_spill", "ships", "look_alike", "wakes"]


class FakeModel:
    """Dark pixels are oil, very bright pixels are ships, the rest is sea."""

    def predict(self, batch, batch_size=8, verbose=0):
        gray = batch[..., 0]
        out = np.zeros(batch.shape[:3] + (len(CLASSES),), dtype=np.float32)
        out[..., 0] = 0.9
        out[..., 3] = 0.1
        dark = gray < 0.25
        out[dark, 0], out[dark, 1], out[dark, 3] = 0.05, 0.85, 0.1
        bright = gray > 0.9
        out[bright, 0], out[bright, 2], out[bright, 3] = 0.15, 0.75, 0.1
        return out


def _app_client() -> TestClient:
    app = FastAPI()
    app.include_router(inspect_module.router)
    return TestClient(app)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(inspect_module, "get_model", lambda path: FakeModel())
    return _app_client()


def _png(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


def _sea_with_slick(height: int = 600, width: int = 900) -> np.ndarray:
    array = np.full((height, width), 160, dtype=np.uint8)
    array[100:200, 300:500] = 20  # a 200 x 100 px dark slick
    array[400:404, 50:54] = 250  # a 4 x 4 px bright hull
    return array


def _post(client: TestClient, name: str, data: bytes, content_type: str = "application/octet-stream"):
    return client.post("/api/inspect", files={"file": (name, data, content_type)})


def _decode_preview(result: dict) -> np.ndarray:
    prefix = "data:image/png;base64,"
    assert result["preview_png"].startswith(prefix)
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(result["preview_png"][len(prefix):]))))


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


# ---------------------------------------------------------------------------
# The two render paths
# ---------------------------------------------------------------------------


def test_png_takes_the_visual_path_and_reports_pixel_space_only(client):
    array = _sea_with_slick()
    response = _post(client, "slick.png", _png(array), "image/png")
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["render"]["path"] == "visual_8bit"
    assert result["render"]["db_window"] is None
    assert result["image"] == {
        "width": 900,
        "height": 600,
        "georeferenced": False,
        "crs": None,
        "bbox": None,
        "pixel_size_m": None,
    }
    # The model saw the 8-bit values untouched. A sigma0 to dB conversion
    # applied to display values would have changed every pixel.
    assert np.array_equal(_decode_preview(result), array)

    oil = [d for d in result["detections"] if d["class_name"] == "oil"]
    assert len(oil) == 1
    slick = oil[0]
    assert slick["geometry"] is None
    assert slick["area_km2"] is None
    assert slick["centroid"] is None
    assert slick["pixel_area"] == 20000
    assert slick["bbox_px"] == [300, 100, 500, 200]
    assert slick["centroid_px"] == [400.0, 150.0]
    assert shape({"type": "Polygon", "coordinates": [slick["polygon_px"]]}).equals(box(300, 100, 500, 200))

    assert len(result["ships"]) == 1
    assert result["ships"][0]["centroid"] is None
    assert result["ships"][0]["mean_backscatter_db"] is None

    assert any("pixel space only" in c for c in result["caveats"])
    assert result["summary"].startswith("1 oil region detected")


def test_georeferenced_geotiff_takes_the_sigma0_path_with_geography(client):
    data = SCENE_PATH.read_bytes()
    response = _post(client, "synthetic_scene.tif", data, "image/tiff")
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["render"]["path"] == "sigma0_db"
    assert result["render"]["db_window"] == [-35.0, 0.0]

    with rasterio.open(SCENE_PATH) as ds:
        expected_bbox = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds, densify_pts=21)
        crs = ds.crs.to_string()
    image = result["image"]
    assert image["georeferenced"] is True
    assert image["crs"] == crs
    assert image["bbox"] == pytest.approx(list(expected_bbox), abs=1e-5)
    assert image["pixel_size_m"] == [10.0, 10.0]

    # The model input is exactly the section 5 render of band 1.
    rendered, _, _ = render_geotiff(str(SCENE_PATH), (-35.0, 0.0))
    assert np.array_equal(_decode_preview(result), rendered[..., 0])

    assert result["detections"], "the fixture scene has a dark slick"
    scene_box = box(*image["bbox"])
    for detection in result["detections"]:
        geometry = detection["geometry"]
        assert geometry["type"] == "Polygon"
        assert scene_box.buffer(1e-4).contains(shape(geometry))
        # 10 m pixels: 100 px to the km2 tenth.
        assert detection["area_km2"] == pytest.approx(detection["pixel_area"] * 1e-4, rel=1e-6)
        lon, lat = detection["centroid"]["lon"], detection["centroid"]["lat"]
        assert scene_box.contains(shape({"type": "Point", "coordinates": [lon, lat]}))


@pytest.mark.filterwarnings("ignore::rasterio.errors.NotGeoreferencedWarning")
def test_float_tiff_already_in_db_skips_only_the_log_step(client, tmp_path):
    db = np.full((300, 300), -18.0, dtype=np.float32)
    db[100:200, 100:200] = -30.0
    path = tmp_path / "db.tif"
    with rasterio.open(path, "w", driver="GTiff", width=300, height=300, count=1, dtype="float32") as ds:
        ds.write(db, 1)
    response = _post(client, "db.tif", path.read_bytes())
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["render"]["path"] == "sigma0_db"
    assert "already in dB" in result["render"]["note"]
    assert result["image"]["georeferenced"] is False
    expected = ((np.clip(db, -35, 0) + 35) / 35 * 255).astype(np.uint8)
    assert np.array_equal(_decode_preview(result), expected)
    assert all(d["geometry"] is None and d["area_km2"] is None for d in result["detections"])


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_response_has_every_contract_key(client):
    for name, data in (("slick.png", _png(_sea_with_slick())), ("synthetic_scene.tif", SCENE_PATH.read_bytes())):
        result = _post(client, name, data).json()

        assert set(result) >= {
            "filename", "content_type", "bytes", "image", "render", "model", "classes", "detections",
            "ships", "gate", "preview_png", "summary", "caveats", "elapsed_ms",
        }
        assert result["filename"] == name
        assert result["bytes"] == len(data)
        assert result["gate"] is None
        assert isinstance(result["elapsed_ms"], int)
        assert set(result["image"]) >= {"width", "height", "georeferenced", "crs", "bbox", "pixel_size_m"}
        assert set(result["render"]) >= {"path", "db_window", "note", "preview"}
        assert set(result["render"]["preview"]) >= {"width", "height", "scale"}
        assert set(result["model"]) >= {"name", "classes", "tile_size", "overlap_px", "n_tiles"}
        assert result["model"]["classes"] == CLASSES
        assert result["model"]["n_tiles"] > 0

        assert [row["name"] for row in result["classes"]] == CLASSES
        assert sum(row["pixel_fraction"] for row in result["classes"]) == pytest.approx(1.0, abs=1e-4)
        for row in result["classes"]:
            assert set(row) >= {"name", "pixel_count", "pixel_fraction", "mean_prob"}
        assert result["detections"] and result["ships"] is not None
        for detection in result["detections"]:
            assert set(detection) >= {
                "detection_id", "class_name", "mean_class_prob", "pixel_area", "area_km2", "centroid",
                "centroid_px", "bbox_px", "geometry",
            }
            assert len(detection["centroid_px"]) == 2 and len(detection["bbox_px"]) == 4
        for ship in result["ships"]:
            assert set(ship) >= {"target_id", "centroid_px", "pixel_area", "mean_backscatter_db", "centroid"}

        assert any("wind" in c and "acquisition time" in c for c in result["caveats"])
        for text in _strings(result):
            assert "\u2014" not in text, f"em dash in response text: {text!r}"


def test_the_same_upload_gives_the_same_answer(client):
    data = SCENE_PATH.read_bytes()
    first = _post(client, "a.tif", data).json()
    second = _post(client, "a.tif", data).json()
    first.pop("elapsed_ms")
    second.pop("elapsed_ms")
    assert first == second


def test_large_image_is_downsampled_and_mapped_back_to_original_pixels(client):
    array = np.full((2000, 2000), 160, dtype=np.uint8)
    array[800:1000, 1200:1600] = 20
    result = _post(client, "big.png", _png(array)).json()

    assert result["model"]["n_tiles"] <= inspect_module.MAX_TILES
    assert result["render"]["inference"]["downsample"] == 2
    assert any(c.startswith("Downsampled 2x") for c in result["caveats"])
    assert result["image"]["width"] == 2000
    preview = result["render"]["preview"]
    assert (preview["width"], preview["height"]) == (1000, 1000)
    assert preview["scale"] == pytest.approx(0.5)

    (slick,) = [d for d in result["detections"] if d["class_name"] == "oil"]
    assert slick["bbox_px"] == [1200, 800, 1600, 1000]
    assert slick["centroid_px"] == [1400.0, 900.0]
    assert slick["pixel_area"] == 80000


def test_transparent_pixels_are_nodata_not_dark_sea(client):
    rgba = np.zeros((400, 400, 4), dtype=np.uint8)
    rgba[..., :3] = 160
    rgba[..., 3] = 255
    rgba[:, :150, 3] = 0  # transparent black strip, which would read as oil
    result = _post(client, "cutout.png", _png(rgba)).json()
    assert [d for d in result["detections"] if d["class_name"] == "oil"] == []
    assert any("nodata" in c for c in result["caveats"])


# ---------------------------------------------------------------------------
# Bad input fails cleanly
# ---------------------------------------------------------------------------

PDF_BYTES = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << >>\n%%EOF\n"


@pytest.mark.parametrize(
    ("name", "data", "fragment"),
    [
        ("notes.png", b"this is a text file wearing a png extension\n", "not a PNG, JPEG or TIFF"),
        ("report.png", PDF_BYTES, "not a PNG, JPEG or TIFF"),
        ("report.pdf", PDF_BYTES, "Unsupported file type (.pdf)"),
        ("noextension", b"\x89PNG\r\n\x1a\n", "Unsupported file type"),
        ("empty.png", b"", "empty"),
        ("truncated.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "Could not read"),
        ("truncated.tif", b"II*\x00" + b"\x00" * 64, "Could not read"),
        ("tiny.png", None, "too small"),
    ],
)
def test_unreadable_or_unsupported_files_return_a_readable_400(client, name, data, fragment):
    if data is None:
        data = _png(np.zeros((8, 8), dtype=np.uint8))
    response = _post(client, name, data)
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert isinstance(detail, str) and fragment in detail
    assert "Traceback" not in detail


def test_a_request_that_is_not_a_file_upload_returns_400(client):
    response = client.post("/api/inspect", json={"file": "slick.png"})
    assert response.status_code == 400
    assert "multipart/form-data" in response.json()["detail"]

    response = client.post("/api/inspect", data={"other": "field"}, files={"image": ("a.png", b"x")})
    assert response.status_code == 400
    assert "field named file" in response.json()["detail"]


def test_an_upload_over_the_cap_is_refused(client, monkeypatch):
    monkeypatch.setattr(inspect_module, "MAX_UPLOAD_BYTES", 1024)
    monkeypatch.setattr(inspect_module, "MULTIPART_OVERHEAD_BYTES", 0)
    response = _post(client, "big.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 4096)
    assert response.status_code == 413
    assert "upload limit" in response.json()["detail"]


def test_a_missing_model_is_a_503_with_the_fix_attached(monkeypatch):
    def _missing(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(inspect_module, "get_model", _missing)
    response = _post(_app_client(), "slick.png", _png(_sea_with_slick()))
    assert response.status_code == 503
    assert "make fetch-model" in response.json()["detail"]


# ---------------------------------------------------------------------------
# The real model
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(not MODEL_PATH.exists(), reason="segmentation model not downloaded (make fetch-model)")
def test_real_model_runs_end_to_end_on_the_fixture_scene():
    response = _post(_app_client(), "synthetic_scene.tif", SCENE_PATH.read_bytes(), "image/tiff")
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["render"]["path"] == "sigma0_db"
    assert result["model"]["n_tiles"] == 9  # 512 px at 256 px tiles, 48 px overlap
    assert [row["name"] for row in result["classes"]] == CLASSES
    assert sum(row["pixel_fraction"] for row in result["classes"]) == pytest.approx(1.0, abs=1e-4)
    for detection in result["detections"]:
        assert detection["geometry"]["type"] == "Polygon"
        assert detection["area_km2"] >= 0.01
