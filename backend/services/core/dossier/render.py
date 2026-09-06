"""Renders the case dossier PDF. See PLAN.md section 15.

Takes the same demo_bundle.json-shaped dict scripts/seed_demo.py already
builds and services/core/app.py already serves at GET /api/demo, so the
PDF and the frontend are always describing the same run. Adds only what
the bundle doesn't carry: file hashes, the git commit, and the scoring
config verbatim, which is what turns this from a report into a case
file. The provenance page and the Section 63 certificate together are
the point: they are what makes this a case file rather than a dashboard.

Everything plotted here is redrawn from the bundle's own numbers with
matplotlib, not a captured screenshot: the footprint, the origin field
snapshots and the factor bars are all regenerated from the same
detections, origin_field grid and suspects the frontend renders.
"""

from __future__ import annotations

import hashlib
import io
import subprocess
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from services.core.dossier.bsa63 import ADMISSIBILITY_NOTE, build_certificate

PAGE_SIZE = A4
MARGIN = 2 * cm

VERDICT_BLURB = {
    "ATTRIBUTED": (
        "One vessel dominates the ranking and was broadcasting throughout the origin "
        "window. This is a ranked evidence package for a human investigator."
    ),
    "RANKED": (
        "Several vessels remain plausible and none dominates. The ranked list, the factor "
        "breakdown behind each score and the full elimination log narrow the field."
    ),
    "DARK_CONFIRMED": (
        "No broadcasting vessel is a plausible candidate, and the SAR scene itself shows a "
        "hull inside the origin envelope that AIS never reported. This is a positive "
        "finding, not an absence of one."
    ),
}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown (not a git checkout, or git unavailable)"


def _fig_to_image(fig: "plt.Figure", width_cm: float) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    width = width_cm * cm
    aspect = fig.get_figheight() / fig.get_figwidth()
    return Image(buf, width=width, height=width * aspect)


GATE_COLORS = {"accept": "#F2A03D", "downgrade": "#c98a3a", "suppress": "#90A5AF"}


def _footprint_figure(bundle: dict) -> "plt.Figure":
    fig, ax = plt.subplots(figsize=(6, 5))
    minlon, minlat, maxlon, maxlat = bundle["scene"]["bbox"]
    ax.set_xlim(minlon, maxlon)
    ax.set_ylim(minlat, maxlat)
    for det in bundle["detections"]:
        coords = det["geometry"]["coordinates"][0]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        color = GATE_COLORS.get(det["gate"]["verdict"], "#90A5AF")
        ax.fill(xs, ys, color=color, alpha=0.6, edgecolor=color)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(f"Scene footprint, {bundle['scene']['scene_id']}")
    ax.set_aspect("equal", adjustable="box")
    return fig


def _origin_field_figure(bundle: dict, time_index: int) -> "plt.Figure":
    field = bundle["origin_field"]
    grid = np.array(field["grid"][time_index])
    fig, ax = plt.subplots(figsize=(4, 3.5))
    extent = [min(field["lon"]), max(field["lon"]), min(field["lat"]), max(field["lat"])]
    ax.imshow(grid, extent=extent, origin="lower", cmap="Oranges", aspect="auto")
    ax.set_title(field["time"][time_index][:16].replace("T", " ") + " UTC")
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    return fig


def _factor_bar_figure(factors: dict[str, float]) -> "plt.Figure":
    names = list(factors.keys())
    values = [factors[n] for n in names]
    fig, ax = plt.subplots(figsize=(6, 2.2))
    colors_list = ["#F2A03D" if v >= 0 else "#4E7C6B" for v in values]
    ax.barh(names, values, color=colors_list)
    ax.axvline(0, color="#2E5567", linewidth=0.8)
    ax.set_xlabel("contribution")
    return fig


def _tri_state(value) -> str:
    """A tri-state condition rendered honestly. None is "not evaluated",
    which is a different claim from "no", and the dossier must not
    collapse the two."""
    if value is None:
        return "not evaluated"
    return "yes" if value else "no"


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Disclaimer", parent=styles["BodyText"], textColor=colors.HexColor("#555555")))
    return styles


def _table(data: list[list[str]], col_widths: list[float] | None = None) -> Table:
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102C3A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f3ee")]),
            ]
        )
    )
    return t


def render_dossier(bundle: dict, scoring_config_text: str, artifact_paths: dict[str, str], out_path: str) -> None:
    """Renders the full case dossier PDF to out_path. artifact_paths maps
    a human-readable label to a file path; every one is hashed onto the
    provenance page."""
    styles = _styles()
    story: list = []

    # --- Cover ---
    story.append(Spacer(1, 4 * cm))
    story.append(Paragraph("DRISHTA", ParagraphStyle(name="Wordmark", fontSize=28, leading=32)))
    story.append(Paragraph("Case dossier", styles["Title"]))
    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph(f"Case ID: {bundle['case_id']}", styles["Normal"]))
    story.append(Paragraph(f"Generated: {datetime.now(timezone.utc).isoformat()}", styles["Normal"]))
    verdict = bundle.get("verdict")
    if verdict:
        story.append(Spacer(1, 0.4 * cm))
        story.append(
            Paragraph(
                f"Verdict class: <b>{verdict['verdict']}</b>",
                ParagraphStyle(name="VerdictLine", fontSize=13, leading=16),
            )
        )
        story.append(Paragraph(VERDICT_BLURB.get(verdict["verdict"], ""), styles["Disclaimer"]))
        story.append(Paragraph(verdict["reasoning"], styles["Disclaimer"]))
    story.append(Spacer(1, 1 * cm))
    story.append(
        Paragraph(
            "This document is ranked evidence for a human investigator. It is not "
            "an automated accusation. Every vessel is ranked by an explicit, "
            "weighted evidence model with named factors, defined in "
            "config/scoring.yaml (reproduced verbatim on the provenance page), "
            "not by a trained classifier. Vessel type never eliminates a vessel, "
            "it only downweights its score. Every eliminated vessel carries a "
            "stated reason, listed in full later in this document.",
            styles["Disclaimer"],
        )
    )
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(bundle["status_note"], styles["Disclaimer"]))
    incident_context = bundle.get("incident_context")
    if incident_context:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(f"Status: {incident_context['status']}", styles["Disclaimer"]))
        story.append(Paragraph(f"Source reference: {incident_context['source_reference']}", styles["Disclaimer"]))
    story.append(PageBreak())

    # --- Scene ---
    story.append(Paragraph("Scene", styles["Heading1"]))
    scene = bundle["scene"]
    story.append(
        _table(
            [
                ["field", "value"],
                ["scene id", scene["scene_id"]],
                ["acquired", scene["acquired_at"]],
                ["sensor", scene.get("sensor", "S1")],
                ["crs", scene["crs"]],
                ["bbox", ", ".join(f"{v:.4f}" for v in scene["bbox"])],
                ["source", scene["source_path"]],
            ],
            col_widths=[4 * cm, 12 * cm],
        )
    )
    story.append(Paragraph(scene["note"], styles["Disclaimer"]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(_fig_to_image(_footprint_figure(bundle), width_cm=14))
    story.append(PageBreak())

    # --- Detection ---
    story.append(Paragraph("Detection", styles["Heading1"]))
    story.append(
        Paragraph(
            "Per-class IoU on a held-out split (PLAN.md section 5, P3) is not "
            "available in this build: it is blocked on obtaining the labeled "
            "oil-spill segmentation dataset (PLAN.md section 4A item 4). This "
            "dossier does not report a substitute number.",
            styles["Disclaimer"],
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    det_rows = [["detection id", "class", "mean prob", "gate verdict", "gate reason"]]
    for d in bundle["detections"]:
        det_rows.append(
            [d["detection_id"], d["class_name"], f"{d['mean_class_prob']:.2f}", d["gate"]["verdict"], d["gate"]["reason"]]
        )
    story.append(_table(det_rows, col_widths=[3.2 * cm, 1.8 * cm, 1.8 * cm, 2.2 * cm, 7 * cm]))

    optical = bundle.get("optical")
    if optical:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph("Optical corroboration", styles["Heading2"]))
        story.append(
            _table(
                [
                    ["field", "value"],
                    ["status", optical["status"]],
                    ["sensor", optical.get("sensor") or "none"],
                    ["acquired", optical.get("acquired_at") or "n/a"],
                    [
                        "offset from SAR (h)",
                        f"{optical['delta_hours']:.1f}" if optical.get("delta_hours") is not None else "n/a",
                    ],
                ],
                col_widths=[5 * cm, 11 * cm],
            )
        )
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(optical["reasoning"], styles["BodyText"]))
    story.append(PageBreak())

    # --- Slick features ---
    story.append(Paragraph("Slick characterisation", styles["Heading1"]))
    sf = bundle["slick_features"]
    story.append(
        _table(
            [
                ["field", "value"],
                ["area (km2)", f"{sf['area_km2']:.3f}"],
                ["perimeter (km)", f"{sf['perimeter_km']:.3f}"],
                ["complexity ratio", f"{sf['complexity_ratio']:.2f}"],
                ["major axis (deg)", f"{sf['major_axis_deg']:.1f}"],
                ["elongation", f"{sf['elongation']:.2f}"],
                ["mean backscatter (dB)", f"{sf['mean_backscatter_db']:.1f}"],
                ["contrast (dB)", f"{sf['contrast_db']:.1f}"],
                ["age band", sf["age_band"]],
            ],
            col_widths=[5 * cm, 11 * cm],
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(sf["age_reasoning"], styles["BodyText"]))
    story.append(
        Paragraph(
            "Absolute slick age in hours cannot be estimated reliably from a "
            "single SAR acquisition. This is a relative band with stated "
            "reasoning, never a number in hours.",
            styles["Disclaimer"],
        )
    )

    # The band is not just characterisation, it is the case's only
    # evidence about WHEN. Stating it here, next to the reasoning that
    # produced it, is what lets a reader follow it through to the
    # ranking rather than meeting a weighted field integral cold.
    ow = bundle.get("origin_window")
    if ow:
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Origin time window", styles["Heading2"]))
        story.append(
            _table(
                [
                    ["age band", ow["age_band"]],
                    [
                        "discharge window",
                        f"{ow['earliest_hours_before']:.0f} to {ow['latest_hours_before']:.0f} "
                        "hours before acquisition",
                    ],
                    ["taper", f"{ow['taper_hours']:.0f} hours either side"],
                    ["weight outside the window", f"{ow['floor_weight']:.2f}"],
                ],
                col_widths=[5 * cm, 11 * cm],
            )
        )
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(ow["statement"], styles["BodyText"]))
        story.append(
            Paragraph(
                "This window weights the origin field's time axis in factors F1 and F2. "
                "It downweights timesteps outside the band and never excludes them: the "
                "weight floors at the value above rather than at zero, so the age band "
                "cannot clear a vessel on its own.",
                styles["Disclaimer"],
            )
        )
    story.append(PageBreak())

    # --- Origin field ---
    story.append(Paragraph("Origin probability field", styles["Heading1"]))
    field = bundle["origin_field"]
    story.append(
        Paragraph(
            f"Ensemble size n={field['n_members']}, seed={field['seed']}, drift kernel "
            f"{field.get('kernel', 'openoil')}, window "
            f"{field['t_min']} to {field['t_max']}. The field sums to 1 over the "
            "whole space-time volume and is never collapsed to a point before "
            f"scoring (PLAN.md non-negotiable 1). Forcing: {field.get('forcing_source', 'unspecified')}.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    n_t = len(field["time"])
    snapshot_indices = sorted({0, n_t // 2, n_t - 1})
    imgs = [_fig_to_image(_origin_field_figure(bundle, i), width_cm=5) for i in snapshot_indices]
    story.append(Table([imgs], colWidths=[5.3 * cm] * len(imgs)))
    story.append(PageBreak())

    # --- Radar cross check ---
    radar = bundle.get("radar_crosscheck")
    if radar:
        story.append(Paragraph("Radar cross check", styles["Heading1"]))
        story.append(
            Paragraph(
                f"{radar['n_targets']} ship target(s) were extracted from the SAR scene. "
                f"{radar['n_matched']} were associated with a broadcasting vessel at the "
                f"acquisition instant within {radar.get('match_radius_m', 'the configured')} "
                f"metres; {radar['n_unmatched']} were not. An unmatched target is a hull the "
                "radar photographed that AIS did not report.",
                styles["BodyText"],
            )
        )
        story.append(Spacer(1, 0.3 * cm))
        radar_rows = [["target", "lat", "lon", "px", "matched MMSI", "field mass", "in dark envelope of"]]
        for t in radar.get("targets", []):
            lon, lat = t["centroid"]
            mass = t.get("field_mass")
            radar_rows.append(
                [
                    t["target_id"],
                    f"{lat:.4f}",
                    f"{lon:.4f}",
                    str(t["pixel_area"]),
                    t.get("matched_mmsi") or "unmatched",
                    f"{mass:.2e}" if mass else "n/a",
                    ", ".join(t.get("envelope_hits", [])) or "none",
                ]
            )
        story.append(_table(radar_rows, col_widths=[3.6 * cm, 2 * cm, 2 * cm, 1.2 * cm, 2.6 * cm, 2.2 * cm, 2.4 * cm]))
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Limitations of this cross check", styles["Heading2"]))
        for caveat in radar.get("caveats", []):
            story.append(Paragraph(f"- {caveat}", styles["Disclaimer"]))
        story.append(PageBreak())

    # --- Suspects ---
    story.append(Paragraph("Suspects", styles["Heading1"]))
    vessel_by_mmsi = {v["mmsi"]: v for v in bundle["vessels"]}
    sus_rows = [["rank", "mmsi", "type", "total", "radar support"]]
    for s in bundle["suspects"]:
        v = vessel_by_mmsi.get(s["mmsi"], {})
        sus_rows.append(
            [
                str(s["rank"]),
                s["mmsi"],
                v.get("vessel_type", ""),
                f"{s['total']:.2f}",
                s.get("radar_support") or "none",
            ]
        )
    story.append(_table(sus_rows, col_widths=[1.5 * cm, 3 * cm, 3 * cm, 2.5 * cm, 6 * cm]))
    story.append(PageBreak())

    for s in bundle["suspects"][:3]:
        v = vessel_by_mmsi.get(s["mmsi"], {})
        story.append(Paragraph(f"Rank {s['rank']}: {s['mmsi']} ({v.get('vessel_type', 'unknown type')})", styles["Heading2"]))
        story.append(_fig_to_image(_factor_bar_figure(s["factors"]), width_cm=14))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(s["narrative"], styles["BodyText"]))
        story.append(PageBreak())

    # --- Eliminations ---
    story.append(Paragraph("Elimination log", styles["Heading1"]))
    elim_rows = [["mmsi", "type", "rule", "reason"]]
    for e in bundle["eliminations"]:
        v = vessel_by_mmsi.get(e["mmsi"], {})
        elim_rows.append([e["mmsi"], v.get("vessel_type", ""), e["rule"], e["reason"]])
    if len(elim_rows) == 1:
        story.append(Paragraph("No vessel was eliminated in this scenario.", styles["BodyText"]))
    else:
        story.append(_table(elim_rows, col_widths=[2.5 * cm, 2 * cm, 3.5 * cm, 8 * cm]))
    story.append(PageBreak())

    # --- MARPOL assessment ---
    marpol = bundle.get("marpol")
    if marpol:
        story.append(Paragraph("MARPOL Annex I assessment", styles["Heading1"]))
        story.append(
            Paragraph(
                "This is a screening aid for a human investigator. It reports which Annex I "
                "conditions the reconstructed behaviour appears not to satisfy. It is not a "
                "determination that any regulation was breached, and it never can be: oil "
                "content in parts per million is not observable from satellite.",
                styles["Disclaimer"],
            )
        )
        story.append(Spacer(1, 0.3 * cm))
        band = marpol.get("est_discharge_l_per_nm")
        story.append(
            _table(
                [
                    ["condition", "finding"],
                    ["vessel", marpol["mmsi"]],
                    ["proceeding en route", _tri_state(marpol.get("en_route"))],
                    [
                        "distance to nearest land (nm)",
                        f"{marpol['distance_to_land_nm']:.1f}" if marpol.get("distance_to_land_nm") is not None else "not evaluated",
                    ],
                    ["inside a special area", _tri_state(marpol.get("in_special_area"))],
                    [
                        "estimated discharge (l/nm)",
                        f"{band[0]:.0f} to {band[1]:.0f} (a band, never a single figure)" if band else "not evaluated",
                    ],
                    ["flag", marpol["flag"]],
                ],
                col_widths=[6 * cm, 10 * cm],
            )
        )
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Assumptions, verbatim", styles["Heading2"]))
        for assumption in marpol.get("assumptions", []):
            story.append(Paragraph(f"- {assumption}", styles["Disclaimer"]))
        story.append(PageBreak())

    # --- Infrastructure flag ---
    infrastructure = bundle.get("infrastructure")
    if infrastructure:
        story.append(Paragraph("Offshore infrastructure overlap", styles["Heading1"]))
        story.append(Paragraph(infrastructure["statement"], styles["BodyText"]))
        story.append(
            Paragraph(
                "This flag never eliminates a vessel and never accuses an installation. It "
                "exists because the most damaging failure mode of an attribution engine is "
                "being confidently wrong about a vessel when the answer was a platform.",
                styles["Disclaimer"],
            )
        )
        story.append(PageBreak())

    # --- Provenance ---
    story.append(Paragraph("Provenance", styles["Heading1"]))
    story.append(Paragraph(f"Git commit: {git_commit_hash()}", styles["BodyText"]))
    story.append(
        Paragraph(
            "Detection model: sahilvishwa2108/oil-spill-deeplab (HuggingFace). "
            "The model card's own self-reported F1 (0.9668) is not reproduced "
            "here or anywhere in this system: see PLAN.md section 5 for why an "
            "unbroken-down, background-dominated figure is not meaningful for "
            "the oil class.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    hash_rows = [["artifact", "sha-256"]]
    artifact_hashes: dict[str, str] = {}
    for label, path in artifact_paths.items():
        try:
            digest = sha256_file(path)
        except OSError:
            digest = f"unavailable: {path}"
        artifact_hashes[label] = digest
        hash_rows.append([label, digest])
    story.append(_table(hash_rows, col_widths=[5 * cm, 11 * cm]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Scoring configuration (config/scoring.yaml, verbatim)", styles["Heading2"]))
    mono = ParagraphStyle(name="Mono", fontName="Courier", fontSize=6.5, leading=8)
    for line in scoring_config_text.splitlines():
        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") or "&nbsp;"
        story.append(Paragraph(safe, mono))

    # --- Section 63 certificate ---
    story.append(PageBreak())
    story.append(
        Paragraph("Certificate under Section 63, Bharatiya Sakshya Adhiniyam, 2023", styles["Heading1"])
    )
    story.append(Paragraph(ADMISSIBILITY_NOTE, styles["Disclaimer"]))
    story.append(Spacer(1, 0.4 * cm))
    certificate = build_certificate(
        bundle,
        artifact_hashes=artifact_hashes,
        git_commit=git_commit_hash(),
        kernel=bundle.get("origin_field", {}).get("kernel", "openoil"),
    )
    story.append(Paragraph("Part A", styles["Heading2"]))
    story.append(_table([["field", "value"]] + [list(row) for row in certificate.as_rows()], col_widths=[5 * cm, 11 * cm]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Part B", styles["Heading2"]))
    story.append(Paragraph(certificate.part_b_blank_reason, styles["BodyText"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(
        _table(
            [
                ["field", "to be completed by hand"],
                ["Name", ""],
                ["Designation", ""],
                ["Organisation", ""],
                ["Date", ""],
                ["Signature", ""],
            ],
            col_widths=[5 * cm, 11 * cm],
        )
    )

    doc = SimpleDocTemplate(
        out_path, pagesize=PAGE_SIZE,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
        title=f"DRISHTA case dossier {bundle['case_id']}",
    )
    doc.build(story)
