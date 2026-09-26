"""Bharatiya Sakshya Adhiniyam, 2023, Section 63 certificate.
See PLAN.md section 15.

Section 63 governs the admissibility of electronic records in Indian
proceedings. Its Schedule has two parts: Part A, which describes the
device or system, the record produced, and the hash of the record, and
Part B, which is signed by an expert. This module fills in Part A from
information the pipeline already carries, and leaves Part B blank,
because that is what the statute requires: a signature is a human act.

What this module claims: the dossier is formatted to carry the
information the certificate requires.

What it does not claim, and what no code here may be changed to claim:
that the document is admissible. Admissibility is decided by a court on
the facts, including who signed Part B and whether they can speak to
the system. Anything stronger than the wording below is a claim the
software cannot support.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone

HASH_ALGORITHM = "SHA-256"

ADMISSIBILITY_NOTE = (
    "This certificate is pre-filled with the information Section 63 of the Bharatiya "
    "Sakshya Adhiniyam, 2023 requires in Part A of its Schedule. It is not a claim that "
    "this document is admissible. Part B is deliberately left blank: the statute requires "
    "it to be completed and signed by a person occupying a responsible official position "
    "in relation to the operation of the device, and that is a human act, not a software "
    "output."
)


@dataclass
class Section63Certificate:
    """Part A fields, plus the blank Part B the statute requires."""

    case_id: str
    generated_at: str
    document_hash: str
    hash_algorithm: str = HASH_ALGORITHM
    system_description: str = ""
    record_description: str = ""
    production_description: str = ""
    artifact_hashes: dict[str, str] = dataclass_field(default_factory=dict)
    part_b_blank_reason: str = (
        "Left blank for completion and signature by an expert, as Section 63 requires."
    )

    def as_rows(self) -> list[tuple[str, str]]:
        """Label and value pairs, in the order the dossier prints them."""
        return [
            ("Case identifier", self.case_id),
            ("Certificate generated (UTC)", self.generated_at),
            ("Hash function used", self.hash_algorithm),
            ("Hash of the electronic record", self.document_hash),
            ("Description of the system", self.system_description),
            ("Description of the record produced", self.record_description),
            ("How the record was produced", self.production_description),
        ]


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_certificate(
    bundle: dict,
    artifact_hashes: dict[str, str],
    document_hash: str = "",
    git_commit: str = "unknown",
    kernel: str = "openoil",
) -> Section63Certificate:
    """Fills Part A from the bundle and the artifact hash table the
    provenance page already computes.

    document_hash is the hash of the finished PDF, which cannot exist
    while the PDF is still being written. The dossier renderer passes
    an empty string on the first pass and the placeholder below is
    printed, naming the file to hash and the command to do it, so the
    certificate is honest about the ordering rather than quietly
    printing a hash of something else.
    """
    scene = bundle.get("scene", {})
    field = bundle.get("origin_field", {})

    return Section63Certificate(
        case_id=bundle.get("case_id", "unknown"),
        generated_at=datetime.now(timezone.utc).isoformat(),
        document_hash=document_hash
        or (
            "To be computed over the finished PDF after generation "
            "(sha256sum on the delivered file), since a document cannot contain "
            "its own hash."
        ),
        system_description=(
            f"Pharos maritime event attribution pipeline, git commit {git_commit}. "
            f"Detection uses the pretrained DeepLabV3+ model sahilvishwa2108/oil-spill-deeplab "
            f"loaded from local storage. The origin probability field was produced by the "
            f"{kernel} drift kernel over an ensemble of {field.get('n_members', 'unknown')} "
            f"members with random seed {field.get('seed', 'unknown')}. Scoring is an explicit "
            "weighted evidence model whose configuration is reproduced verbatim on the "
            "provenance page of this document; no trained classifier is used for attribution."
        ),
        record_description=(
            f"Case dossier for {bundle.get('case_id', 'unknown')}, covering scene "
            f"{scene.get('scene_id', 'unknown')} acquired at {scene.get('acquired_at', 'unknown')} "
            f"by sensor {scene.get('sensor', 'S1')}. The record comprises the detection, wind "
            "gate assessment, slick characterisation, origin probability field, radar cross "
            "check, ranked suspects with factor breakdowns, the elimination log, the MARPOL "
            "assessment and the provenance page."
        ),
        production_description=(
            "Produced automatically from the pipeline outputs by "
            "services/core/dossier/render.py, without manual editing. Every input artifact is "
            f"listed with its {HASH_ALGORITHM} hash on the provenance page. The run is "
            "deterministic: every stochastic component takes its seed from configuration, so "
            "re-running the pipeline on the same inputs reproduces the same numbers."
        ),
        artifact_hashes=dict(artifact_hashes),
    )
