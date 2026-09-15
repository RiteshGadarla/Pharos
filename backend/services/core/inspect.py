"""Upload inspection: run the detection model on one arbitrary image.

A judge hands over any image and the engine looks at it. This is the
PLAN.md section 5 detection path (render, tile, infer, stitch,
vectorise) run on a single upload, reporting what the model saw and
nothing it cannot know.

Two separate questions decide how an upload is handled.

Where is it? Geography comes from the file. A GeoTIFF with a CRS and an
affine transform gets EPSG:4326 polygons and km2 areas. Anything else is
reported in pixel space only: no lat/lon, no km2, and a caveat says why.

What radiometry is it? Section 5's rendering trap is that the model
degrades silently on the wrong input space, so the render follows the
pixel values, not the file extension. Calibrated linear sigma0 is
converted to dB and rendered through the configured db_window (path
"sigma0_db"). A float band already in dB skips only the log step. An
8-bit image is already a visual product and goes to the model as it is
(path "visual_8bit"): running sigma0 to dB over display values would be
the trap itself.

The wind gate never runs here. It needs a wind field and an acquisition
time, and an uploaded image carries neither, so gate is null and a
caveat says so. Nothing in this module is random.

The multipart body is parsed with the standard library rather than
through FastAPI's UploadFile, which needs python-multipart. That package
is not a DRISHTA dependency, and a route that requires it fails at
import time, which would take the whole core service down with it.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import math
import os
import shutil
import tempfile
import threading
import time
import warnings
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path

import numpy as np
import rasterio
import rasterio.features
from affine import Affine
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from PIL import Image
from rasterio.enums import Resampling
from rasterio.errors import NotGeoreferencedWarning
from rasterio.warp import transform as warp_transform
from rasterio.warp import transform_bounds, transform_geom
from scipy import ndimage
from shapely import affinity
from shapely.geometry import mapping, shape

from services.detection.app import get_model, load_config
from services.detection.infer import run_inference
from services.detection.polygonize import MODEL_TO_SCHEMA_CLASS
from services.detection.render import render_to_rgb8, sigma0_to_db
from services.detection.tiling import make_tile_windows, select_tiles

log = logging.getLogger(__name__)

router = APIRouter()

BACKEND_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BACKEND_DIR / "config" / "pipeline.yaml"

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
# Form boundaries and part headers on top of the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_INPUT_PIXELS = 100_000_000
MIN_SIDE_PX = 32
PREVIEW_MAX_SIDE = 1024
# About 0.3 s per tile on a two core CPU once the model is warm, so this
# bounds a worst case upload to roughly 20 s. Larger images are block
# averaged before inference until they fit.
MAX_TILES = 64
MAX_REGIONS_PER_CLASS = 50
MAX_SHIPS = 200
# Pixel space has no km2, so the region floor is set in pixels: 100 px
# is the configured 0.01 km2 floor at Sentinel-1 GRD's 10 m pixel.
MIN_REGION_PX_PIXEL_SPACE = 100
# Area classes vectorised into detections. Ships are point targets and
# are reported separately.
REGION_CLASSES = ("oil_spill", "look_alike")
SIMPLIFY_TOLERANCE_DEG = 0.0001  # same as polygonize.py
SIMPLIFY_TOLERANCE_PX = 0.75
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON_EQUATOR = 111_320.0

EXTENSION_FORMAT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".tif": "tiff", ".tiff": "tiff"}
MAGIC_FORMAT = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
    (b"II+\x00", "tiff"),
    (b"MM\x00+", "tiff"),
)
SUFFIX_FOR_FORMAT = {"png": ".png", "jpeg": ".jpg", "tiff": ".tif"}

# One inference at a time: two concurrent first requests would otherwise
# each load the 214 MB model, and two CPU bound runs gain nothing.
_MODEL_LOCK = threading.Lock()

_OPENAPI_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


@router.post("/api/inspect", openapi_extra=_OPENAPI_BODY)
async def inspect_upload(request: Request) -> dict:
    """Runs detection on one uploaded image, form field "file"."""
    started = time.perf_counter()
    filename, content_type, data = await _read_multipart_file(request)
    result = await run_in_threadpool(inspect_bytes, filename, content_type, data)
    result["elapsed_ms"] = int(round((time.perf_counter() - started) * 1000))
    return result


# ---------------------------------------------------------------------------
# Upload handling
# ---------------------------------------------------------------------------


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=f"The file is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
    )


async def _read_multipart_file(request: Request) -> tuple[str, str | None, bytes]:
    content_type = request.headers.get("content-type", "")
    header = Message()
    header["content-type"] = content_type
    boundary = header.get_boundary()
    if header.get_content_type() != "multipart/form-data" or not boundary:
        raise _bad_request("Send the image as multipart/form-data in a field named file.")

    limit = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _too_large()

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise _too_large()
        chunks.append(chunk)

    filename, part_type, data = _parse_multipart(b"".join(chunks), boundary.encode("latin-1"))
    if len(data) > MAX_UPLOAD_BYTES:
        raise _too_large()
    return filename, part_type, data


def _parse_multipart(body: bytes, boundary: bytes) -> tuple[str, str | None, bytes]:
    """Returns (filename, content type, bytes) of the part named "file".

    RFC 7578 framing: every delimiter is CRLF, "--", boundary, and the
    CRLF before the first one is optional, so one is prepended to make
    every part split the same way."""
    delimiter = b"\r\n--" + boundary
    for part in (b"\r\n" + body).split(delimiter)[1:]:
        if part.startswith(b"--"):
            break
        _, _, part = part.partition(b"\r\n")
        head, sep, payload = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = Message()
        for line in head.decode("utf-8", errors="replace").split("\r\n"):
            name, colon, value = line.partition(":")
            if colon:
                headers[name.strip()] = value.strip()
        disposition = headers.get("content-disposition", "")
        holder = Message()
        holder["content-disposition"] = disposition
        if holder.get_param("name", header="content-disposition") != "file":
            continue
        raw_name = holder.get_filename() or "upload"
        filename = os.path.basename(raw_name.replace("\\", "/"))[:200] or "upload"
        return filename, headers.get("content-type"), payload
    raise _bad_request("No file in the upload. Send the image in a form field named file.")


def sniff_format(data: bytes) -> str | None:
    for magic, fmt in MAGIC_FORMAT:
        if data.startswith(magic):
            return fmt
    return None


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


@dataclass
class _Scene:
    """One upload, read at inference resolution."""

    band: np.ndarray  # 2D, inference resolution, dtype as read
    nodata: np.ndarray  # bool, same shape, True where there is no data
    width: int  # original
    height: int  # original
    georeferenced: bool = False
    crs: object | None = None  # rasterio CRS
    transform: Affine | None = None  # of the inference grid
    bbox: list[float] | None = None
    pixel_size_m: list[float] | None = None
    downsample: int = 1
    multiband_note: str = ""
    caveats: list[str] = field(default_factory=list)


def inspect_bytes(filename: str, content_type: str | None, data: bytes) -> dict:
    """Validates, reads, renders, infers and reports on one upload. Raises
    HTTPException with a readable message for anything it cannot read."""
    if not data:
        raise _bad_request("The file is empty.")

    extension = os.path.splitext(filename)[1].lower()
    if extension not in EXTENSION_FORMAT:
        shown = extension or "no extension"
        raise _bad_request(f"Unsupported file type ({shown}). Upload a .png, .jpg, .jpeg, .tif or .tiff image.")

    fmt = sniff_format(data)
    if fmt is None:
        raise _bad_request(f"{filename} is not a PNG, JPEG or TIFF image, whatever its extension says.")

    config = load_config(str(CONFIG_PATH))
    det_cfg = config["detection"]
    tile_size = int(det_cfg["tiling"]["tile_size"])
    overlap = int(det_cfg["tiling"]["overlap_px"])

    workdir = tempfile.mkdtemp(prefix="drishta-inspect-")
    try:
        path = os.path.join(workdir, "upload" + SUFFIX_FOR_FORMAT[fmt])
        with open(path, "wb") as f:
            f.write(data)
        try:
            if fmt == "tiff":
                scene = _read_tiff(path, tile_size, overlap)
            else:
                scene = _read_pil(path, fmt, tile_size, overlap)
        except HTTPException:
            raise
        except Exception as exc:  # corrupt or truncated content behind a valid signature
            raise _bad_request(f"Could not read {filename} as an image: {_short(exc)}") from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if EXTENSION_FORMAT[extension] != fmt:
        scene.caveats.append(f"Named {extension} but the content is {fmt.upper()}, so it was read as {fmt.upper()}.")

    try:
        return _run(scene, filename, content_type, data, config)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("inspect run failed for %s", filename)
        raise HTTPException(status_code=500, detail=f"The detection run failed: {_short(exc)}") from exc


def _short(exc: Exception) -> str:
    text = " ".join(str(exc).split()) or type(exc).__name__
    return text[:300]


def _check_dimensions(width: int, height: int) -> None:
    if width * height > MAX_INPUT_PIXELS:
        raise _bad_request(
            f"The image is {width} x {height} pixels, above the {MAX_INPUT_PIXELS // 1_000_000} megapixel limit."
        )
    if min(width, height) < MIN_SIDE_PX:
        raise _bad_request(f"The image is {width} x {height} pixels, too small to inspect (minimum {MIN_SIDE_PX} px a side).")


def tile_count(height: int, width: int, tile_size: int, overlap: int) -> int:
    return len(make_tile_windows((max(height, tile_size), max(width, tile_size)), tile_size, overlap))


def downsample_factor(height: int, width: int, tile_size: int, overlap: int) -> int:
    """Smallest integer block factor that brings the tile count within MAX_TILES."""
    factor = 1
    while tile_count(math.ceil(height / factor), math.ceil(width / factor), tile_size, overlap) > MAX_TILES:
        factor += 1
    return factor


def _reduced_shape(height: int, width: int, factor: int) -> tuple[int, int]:
    return math.ceil(height / factor), math.ceil(width / factor)


def _block_reduce(array: np.ndarray, out_shape: tuple[int, int]) -> np.ndarray:
    """Box average to out_shape. uint8 stays uint8, anything else becomes float32."""
    if array.shape == out_shape:
        return array
    size = (out_shape[1], out_shape[0])
    if array.dtype == np.uint8:
        return np.asarray(Image.fromarray(array).resize(size, Image.Resampling.BOX))
    as_float = np.ascontiguousarray(array, dtype=np.float32)
    return np.asarray(Image.fromarray(as_float).resize(size, Image.Resampling.BOX))


def _read_pil(path: str, fmt: str, tile_size: int, overlap: int) -> _Scene:
    with Image.open(path) as img:
        width, height = img.size
        _check_dimensions(width, height)
        factor = downsample_factor(height, width, tile_size, overlap)
        out_shape = _reduced_shape(height, width, factor)

        alpha = None
        if "A" in img.getbands() or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            alpha = np.asarray(rgba.getchannel("A"))
            img_for_band = rgba
        else:
            img_for_band = img

        if img_for_band.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
            band = np.asarray(img_for_band)
        else:
            band = np.asarray(img_for_band.convert("L"))

    nodata = np.zeros(out_shape, dtype=bool)
    if alpha is not None:
        nodata = _block_reduce(alpha, out_shape) < 128
    band = _block_reduce(band, out_shape)

    scene = _Scene(band=band, nodata=nodata, width=width, height=height, downsample=factor)
    scene.caveats.append(
        f"{fmt.upper()} carries no georeferencing, so results are in pixel space only: no latitude, longitude or km2."
    )
    return scene


def _read_tiff(path: str, tile_size: int, overlap: int) -> _Scene:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(path) as ds:
            width, height = ds.width, ds.height
            _check_dimensions(width, height)
            factor = downsample_factor(height, width, tile_size, overlap)
            out_shape = _reduced_shape(height, width, factor)
            resampling = Resampling.average if factor > 1 else Resampling.nearest

            dtype = np.dtype(ds.dtypes[0])
            multiband_note = ""
            if dtype == np.uint8 and ds.count >= 3:
                rgb = ds.read([1, 2, 3], out_shape=(3, *out_shape), resampling=resampling).astype(np.float32)
                band = np.clip(0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] + 0.5, 0, 255).astype(np.uint8)
                multiband_note = "Bands 1 to 3 combined to 8-bit grayscale. "
            else:
                band = ds.read(1, out_shape=out_shape, resampling=resampling)
                if ds.count > 1:
                    multiband_note = f"Band 1 of {ds.count} used, read as VV. "
            mask = ds.read_masks(1, out_shape=out_shape, resampling=Resampling.nearest)
            nodata = mask == 0
            if np.issubdtype(band.dtype, np.floating):
                nodata |= ~np.isfinite(band)

            scene = _Scene(
                band=band,
                nodata=nodata,
                width=width,
                height=height,
                downsample=factor,
                multiband_note=multiband_note,
            )

            has_transform = ds.transform != Affine.identity()
            if ds.crs is not None and has_transform:
                try:
                    bounds = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds, densify_pts=21)
                    scene.georeferenced = True
                    scene.crs = ds.crs
                    scene.transform = ds.transform @ Affine.scale(width / out_shape[1], height / out_shape[0])
                    scene.bbox = [round(float(v), 6) for v in bounds]
                    center_lat = (bounds[1] + bounds[3]) / 2.0
                    scene.pixel_size_m = [round(v, 3) for v in _pixel_size_m(ds.transform, ds.crs, center_lat)]
                    if ds.crs.is_geographic:
                        scene.caveats.append(
                            "The CRS is geographic, so km2 areas are approximated at the scene centre latitude."
                        )
                except Exception as exc:
                    scene.caveats.append(
                        f"The CRS could not be converted to EPSG:4326 ({_short(exc)}), so results are in pixel space only."
                    )
            elif ds.gcps[0]:
                scene.caveats.append(
                    "The TIFF has ground control points but no affine transform. Results are in pixel space only; "
                    "warp it to a map projection for lat/lon and km2."
                )
            elif has_transform:
                scene.caveats.append("The TIFF has a transform but no CRS, so results are in pixel space only.")
            else:
                scene.caveats.append(
                    "The TIFF has no CRS or transform, so results are in pixel space only: no latitude, longitude or km2."
                )
    return scene


def _pixel_size_m(transform: Affine, crs, center_lat: float) -> tuple[float, float]:
    size_x = math.hypot(transform.a, transform.d)
    size_y = math.hypot(transform.b, transform.e)
    if crs.is_geographic:
        return (
            size_x * M_PER_DEG_LON_EQUATOR * math.cos(math.radians(center_lat)),
            size_y * M_PER_DEG_LAT,
        )
    unit_factor = float(crs.linear_units_factor[1])
    return size_x * unit_factor, size_y * unit_factor


@dataclass
class _Render:
    rgb8: np.ndarray  # (h, w, 3) uint8, what the model sees
    db: np.ndarray | None  # backscatter in dB before the clip, sigma0 path only
    path: str
    db_window: list[float] | None
    note: str
    caveats: list[str]


def render_band(band: np.ndarray, nodata: np.ndarray, db_window: tuple[float, float]) -> _Render:
    """Picks the render path from the pixel values themselves.

    uint8 is an 8-bit visual product: used as is, no dB conversion.
    Other integers are neither sigma0 nor a visual product we can trust,
    so they are percentile stretched to 8 bits and flagged. Floats are
    sigma0: already dB when most values are negative (linear power never
    is), otherwise linear and converted with render.sigma0_to_db."""
    valid = ~nodata
    values = band[valid]
    band = band.copy()
    band[nodata] = np.median(values).astype(band.dtype)
    caveats: list[str] = []

    if band.dtype == np.uint8:
        gray = band
        return _Render(
            rgb8=np.repeat(gray[:, :, None], 3, axis=2),
            db=None,
            path="visual_8bit",
            db_window=None,
            note="8-bit image fed to the model as is. It is already a visual product, so no sigma0 to dB conversion.",
            caveats=[
                "Read as an already rendered 8-bit SAR image. On imagery that is not SAR the class labels mean little."
            ],
        )

    if np.issubdtype(band.dtype, np.integer) or np.issubdtype(band.dtype, np.bool_):
        lo, hi = (float(v) for v in np.percentile(values, [0.5, 99.5]))
        scale = 255.0 / (hi - lo) if hi > lo else 0.0
        gray = np.clip((band.astype(np.float32) - lo) * scale, 0, 255).astype(np.uint8)
        caveats.append(
            f"{band.dtype} band is not calibrated sigma0, so it was stretched to 8 bits between its 0.5 and 99.5 "
            "percentiles. Read the output with that in mind."
        )
        return _Render(
            rgb8=np.repeat(gray[:, :, None], 3, axis=2),
            db=None,
            path="visual_8bit",
            db_window=None,
            note="Integer band percentile stretched to 8 bits. No sigma0 to dB conversion.",
            caveats=caveats,
        )

    window = [float(db_window[0]), float(db_window[1])]
    if float(np.mean(values < 0)) > 0.5:
        db = band.astype(np.float32)
        note = "Band already in dB, so only the db_window clip and 0 to 255 stretch were applied."
    else:
        db = sigma0_to_db(band.astype(np.float32))
        note = "Read as calibrated linear sigma0, converted to dB, clipped to the db_window and stretched to 0 to 255."
        if float(np.median(values)) > 1.0:
            caveats.append(
                "Median value is above 1, high for calibrated linear sigma0. If this is raw DN the render is wrong."
            )
    return _Render(
        rgb8=render_to_rgb8(db, (window[0], window[1])),
        db=db,
        path="sigma0_db",
        db_window=window,
        note=note,
        caveats=caveats,
    )


def _infer(image_rgb8: np.ndarray, land_mask: np.ndarray, det_cfg: dict) -> np.ndarray:
    model_path = BACKEND_DIR / det_cfg["model_local_dir"] / "model.keras"
    with _MODEL_LOCK:
        try:
            model = get_model(str(model_path))
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail="The segmentation model is not installed. Run make fetch-model from backend/, then retry.",
            ) from exc
        return run_inference(
            model,
            image_rgb8,
            tile_size=int(det_cfg["tiling"]["tile_size"]),
            overlap=int(det_cfg["tiling"]["overlap_px"]),
            n_classes=len(det_cfg["classes"]),
            land_mask=land_mask,
            land_skip_fraction=float(det_cfg["tiling"]["land_skip_fraction"]),
        )


def _run(scene: _Scene, filename: str, content_type: str | None, data: bytes, config: dict) -> dict:
    det_cfg = config["detection"]
    classes: list[str] = list(det_cfg["classes"])
    tile_size = int(det_cfg["tiling"]["tile_size"])
    overlap = int(det_cfg["tiling"]["overlap_px"])
    caveats = list(scene.caveats)

    height, width = scene.band.shape
    if scene.nodata.all():
        raise _bad_request(f"{filename} has no valid pixels: every pixel is nodata.")

    render = render_band(scene.band, scene.nodata, tuple(det_cfg["render"]["db_window"]))
    caveats.extend(render.caveats)

    # Pad anything smaller than one tile, so every tile the model sees is
    # full size, then crop the softmax back. Padding is not nodata: it
    # must not push the only tile over the land skip fraction.
    pad_h, pad_w = max(0, tile_size - height), max(0, tile_size - width)
    image = render.rgb8
    land_mask = scene.nodata
    if pad_h or pad_w:
        image = np.pad(image, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
        land_mask = np.pad(land_mask, ((0, pad_h), (0, pad_w)), constant_values=False)
        caveats.append(f"Smaller than one {tile_size} px tile, so it was edge padded before inference.")

    land_skip = float(det_cfg["tiling"]["land_skip_fraction"])
    n_tiles = len(select_tiles(image.shape[:2], tile_size, overlap, land_mask, land_skip))
    softmax = _infer(image, land_mask, det_cfg)[:height, :width]
    softmax[scene.nodata] = 0.0
    softmax[scene.nodata, 0] = 1.0  # no data, no detection

    if scene.downsample > 1:
        caveats.append(
            f"Downsampled {scene.downsample}x ({scene.width} x {scene.height} to {width} x {height} px) to stay "
            f"within {MAX_TILES} tiles. Coordinates and areas are scaled back to the original pixels."
        )
    nodata_fraction = float(scene.nodata.mean())
    if nodata_fraction > 0:
        caveats.append(f"{_percent(nodata_fraction)} of pixels are nodata and were excluded from detection.")

    argmax = np.argmax(softmax, axis=-1)
    scale_x = scene.width / width
    scale_y = scene.height / height
    sha256 = hashlib.sha256(data).hexdigest()
    id_prefix = f"INSPECT-{sha256[:8].upper()}"

    class_rows = []
    for index, name in enumerate(classes):
        assigned = argmax == index
        count = int(assigned.sum())
        class_rows.append(
            {
                "name": name,
                "pixel_count": int(round(count * scale_x * scale_y)),
                "pixel_fraction": round(count / argmax.size, 6),
                "mean_prob": round(float(softmax[..., index][assigned].mean()), 4) if count else 0.0,
            }
        )

    grid = _Grid(scene=scene, scale_x=scale_x, scale_y=scale_y, min_area_km2=float(det_cfg["polygonize"]["min_area_km2"]))
    detections: list[dict] = []
    region_totals: dict[str, tuple[int, int]] = {}
    for model_class in REGION_CLASSES:
        if model_class not in classes:
            continue
        rows, n_found, covered_px = _regions(softmax, argmax, classes.index(model_class), model_class, id_prefix, grid)
        detections.extend(rows)
        region_totals[model_class] = (n_found, covered_px)
        if n_found > len(rows):
            caveats.append(f"{n_found} {model_class} regions found, the largest {len(rows)} are listed.")
    if not scene.georeferenced:
        floor = f"{MIN_REGION_PX_PIXEL_SPACE} px"
    else:
        floor = f"{grid.min_area_km2} km2"
    caveats.append(f"Regions smaller than {floor} are not listed.")

    ships_cfg = det_cfg.get("ships", {})
    ships = []
    if "ships" in classes:
        ships = _ships(
            argmax,
            classes.index("ships"),
            render.db,
            id_prefix,
            grid,
            int(ships_cfg.get("min_pixel_area", 4)),
            int(ships_cfg.get("max_pixel_area", 20000)),
        )

    caveats.append(
        "No wind gate verdict. The gate needs a wind field and an acquisition time, and an uploaded image carries "
        "neither, so dark patches are not screened against wind."
    )
    caveats.append("Detection only. Drift, AIS and attribution need a scene time and position and do not run on uploads.")

    preview_png, preview = _preview(render.rgb8[:, :, 0], scene.width)
    oil_regions, oil_px = region_totals.get("oil_spill", (0, 0))
    lookalike_regions, _ = region_totals.get("look_alike", (0, 0))

    return {
        "filename": filename,
        "content_type": content_type,
        "bytes": len(data),
        "sha256": sha256,
        "image": {
            "width": scene.width,
            "height": scene.height,
            "georeferenced": scene.georeferenced,
            "crs": scene.crs.to_string() if scene.georeferenced else None,
            "bbox": scene.bbox if scene.georeferenced else None,
            "pixel_size_m": scene.pixel_size_m if scene.georeferenced else None,
        },
        "render": {
            "path": render.path,
            "db_window": render.db_window,
            "note": scene.multiband_note + render.note,
            "inference": {"width": width, "height": height, "downsample": scene.downsample},
            "preview": preview,
        },
        "model": {
            "name": str(det_cfg.get("model_repo", det_cfg["model_local_dir"])),
            "classes": classes,
            "tile_size": tile_size,
            "overlap_px": overlap,
            "n_tiles": n_tiles,
        },
        "classes": class_rows,
        "detections": detections,
        "ships": ships,
        "gate": None,
        "preview_png": preview_png,
        "summary": _summary(oil_regions, oil_px, lookalike_regions, len(ships), scene.width * scene.height),
        "caveats": caveats,
        "elapsed_ms": 0,
    }


@dataclass
class _Grid:
    """Maps inference grid pixels to original pixels and, when the scene is
    georeferenced, to EPSG:4326 and km2."""

    scene: _Scene
    scale_x: float
    scale_y: float
    min_area_km2: float

    @property
    def px_area_scale(self) -> float:
        return self.scale_x * self.scale_y

    def pixel_area_km2(self) -> float | None:
        """Area of one inference grid pixel, or None in pixel space."""
        scene = self.scene
        if not scene.georeferenced or scene.transform is None:
            return None
        t = scene.transform
        determinant = abs(t.a * t.e - t.b * t.d)
        if scene.crs.is_geographic:
            center_lat = (scene.bbox[1] + scene.bbox[3]) / 2.0
            m2 = determinant * M_PER_DEG_LAT * M_PER_DEG_LON_EQUATOR * math.cos(math.radians(center_lat))
        else:
            m2 = determinant * float(scene.crs.linear_units_factor[1]) ** 2
        return m2 / 1e6

    def min_region_px(self) -> float:
        """Region floor in inference grid pixels."""
        km2 = self.pixel_area_km2()
        if km2 is None:
            return MIN_REGION_PX_PIXEL_SPACE / self.px_area_scale
        return self.min_area_km2 / km2

    def lonlat(self, col: float, row: float) -> dict | None:
        scene = self.scene
        if not scene.georeferenced:
            return None
        x, y = scene.transform @ (col, row)
        lons, lats = warp_transform(scene.crs, "EPSG:4326", [x], [y])
        return {"lon": round(float(lons[0]), 6), "lat": round(float(lats[0]), 6)}


def _components(mask: np.ndarray) -> tuple[np.ndarray, list, np.ndarray]:
    labels, n = ndimage.label(mask)
    if n == 0:
        return labels, [], np.zeros(0, dtype=np.int64)
    counts = np.bincount(labels.ravel(), minlength=n + 1)[1:]
    return labels, ndimage.find_objects(labels), counts


def _regions(
    softmax: np.ndarray,
    argmax: np.ndarray,
    class_index: int,
    model_class: str,
    id_prefix: str,
    grid: _Grid,
) -> tuple[list[dict], int, int]:
    """Connected regions of one class, largest first. Returns the listed
    rows, how many regions cleared the floor, and how many original
    pixels those regions cover in total."""
    labels, objects, counts = _components(argmax == class_index)
    floor = grid.min_region_px()
    kept = [i for i in range(len(counts)) if counts[i] >= floor]
    kept.sort(key=lambda i: (-int(counts[i]), objects[i][0].start, objects[i][1].start))
    covered_px = int(round(sum(int(counts[i]) for i in kept) * grid.px_area_scale))
    listed = kept[:MAX_REGIONS_PER_CLASS]
    if not listed:
        return [], len(kept), covered_px

    label_ids = [i + 1 for i in listed]
    probability = softmax[..., class_index]
    means = ndimage.mean(probability, labels, label_ids)
    centers = ndimage.center_of_mass(argmax == class_index, labels, label_ids)
    km2_per_px = grid.pixel_area_km2()
    schema_class = MODEL_TO_SCHEMA_CLASS[model_class]
    scene = grid.scene

    rows = []
    for order, i in enumerate(listed):
        rs, cs = objects[i]
        component = labels[rs, cs] == i + 1
        polygon = _component_polygon(component, cs.start, rs.start)
        row_c, col_c = centers[order]
        col_c, row_c = float(col_c) + 0.5, float(row_c) + 0.5

        geometry = None
        if scene.georeferenced:
            t = scene.transform
            projected = affinity.affine_transform(polygon, [t.a, t.b, t.d, t.e, t.c, t.f])
            geographic = shape(transform_geom(scene.crs, "EPSG:4326", mapping(projected)))
            geometry = _rounded_geojson(geographic.simplify(SIMPLIFY_TOLERANCE_DEG, preserve_topology=True), 6)

        outline = polygon.simplify(SIMPLIFY_TOLERANCE_PX, preserve_topology=True)
        outline = affinity.scale(outline, xfact=grid.scale_x, yfact=grid.scale_y, origin=(0, 0))

        rows.append(
            {
                "detection_id": f"{id_prefix}-{schema_class}-{order:03d}",
                "class_name": schema_class,
                "mean_class_prob": round(float(means[order]), 4),
                "pixel_area": int(round(int(counts[i]) * grid.px_area_scale)),
                "area_km2": round(int(counts[i]) * km2_per_px, 4) if km2_per_px is not None else None,
                "centroid": grid.lonlat(col_c, row_c),
                "centroid_px": [round(col_c * grid.scale_x, 2), round(row_c * grid.scale_y, 2)],
                "bbox_px": [
                    int(math.floor(cs.start * grid.scale_x)),
                    int(math.floor(rs.start * grid.scale_y)),
                    min(scene.width, int(math.ceil(cs.stop * grid.scale_x))),
                    min(scene.height, int(math.ceil(rs.stop * grid.scale_y))),
                ],
                "geometry": geometry,
                "polygon_px": [[round(x, 2), round(y, 2)] for x, y in outline.exterior.coords],
            }
        )
    return rows, len(kept), covered_px


def _component_polygon(component: np.ndarray, col_off: int, row_off: int):
    """Outline of one 4-connected component, in inference grid pixel
    corner coordinates (x = column, y = row)."""
    offset = Affine.translation(col_off, row_off)
    polygons = [
        shape(geom)
        for geom, value in rasterio.features.shapes(component.astype(np.uint8), mask=component, transform=offset)
        if value == 1
    ]
    return max(polygons, key=lambda p: p.area)


def _rounded_geojson(geometry, digits: int) -> dict:
    geojson = mapping(geometry)

    def _round(coords):
        if isinstance(coords[0], (int, float)):
            return [round(float(c), digits) for c in coords]
        return [_round(c) for c in coords]

    return {"type": geojson["type"], "coordinates": _round(geojson["coordinates"])}


def _ships(
    argmax: np.ndarray,
    ships_index: int,
    db: np.ndarray | None,
    id_prefix: str,
    grid: _Grid,
    min_pixel_area: int,
    max_pixel_area: int,
) -> list[dict]:
    """Ship targets, by the same rule as services/detection/ships.py:
    connected components of the Ships class inside the configured pixel
    area bounds, which reject speckle at the low end and land or a
    platform at the high end. Bounds apply to original pixels."""
    mask = argmax == ships_index
    labels, objects, counts = _components(mask)
    kept = [
        i for i in range(len(counts)) if min_pixel_area <= counts[i] * grid.px_area_scale <= max_pixel_area
    ]
    kept.sort(key=lambda i: (objects[i][0].start, objects[i][1].start))
    kept = kept[:MAX_SHIPS]
    if not kept:
        return []
    label_ids = [i + 1 for i in kept]
    centers = ndimage.center_of_mass(mask, labels, label_ids)
    mean_db = ndimage.mean(db, labels, label_ids) if db is not None else None

    targets = []
    for order, i in enumerate(kept):
        row_c, col_c = centers[order]
        col_c, row_c = float(col_c) + 0.5, float(row_c) + 0.5
        backscatter = None
        if mean_db is not None and math.isfinite(float(mean_db[order])):
            backscatter = round(float(mean_db[order]), 2)
        targets.append(
            {
                "target_id": f"{id_prefix}-ship-{order:03d}",
                "centroid_px": [round(col_c * grid.scale_x, 2), round(row_c * grid.scale_y, 2)],
                "pixel_area": int(round(int(counts[i]) * grid.px_area_scale)),
                "mean_backscatter_db": backscatter,
                "centroid": grid.lonlat(col_c, row_c),
            }
        )
    return targets


def _preview(gray: np.ndarray, original_width: int) -> tuple[str, dict]:
    """The rendered model input, longest side at most PREVIEW_MAX_SIDE, as
    a PNG data URL. scale maps original pixels to preview pixels."""
    height, width = gray.shape
    ratio = min(1.0, PREVIEW_MAX_SIDE / max(height, width))
    size = (max(1, int(round(width * ratio))), max(1, int(round(height * ratio))))
    image = Image.fromarray(np.ascontiguousarray(gray))
    if size != (width, height):
        image = image.resize(size, Image.Resampling.BOX)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}", {
        "width": size[0],
        "height": size[1],
        "scale": round(size[0] / original_width, 6),
    }


def _percent(fraction: float) -> str:
    pct = fraction * 100.0
    if 0 < pct < 0.1:
        return "under 0.1 percent"
    return f"{pct:.1f} percent"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _summary(oil_regions: int, oil_px: int, lookalike_regions: int, n_ships: int, total_px: int) -> str:
    if oil_regions:
        text = f"{_plural(oil_regions, 'oil region')} detected, covering {_percent(oil_px / total_px)} of the image"
    else:
        text = "No oil regions detected"
    extras = []
    if lookalike_regions:
        extras.append(_plural(lookalike_regions, "look-alike region"))
    if n_ships:
        extras.append(_plural(n_ships, "ship target"))
    if extras:
        text += ", plus " + " and ".join(extras)
    return text
