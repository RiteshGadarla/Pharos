"""Enforces PLAN.md non-negotiable 5: Cerulean is never in the runtime path.

Cerulean is another model with partial human review, not ground truth.
Using it at runtime would make the demo depend on a third-party network
service, which breaks the "network cable unplugged" requirement, and it
would let an external system's operating point leak into DRISHTA's own
claims.

This test scans the source rather than trusting a code review, because
the failure mode it guards against is a plausible-looking single-line
import that nobody notices in a diff.
"""

from __future__ import annotations

import ast
import os

SERVICE_ROOTS = ["services"]
FORBIDDEN_PREFIXES = ("validation.cerulean_client", "validation.cerulean_agreement")
FORBIDDEN_SUBSTRINGS = ("cerulean", "skytruth")


def _python_files(root: str) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".venv"}]
        found.extend(os.path.join(dirpath, f) for f in filenames if f.endswith(".py"))
    return found


def _imported_modules(path: str) -> list[str]:
    with open(path) as f:
        tree = ast.parse(f.read(), filename=path)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_no_module_under_services_imports_the_cerulean_client():
    offenders = []
    for root in SERVICE_ROOTS:
        for path in _python_files(root):
            for module in _imported_modules(path):
                if module.startswith(FORBIDDEN_PREFIXES) or any(
                    s in module.lower() for s in FORBIDDEN_SUBSTRINGS
                ):
                    offenders.append(f"{path} imports {module}")
    assert not offenders, (
        "Cerulean must never be in the runtime path (PLAN.md non-negotiable 5). "
        "Offending imports: " + "; ".join(offenders)
    )


def test_no_module_under_services_imports_the_validation_package_at_all():
    """The stronger form, and the one worth keeping: validation/ is a
    sibling of services/, not a dependency of it. Anything under
    services/ that reaches into validation/ has put a measurement tool
    into the pipeline, which is how the Cerulean rule gets broken by
    accident rather than on purpose."""
    offenders = []
    for root in SERVICE_ROOTS:
        for path in _python_files(root):
            for module in _imported_modules(path):
                if module == "validation" or module.startswith("validation."):
                    offenders.append(f"{path} imports {module}")
    assert not offenders, (
        "services/ must not import validation/. Offending imports: " + "; ".join(offenders)
    )


def test_the_cerulean_client_exists_and_says_it_is_validation_only():
    """The rule is only enforceable if the module states it, since the
    next person to touch it reads the docstring, not this test."""
    with open("validation/cerulean_client.py") as f:
        source = f.read()
    assert "VALIDATION ONLY" in source
    assert "non-negotiable 5" in source.lower() or "non-negotiable 5" in source
