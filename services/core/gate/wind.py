"""Wind physics gate. See PLAN.md section 6.

Oil damps capillary waves, which is why it appears dark on SAR. Below
roughly wind_min_ms there are not enough capillary waves for the damping
to be a meaningful signal, so a dark patch is ambiguous rather than
oil. Above wind_max_ms wind mixes any slick into the water column and
the contrast disappears. Suppressed detections are never deleted, only
marked, so the UI can grey them with the reason on hover.
"""

from __future__ import annotations

import xarray as xr
from shapely.geometry import shape

from services.core.schemas import Detection, GateResult


def detection_centroid(detection: Detection) -> tuple[float, float]:
    """Returns (lon, lat) of the detection polygon's centroid. Orientation
    only, per PLAN.md non-negotiable 1: this never enters scoring math,
    it is just where we sample the wind field."""
    centroid = shape(detection.geometry).centroid
    return centroid.x, centroid.y


def load_wind_field(path: str) -> xr.Dataset:
    return xr.open_dataset(path)


def wind_speed_at(wind_ds: xr.Dataset, lon: float, lat: float, time) -> float:
    """Nearest-neighbour sample of the wind field at (lon, lat, time).
    Nearest, not bilinear, because forcing grids are coarse relative to a
    detection footprint and a smoothed boundary would blur exactly the
    accept/suppress edge this gate depends on being crisp."""
    point = wind_ds.interp(lon=lon, lat=lat, time=time, method="nearest")
    u = float(point["u10"].values)
    v = float(point["v10"].values)
    return float((u**2 + v**2) ** 0.5)


def gate_one(detection: Detection, wind_speed_ms: float, config: dict) -> GateResult:
    wind_min = config["wind_min_ms"]
    wind_max = config["wind_max_ms"]
    margin = config["downgrade_margin_ms"]

    if wind_speed_ms < wind_min:
        verdict = "suppress"
        reason = (
            f"Wind speed {wind_speed_ms:.1f} m/s is below {wind_min:.1f} m/s. "
            "At this wind speed there are too few capillary waves for oil to "
            "produce a distinguishing damping signal, so this dark patch "
            "cannot be reliably called oil."
        )
    elif wind_speed_ms > wind_max:
        verdict = "suppress"
        reason = (
            f"Wind speed {wind_speed_ms:.1f} m/s is above {wind_max:.1f} m/s. "
            "Wind this strong mixes a slick into the water column, so a dark "
            "patch this size is unlikely to be an intact oil slick."
        )
    elif wind_speed_ms <= wind_min + margin:
        verdict = "downgrade"
        reason = (
            f"Wind speed {wind_speed_ms:.1f} m/s is within {margin:.1f} m/s of "
            f"the low-wind threshold ({wind_min:.1f} m/s). Confidence is "
            "reduced but the detection is kept."
        )
    else:
        verdict = "accept"
        reason = (
            f"Wind speed {wind_speed_ms:.1f} m/s is within the valid "
            "capillary-wave damping window."
        )

    return GateResult(
        detection_id=detection.detection_id,
        wind_speed_ms=wind_speed_ms,
        verdict=verdict,
        reason=reason,
    )


def gate_detections(
    detections: list[Detection],
    wind_ds: xr.Dataset,
    time,
    config: dict,
) -> list[GateResult]:
    """One GateResult per detection, in the same order. Never drops a
    detection, per PLAN.md section 6: suppressed ones are marked, not
    removed."""
    results = []
    for detection in detections:
        lon, lat = detection_centroid(detection)
        speed = wind_speed_at(wind_ds, lon, lat, time)
        results.append(gate_one(detection, speed, config))
    return results
