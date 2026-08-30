import numpy as np
import pytest

from services.detection.render import render_to_rgb8, sigma0_to_db


def test_sigma0_to_db_matches_definition():
    sigma0 = np.array([1.0, 0.1, 0.01])
    db = sigma0_to_db(sigma0)
    np.testing.assert_allclose(db, [0.0, -10.0, -20.0], atol=1e-5)


def test_sigma0_to_db_floors_nonpositive_values():
    sigma0 = np.array([0.0, -1.0, 1e-12])
    db = sigma0_to_db(sigma0)
    assert np.all(np.isfinite(db))


def test_render_to_rgb8_clips_and_stretches():
    db = np.array([[-40.0, -35.0, -17.5, 0.0, 10.0]])
    rgb = render_to_rgb8(db, db_window=(-35.0, 0.0))
    assert rgb.dtype == np.uint8
    assert rgb.shape == (1, 5, 3)
    # below window clips to 0, above window clips to 255, midpoint to ~half
    assert rgb[0, 0, 0] == 0
    assert rgb[0, 1, 0] == 0
    assert 120 <= rgb[0, 2, 0] <= 135
    assert rgb[0, 3, 0] == 255
    assert rgb[0, 4, 0] == 255


def test_render_to_rgb8_replicates_to_three_identical_channels():
    db = np.full((4, 4), -10.0)
    rgb = render_to_rgb8(db, db_window=(-35.0, 0.0))
    assert rgb.shape == (4, 4, 3)
    np.testing.assert_array_equal(rgb[..., 0], rgb[..., 1])
    np.testing.assert_array_equal(rgb[..., 1], rgb[..., 2])


def test_render_to_rgb8_rejects_invalid_window():
    with pytest.raises(ValueError):
        render_to_rgb8(np.zeros((2, 2)), db_window=(0.0, -35.0))
