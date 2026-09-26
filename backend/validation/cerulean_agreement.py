"""Agreement between Pharos detection and Cerulean's reviewed slick
polygons. See PLAN.md section 17.2.

VALIDATION ONLY, see the header of cerulean_client.py.

Report this as **agreement with an independent production system**,
never as accuracy. Cerulean is another model with human review on some
records, not ground truth. Two systems at different operating points
will disagree, and that disagreement is not error on either side, so
every table this module writes carries the operating point note.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from shapely.geometry import shape
from shapely.ops import unary_union

from validation.cerulean_client import ATTRIBUTION, OPERATING_POINT_NOTE


@dataclass
class SceneAgreement:
    scene_id: str
    n_cerulean_polygons: int
    n_pharos_polygons: int
    iou: float
    cerulean_area_km2: float
    pharos_area_km2: float


@dataclass
class AgreementReport:
    scenes: list[SceneAgreement] = dataclass_field(default_factory=list)

    @property
    def mean_iou(self) -> float | None:
        if not self.scenes:
            return None
        return sum(s.iou for s in self.scenes) / len(self.scenes)


# Degrees squared to square kilometres, at the latitudes this system
# works in. Good enough for a comparison table; anything that needs
# real area goes through a projected CRS.
KM2_PER_DEG2 = 111.32 * 111.32


def polygon_iou(a_geoms: list[dict], b_geoms: list[dict]) -> tuple[float, float, float]:
    """IoU between two sets of GeoJSON polygons, unioned first.

    Unioned rather than matched one to one on purpose: the two systems
    segment the same slick differently, one into three fragments and
    the other into one, and a per-polygon match would penalise a
    difference in fragmentation as if it were a difference in
    detection.
    """
    if not a_geoms or not b_geoms:
        return 0.0, _area_km2(a_geoms), _area_km2(b_geoms)

    a = unary_union([shape(g) for g in a_geoms])
    b = unary_union([shape(g) for g in b_geoms])
    intersection = a.intersection(b).area
    union = a.union(b).area
    iou = float(intersection / union) if union > 0 else 0.0
    return iou, float(a.area * KM2_PER_DEG2), float(b.area * KM2_PER_DEG2)


def _area_km2(geoms: list[dict]) -> float:
    if not geoms:
        return 0.0
    return float(unary_union([shape(g) for g in geoms]).area * KM2_PER_DEG2)


def compare_scene(
    scene_id: str,
    cerulean_features: list[dict],
    pharos_feature_collection: dict,
) -> SceneAgreement:
    """One scene's agreement figure."""
    cerulean_geoms = [f["geometry"] for f in cerulean_features if f.get("geometry")]
    pharos_geoms = [
        f["geometry"] for f in pharos_feature_collection.get("features", []) if f.get("geometry")
    ]
    iou, cerulean_area, pharos_area = polygon_iou(cerulean_geoms, pharos_geoms)
    return SceneAgreement(
        scene_id=scene_id,
        n_cerulean_polygons=len(cerulean_geoms),
        n_pharos_polygons=len(pharos_geoms),
        iou=iou,
        cerulean_area_km2=cerulean_area,
        pharos_area_km2=pharos_area,
    )


def render_markdown(report: AgreementReport) -> str:
    """The agreement table, as it goes into validation.md."""
    lines = [
        "## External agreement on detection (Cerulean, SkyTruth)",
        "",
        "This is **agreement with an independent production system**, not accuracy.",
        "Cerulean is another model with human review on some records, not ground truth.",
        "",
        OPERATING_POINT_NOTE,
        "",
    ]
    if not report.scenes:
        lines += [
            "No shared scenes were compared in this run. The harness caches every Cerulean",
            "response under `data/cerulean/`, so it runs offline after the first fetch; an",
            "empty table here means the fetch has not been run, not that agreement is zero.",
            "",
            ATTRIBUTION,
            "",
        ]
        return "\n".join(lines)

    lines += [
        "| scene | Cerulean polygons | Pharos polygons | IoU | Cerulean km2 | Pharos km2 |",
        "|---|---|---|---|---|---|",
    ]
    for s in report.scenes:
        lines.append(
            f"| `{s.scene_id}` | {s.n_cerulean_polygons} | {s.n_pharos_polygons} | "
            f"{s.iou:.3f} | {s.cerulean_area_km2:.2f} | {s.pharos_area_km2:.2f} |"
        )
    mean_iou = report.mean_iou
    lines += [
        "",
        f"Mean IoU across {len(report.scenes)} shared scene(s): "
        f"{mean_iou:.3f}" if mean_iou is not None else "",
        "",
        ATTRIBUTION,
        "",
    ]
    return "\n".join(lines)
