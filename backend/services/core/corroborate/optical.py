"""Optical corroboration of a SAR detection. See PLAN.md section 7.

The problem statement says "SAR and EO imagery". SAR alone was a literal
gap against that wording, and this stage closes it. It does not need to
be sophisticated, and it must not overclaim: optical oil detection is
hard, cloud dependent and daylight only, which is exactly why SAR is the
primary sensor here.

Three honest states, and no fourth:

  agree        a near-coincident optical scene shows the detection
               polygon anomalous against a surrounding sea reference ring
  disagree     a near-coincident optical scene shows nothing unusual there
  no_coverage  no optical acquisition intersects the footprint within the
               configured window

no_coverage is the common outcome and is not a failure. The value of
this stage is that the requirement is met and the reasoning is
inspectable, not that optical confirms anything.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import numpy as np

from services.core.schemas import Detection, OpticalCorroboration

SAR_PRIMACY_NOTE = (
    "SAR is the primary sensor for this system because it images through cloud, "
    "at night, and in any weather, none of which optical can do. An absence of "
    "optical coverage weakens nothing in the SAR detection."
)


@dataclass(frozen=True)
class OpticalScene:
    """One candidate optical acquisition.

    reflectance is a 2D array covering `bbox`, already normalised to
    0-1. Keeping this a plain array rather than a product path means
    the corroboration logic is testable without a Sentinel-2 download.
    """

    sensor: str
    acquired_at: datetime.datetime
    bbox: tuple[float, float, float, float]  # minlon, minlat, maxlon, maxlat
    reflectance: np.ndarray


def find_coincident_scene(
    scenes: list[OpticalScene],
    detection_bbox: tuple[float, float, float, float],
    sar_acquired_at: datetime.datetime,
    window_hours: float,
) -> OpticalScene | None:
    """The optical acquisition closest in time that intersects the
    detection footprint and falls inside the window."""
    candidates = []
    for scene in scenes:
        if not _bboxes_intersect(scene.bbox, detection_bbox):
            continue
        delta_hours = abs((scene.acquired_at - sar_acquired_at).total_seconds()) / 3600.0
        if delta_hours <= window_hours:
            candidates.append((delta_hours, scene))
    if not candidates:
        return None
    return min(candidates, key=lambda c: c[0])[1]


def _bboxes_intersect(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _polygon_and_ring_means(
    scene: OpticalScene, polygon_coords: list[list[float]]
) -> tuple[float, float]:
    """Mean reflectance inside the detection polygon's bounding box, and
    in the surrounding sea reference ring.

    Bounding box rather than the polygon itself: at Sentinel-2's 10 m
    pixel over a slick of a few square kilometres the difference is
    small, and the honest statistic here is a contrast ratio, not a
    precise per-pixel segmentation we are not claiming to have.
    """
    lons = [c[0] for c in polygon_coords]
    lats = [c[1] for c in polygon_coords]
    minlon, maxlon, minlat, maxlat = min(lons), max(lons), min(lats), max(lats)

    height, width = scene.reflectance.shape
    s_minlon, s_minlat, s_maxlon, s_maxlat = scene.bbox

    def to_index(lon: float, lat: float) -> tuple[int, int]:
        col = int(np.clip((lon - s_minlon) / max(s_maxlon - s_minlon, 1e-9) * (width - 1), 0, width - 1))
        row = int(np.clip((lat - s_minlat) / max(s_maxlat - s_minlat, 1e-9) * (height - 1), 0, height - 1))
        return row, col

    r0, c0 = to_index(minlon, minlat)
    r1, c1 = to_index(maxlon, maxlat)
    r0, r1 = min(r0, r1), max(r0, r1) + 1
    c0, c1 = min(c0, c1), max(c0, c1) + 1

    inside = scene.reflectance[r0:r1, c0:c1]
    if inside.size == 0:
        return float("nan"), float("nan")

    pad_r = max(1, (r1 - r0))
    pad_c = max(1, (c1 - c0))
    ring_mask = np.zeros(scene.reflectance.shape, dtype=bool)
    ring_mask[max(0, r0 - pad_r) : min(height, r1 + pad_r), max(0, c0 - pad_c) : min(width, c1 + pad_c)] = True
    ring_mask[r0:r1, c0:c1] = False
    ring = scene.reflectance[ring_mask]
    if ring.size == 0:
        return float(inside.mean()), float("nan")
    return float(inside.mean()), float(ring.mean())


def corroborate(
    detection: Detection,
    sar_acquired_at: datetime.datetime,
    optical_scenes: list[OpticalScene],
    optical_config: dict,
) -> OpticalCorroboration:
    """Emits one of the three states for one detection."""
    window_hours = float(optical_config.get("window_hours", 6.0))
    threshold = float(optical_config.get("anomaly_threshold", 0.08))

    coords = detection.geometry["coordinates"][0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    detection_bbox = (min(lons), min(lats), max(lons), max(lats))

    scene = find_coincident_scene(optical_scenes, detection_bbox, sar_acquired_at, window_hours)
    if scene is None:
        return OpticalCorroboration(
            detection_id=detection.detection_id,
            status="no_coverage",
            reasoning=(
                f"No optical acquisition intersecting this detection was found within "
                f"{window_hours:.0f} hours of the SAR acquisition. " + SAR_PRIMACY_NOTE
            ),
        )

    delta_hours = (scene.acquired_at - sar_acquired_at).total_seconds() / 3600.0
    inside_mean, ring_mean = _polygon_and_ring_means(scene, coords)
    if not np.isfinite(inside_mean) or not np.isfinite(ring_mean) or ring_mean <= 0:
        return OpticalCorroboration(
            detection_id=detection.detection_id,
            status="no_coverage",
            sensor=scene.sensor,
            acquired_at=scene.acquired_at,
            delta_hours=delta_hours,
            reasoning=(
                f"An {scene.sensor} scene was found {abs(delta_hours):.1f} hours from the SAR "
                "acquisition, but it did not cover enough sea around the detection to "
                "compute a reference statistic. " + SAR_PRIMACY_NOTE
            ),
        )

    contrast = (ring_mean - inside_mean) / ring_mean
    if abs(contrast) >= threshold:
        status = "agree"
        verdict_text = (
            f"the detection polygon is {abs(contrast):.1%} "
            f"{'darker' if contrast > 0 else 'brighter'} than the surrounding sea, "
            f"above the {threshold:.1%} threshold"
        )
    else:
        status = "disagree"
        verdict_text = (
            f"the detection polygon differs from the surrounding sea by only "
            f"{abs(contrast):.1%}, below the {threshold:.1%} threshold, so optical shows "
            "nothing unusual at this position"
        )

    return OpticalCorroboration(
        detection_id=detection.detection_id,
        status=status,
        sensor=scene.sensor,
        acquired_at=scene.acquired_at,
        delta_hours=delta_hours,
        reasoning=(
            f"{scene.sensor} acquired {abs(delta_hours):.1f} hours "
            f"{'after' if delta_hours >= 0 else 'before'} the SAR scene: {verdict_text}. "
            "Optical is corroboration only and never overrides the SAR detection, which "
            "the wind gate has already assessed."
        ),
    )
