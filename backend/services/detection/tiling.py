"""Tiling and softmax-averaged stitching. See PLAN.md section 5, "Tiling".

Stitch by averaging softmax over overlaps, then argmax at the end.
Argmaxing per tile and stitching masks produces visible grid seams
straight through slicks, so that path must never be used.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TileWindow:
    row_off: int
    col_off: int
    size: int

    def slice(self) -> tuple[slice, slice]:
        return (
            slice(self.row_off, self.row_off + self.size),
            slice(self.col_off, self.col_off + self.size),
        )


def _axis_offsets(length: int, tile_size: int, overlap: int) -> list[int]:
    if length <= tile_size:
        return [0]
    stride = tile_size - overlap
    if stride <= 0:
        raise ValueError(f"overlap ({overlap}) must be smaller than tile_size ({tile_size})")
    offsets: list[int] = []
    pos = 0
    while pos + tile_size < length:
        offsets.append(pos)
        pos += stride
    offsets.append(length - tile_size)  # clamp final tile to the edge
    # dedupe while preserving order, in case stride landed exactly on the edge
    seen: set[int] = set()
    deduped = []
    for o in offsets:
        if o not in seen:
            seen.add(o)
            deduped.append(o)
    return deduped


def make_tile_windows(image_shape: tuple[int, int], tile_size: int, overlap: int) -> list[TileWindow]:
    height, width = image_shape[:2]
    row_offsets = _axis_offsets(height, tile_size, overlap)
    col_offsets = _axis_offsets(width, tile_size, overlap)
    return [TileWindow(r, c, tile_size) for r in row_offsets for c in col_offsets]


def land_fraction(window: TileWindow, land_mask: np.ndarray | None) -> float:
    if land_mask is None:
        return 0.0
    rows, cols = window.slice()
    patch = land_mask[rows, cols]
    return float(patch.mean())


def select_tiles(
    image_shape: tuple[int, int],
    tile_size: int,
    overlap: int,
    land_mask: np.ndarray | None = None,
    land_skip_fraction: float = 0.9,
) -> list[TileWindow]:
    """Returns tile windows, dropping any tile more than land_skip_fraction
    land or nodata, per PLAN.md section 5."""
    windows = make_tile_windows(image_shape, tile_size, overlap)
    return [w for w in windows if land_fraction(w, land_mask) <= land_skip_fraction]


class SoftmaxAccumulator:
    """Accumulates per-tile softmax predictions over a full scene, averaging
    overlaps, so the caller can argmax once at the end instead of per tile."""

    def __init__(self, image_shape: tuple[int, int], n_classes: int):
        self.height, self.width = image_shape[:2]
        self.n_classes = n_classes
        self.sum = np.zeros((self.height, self.width, n_classes), dtype=np.float32)
        self.count = np.zeros((self.height, self.width), dtype=np.int32)

    def add(self, window: TileWindow, softmax_tile: np.ndarray) -> None:
        rows, cols = window.slice()
        self.sum[rows, cols] += softmax_tile
        self.count[rows, cols] += 1

    def finalize(self, background_class: int = 0) -> np.ndarray:
        """Returns the averaged softmax field, shape (H, W, n_classes).
        Pixels never covered by any kept tile default to a background
        one-hot distribution rather than dividing by zero."""
        covered = self.count > 0
        averaged = np.zeros_like(self.sum)
        averaged[covered] = self.sum[covered] / self.count[covered, None]
        averaged[~covered, background_class] = 1.0
        return averaged
