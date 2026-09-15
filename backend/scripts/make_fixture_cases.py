"""Builds the inputs of every case study in config/cases.yaml that does
not share the default fixture paths: its SAR scene, its wind and its
currents. The default case's inputs are the top-level fixtures, built by
make_fixture_scene.py (committed), make_fixture_wind_offshore.py and
make_fixture_currents.py, so this skips it.

The synthetic AIS for each case is not written here, for the same reason
as the hero case's: it is positioned relative to the origin field, so
scripts/seed_demo.py generates it in memory once the field exists.

Run: python3 scripts/make_fixture_cases.py [--force] [--case <id>]
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import case_registry  # noqa: E402
import make_fixture_currents  # noqa: E402
import make_fixture_scene  # noqa: E402
import make_fixture_wind_offshore  # noqa: E402


def outputs(registry: dict, case: dict) -> list[str]:
    paths = case_registry.paths_for(registry, case)
    out = []
    if case["scene"] != "committed":
        out.append(paths.scene)
    if not case_registry.is_default(registry, case):
        out.extend([paths.wind, paths.currents])
    return out


def all_outputs(registry: dict | None = None) -> list[str]:
    registry = registry or case_registry.load_registry()
    return [p for case in registry["cases"] for p in outputs(registry, case)]


def build(registry: dict, case: dict, force: bool) -> None:
    paths = case_registry.paths_for(registry, case)
    if case["scene"] != "committed" and (force or not os.path.exists(paths.scene)):
        make_fixture_scene.build(case["scene"], paths.scene)
    if case_registry.is_default(registry, case):
        return
    if force or not os.path.exists(paths.wind):
        make_fixture_wind_offshore.build_case(case, paths.wind)
    if force or not os.path.exists(paths.currents):
        make_fixture_currents.build_case(case, paths.currents)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--case", default="")
    args = parser.parse_args(argv)
    registry = case_registry.load_registry()
    cases = [case_registry.get_case(registry, args.case)] if args.case else registry["cases"]
    for case in cases:
        build(registry, case, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] if len(sys.argv) > 1 else []))
