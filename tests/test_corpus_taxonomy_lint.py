"""Tests for the corpus-loader taxonomy drift lint (Sprint 11 item #3).

The lint's job is to catch ANY corpus loader that emits an entity_type
label which does not exist in ``data_classifier/profiles/standard.yaml``.
This is how Sprint 10 silently shipped ~0.05 points of fake Nemotron
regression: the CREDENTIAL label was split into 4 subtypes, but the
loaders kept emitting the legacy flat CREDENTIAL string, and nothing in
CI caught the drift.

These tests pin three invariants:

1. **Positive baseline** — every current loader in
   ``tests/benchmarks/corpus_loader.py`` passes the lint (minus the
   explicit Gretel-finance fixture-carryover skip documented in
   ``lint_corpus_taxonomy``).
2. **Negative regression** — injecting a fake loader module that
   contains a ``*_TYPE_MAP`` dict emitting the stale ``CREDENTIAL``
   label causes the lint to fail with a violation that names both the
   offending map and the offending value. This is the guard that would
   have caught Sprint 10's drift.
3. **Sanity** — a fake loader module emitting a VALID post-split label
   (``API_KEY``) passes cleanly, confirming the lint doesn't have a
   false-positive for correctly-refreshed maps.
"""

from __future__ import annotations

import types

import pytest


def test_lint_passes_on_current_corpus_loaders() -> None:
    """Baseline: real loaders must pass the lint post-item-#1 refresh."""
    from tests.benchmarks import corpus_loader
    from tests.benchmarks.lint_corpus_taxonomy import lint_loader_vocabulary

    violations = lint_loader_vocabulary(corpus_loader)
    assert violations == [], f"Current corpus loaders violate taxonomy lint: {violations}"


def test_lint_catches_stale_credential_label() -> None:
    """Negative regression: a fake map emitting legacy CREDENTIAL must be caught."""
    from tests.benchmarks.lint_corpus_taxonomy import lint_loader_vocabulary

    fake_module = types.ModuleType("fake_loader_with_stale_credential")
    fake_module.FAKE_TYPE_MAP = {  # type: ignore[attr-defined]
        "password": "CREDENTIAL",
        "email": "EMAIL",
    }

    violations = lint_loader_vocabulary(fake_module)
    assert len(violations) == 1
    violation = violations[0]
    assert violation.map_name == "FAKE_TYPE_MAP"
    assert violation.invalid_values == {"password": "CREDENTIAL"}
    # EMAIL is a valid entity_type so it must NOT be flagged.
    assert "email" not in violation.invalid_values


def test_lint_catches_arbitrary_non_taxonomy_label() -> None:
    """Negative regression: any non-taxonomy label must be caught, not just CREDENTIAL."""
    from tests.benchmarks.lint_corpus_taxonomy import lint_loader_vocabulary

    fake_module = types.ModuleType("fake_loader_with_typo")
    fake_module.TYPO_TYPE_MAP = {  # type: ignore[attr-defined]
        "phone": "PHONENUMBER",  # typo: should be PHONE
    }

    violations = lint_loader_vocabulary(fake_module)
    assert len(violations) == 1
    assert violations[0].map_name == "TYPO_TYPE_MAP"
    assert violations[0].invalid_values == {"phone": "PHONENUMBER"}


def test_lint_passes_on_valid_subtype_labels() -> None:
    """Sanity: a fake map using the 4 new credential subtypes passes cleanly."""
    from tests.benchmarks.lint_corpus_taxonomy import lint_loader_vocabulary

    fake_module = types.ModuleType("fake_loader_with_valid_subtypes")
    fake_module.GOOD_TYPE_MAP = {  # type: ignore[attr-defined]
        "api_key": "API_KEY",
        "private_key": "PRIVATE_KEY",
        "password_hash": "PASSWORD_HASH",
        "password": "OPAQUE_SECRET",
    }

    violations = lint_loader_vocabulary(fake_module)
    assert violations == []


def test_lint_skips_non_type_map_dicts() -> None:
    """The lint filter must only target ``*_TYPE_MAP`` / ``*_POST_ETL_IDENTITY`` dicts."""
    from tests.benchmarks.lint_corpus_taxonomy import lint_loader_vocabulary

    fake_module = types.ModuleType("fake_loader_with_unrelated_dict")
    fake_module.SOME_RANDOM_CONFIG = {"not_a_taxonomy": "at_all"}  # type: ignore[attr-defined]
    fake_module.GOOD_TYPE_MAP = {"api_key": "API_KEY"}  # type: ignore[attr-defined]

    violations = lint_loader_vocabulary(fake_module)
    assert violations == []  # SOME_RANDOM_CONFIG must be ignored


def test_lint_raises_if_nothing_to_check() -> None:
    """Guardrail: a module with zero ``*_TYPE_MAP`` dicts must error, not silently pass.

    This catches the failure mode where someone refactors loader dict
    naming (e.g. drops the ``_TYPE_MAP`` suffix) and the lint silently
    covers nothing.
    """
    from tests.benchmarks.lint_corpus_taxonomy import lint_loader_vocabulary

    fake_module = types.ModuleType("fake_loader_with_no_maps")

    with pytest.raises(ValueError, match="no .* dicts found"):
        lint_loader_vocabulary(fake_module)


def test_entry_point_runs_against_real_corpus_loader() -> None:
    """The ``__main__`` entry point must exit 0 on current loaders."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "tests.benchmarks.lint_corpus_taxonomy"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"lint CLI failed unexpectedly: stderr={result.stderr}"
