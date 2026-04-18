"""Dataset loading helper — local DVC data with HuggingFace streaming fallback.

Usage::

    from data_classifier.datasets import load_local_or_remote

    ds = load_local_or_remote("wildchat_1m")                    # default split="train"
    ds = load_local_or_remote("nemotron_pii", split="train")
    ds = load_local_or_remote("wildchat_1m", streaming=True)    # force streaming even if local

See ``docs/process/dataset_management.md`` for the full DVC workflow.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Map local directory names to HuggingFace dataset identifiers.
_HF_REGISTRY: dict[str, str] = {
    "wildchat_1m": "allenai/WildChat-1M",
    "ai4privacy_openpii": "ai4privacy/pii-masking-300k",
    "nemotron_pii": "nvidia/Nemotron-PII",
    "gretel_en": "gretelai/gretel-pii-masking-en-v1",
    "gretel_finance": "gretelai/gretel-pii-finance-multilingual",
}

# Project root → data/ directory.  Works from any worktree because
# data_classifier is always installed as editable (`pip install -e`).
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_local_or_remote(
    name: str,
    *,
    split: str = "train",
    streaming: bool = False,
):
    """Load a dataset from local DVC cache or fall back to HuggingFace.

    Parameters
    ----------
    name:
        Dataset name matching a key in ``_HF_REGISTRY`` and a subdirectory
        under ``data/``.
    split:
        HuggingFace split name (default ``"train"``).
    streaming:
        If ``True``, force HuggingFace streaming even when local data exists.
        Useful for large datasets when you only need a small sample.

    Returns
    -------
    A ``datasets.Dataset`` (local) or ``datasets.IterableDataset`` (streaming).
    """
    from datasets import load_dataset

    local_dir = _DATA_DIR / name
    parquet_files = list(local_dir.glob("*.parquet")) if local_dir.exists() else []

    if parquet_files and not streaming:
        log.info("loading %s from local DVC data: %s (%d files)", name, local_dir, len(parquet_files))
        return load_dataset(
            "parquet",
            data_files=[str(p) for p in sorted(parquet_files)],
            split=split,
        )

    hf_id = _HF_REGISTRY.get(name)
    if not hf_id:
        raise ValueError(
            f"Unknown dataset {name!r}. Known datasets: {sorted(_HF_REGISTRY)}. "
            f"Add an entry to _HF_REGISTRY in {__file__} and run `dvc add data/{name}`."
        )

    if parquet_files:
        log.info("loading %s via HuggingFace streaming (forced): %s", name, hf_id)
    else:
        log.warning(
            "local data not found for %s at %s — falling back to HuggingFace streaming. "
            "Run `dvc pull data/%s.dvc` to hydrate local copy.",
            name,
            local_dir,
            name,
        )

    return load_dataset(hf_id, split=split, streaming=streaming or not parquet_files)
