"""Sensor adapters. See PLAN.md section 5A.

Ingest sits behind a protocol so the pipeline reads backscatter in
decibels and a SceneMeta, and never a Sentinel-1 product layout.
Sentinel1Adapter is implemented; EOS04Adapter is a documented stub that
raises rather than pretending.

This is fifteen minutes of work and it is the difference between
claiming sensor agnosticism and demonstrating it. SceneMeta.sensor
carries through to the dossier provenance page, so what actually read
the scene is printed in the case file rather than assumed.
"""

from __future__ import annotations

import datetime
import os
from typing import Protocol, runtime_checkable

import numpy as np
import rasterio
from affine import Affine
from rasterio.warp import transform_bounds

from services.core.schemas import SceneMeta
from services.detection.render import sigma0_to_db


@runtime_checkable
class SensorAdapter(Protocol):
    """Reads one sensor's product into the two things the pipeline needs."""

    name: str

    def read_backscatter_db(self, path: str) -> tuple[np.ndarray, Affine, str]:
        """Returns (backscatter in dB, affine transform, CRS string)."""
        ...

    def read_metadata(self, path: str, scene_id: str, acquired_at: datetime.datetime) -> SceneMeta:
        ...


class Sentinel1Adapter:
    """Sentinel-1 GRD, band 1 assumed to be calibrated VV sigma0 in
    linear power. The dB conversion is the one in render.py, so the
    adapter and the model input path can never drift apart."""

    name = "S1"

    def read_backscatter_db(self, path: str) -> tuple[np.ndarray, Affine, str]:
        with rasterio.open(path) as ds:
            sigma0 = ds.read(1).astype(np.float32)
            transform = ds.transform
            crs = ds.crs.to_string()
        return sigma0_to_db(sigma0), transform, crs

    def read_metadata(self, path: str, scene_id: str, acquired_at: datetime.datetime) -> SceneMeta:
        with rasterio.open(path) as ds:
            bbox = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
            crs = ds.crs.to_string()
        return SceneMeta(
            scene_id=scene_id,
            acquired_at=acquired_at,
            bbox=tuple(float(v) for v in bbox),
            crs=crs,
            source_path=os.fspath(path),
            sensor=self.name,
        )


class EOS04Adapter:
    """EOS-04 (RISAT-1A) C-band SAR. Not implemented.

    Expected input is a georeferenced, radiometrically calibrated
    single-band raster of sigma0 in linear power, in a metre-based
    projected CRS, the same shape Sentinel1Adapter consumes. Once that
    is available the rest of the pipeline needs no change: render,
    tiling, inference, polygonize, the wind gate and everything
    downstream all work from backscatter in dB plus an affine
    transform.

    This stub exists so the gap is visible in the code rather than
    hidden in a claim on a slide.
    """

    name = "EOS04"

    def read_backscatter_db(self, path: str) -> tuple[np.ndarray, Affine, str]:
        raise NotImplementedError(
            "EOS04Adapter is a documented stub. It expects a calibrated single-band "
            "sigma0 raster in linear power, in a metre-based projected CRS. See "
            "PLAN.md section 5A."
        )

    def read_metadata(self, path: str, scene_id: str, acquired_at: datetime.datetime) -> SceneMeta:
        raise NotImplementedError(
            "EOS04Adapter is a documented stub. See PLAN.md section 5A."
        )


ADAPTERS: dict[str, type] = {
    "sentinel1": Sentinel1Adapter,
    "s1": Sentinel1Adapter,
    "eos04": EOS04Adapter,
}


def get_adapter(name: str) -> SensorAdapter:
    """Resolves the adapter named in config/pipeline.yaml (`sensor`)."""
    key = name.strip().lower()
    if key not in ADAPTERS:
        raise ValueError(
            f"unknown sensor {name!r}. Known sensors: {', '.join(sorted(set(ADAPTERS)))}. "
            "See PLAN.md section 5A."
        )
    return ADAPTERS[key]()
