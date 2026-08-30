"""Measures false-positive reduction from the wind gate, PLAN.md section 6:
"Assemble a small set of scenes containing known look-alikes and known
slicks, and report false positives before the gate versus after. That
number goes on the slide, not the model card's number."

There is no curated real dataset available yet (PLAN.md section 4A).
This uses a small synthetic curated set instead, built from the same
wind zones as data/fixtures/synthetic_wind.nc, with ground truth labels
assigned by construction. The output is explicitly labeled as synthetic
and must never be presented as a measurement on real imagery.

Run: python3 scripts/measure_wind_gate.py
"""

from __future__ import annotations

import numpy as np
import yaml

from services.core.gate.wind import gate_detections, load_wind_field
from services.core.schemas import Detection

WIND_FIXTURE = "data/fixtures/synthetic_wind.nc"
ACQUIRED_AT = np.datetime64("2026-01-15T02:30:00")
OUT_PATH = "data/processed/wind_gate_evaluation.md"


def _square_detection(detection_id: str, center_lon: float, center_lat: float, half=0.01) -> Detection:
    coords = [
        [center_lon - half, center_lat - half],
        [center_lon - half, center_lat + half],
        [center_lon + half, center_lat + half],
        [center_lon + half, center_lat - half],
        [center_lon - half, center_lat - half],
    ]
    return Detection(
        detection_id=detection_id,
        scene_id="SYNTHETIC-CURATED",
        class_name="oil",
        geometry={"type": "Polygon", "coordinates": [coords]},
        mean_class_prob=0.8,
        pixel_area=1000,
    )


# (detection_id, lon, ground_truth) ground_truth is "oil" or "look_alike".
# Three real oil detections sit in the valid wind window. Three
# look-alikes: one in low wind (the classic false-calm case), one in
# high wind (slick breakup), and one that ALSO happens to sit in the
# valid wind window, deliberately, because not every look-alike is
# wind-driven and the gate should not be credited with catching those.
CURATED_SET = [
    ("oil-1", 73.0, "oil"),
    ("oil-2", 73.05, "oil"),
    ("oil-3", 72.95, "oil"),
    ("lookalike-low-wind", 72.2, "look_alike"),
    ("lookalike-high-wind", 73.4, "look_alike"),
    ("lookalike-valid-wind", 73.02, "look_alike"),
]


def main() -> None:
    with open("config/pipeline.yaml") as f:
        wind_config = yaml.safe_load(f)["wind_gate"]
    wind_ds = load_wind_field(WIND_FIXTURE)

    detections = [_square_detection(det_id, lon, 19.5) for det_id, lon, _ in CURATED_SET]
    truth = {det_id: label for det_id, _, label in CURATED_SET}

    results = gate_detections(detections, wind_ds, ACQUIRED_AT, wind_config)
    verdict_by_id = {r.detection_id: r.verdict for r in results}

    # Before the gate: every raw detection is treated as a positive.
    fp_before = sum(1 for det_id, label in truth.items() if label == "look_alike")
    tp_before = sum(1 for det_id, label in truth.items() if label == "oil")

    # After the gate: a positive is anything not suppressed.
    kept = {det_id for det_id, verdict in verdict_by_id.items() if verdict != "suppress"}
    fp_after = sum(1 for det_id in kept if truth[det_id] == "look_alike")
    tp_after = sum(1 for det_id in kept if truth[det_id] == "oil")

    reduction_pct = 100.0 * (fp_before - fp_after) / fp_before if fp_before else 0.0

    lines = [
        "# Wind gate false-positive reduction",
        "",
        "SYNTHETIC MEASUREMENT. This is a small synthetic curated set built "
        "from data/fixtures/synthetic_wind.nc, not real Sentinel-1 scenes. "
        "PLAN.md section 4A blocks assembling a real curated set until "
        "Sentinel-1 access exists. Re-run this script against real scenes "
        "before this number goes on a slide.",
        "",
        "| detection | wind zone lon | ground truth | verdict | kept after gate |",
        "|---|---|---|---|---|",
    ]
    for det_id, lon, label in CURATED_SET:
        verdict = verdict_by_id[det_id]
        kept_flag = "yes" if verdict != "suppress" else "no"
        lines.append(f"| {det_id} | {lon} | {label} | {verdict} | {kept_flag} |")

    lines += [
        "",
        f"- True positives before gate: {tp_before}, after gate: {tp_after}",
        f"- False positives before gate: {fp_before}, after gate: {fp_after}",
        f"- False positive reduction: {reduction_pct:.1f}%",
        "",
        "The gate is wind-physics only. It catches look-alikes whose false "
        "signal depends on wind conditions (too calm, or slick breakup at "
        "high wind). It does not and cannot catch a look-alike that occurs "
        "under otherwise valid wind conditions (lookalike-valid-wind, "
        "above), which is why false positives are reduced, not eliminated.",
    ]

    with open(OUT_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")

    print("\n".join(lines))
    print(f"\nwrote {OUT_PATH}")


if __name__ == "__main__":
    main()
