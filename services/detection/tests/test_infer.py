import keras
import numpy as np
import pytest

from services.detection.infer import predict_tiles, run_inference
from services.detection.tiling import TileWindow


@pytest.fixture(scope="module")
def tiny_model():
    """A cheap stand-in with the real model's input/output contract
    (256, 256, 3) -> (256, 256, 5) softmax, so infer.py's tiling and
    stitching logic can be tested fast, without the 205 MB download."""
    inputs = keras.Input(shape=(256, 256, 3))
    outputs = keras.layers.Conv2D(5, 1, activation="softmax")(inputs)
    return keras.Model(inputs, outputs)


def test_predict_tiles_returns_one_softmax_per_window(tiny_model):
    image = np.random.default_rng(0).integers(0, 255, size=(256, 512, 3), dtype=np.uint8)
    windows = [TileWindow(0, 0, 256), TileWindow(0, 256, 256)]
    predictions = predict_tiles(tiny_model, image, windows, batch_size=2)
    assert len(predictions) == 2
    for pred in predictions:
        assert pred.shape == (256, 256, 5)
        # softmax output sums to 1 per pixel
        np.testing.assert_allclose(pred.sum(axis=-1), 1.0, atol=1e-4)


def test_predict_tiles_empty_windows_returns_empty_list(tiny_model):
    image = np.zeros((256, 256, 3), dtype=np.uint8)
    assert predict_tiles(tiny_model, image, []) == []


def test_run_inference_produces_full_scene_softmax(tiny_model):
    image = np.random.default_rng(1).integers(0, 255, size=(512, 512, 3), dtype=np.uint8)
    softmax = run_inference(tiny_model, image, tile_size=256, overlap=48, n_classes=5)
    assert softmax.shape == (512, 512, 5)
    np.testing.assert_allclose(softmax.sum(axis=-1), 1.0, atol=1e-4)


def test_run_inference_respects_land_mask(tiny_model):
    image = np.random.default_rng(2).integers(0, 255, size=(512, 512, 3), dtype=np.uint8)
    land_mask = np.ones((512, 512), dtype=bool)  # scene is entirely land
    softmax = run_inference(
        tiny_model, image, tile_size=256, overlap=48, n_classes=5,
        land_mask=land_mask, land_skip_fraction=0.9,
    )
    # every tile skipped, so the whole field defaults to background
    assert np.all(softmax[..., 0] == 1.0)
