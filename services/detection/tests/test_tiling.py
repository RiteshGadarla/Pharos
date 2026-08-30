import numpy as np
import pytest

from services.detection.tiling import (
    SoftmaxAccumulator,
    make_tile_windows,
    select_tiles,
)


def test_make_tile_windows_covers_full_image_without_gaps():
    shape = (512, 512)
    windows = make_tile_windows(shape, tile_size=256, overlap=48)
    covered = np.zeros(shape, dtype=bool)
    for w in windows:
        rows, cols = w.slice()
        covered[rows, cols] = True
    assert covered.all()


def test_make_tile_windows_clamps_last_tile_to_the_edge():
    windows = make_tile_windows((300, 300), tile_size=256, overlap=48)
    row_offs = sorted({w.row_off for w in windows})
    # last tile must end exactly at the image edge, not run off it
    assert max(row_offs) + 256 == 300


def test_make_tile_windows_single_tile_when_image_smaller_than_tile():
    windows = make_tile_windows((200, 200), tile_size=256, overlap=48)
    assert len(windows) == 1
    assert windows[0].row_off == 0
    assert windows[0].col_off == 0


def test_make_tile_windows_rejects_overlap_not_smaller_than_tile():
    with pytest.raises(ValueError):
        make_tile_windows((1000, 1000), tile_size=256, overlap=256)


def test_select_tiles_drops_mostly_land_tiles():
    shape = (512, 512)
    land_mask = np.zeros(shape, dtype=bool)
    land_mask[:256, :256] = True  # first tile is fully land
    kept = select_tiles(shape, tile_size=256, overlap=48, land_mask=land_mask, land_skip_fraction=0.9)
    all_windows = make_tile_windows(shape, tile_size=256, overlap=48)
    assert len(kept) < len(all_windows)
    assert not any(w.row_off == 0 and w.col_off == 0 for w in kept)


def test_select_tiles_keeps_everything_without_a_land_mask():
    shape = (512, 512)
    kept = select_tiles(shape, tile_size=256, overlap=48, land_mask=None)
    all_windows = make_tile_windows(shape, tile_size=256, overlap=48)
    assert len(kept) == len(all_windows)


def test_softmax_accumulator_averages_overlapping_tiles():
    from services.detection.tiling import TileWindow

    acc = SoftmaxAccumulator((4, 4), n_classes=2)
    w1 = TileWindow(0, 0, 2)
    w2 = TileWindow(0, 1, 2)  # overlaps column 1 with w1

    tile_a = np.zeros((2, 2, 2), dtype=np.float32)
    tile_a[..., 0] = 1.0  # w1 says fully class 0
    tile_b = np.zeros((2, 2, 2), dtype=np.float32)
    tile_b[..., 1] = 1.0  # w2 says fully class 1

    acc.add(w1, tile_a)
    acc.add(w2, tile_b)
    field = acc.finalize()

    # column 0 (only w1) stays class 0
    assert field[0, 0, 0] == pytest.approx(1.0)
    # column 1 (overlap of w1 and w2) averages to 0.5/0.5
    assert field[0, 1, 0] == pytest.approx(0.5)
    assert field[0, 1, 1] == pytest.approx(0.5)
    # column 2 (only w2) is class 1
    assert field[0, 2, 1] == pytest.approx(1.0)


def test_softmax_accumulator_defaults_uncovered_pixels_to_background():
    acc = SoftmaxAccumulator((4, 4), n_classes=3)
    field = acc.finalize(background_class=0)
    assert np.all(field[..., 0] == 1.0)
    assert np.all(field[..., 1:] == 0.0)
