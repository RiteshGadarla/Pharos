"""Tests for the map basemap render (services/core/preview.py).

The thing worth protecting here is geometry, not looks: if the PNG's
reported bounds drift from the scene's real footprint, the frontend
draws the imagery in the wrong place and every detection polygon appears
to sit off its own slick. That failure looks like a modelling problem on
screen, so it is worth a test.
"""

import numpy as np
import pytest
import rasterio
from affine import Affine
from PIL import Image
from rasterio.crs import CRS
from rasterio.warp import transform_bounds

from services.core.preview import render_scene_preview

SIZE = 64
PIXEL_SIZE_M = 10.0
ORIGIN_X, ORIGIN_Y = 391020.5, 1887918.6
SEA_DB, OIL_DB = -17.0, -28.0


@pytest.fixture
def scene(tmp_path):
    """A tiny UTM scene: uniform sea with one dark square of 'oil'."""
    db = np.full((SIZE, SIZE), SEA_DB, dtype=np.float32)
    db[20:30, 20:30] = OIL_DB
    sigma0 = (10.0 ** (db / 10.0)).astype(np.float32)

    path = tmp_path / "scene.tif"
    transform = Affine(PIXEL_SIZE_M, 0.0, ORIGIN_X, 0.0, -PIXEL_SIZE_M, ORIGIN_Y)
    with rasterio.open(
        path, "w", driver="GTiff", height=SIZE, width=SIZE, count=1,
        dtype="float32", crs=CRS.from_epsg(32642), transform=transform,
    ) as ds:
        ds.write(sigma0, 1)
    return path


def test_reported_bounds_match_the_scene_footprint(scene, tmp_path):
    """The bounds handed to the frontend have to be the scene's real
    footprint in lon/lat, or the imagery lands off its own detections."""
    meta = render_scene_preview(str(scene), str(tmp_path / "out.png"))

    with rasterio.open(scene) as ds:
        expected = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)

    # The warped grid is axis aligned in EPSG:4326 and the source is not,
    # so its bounds are the source footprint rounded out to whole
    # destination pixels. One pixel here is well under 0.0002 degrees.
    assert meta["bounds"] == pytest.approx(list(expected), abs=2e-4)
    assert meta["native_bounds"] == pytest.approx(list(expected), abs=1e-9)


def test_oil_renders_darker_than_sea(scene, tmp_path):
    """A slick is a low backscatter feature: it has to come out dark, and
    the sea has to keep enough headroom to stay visibly grey rather than
    clipping to black alongside it."""
    out = tmp_path / "out.png"
    render_scene_preview(str(scene), str(out))

    grey = np.array(Image.open(out).convert("L"))
    alpha = np.array(Image.open(out))[:, :, 3]
    valid = alpha > 0

    # The dark square is 100 of 4096 source pixels, so the darkest
    # percentile is oil and the median is sea.
    oil_level = np.percentile(grey[valid], 1)
    sea_level = np.median(grey[valid])
    assert oil_level < sea_level
    assert sea_level > 128


def test_stretch_is_anchored_on_the_sea_not_on_percentiles(scene, tmp_path):
    """The window is the sea level plus the configured dB offsets. A
    percentile stretch would land inside the sea's own distribution on a
    scene that is almost entirely sea, and render speckle as full range
    noise."""
    meta = render_scene_preview(str(scene), str(tmp_path / "out.png"), window_db=(-10.0, 4.0))
    lo, hi = meta["display_db_window"]
    assert lo == pytest.approx(SEA_DB - 10.0, abs=0.1)
    assert hi == pytest.approx(SEA_DB + 4.0, abs=0.1)


def test_outside_the_footprint_is_transparent(scene, tmp_path):
    """Warping a rotated footprint into an axis aligned grid leaves empty
    corners. They have to be transparent, not black, or the map shows a
    black rectangle around the scene."""
    out = tmp_path / "out.png"
    render_scene_preview(str(scene), str(out))

    rgba = np.array(Image.open(out))
    assert rgba.shape[2] == 4
    assert rgba[:, :, 3].max() == 255
    # UTM 32642 at 17 degrees north is very nearly north up, so the warp
    # leaves only a thin transparent margin. It must exist, and it must
    # be a small fraction of the image.
    transparent_fraction = float((rgba[:, :, 3] == 0).mean())
    assert transparent_fraction < 0.2
