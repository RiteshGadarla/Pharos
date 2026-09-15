"""Copies the precomputed case outputs into frontend/public/data/ so the
static build can serve every case with the core service stopped.

  data/precomputed/cases.json          -> frontend/public/data/cases.json
  data/precomputed/cases/<id>/*        -> frontend/public/data/cases/<id>/
  data/precomputed/demo_bundle.json    -> frontend/public/data/demo_bundle.json
  (and scene_preview.png, case_dossier.pdf beside it, the default case)

Only cases listed in the index are copied, and any directory under
frontend/public/data/cases/ that the index does not list is removed, so a
stale or hand-made test case cannot linger in the static build beside the
real ones.

Run from backend/: .venv/bin/python scripts/publish_cases.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import case_registry  # noqa: E402

FRONTEND_DATA = os.path.join(case_registry.BACKEND_DIR, "..", "frontend", "public", "data")
CASE_FILES = ("demo_bundle.json", "scene_preview.png", "case_dossier.pdf")
LEGACY_FILES = ("demo_bundle.json", "scene_preview.png", "case_dossier.pdf")


def main() -> int:
    os.chdir(case_registry.BACKEND_DIR)
    if not os.path.exists(case_registry.CASES_INDEX):
        raise SystemExit(f"{case_registry.CASES_INDEX} not built. Run: make seed-demo")
    with open(case_registry.CASES_INDEX) as f:
        index = json.load(f)
    ids = [c["id"] for c in index["cases"]]
    for cid in ids:
        if not case_registry.CASE_ID_PATTERN.match(cid):
            raise SystemExit(f"refusing to publish case id {cid!r}")

    dest_cases = os.path.join(FRONTEND_DATA, "cases")
    os.makedirs(dest_cases, exist_ok=True)

    for name in LEGACY_FILES:
        src = os.path.join(case_registry.PRECOMPUTED_DIR, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(FRONTEND_DATA, name))

    for cid in ids:
        target = os.path.join(dest_cases, cid)
        os.makedirs(target, exist_ok=True)
        for name in CASE_FILES:
            shutil.copyfile(os.path.join(case_registry.PRECOMPUTED_DIR, "cases", cid, name), os.path.join(target, name))

    removed = []
    for entry in sorted(os.listdir(dest_cases)):
        if entry not in ids:
            path = os.path.join(dest_cases, entry)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            removed.append(entry)

    shutil.copyfile(case_registry.CASES_INDEX, os.path.join(FRONTEND_DATA, "cases.json"))
    print(f"published {len(ids)} case(s) to frontend/public/data/: {', '.join(ids)}")
    if removed:
        print(f"removed entries not in the index: {', '.join(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
