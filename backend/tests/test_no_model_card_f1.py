"""Enforces PLAN.md non-negotiable 8.

  "Never surface an aggregate accuracy figure without the class name
   attached. Specifically, never surface the HuggingFace model card's
   self reported 0.9668 anywhere: not the UI, not the README, not the
   dossier, not a slide."

Why a test rather than a review note: the number is genuinely tempting.
It is the only accuracy figure that currently exists for this model, it
is printed on the model card, and under deadline pressure somebody will
reach for it. On this five class taxonomy background pixels dominate, so
0.9668 says nothing about oil class performance, and a jury member who
finds that out has found a real problem with the pitch rather than a
presentational one.

The number may appear in prose that explains why it is not used. This
test allows that and forbids everything else, by checking whether the
line it appears on also carries the explanation.
"""

from __future__ import annotations

import os

FORBIDDEN = "0.9668"

# Directories scanned, relative to backend/. The frontend, the deck and
# the docs tree are scanned via their own relative paths since they sit
# outside this tree.
#
# ../docs is in this list because the README was split into docs/ and the
# paragraph that explains why this number is not used moved to
# docs/DATA.md with it. A prose split is exactly how a guard like this
# goes blind: the text moves, the test keeps passing, and nothing says
# the scanned set no longer covers the file that matters.
SCAN_ROOTS = ["services", "validation", "scripts", "config", "../frontend/src", "../deck", "../docs"]
SCAN_FILES = ["../README.md"]
SCAN_EXTENSIONS = {".py", ".ts", ".tsx", ".yaml", ".yml", ".md", ".html", ".css", ".json"}

# A mention is allowed only if its own line also explains that the figure
# is not used. Anything else is the number leaking into an output.
EXCUSING_MARKERS = (
    "not reproduced",
    "never surface",
    "not surface",
    "is not used",
    "self reported",
    "self-reported",
    "forbid",
)


def _files_to_scan() -> list[str]:
    found = list(SCAN_FILES)
    for root in SCAN_ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", "node_modules", ".venv", "dist"}]
            for name in filenames:
                if os.path.splitext(name)[1] in SCAN_EXTENSIONS:
                    found.append(os.path.join(dirpath, name))
    return found


def test_the_model_cards_self_reported_f1_never_appears_unexplained():
    offenders = []
    for path in _files_to_scan():
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            continue
        for i, line in enumerate(lines, start=1):
            if FORBIDDEN not in line:
                continue
            lowered = line.lower()
            if any(marker in lowered for marker in EXCUSING_MARKERS):
                continue
            offenders.append(f"{path}:{i}: {line.strip()[:100]}")

    assert not offenders, (
        "PLAN.md non-negotiable 8: the model card's self reported "
        f"{FORBIDDEN} must never be surfaced. Offending lines: " + "; ".join(offenders)
    )


def test_the_scan_actually_covers_something():
    """A guard on the guard. If SCAN_ROOTS ever goes stale, the test
    above passes by scanning nothing, which is worse than not having it."""
    files = _files_to_scan()
    assert len(files) > 30
    assert any(p.endswith("README.md") for p in files)
    assert any(p.endswith(".tsx") for p in files)
    # The docs tree carries the prose that explains why the figure is not
    # used, so a scan that misses it is a scan that misses the one file
    # most likely to quote the number.
    assert any(os.path.normpath(p).startswith(os.path.normpath("../docs")) for p in files), (
        "../docs is not being scanned; the README split moved prose there"
    )
