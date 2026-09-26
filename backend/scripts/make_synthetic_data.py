"""The one command that builds every synthetic input Pharos needs to run.

Pharos ships with no downloaded dataset. Real Sentinel-1 scenes, real
CMEMS currents, real ERA5 wind and real AIS feeds are all blocked on the
account registrations in PLAN.md section 4A, and none of them are needed
to run the system: every input the pipeline consumes can be generated
locally, deterministically, from the seed in config/pipeline.yaml.

This script is that generator. It replaces having to remember five
separate make_fixture_*.py invocations and the order they go in, and it
sets sys.path itself so it runs identically on Linux, macOS and Windows
with no PYTHONPATH ceremony:

    python scripts/make_synthetic_data.py

What it produces, in dependency order:

  scene           data/fixtures/synthetic_scene.tif
                  A 512x512 calibrated-sigma0 GeoTIFF standing in for a
                  Sentinel-1 GRD acquisition. Already committed to the
                  repository as the staged sample image (see
                  data/fixtures/SAMPLE_SCENE.md), so this step only
                  matters if you want to rebuild or modify it.
  wind            data/fixtures/synthetic_wind.nc
                  Near-shore 10m wind with four distinct speed zones, so
                  all four wind-gate verdicts are reachable.
  currents        data/fixtures/synthetic_currents.nc
                  Open-ocean surface currents with a real time axis.
  wind_offshore   data/fixtures/synthetic_wind_offshore.nc
                  Open-ocean 10m wind over the same domain as currents.
                  Currents and wind_offshore are the default case study's
                  forcing, from config/cases.yaml, built by the shared
                  generator in scripts/synthetic_metocean.py.
  origin_field    data/fixtures/synthetic_origin_field.nc
                  A cached small backward ensemble. Needs currents and
                  wind_offshore on disk first.
  cases           data/fixtures/*__<case id>.{tif,nc}
                  Every other case study's scene, wind and currents.

The synthetic AIS traffic is NOT written here. It is generated in memory
from the origin field every time, by services/core/ais/synthetic.py, so
that the vessels are always positioned relative to the field they are
being scored against. scripts/seed_demo.py is what exercises that path.

Usage:

    python scripts/make_synthetic_data.py              # build what's missing
    python scripts/make_synthetic_data.py --force      # rebuild everything
    python scripts/make_synthetic_data.py --only wind,currents
    python scripts/make_synthetic_data.py --list       # show status, build nothing

Run it from the backend/ directory. Everything is seeded, so two runs on
two machines produce byte-identical output.
"""

from __future__ import annotations

import argparse
import os
import runpy
import sys
import time

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BACKEND_DIR, "scripts")

# Ordered, because origin_field integrates through currents and
# wind_offshore and needs both already written.
DATASETS: list[tuple[str, str, str, str]] = [
    (
        "scene",
        "make_fixture_scene.py",
        "data/fixtures/synthetic_scene.tif",
        "SAR scene, real oil texture composited into a synthetic sea",
    ),
    (
        "wind",
        "make_fixture_wind.py",
        "data/fixtures/synthetic_wind.nc",
        "near-shore 10m wind, four gate zones",
    ),
    (
        "currents",
        "make_fixture_currents.py",
        "data/fixtures/synthetic_currents.nc",
        "open-ocean surface currents and SST",
    ),
    (
        "wind_offshore",
        "make_fixture_wind_offshore.py",
        "data/fixtures/synthetic_wind_offshore.nc",
        "open-ocean 10m wind, the ensemble's windage forcing",
    ),
    (
        "origin_field",
        "make_fixture_origin_field.py",
        "data/fixtures/synthetic_origin_field.nc",
        "cached backward ensemble, needs currents and wind_offshore",
    ),
    (
        "cases",
        "make_fixture_cases.py",
        "",
        "each other case study's scene, wind and currents, from config/cases.yaml",
    ),
]


def _outputs(name: str, out_path: str) -> list[str]:
    """Every file a dataset writes. The case studies write several, listed
    by the registry, so they are resolved here rather than hardcoded."""
    if name != "cases":
        return [out_path]
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    import make_fixture_cases

    return make_fixture_cases.all_outputs()

NAMES = [name for name, _, _, _ in DATASETS]


def _human_size(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}GB"


def _print_status() -> None:
    print(f"{'dataset':<16} {'status':<9} {'size':>8}  output")
    print("-" * 78)
    for name, _, out_path, _ in DATASETS:
        for path in _outputs(name, out_path):
            present = os.path.exists(os.path.join(BACKEND_DIR, path))
            status = "present" if present else "missing"
            size = _human_size(os.path.join(BACKEND_DIR, path)) if present else "-"
            print(f"{name:<16} {status:<9} {size:>8}  {path}")


def _run_generator(script_name: str, force: bool = False) -> None:
    """Executes one make_fixture_*.py as if it were run directly.

    runpy rather than subprocess so the interpreter already running this
    file is the one that builds the data: no venv path guessing, no
    PYTHONPATH environment variable, and a traceback that points at the
    real failure instead of a non-zero exit code.
    """
    if script_name == "make_fixture_cases.py":
        # Several outputs, some possibly present: let it skip per file.
        if SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, SCRIPTS_DIR)
        import make_fixture_cases

        make_fixture_cases.main(["--force"] if force else [])
        return
    runpy.run_path(os.path.join(SCRIPTS_DIR, script_name), run_name="__main__")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate every synthetic input Pharos needs. No dataset download required.",
    )
    parser.add_argument(
        "--only",
        default="",
        help=f"comma-separated subset to build, from: {', '.join(NAMES)}",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild even if the output file is already on disk",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="show what exists and what is missing, then exit without building",
    )
    args = parser.parse_args(argv)

    if args.list:
        _print_status()
        return 0

    selected = NAMES
    if args.only:
        selected = [part.strip() for part in args.only.split(",") if part.strip()]
        unknown = [name for name in selected if name not in NAMES]
        if unknown:
            parser.error(f"unknown dataset(s): {', '.join(unknown)}. Choose from: {', '.join(NAMES)}")

    # backend/ on sys.path so make_fixture_origin_field.py can import
    # services.core, and cwd at backend/ so every script's relative
    # OUT_PATH lands where the config files expect it. Doing both here is
    # what lets this run from a plain `python scripts/make_synthetic_data.py`
    # on Windows PowerShell, where `PYTHONPATH=. python ...` is not valid.
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)
    os.chdir(BACKEND_DIR)

    built, skipped = [], []
    for name, script_name, out_path, description in DATASETS:
        if name not in selected:
            continue
        if all(os.path.exists(p) for p in _outputs(name, out_path)) and not args.force:
            print(f"[skip]  {name:<14} already present (use --force to rebuild)")
            skipped.append(name)
            continue
        print(f"[build] {name:<14} {description}")
        started = time.monotonic()
        _run_generator(script_name, force=args.force)
        print(f"        {name:<14} done in {time.monotonic() - started:.1f}s")
        built.append(name)

    print()
    print(f"built {len(built)}, skipped {len(skipped)}")
    if built:
        print("  built:   " + ", ".join(built))
    if skipped:
        print("  skipped: " + ", ".join(skipped))
    print()
    _print_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
