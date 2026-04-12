#!/usr/bin/env python3
"""Fresh-install smoke test for data_classifier.

Runs after a ``pip install .`` (non-editable) in a clean venv to prove that
all bundled data files (profiles, configs, patterns) actually shipped inside
the installed wheel AND that an end-to-end classification works.

This exists to catch packaging regressions like the Sprint 5 bug, where
``data_classifier/config/engine_defaults.yaml`` silently failed to ship
because the ``config/*.yaml`` glob was missing from
``[tool.setuptools.package-data]``.

Usage:
    python scripts/install_smoke_test.py [--verbose]

Exit codes:
    0 — all checks passed
    1 — one or more checks failed

Intentionally imports ``data_classifier`` via the installed package and walks
resources via :mod:`importlib.resources` so filesystem layout in the source
checkout cannot mask a missing file in the wheel.
"""

from __future__ import annotations

import argparse
import logging
import os

# Disable the ML engine *before* any data_classifier import — the default
# engine list is built at module import time, so the env var has to be set
# first or the GLiNER2 engine will be constructed even though the smoke
# test does not need it.
os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

import sys  # noqa: E402
import traceback  # noqa: E402
from importlib.resources import as_file, files  # noqa: E402
from importlib.resources.abc import Traversable  # noqa: E402

logger = logging.getLogger("install_smoke_test")

# Subpackages whose *.yaml resources must ship and load cleanly.
_YAML_RESOURCE_PACKAGES: tuple[str, ...] = (
    "data_classifier.profiles",
    "data_classifier.config",
)

# Subpackages whose *.json resources must ship and load cleanly.
_JSON_RESOURCE_PACKAGES: tuple[str, ...] = ("data_classifier.patterns",)


class CheckResult:
    """Single named check outcome."""

    def __init__(self, name: str, ok: bool, detail: str = "") -> None:
        self.name = name
        self.ok = ok
        self.detail = detail

    def __str__(self) -> str:
        tag = "[OK]  " if self.ok else "[FAIL]"
        if self.detail:
            return f"{tag} {self.name} — {self.detail}"
        return f"{tag} {self.name}"


def _iter_resources(pkg: str, suffix: str) -> list[Traversable]:
    """Return all top-level files ending in ``suffix`` inside package ``pkg``."""
    root = files(pkg)
    return [entry for entry in root.iterdir() if entry.is_file() and entry.name.endswith(suffix)]


def check_imports() -> CheckResult:
    """Import the public API surface — fails fast on missing deps."""
    try:
        from data_classifier import ColumnInput, classify_columns, load_profile  # noqa: F401

        logger.debug("imported classify_columns=%s ColumnInput=%s", classify_columns, ColumnInput)
        return CheckResult("import public API", True, "classify_columns, ColumnInput, load_profile")
    except Exception as exc:  # pragma: no cover — explicit CI signal
        return CheckResult("import public API", False, f"{type(exc).__name__}: {exc}")


def check_yaml_resources() -> list[CheckResult]:
    """Verify every bundled *.yaml resource loads via the installed package."""
    import yaml  # local import so the import failure surfaces as a check, not a crash

    results: list[CheckResult] = []
    for pkg in _YAML_RESOURCE_PACKAGES:
        try:
            entries = _iter_resources(pkg, ".yaml")
        except (ModuleNotFoundError, FileNotFoundError) as exc:
            results.append(CheckResult(f"enumerate {pkg}/*.yaml", False, f"{type(exc).__name__}: {exc}"))
            continue

        if not entries:
            results.append(
                CheckResult(
                    f"enumerate {pkg}/*.yaml",
                    False,
                    "no YAML resources found in installed package — package-data glob likely missing",
                )
            )
            continue

        results.append(CheckResult(f"enumerate {pkg}/*.yaml", True, f"{len(entries)} file(s)"))

        for entry in entries:
            name = f"{pkg}/{entry.name}"
            try:
                with as_file(entry) as path:
                    with open(path, encoding="utf-8") as handle:
                        yaml.safe_load(handle)
                results.append(CheckResult(f"load {name}", True))
            except Exception as exc:
                results.append(CheckResult(f"load {name}", False, f"{type(exc).__name__}: {exc}"))
    return results


def check_json_resources() -> list[CheckResult]:
    """Verify every bundled *.json pattern resource loads via the installed package."""
    import json

    results: list[CheckResult] = []
    for pkg in _JSON_RESOURCE_PACKAGES:
        try:
            entries = _iter_resources(pkg, ".json")
        except (ModuleNotFoundError, FileNotFoundError) as exc:
            results.append(CheckResult(f"enumerate {pkg}/*.json", False, f"{type(exc).__name__}: {exc}"))
            continue

        if not entries:
            results.append(
                CheckResult(
                    f"enumerate {pkg}/*.json",
                    False,
                    "no JSON resources found in installed package — package-data glob likely missing",
                )
            )
            continue

        results.append(CheckResult(f"enumerate {pkg}/*.json", True, f"{len(entries)} file(s)"))

        for entry in entries:
            name = f"{pkg}/{entry.name}"
            try:
                with as_file(entry) as path:
                    with open(path, encoding="utf-8") as handle:
                        json.load(handle)
                results.append(CheckResult(f"load {name}", True))
            except Exception as exc:
                results.append(CheckResult(f"load {name}", False, f"{type(exc).__name__}: {exc}"))
    return results


def check_profile_loads() -> CheckResult:
    """Load the standard profile via the public API."""
    try:
        from data_classifier import load_profile

        profile = load_profile("standard")
        if not profile.rules:
            return CheckResult("load_profile('standard')", False, "profile loaded but contains zero rules")
        return CheckResult("load_profile('standard')", True, f"{len(profile.rules)} rules, name={profile.name!r}")
    except Exception as exc:
        return CheckResult("load_profile('standard')", False, f"{type(exc).__name__}: {exc}")


def check_end_to_end_email() -> CheckResult:
    """Classify a sample column containing real email addresses end-to-end."""
    try:
        from data_classifier import ColumnInput, classify_columns, load_profile

        profile = load_profile("standard")
        columns = [
            ColumnInput(
                column_id="email_col",
                column_name="email",
                sample_values=[
                    "test@example.com",
                    "user@domain.org",
                    "admin@company.io",
                    "jane.doe@acme.co.uk",
                    "ops+alerts@service.net",
                ],
            )
        ]
        findings = classify_columns(columns, profile)
        if not findings:
            return CheckResult("classify email column", False, "no findings returned at all")

        email_findings = [f for f in findings if f.entity_type == "EMAIL"]
        if not email_findings:
            types = sorted({f.entity_type for f in findings})
            return CheckResult(
                "classify email column",
                False,
                f"EMAIL not detected; got entity_types={types}",
            )

        top = max(email_findings, key=lambda f: f.confidence)
        return CheckResult(
            "classify email column",
            True,
            f"EMAIL confidence={top.confidence:.2f} engine={top.engine}",
        )
    except Exception as exc:
        logger.debug("end-to-end failure", exc_info=True)
        return CheckResult("classify email column", False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")


def run_all() -> list[CheckResult]:
    results: list[CheckResult] = []
    results.append(check_imports())
    # If imports failed, the remainder would crash — still run resource checks
    # since they do not need the public API.
    results.extend(check_yaml_resources())
    results.extend(check_json_resources())
    results.append(check_profile_loads())
    results.append(check_end_to_end_email())
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    results = run_all()

    # Emit every result through logging so CI logs capture them.
    for r in results:
        if r.ok:
            logger.info("%s", r)
        else:
            logger.error("%s", r)

    failed = [r for r in results if not r.ok]
    total = len(results)
    passed = total - len(failed)

    summary = f"SUMMARY: {passed}/{total} checks passed"
    if failed:
        logger.error("%s — FAILED checks: %s", summary, ", ".join(r.name for r in failed))
        return 1
    logger.info("%s — all checks passed", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
