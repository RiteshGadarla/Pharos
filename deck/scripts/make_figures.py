"""Produces the four P-1 deck figures. See PLAN.md section 19.

Throwaway. Do not let this become the real pipeline, and do not import
it from anything under backend/.

It reads backend/data/precomputed/demo_bundle.json, the output of a real
end to end run on the committed fixtures, rather than standing up a
second parallel OpenDrift script. See deck/README.md for why, and for
what is and is not real in that bundle.

Run from the repository root:
    backend/.venv/bin/python deck/scripts/make_figures.py
"""

from __future__ import annotations

import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUNDLE_PATH = os.path.join(REPO_ROOT, "backend", "data", "precomputed", "demo_bundle.json")
FIGURES_DIR = os.path.join(REPO_ROOT, "deck", "figures")

# The chart palette from PLAN.md section 16. The figures have to sit
# beside screenshots of the console without looking like a different
# product.
INK = "#0A1E29"
PANEL = "#102C3A"
GRATICULE = "#2E5567"
PAPER = "#E9E3D2"
MUTED = "#90A5AF"
OIL = "#F2A03D"
SUSPECT = "#D6455E"
CLEARED = "#4E7C6B"
RADAR = "#7FB2C4"

# Single hue, transparent at zero mass through to --oil at the peak.
# Never a rainbow ramp: a rainbow makes uncertainty look like structure.
OIL_RAMP = LinearSegmentedColormap.from_list(
    "oil_ramp", [(0, (0.949, 0.627, 0.239, 0.0)), (1, (0.949, 0.627, 0.239, 1.0))]
)


def load_bundle() -> dict:
    if not os.path.exists(BUNDLE_PATH):
        sys.exit(
            f"No demo bundle at {BUNDLE_PATH}. Build it first:\n"
            "  cd backend && PYTHONPATH=. .venv/bin/python scripts/seed_demo.py"
        )
    with open(BUNDLE_PATH) as f:
        return json.load(f)


def _style(ax, title: str = "", xlabel: str = "longitude", ylabel: str = "latitude") -> None:
    ax.set_facecolor(INK)
    for spine in ax.spines.values():
        spine.set_color(GRATICULE)
    ax.tick_params(colors=MUTED, labelsize=7)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=8)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=8)
    if title:
        ax.set_title(title, color=PAPER, fontsize=10, loc="left")


def _figure(width: float, height: float):
    fig, ax = plt.subplots(figsize=(width, height))
    fig.patch.set_facecolor(INK)
    return fig, ax


def _save(fig, name: str) -> None:
    os.makedirs(FIGURES_DIR, exist_ok=True)
    path = os.path.join(FIGURES_DIR, name)
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  wrote {os.path.relpath(path, REPO_ROOT)}")


def figure_1_slick_on_sar(bundle: dict) -> None:
    """The detected slick, on the scene it came from, with the gate verdict."""
    fig, ax = _figure(7, 6)
    scene = bundle["scene"]
    minlon, minlat, maxlon, maxlat = scene["bbox"]

    preview_path = os.path.join(REPO_ROOT, "backend", "data", "precomputed", "scene_preview.png")
    if os.path.exists(preview_path):
        image = plt.imread(preview_path)
        bounds = scene.get("preview", {}).get("bounds", scene["bbox"])
        ax.imshow(image, extent=[bounds[0], bounds[2], bounds[1], bounds[3]], origin="upper")

    for det in bundle["detections"]:
        coords = det["geometry"]["coordinates"][0]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        suppressed = det["gate"]["verdict"] == "suppress"
        ax.fill(xs, ys, color=MUTED if suppressed else OIL, alpha=0.35)
        ax.plot(xs, ys, color=MUTED if suppressed else OIL, linewidth=2)

    gate = bundle["detections"][0]["gate"] if bundle["detections"] else None
    _style(ax, f"Detected slick, {scene['scene_id']}")
    ax.set_xlim(minlon, maxlon)
    ax.set_ylim(minlat, maxlat)
    ax.set_aspect("equal", adjustable="box")
    if gate:
        ax.text(
            0.02, 0.02,
            f"wind gate: {gate['verdict']} at {gate['wind_speed_ms']:.1f} m/s",
            transform=ax.transAxes, color=PAPER, fontsize=8,
            family="monospace", va="bottom",
        )
    _save(fig, "01_slick_on_sar.png")


def figure_2_origin_field(bundle: dict) -> None:
    """The money image. Protect this one above all the others.

    Three time slices side by side, so the single frame carries the
    whole argument: the answer is not a point, it is a distribution over
    space AND time, and it widens as the hindcast runs backwards.
    """
    field = bundle["origin_field"]
    grid = np.array(field["grid"])
    n_t = grid.shape[0]
    indices = [0, n_t // 2, n_t - 1]

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6))
    fig.patch.set_facecolor(INK)
    extent = [min(field["lon"]), max(field["lon"]), min(field["lat"]), max(field["lat"])]

    for ax, ti in zip(axes, indices):
        slice_ = grid[ti]
        # Normalised per slice, deliberately. The same probability mass
        # covers steadily more ground as the hindcast runs back and the
        # peak density falls by over an order of magnitude, so a single
        # global scale renders the earliest slice as almost nothing,
        # which reads as "there is nothing here" rather than "little is
        # known here". The spread is printed on each panel instead.
        peak = slice_.max() or 1.0
        ax.imshow(slice_ / peak, extent=extent, origin="lower", cmap=OIL_RAMP, aspect="auto", vmin=0, vmax=1)
        label = field["time"][ti].replace("T", " ")[:16]
        _style(ax, f"{label} UTC")
        ax.text(
            0.03, 0.95, f"spread {_spread_km(field, ti):.1f} km",
            transform=ax.transAxes, color=PAPER, fontsize=8, family="monospace", va="top",
        )

    fig.suptitle(
        f"Origin probability field, ensemble n={field['n_members']}, seed={field['seed']}. "
        "Not a point, a probability over space and time.",
        color=PAPER, fontsize=11,
    )
    fig.tight_layout()
    _save(fig, "02_origin_field.png")


def _spread_km(field: dict, ti: int) -> float:
    """Mass-weighted RMS distance of one time slice from its own centroid."""
    slice_ = np.array(field["grid"][ti])
    mass = slice_.sum()
    if mass <= 0:
        return 0.0
    weights = slice_ / mass
    lat = np.array(field["lat"])
    lon = np.array(field["lon"])
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    centre_lat = float((weights * lat_grid).sum())
    centre_lon = float((weights * lon_grid).sum())
    dlat_km = (lat_grid - centre_lat) * 111.32
    dlon_km = (lon_grid - centre_lon) * 111.32 * np.cos(np.radians(centre_lat))
    return float(np.sqrt((weights * (dlat_km**2 + dlon_km**2)).sum()))


def figure_3_ais_over_field(bundle: dict) -> None:
    """Every vessel over the field, with the culprit's dark gap dashed
    and its dead-reckoned envelope drawn as a polygon."""
    fig, ax = _figure(9, 7.5)
    field = bundle["origin_field"]
    grid = np.array(field["grid"])
    collapsed = grid.max(axis=0)  # for orientation only, never for scoring
    extent = [min(field["lon"]), max(field["lon"]), min(field["lat"]), max(field["lat"])]
    ax.imshow(
        collapsed / (collapsed.max() or 1.0),
        extent=extent, origin="lower", cmap=OIL_RAMP, aspect="auto", vmin=0, vmax=1,
    )

    culprit = bundle["culprit_mmsi"]
    for vessel in bundle["vessels"]:
        lons = [p["lon"] for p in vessel["points"]]
        lats = [p["lat"] for p in vessel["points"]]
        if vessel["status"] == "eliminated":
            color, width, z = CLEARED, 1.2, 2
        elif vessel["mmsi"] == culprit:
            color, width, z = SUSPECT, 2.4, 5
        else:
            color, width, z = MUTED, 1.4, 3
        ax.plot(lons, lats, color=color, linewidth=width, zorder=z)

        for gap in vessel["dark_gaps"]:
            coords = gap["envelope"]["coordinates"][0]
            ax.fill(
                [c[0] for c in coords], [c[1] for c in coords],
                color=color, alpha=0.10, zorder=z - 1,
            )
            ax.plot(
                [gap["entry_point"][0], gap["exit_point"][0]],
                [gap["entry_point"][1], gap["exit_point"][1]],
                color=color, linewidth=2, linestyle=(0, (4, 3)), zorder=z + 1,
            )

    radar = bundle.get("radar_crosscheck", {})
    for target in radar.get("targets", []):
        lon, lat = target["centroid"]
        if target["matched_mmsi"] is None:
            ax.scatter([lon], [lat], s=70, facecolor=RADAR, edgecolor=PAPER, linewidth=1.2, zorder=8)
            ax.annotate(
                "unmatched radar target", (lon, lat), textcoords="offset points",
                xytext=(8, 8), color=RADAR, fontsize=8, family="monospace", zorder=8,
            )
        else:
            ax.scatter([lon], [lat], s=50, facecolor="none", edgecolor=RADAR, linewidth=1.2, zorder=7)

    _style(ax, "AIS traffic through the origin field")
    ax.text(
        0.02, 0.02,
        f"rank 1 {culprit} in red, eliminated vessels in green, dark periods dashed with their\n"
        "dead-reckoned reachable envelope. Field shown collapsed over time for orientation only.",
        transform=ax.transAxes, color=MUTED, fontsize=7.5, family="monospace", va="bottom",
    )
    _save(fig, "03_ais_over_field.png")


def figure_4_scoring_table(bundle: dict) -> str:
    """The scoring table and the elimination log, as terminal text.

    Terminal output reads as real in a way a mockup never does, which is
    the whole reason this one is not a rendered chart.
    """
    factor_order = [
        "field_integral", "dark_overlap", "axis_alignment", "speed_anomaly",
        "course_anomaly", "vessel_plausibility", "ais_integrity", "radar_confirmed_dark",
    ]
    short = {
        "field_integral": "F1", "dark_overlap": "F2", "axis_alignment": "F3",
        "speed_anomaly": "F4", "course_anomaly": "F5", "vessel_plausibility": "F6",
        "ais_integrity": "F7", "radar_confirmed_dark": "F8",
    }
    vessel_type = {v["mmsi"]: v["vessel_type"] for v in bundle["vessels"]}

    lines = [
        f"PHAROS  case {bundle['case_id']}",
        f"verdict  {bundle.get('verdict', {}).get('verdict', 'n/a')}",
        "",
        "RANKED SUSPECTS",
        "",
    ]
    header = f"{'rank':>4}  {'mmsi':<10} {'type':<8} {'total':>8}  " + "  ".join(
        f"{short[f]:>7}" for f in factor_order
    )
    lines += [header, "-" * len(header)]
    for s in bundle["suspects"]:
        row = (
            f"{s['rank']:>4}  {s['mmsi']:<10} {vessel_type.get(s['mmsi'], ''):<8} {s['total']:>8.3f}  "
            + "  ".join(f"{s['factors'].get(f, 0.0):>7.3f}" for f in factor_order)
        )
        lines.append(row)

    lines += ["", "ELIMINATED, WITH THE REASON RECORDED FOR EACH", ""]
    for e in bundle["eliminations"]:
        lines.append(f"  {e['mmsi']}  [{e['rule']}]")
        lines.append(f"    {e['reason']}")
    if not bundle["eliminations"]:
        lines.append("  none")

    lines += [
        "",
        "F1 field integral   F2 dark overlap   F3 axis alignment   F4 speed anomaly",
        "F5 course anomaly   F6 vessel plausibility (downweights only, never eliminates)",
        "F7 AIS integrity    F8 radar confirmed dark",
        "",
        "Weights are in backend/config/scoring.yaml and are printed verbatim in the dossier.",
        "No classifier is trained for attribution.",
    ]

    text = "\n".join(lines)
    os.makedirs(FIGURES_DIR, exist_ok=True)
    path = os.path.join(FIGURES_DIR, "04_scoring_table.txt")
    with open(path, "w") as f:
        f.write(text + "\n")
    print(f"  wrote {os.path.relpath(path, REPO_ROOT)}")
    return text


def main() -> None:
    bundle = load_bundle()
    print("Building deck figures from the precomputed demo bundle...")
    figure_1_slick_on_sar(bundle)
    figure_2_origin_field(bundle)
    figure_3_ais_over_field(bundle)
    text = figure_4_scoring_table(bundle)
    print()
    print(text)


if __name__ == "__main__":
    main()
