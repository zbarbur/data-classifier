"""Corpus-loader entity-taxonomy drift lint (Sprint 11 item #3).

This module walks every module-level ``*_TYPE_MAP`` and
``*_POST_ETL_IDENTITY`` dict in a corpus loader module and asserts that
every emitted value is a valid ``entity_type`` defined in
``data_classifier/profiles/standard.yaml``.

The motivating failure is Sprint 8's CREDENTIAL split, which broke
three loaders (Nemotron, Gretel-EN, _DETECT_SECRETS) silently. The
drift surfaced ~2 sprints later as a fake ~0.05 point Nemotron blind-F1
regression, when the scanner started correctly predicting the new
``API_KEY`` subtype while the loaders kept emitting the legacy flat
``CREDENTIAL`` label. See the Sprint 10 handover lesson #1 and the
Sprint 11 item #1 plan for the full history.

Usage:

* **From tests** — import :func:`lint_loader_vocabulary` and call it on
  the ``tests.benchmarks.corpus_loader`` module. Returns a (possibly
  empty) list of :class:`DriftViolation` records. Used by
  ``tests/test_corpus_taxonomy_lint.py``.
* **From CI / pre-commit / shell** — run ``python -m
  tests.benchmarks.lint_corpus_taxonomy``. Exits 0 on clean, 1 on
  violations with a human-readable report on stderr.

Gretel-finance is explicitly skipped (see ``_SKIP_MAPS`` below) because
its shipped fixture still uses the legacy CREDENTIAL label and
refreshing it requires rebuilding the per-record ``raw_label`` /
``source_context`` metadata — out of scope for Sprint 11 and filed as
a separate follow-up backlog item.
"""

from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

import yaml

#: Names of dicts that the lint must NOT walk, paired with the sprint
#: by which the skip is expected to be removed.  Every skip MUST carry
#: an expected-removal sprint and a link to the follow-up backlog item
#: that will refresh the underlying fixture — this is the guardrail
#: that prevents "temporary" skips from becoming permanent blind spots
#: (Sprint 10 drift story, recorded in
#: docs/sprints/SPRINT10_HANDOVER.md "Lessons learned #1").
#:
#: When adding a new skip: also file a backlog item scoped to the
#: target-removal sprint, cite it here, and do NOT add the entry without
#: an expiry sprint.  When removing a skip: delete the entry entirely
#: (do not leave the comment behind as a tombstone — git history is the
#: record).
_SKIP_MAPS_WITH_EXPIRY: dict[str, str] = {
    # Gretel-finance fixture still uses the legacy CREDENTIAL label
    # because the shipped fixture preserves per-record ``raw_label`` /
    # ``source_context`` metadata keyed on ``entity_type == "CREDENTIAL"``.
    # Refreshing requires rebuilding the fixture end-to-end; filed as a
    # Sprint 12 chore: ``gretel-finance-fixture-refresh-drop-legacy-credential-label``.
    "GRETEL_FINANCE_TYPE_MAP": "Sprint 12",
    "_GRETEL_FINANCE_POST_ETL_IDENTITY": "Sprint 12",
}

#: Frozen-set view used by the walk.  Derived from the source-of-truth
#: ``_SKIP_MAPS_WITH_EXPIRY`` dict so adding or removing a skip only
#: requires touching one place.
_SKIP_MAPS: frozenset[str] = frozenset(_SKIP_MAPS_WITH_EXPIRY.keys())

#: Labels that are legitimately emitted by loaders but are not first-class
#: ``entity_type`` entries in ``standard.yaml``. Kept small and explicit;
#: expand only when a new category of legitimate non-taxonomy label is
#: introduced.
_EXTRA_VALID_LABELS: frozenset[str] = frozenset(
    {
        "NEGATIVE",  # tests.benchmarks.corpus_loader.NEGATIVE_GROUND_TRUTH
        "URL",  # engine-emittable, not yet promoted to standard.yaml
    }
)

_STANDARD_YAML_RELATIVE: pathlib.PurePosixPath = pathlib.PurePosixPath("data_classifier/profiles/standard.yaml")


@dataclass
class DriftViolation:
    """One loader-level drift finding.

    Attributes
    ----------
    map_name
        Name of the offending dict in the module (e.g. ``NEMOTRON_TYPE_MAP``).
    invalid_values
        Mapping from raw_label -> the stale emitted label.  A single
        dict can contain multiple offenders; they are all reported at
        once so the fix is a single round-trip.
    """

    map_name: str
    invalid_values: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        pairs = ", ".join(f"{k!r}→{v!r}" for k, v in sorted(self.invalid_values.items()))
        return f"{self.map_name}: {pairs}"


def load_valid_entity_types(standard_yaml_path: pathlib.Path | None = None) -> set[str]:
    """Extract the set of valid entity_type names from ``standard.yaml``.

    Reads the bundled default profile directly rather than importing any
    engine code. Stays dependency-free so it can run in a pre-commit or
    CI lint hook without spinning up the full classifier stack.
    """
    if standard_yaml_path is None:
        # Walk up from this file to find the repo root, then descend
        # into the packaged profile YAML. Works in both the main
        # worktree and any Sprint worktree as long as the repo layout
        # is stable.
        here = pathlib.Path(__file__).resolve()
        repo_root = here.parent.parent.parent
        standard_yaml_path = repo_root / _STANDARD_YAML_RELATIVE

    profile_doc: dict[str, Any] = yaml.safe_load(standard_yaml_path.read_text(encoding="utf-8"))
    entity_types: set[str] = set()
    # The profile schema has ``profiles: {name: {rules: [{entity_type: ...}]}}``.
    for _name, body in profile_doc.get("profiles", {}).items():
        for rule in body.get("rules", []):
            et = rule.get("entity_type")
            if et:
                entity_types.add(et)
    return entity_types | _EXTRA_VALID_LABELS


def lint_loader_vocabulary(loader_module: ModuleType) -> list[DriftViolation]:
    """Walk a corpus-loader module and report any drifted labels.

    Parameters
    ----------
    loader_module
        A Python module containing one or more module-level dicts whose
        names end with ``_TYPE_MAP`` or ``_POST_ETL_IDENTITY``. These
        are assumed to map a raw upstream label to a normalised
        ``entity_type`` string.

    Returns
    -------
    list[DriftViolation]
        One record per offending dict. Empty list means the module is
        clean. Use ``bool(violations)`` for a quick pass/fail check.

    Raises
    ------
    ValueError
        If the module contains ZERO dicts that match the name filter.
        This guardrail catches silent-coverage regressions where a
        refactor renames every loader dict and the lint ends up
        vacuously passing.
    """
    valid = load_valid_entity_types()

    violations: list[DriftViolation] = []
    maps_checked: list[str] = []

    for name in dir(loader_module):
        if name in _SKIP_MAPS:
            continue
        if not (name.endswith("_TYPE_MAP") or name.endswith("_POST_ETL_IDENTITY")):
            continue
        obj = getattr(loader_module, name)
        if not isinstance(obj, dict):
            continue

        maps_checked.append(name)
        invalid = {k: v for k, v in obj.items() if v not in valid}
        if invalid:
            violations.append(DriftViolation(map_name=name, invalid_values=invalid))

    if not maps_checked:
        msg = (
            f"lint_loader_vocabulary: no *_TYPE_MAP or *_POST_ETL_IDENTITY dicts found on "
            f"module {loader_module.__name__!r} — did a refactor rename them?"
        )
        raise ValueError(msg)

    return violations


def _main() -> int:
    """CLI entry point: lint ``tests.benchmarks.corpus_loader`` and exit 0/1.

    Kept deliberately tiny so the CI matrix can call it with ``python -m
    tests.benchmarks.lint_corpus_taxonomy`` instead of wrapping it in a
    pytest invocation.  Prints a concise human-readable report when
    violations are found.

    Uses ``print`` (not ``logging``) because this is a pre-commit / CI
    tool whose output IS the user interface — the success line goes to
    stdout so grep / CI parsers see it, and violation lines go to
    stderr so a `&&`-chained shell pipeline stops on failure without
    mixing streams.  CLAUDE.md's "no print statements" rule is for
    library code; CLI entrypoints are the documented exception here,
    which is why each print carries an explicit ``# noqa: T201``
    annotation to survive a future ruff rule addition.
    """
    from tests.benchmarks import corpus_loader

    try:
        violations = lint_loader_vocabulary(corpus_loader)
    except ValueError as exc:
        print(f"lint ERROR: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    if not violations:
        print("lint_corpus_taxonomy: OK — 0 drift violations")  # noqa: T201
        return 0

    print(  # noqa: T201
        f"lint_corpus_taxonomy: {len(violations)} drift violation(s) in tests/benchmarks/corpus_loader.py",
        file=sys.stderr,
    )
    for v in violations:
        print(f"  - {v}", file=sys.stderr)  # noqa: T201
    print(  # noqa: T201
        "Fix: route each raw_label to a valid entity_type from "
        "data_classifier/profiles/standard.yaml. See "
        "docs/plans/nemotron-corpus-loader-taxonomy-refresh.md for the "
        "Sprint 11 drift-fix mapping table.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
