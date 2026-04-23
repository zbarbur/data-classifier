"""Local conftest for test_zone_v2.

Overrides the global autouse fixture _patch_meta_classifier_artifact
which requires sklearn (a meta-classifier dev dependency). Zone v2 tests
have no dependency on the meta-classifier model artifact.
"""
import pytest


@pytest.fixture(autouse=True)
def _patch_meta_classifier_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op override: zone v2 tests don't use the meta-classifier."""
