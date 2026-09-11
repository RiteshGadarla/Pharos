"""Tile-batched inference and stitching. See PLAN.md section 5.

Keeps the full 5-channel softmax per tile and stitches by averaging
overlaps (tiling.SoftmaxAccumulator), argmaxing only once at the end.
"""

from __future__ import annotations

import numpy as np

from services.detection.tiling import SoftmaxAccumulator, TileWindow, select_tiles


def load_model(model_path: str):
    """Loads the segmentation model from local disk.

    The weights are the one artifact DRISHTA cannot generate for itself
    and cannot commit (they are ~200MB), so a missing file is the single
    most likely first-run failure. Keras reports it as a bare
    ValueError about the file format, which sends people looking at
    their Keras version rather than at the download step, so the check
    happens here with the command that fixes it attached.
    """
    import os

    import keras

    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"Segmentation model not found at {model_path}.\n"
            "It is downloaded once from HuggingFace (no account, no API token) with:\n"
            "    make fetch-model            (from backend/)\n"
            "    make setup                  (from the repository root, does this and the rest)\n"
            "This is the only download DRISHTA needs. Every data input it consumes is "
            "generated locally by scripts/make_synthetic_data.py."
        )

    return keras.saving.load_model(model_path, compile=False)


def predict_tiles(model, image_rgb8: np.ndarray, windows: list[TileWindow], batch_size: int = 8) -> list[np.ndarray]:
    """Runs the model over the given tile windows, batched. Returns one
    softmax array per window, same order as windows."""
    if not windows:
        return []
    batch = np.stack(
        [image_rgb8[w.slice()].astype(np.float32) / 255.0 for w in windows],
        axis=0,
    )
    predictions = model.predict(batch, batch_size=batch_size, verbose=0)
    return [predictions[i] for i in range(len(windows))]


def run_inference(
    model,
    image_rgb8: np.ndarray,
    tile_size: int,
    overlap: int,
    n_classes: int,
    land_mask: np.ndarray | None = None,
    land_skip_fraction: float = 0.9,
    batch_size: int = 8,
) -> np.ndarray:
    """End to end: select tiles, predict, stitch by averaging softmax over
    overlaps. Returns the full-scene averaged softmax, shape (H, W, n_classes)."""
    image_shape = image_rgb8.shape[:2]
    windows = select_tiles(image_shape, tile_size, overlap, land_mask, land_skip_fraction)
    predictions = predict_tiles(model, image_rgb8, windows, batch_size=batch_size)

    accumulator = SoftmaxAccumulator(image_shape, n_classes)
    for window, softmax_tile in zip(windows, predictions):
        accumulator.add(window, softmax_tile)
    return accumulator.finalize()
