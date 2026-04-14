"""Corpus loader — loads external and synthetic corpora for benchmarking.

Supports multiple corpus sources:
- Synthetic (Faker-based, via corpus_generator.py)
- Nemotron-PII (HuggingFace sample)
- SecretBench (credential scanner benchmark, TP + TN)
- Gitleaks fixtures (credential scanner FP-hardening corpus, TP + TN)
- detect_secrets fixtures (hand-curated credential positives + placeholder
  negatives)
- Gretel-PII-masking-en-v1 (HuggingFace sample; Apache 2.0 mixed-label
  corpus, 60k rows / 47 domains) — replaced a retired 300k-row corpus
  in Sprint 9 (license non-OSS, see docs/process/LICENSE_AUDIT.md).

Sample data ships in tests/fixtures/corpora/ for offline benchmarking.

Usage:
    from tests.benchmarks.corpus_loader import load_corpus
    corpus = load_corpus("nemotron", max_rows=500)

``NEGATIVE`` ground-truth label
-------------------------------
SecretBench and gitleaks ship hard negative (``is_secret=False``) rows that
are the *hardest* disagreement cases for a credential classifier.  Rather
than drop them, the loaders emit those rows with ``ground_truth="NEGATIVE"``
— a generic sentinel label that the meta-classifier learns as a real class
(it means "no sensitive entity type fires"). The training pipeline in
``tests/benchmarks/meta_classifier/build_training_data.py`` treats
``NEGATIVE`` as a full-fledged class alongside the 22 positive entity
types. Consumers that only want positive entity types must filter on
``ground_truth != "NEGATIVE"`` explicitly.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from data_classifier.core.types import ColumnInput

logger = logging.getLogger(__name__)

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "corpora"

# ── Entity type mappings from external corpora to our types ──────────────────

# Gretel-PII-masking-EN-v1 label map (locked 2026-04-13, path-(d) decision).
#
# Only the 17 Gretel labels below are mapped to data_classifier types.
# Dropped Gretel labels (``date`` [generic], ``customer_id``, ``employee_id``,
# ``license_plate``, ``company_name``, ``device_identifier``,
# ``biometric_identifier``, ``unique_identifier``, ``time``, ``user_name``,
# ``coordinate``, ``country``, ``date_time``, ``city``, ``url``, ``cvv``,
# ``certificate_license_number``) are deferred to a Sprint 10 taxonomy
# expansion item — do NOT add new entity classes here without updating that
# decision. Target coverage: ~71% of labeled Gretel instances, by design.
GRETEL_EN_TYPE_MAP: dict[str, str] = {
    # PII
    "date_of_birth": "DATE_OF_BIRTH",
    "ssn": "SSN",
    "first_name": "PERSON_NAME",
    "name": "PERSON_NAME",
    "last_name": "PERSON_NAME",
    "email": "EMAIL",
    "phone_number": "PHONE",
    # Address family
    "address": "ADDRESS",
    "street_address": "ADDRESS",
    # Financial
    "credit_card_number": "CREDIT_CARD",
    "bank_routing_number": "ABA_ROUTING",
    "account_number": "BANK_ACCOUNT",
    # Network
    "ipv4": "IP_ADDRESS",
    "ipv6": "IP_ADDRESS",
    # Vehicle
    "vehicle_identifier": "VIN",
    # Health — coarse bucket for MRN (largest single Gretel label in the
    # discovery sample).
    "medical_record_number": "HEALTH",
}

# The fixture shipped in tests/fixtures/corpora/gretel_en_sample.json is
# ALREADY flattened into the ``{entity_type, value}`` schema the loader
# expects.  The downstream data_classifier taxonomy labels (e.g.
# ``DATE_OF_BIRTH``, ``PERSON_NAME``) are already applied during
# download; so the loader only needs an identity map over the post-ETL
# labels.  We do not re-map from the raw Gretel labels here because the
# raw labels never appear in the fixture.
_GRETEL_EN_POST_ETL_IDENTITY: dict[str, str] = {label: label for label in set(GRETEL_EN_TYPE_MAP.values())}


# Gretel synthetic_pii_finance_multilingual label map — locked
# 2026-04-14, Sprint 10. Mirrors ``scripts.download_corpora.GRETEL_FINANCE_TYPE_MAP``
# verbatim; keep these in sync.  See the download-side docstring for the
# full rationale: the Gretel-finance dataset is the targeted intervention
# for the ``heuristic_avg_length`` corpus-fingerprint shortcut because
# it ships credential labels inside long-form financial-document prose,
# not in isolated KV lines.  15 of 27 raw labels in the discovery sample
# map to existing ``data_classifier`` entity types; the 12 unmapped
# labels are either generic/ambiguous (``date``, ``time``, ``company``,
# ``customer_id``, ``employee_id``, ``user_name``, ``date_time``,
# ``credit_card_security_code``, ``local_latlng``) or net-new taxonomy
# candidates filed as a Sprint 11 backlog item (``account_pin``,
# ``bban``, ``driver_license_number``).  Do NOT widen this map without
# updating the Sprint 11 follow-up item.
GRETEL_FINANCE_TYPE_MAP: dict[str, str] = {
    # Identity / PII
    "name": "PERSON_NAME",
    "first_name": "PERSON_NAME",
    "street_address": "ADDRESS",
    "phone_number": "PHONE",
    "email": "EMAIL",
    "date_of_birth": "DATE_OF_BIRTH",
    "ssn": "SSN",
    # Financial
    "iban": "IBAN",
    "credit_card_number": "CREDIT_CARD",
    "bank_routing_number": "ABA_ROUTING",
    "swift_bic_code": "SWIFT_BIC",
    # Network
    "ipv4": "IP_ADDRESS",
    "ipv6": "IP_ADDRESS",
    # Credentials (the reason this corpus exists)
    "password": "CREDENTIAL",
    "api_key": "CREDENTIAL",
}

#: Identity map over the already-flattened post-ETL labels in the
#: Gretel-finance fixture, matching the Gretel-EN approach.
_GRETEL_FINANCE_POST_ETL_IDENTITY: dict[str, str] = {label: label for label in set(GRETEL_FINANCE_TYPE_MAP.values())}


NEMOTRON_TYPE_MAP: dict[str, str] = {
    "first_name": "PERSON_NAME",
    "last_name": "PERSON_NAME",
    "date_of_birth": "DATE_OF_BIRTH",
    "street_address": "ADDRESS",
    "email": "EMAIL",
    "email_address": "EMAIL",
    "phone_number": "PHONE",
    "social_security_number": "SSN",
    "ssn": "SSN",
    "credit_debit_card": "CREDIT_CARD",
    "credit_card_number": "CREDIT_CARD",
    "ip_address": "IP_ADDRESS",
    "ipv4": "IP_ADDRESS",
    "ipv6": "IP_ADDRESS",
    "url": "URL",
    "iban": "IBAN",
    "swift_bic": "SWIFT_BIC",
    "swift_code": "SWIFT_BIC",
    "mac_address": "MAC_ADDRESS",
    "bank_routing_number": "ABA_ROUTING",
    "routing_number": "ABA_ROUTING",
    "password": "CREDENTIAL",
    "api_key": "CREDENTIAL",
    "pin": "CREDENTIAL",
    "PERSON_NAME": "PERSON_NAME",
    "ADDRESS": "ADDRESS",
    "EMAIL": "EMAIL",
    "PHONE": "PHONE",
    "SSN": "SSN",
    "CREDIT_CARD": "CREDIT_CARD",
    "IP_ADDRESS": "IP_ADDRESS",
    "URL": "URL",
    "SWIFT_BIC": "SWIFT_BIC",
    "MAC_ADDRESS": "MAC_ADDRESS",
    "ABA_ROUTING": "ABA_ROUTING",
    "CREDENTIAL": "CREDENTIAL",
    "DATE_OF_BIRTH": "DATE_OF_BIRTH",
}


def _load_json_corpus(path: Path) -> list[dict]:
    """Load a JSON corpus file, returning list of records."""
    if not path.exists():
        logger.warning("Corpus file not found: %s", path)
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _records_to_corpus(
    records: list[dict],
    type_map: dict[str, str],
    source_name: str,
    max_rows: int = 500,
    *,
    blind: bool = False,
) -> list[tuple[ColumnInput, str | None]]:
    """Convert corpus records to (ColumnInput, expected_entity_type) tuples.

    Groups values by mapped entity type, creates one ColumnInput per type
    with up to max_rows sample values.

    Args:
        blind: If True, use generic column names (col_0, col_1, ...) so
            the column name engine cannot cheat.  This tests whether
            classification works from sample values alone.
    """
    # Group values by our entity type
    by_type: dict[str, list[str]] = {}
    for record in records:
        ext_type = record.get("entity_type", record.get("type", ""))
        value = record.get("value", "")
        if not value or not ext_type:
            continue

        our_type = type_map.get(ext_type)
        if our_type is None:
            continue

        by_type.setdefault(our_type, []).append(str(value))

    corpus: list[tuple[ColumnInput, str | None]] = []
    for idx, (entity_type, values) in enumerate(sorted(by_type.items())):
        # Truncate to max_rows
        values = values[:max_rows]
        if blind:
            col_name = f"col_{idx}"
            col_id = f"col_{idx}"
        else:
            col_name = f"{source_name}_{entity_type.lower()}"
            col_id = f"{source_name}_{entity_type}_0"
        col = ColumnInput(
            column_name=col_name,
            column_id=col_id,
            data_type="STRING",
            sample_values=values,
        )
        corpus.append((col, entity_type))

    return corpus


def load_nemotron_corpus(
    path: Path | str | None = None,
    max_rows: int = 500,
    *,
    blind: bool = False,
) -> list[tuple[ColumnInput, str | None]]:
    """Load Nemotron-PII corpus sample and convert to our format.

    Args:
        path: Path to JSON sample file. Defaults to bundled fixture.
        max_rows: Maximum sample values per entity type.

    Returns:
        List of (ColumnInput, expected_entity_type) tuples.
    """
    if path is None:
        path = _FIXTURES_DIR / "nemotron_sample.json"
    else:
        path = Path(path)

    records = _load_json_corpus(path)
    if not records:
        logger.warning("No records loaded from Nemotron corpus at %s", path)
        return []

    return _records_to_corpus(records, NEMOTRON_TYPE_MAP, "nemotron", max_rows, blind=blind)


def load_gretel_en_corpus(
    path: Path | str | None = None,
    max_rows: int = 500,
    *,
    blind: bool = False,
) -> list[tuple[ColumnInput, str | None]]:
    """Load Gretel-PII-masking-EN-v1 corpus sample and convert to our format.

    The bundled fixture (``tests/fixtures/corpora/gretel_en_sample.json``)
    is **already flattened**: each record is ``{"entity_type": <data_classifier
    type>, "value": <raw value>}``.  The downloader in
    ``scripts/download_corpora.py`` performs the raw-span ETL via
    :func:`ast.literal_eval` over Gretel's Python-repr ``entities`` field,
    maps labels through :data:`GRETEL_EN_TYPE_MAP`, and writes the mapped
    post-ETL labels to disk.  The loader therefore uses an identity map
    over the already-mapped taxonomy labels.

    Args:
        path: Path to JSON sample file. Defaults to bundled fixture.
        max_rows: Maximum sample values per entity type.
        blind: If True, use generic column names (col_0, col_1, ...) so
            the column name engine cannot cheat.

    Returns:
        List of ``(ColumnInput, expected_entity_type)`` tuples.
    """
    if path is None:
        path = _FIXTURES_DIR / "gretel_en_sample.json"
    else:
        path = Path(path)

    records = _load_json_corpus(path)
    if not records:
        logger.warning("No records loaded from Gretel-EN corpus at %s", path)
        return []

    return _records_to_corpus(records, _GRETEL_EN_POST_ETL_IDENTITY, "gretel_en", max_rows, blind=blind)


def load_gretel_finance_corpus(
    path: Path | str | None = None,
    max_rows: int = 500,
    *,
    blind: bool = False,
    language: str | None = None,
) -> list[tuple[ColumnInput, str | None]]:
    """Load the Gretel synthetic_pii_finance_multilingual corpus sample.

    Like :func:`load_gretel_en_corpus`, the bundled fixture
    (``tests/fixtures/corpora/gretel_finance_sample.json``) is
    **already flattened** to the ``{"entity_type": <data_classifier
    type>, "value": <raw value>}`` schema.  The download-side ETL in
    ``scripts/download_corpora.py`` slices span values out of
    ``generated_text`` via ``pii_spans`` offsets, maps labels through
    :data:`GRETEL_FINANCE_TYPE_MAP`, and writes the post-ETL taxonomy
    labels to disk.  Credential records in the fixture additionally
    retain a ``source_context`` field so that downstream tests can
    spot-check credentials-in-prose — the loader ignores it.

    Args:
        path: Path to JSON sample file. Defaults to bundled fixture.
        max_rows: Maximum sample values per entity type.
        blind: If True, use generic column names (``col_0``, ``col_1``,
            ...) so the column-name engine cannot cheat.
        language: Optional filter on the ``source_language`` metadata
            field; only applied to records that carry one (credentials
            only in the bundled fixture).  Reserved for future
            per-language evaluation hooks.

    Returns:
        List of ``(ColumnInput, expected_entity_type)`` tuples.
    """
    if path is None:
        path = _FIXTURES_DIR / "gretel_finance_sample.json"
    else:
        path = Path(path)

    records = _load_json_corpus(path)
    if not records:
        logger.warning("No records loaded from Gretel-finance corpus at %s", path)
        return []

    if language is not None:
        records = [r for r in records if r.get("source_language") is None or r.get("source_language") == language]

    return _records_to_corpus(
        records,
        _GRETEL_FINANCE_POST_ETL_IDENTITY,
        "gretel_finance",
        max_rows,
        blind=blind,
    )


#: Generic sentinel for "this column's ground truth is that nothing
#: sensitive should fire".  Used for SecretBench/gitleaks `is_secret=False`
#: rows and `detect_secrets` `non_secret`/`false_positive` rows.  The
#: meta-classifier learns this as a real class.
NEGATIVE_GROUND_TRUTH: str = "NEGATIVE"

# Map detect_secrets record `type` → positive entity_type.  Anything not in
# the map (e.g. `non_secret`, `false_positive`) becomes NEGATIVE.
_DETECT_SECRETS_TYPE_MAP: dict[str, str] = {
    "aws_access_key": "CREDENTIAL",
    "slack_token": "CREDENTIAL",
    "stripe_key": "CREDENTIAL",
    "basic_auth": "CREDENTIAL",
    "jwt": "CREDENTIAL",
    "private_key": "CREDENTIAL",
    "generic_secret": "CREDENTIAL",
    "password_in_url": "CREDENTIAL",
    "github_token": "CREDENTIAL",
}


def _credential_corpus_to_columns(
    records: list[dict],
    *,
    source_name: str,
    positive_label: str,
    shard_size: int,
    blind: bool,
    extra_metadata_key: str | None = None,
) -> list[tuple[ColumnInput, str | None]]:
    """Convert credential-scanner-style records to one-column-per-shard.

    Unlike :func:`_records_to_corpus`, this does NOT collapse to a single
    column per type: each positive/negative pool is chunked into
    ``shard_size``-sized ``ColumnInput``s so the meta-classifier sees
    multiple column-level examples per corpus.  This is the loader-level
    half of the sharding strategy — the shard_builder does more elaborate
    stratification on top of these raw records.

    ``positive_label`` is the ground truth for ``is_secret=True`` rows
    (typically ``"CREDENTIAL"``).  ``is_secret=False`` rows become
    ``NEGATIVE_GROUND_TRUTH``.

    ``extra_metadata_key`` (optional): if set, the per-record value of
    that key (e.g. ``source_type`` for gitleaks) is preserved by grouping
    positive rows by its value.  Negative rows are always grouped as one
    pool — the sharder can re-slice them later.

    Returns a list of ``(ColumnInput, ground_truth_label)`` tuples.  The
    raw records remain available to callers that want finer control
    via :func:`load_secretbench_raw_records`, etc.
    """
    positives: list[str] = []
    negatives: list[str] = []
    pos_by_key: dict[str, list[str]] = {}

    for rec in records:
        value = rec.get("value")
        if not value:
            continue
        is_secret = rec.get("is_secret")
        # Default: treat records with no is_secret flag as positive.
        if is_secret is False:
            negatives.append(str(value))
        else:
            positives.append(str(value))
            if extra_metadata_key is not None:
                key = str(rec.get(extra_metadata_key, "_unknown"))
                pos_by_key.setdefault(key, []).append(str(value))

    corpus: list[tuple[ColumnInput, str | None]] = []
    shard_idx = 0

    def _emit(values: list[str], label: str, slug: str) -> None:
        nonlocal shard_idx
        for k in range(0, len(values), shard_size):
            chunk = values[k : k + shard_size]
            if not chunk:
                continue
            if blind:
                col_name = f"col_{shard_idx}"
                col_id = f"{source_name}_blind_{slug}_{shard_idx}"
            else:
                col_name = f"{source_name}_{slug}"
                col_id = f"{source_name}_{slug}_{shard_idx}"
            corpus.append(
                (
                    ColumnInput(
                        column_name=col_name,
                        column_id=col_id,
                        data_type="STRING",
                        sample_values=list(chunk),
                    ),
                    label,
                )
            )
            shard_idx += 1

    # Emit positives.  If we have a per-key breakdown preserve it, else
    # emit as one pool.
    if pos_by_key:
        for key, vs in sorted(pos_by_key.items()):
            _emit(vs, positive_label, f"pos_{key}")
    elif positives:
        _emit(positives, positive_label, "pos")

    # Emit negatives as a single pool (sharder can re-stratify).
    if negatives:
        _emit(negatives, NEGATIVE_GROUND_TRUTH, "neg")

    return corpus


def load_secretbench_corpus(
    path: Path | str | None = None,
    *,
    shard_size: int = 200,
    blind: bool = False,
) -> list[tuple[ColumnInput, str | None]]:
    """Load the SecretBench sample (TP + TN) as sharded columns.

    Emits ``CREDENTIAL`` ground-truth rows for ``is_secret=True`` records
    and ``NEGATIVE`` ground-truth rows for ``is_secret=False`` records,
    chunking each pool into ``shard_size``-sized ``ColumnInput``s.

    Args:
        path: Path to JSON file. Defaults to bundled fixture.
        shard_size: Sample values per emitted column.
        blind: If True, use generic column names (col_0, col_1, ...).

    Returns:
        List of ``(ColumnInput, ground_truth_label)`` tuples where
        ground_truth is ``"CREDENTIAL"`` or ``"NEGATIVE"``.
    """
    if path is None:
        path = _FIXTURES_DIR / "secretbench_sample.json"
    else:
        path = Path(path)

    records = _load_json_corpus(path)
    if not records:
        logger.warning("No records loaded from SecretBench corpus at %s", path)
        return []

    return _credential_corpus_to_columns(
        records,
        source_name="secretbench",
        positive_label="CREDENTIAL",
        shard_size=shard_size,
        blind=blind,
    )


def load_gitleaks_corpus(
    path: Path | str | None = None,
    *,
    shard_size: int = 50,
    blind: bool = False,
) -> list[tuple[ColumnInput, str | None]]:
    """Load the gitleaks fixtures (30 TP / 141 TN) as sharded columns.

    Preserves ``source_type`` (gitleaks rule id) as a grouping key for
    positive rows so the loader emits one column per vendor (gcp, aws,
    azure, hashicorp, ...) rather than merging all TPs into one bucket.
    Negatives are emitted as a single pool.

    The hashicorp row (1 row, ``is_secret=False``) is preserved at its
    original label — this reinforces the XOR-encoded Hashicorp Terraform
    Cloud suppression behaviour shipped in commit 3773e25.

    Args:
        path: Path to JSON file. Defaults to bundled fixture.
        shard_size: Sample values per emitted column. Default 50 keeps
            even small vendor buckets (1-5 rows) as discoverable columns.
        blind: If True, use generic column names.

    Returns:
        List of ``(ColumnInput, ground_truth_label)`` tuples.
    """
    if path is None:
        path = _FIXTURES_DIR / "gitleaks_fixtures.json"
    else:
        path = Path(path)

    records = _load_json_corpus(path)
    if not records:
        logger.warning("No records loaded from gitleaks corpus at %s", path)
        return []

    return _credential_corpus_to_columns(
        records,
        source_name="gitleaks",
        positive_label="CREDENTIAL",
        shard_size=shard_size,
        blind=blind,
        extra_metadata_key="source_type",
    )


def load_detect_secrets_corpus(
    path: Path | str | None = None,
    *,
    shard_size: int = 20,
    blind: bool = False,
) -> list[tuple[ColumnInput, str | None]]:
    """Load the detect_secrets fixtures (13 hand-curated rows).

    Schema is different from SecretBench/gitleaks: uses ``type`` (e.g.
    ``aws_access_key``) and ``expected_detected`` instead of
    ``is_secret``.  Types in :data:`_DETECT_SECRETS_TYPE_MAP` become
    ``CREDENTIAL`` rows; ``non_secret`` and ``false_positive`` rows
    become ``NEGATIVE`` rows.

    Args:
        path: Path to JSON file. Defaults to bundled fixture.
        shard_size: Sample values per emitted column.  Default is small
            because this fixture only has 13 rows.
        blind: If True, use generic column names.

    Returns:
        List of ``(ColumnInput, ground_truth_label)`` tuples.
    """
    if path is None:
        path = _FIXTURES_DIR / "detect_secrets_fixtures.json"
    else:
        path = Path(path)

    records = _load_json_corpus(path)
    if not records:
        logger.warning("No records loaded from detect_secrets corpus at %s", path)
        return []

    # Normalise into the common {is_secret, value} schema so we can reuse
    # the _credential_corpus_to_columns helper.
    normalised: list[dict] = []
    for rec in records:
        t = rec.get("type", "")
        value = rec.get("value")
        if not value:
            continue
        if t in _DETECT_SECRETS_TYPE_MAP:
            normalised.append({"value": value, "is_secret": True, "source_type": t})
        else:
            normalised.append({"value": value, "is_secret": False, "source_type": t})

    return _credential_corpus_to_columns(
        normalised,
        source_name="detect_secrets",
        positive_label="CREDENTIAL",
        shard_size=shard_size,
        blind=blind,
    )


def load_synthetic_corpus(
    samples_per_type: int = 200,
) -> list[tuple[ColumnInput, str | None]]:
    """Wrap the existing Faker-based synthetic generator.

    Args:
        samples_per_type: Number of sample values per entity type.

    Returns:
        List of (ColumnInput, expected_entity_type) tuples.
    """
    from tests.benchmarks.corpus_generator import generate_corpus

    return generate_corpus(samples_per_type=samples_per_type)


def load_corpus(
    source: str,
    *,
    max_rows: int = 500,
    path: Path | str | None = None,
    samples_per_type: int = 200,
    blind: bool = False,
) -> list[tuple[ColumnInput, str | None]]:
    """Dispatcher — load corpus by source name.

    Args:
        source: One of ``"synthetic"``, ``"nemotron"``,
            ``"secretbench"``, ``"gitleaks"``, ``"detect_secrets"``,
            ``"gretel_en"``, ``"gretel_finance"``, or ``"all"``.
        max_rows: Max rows for real-world corpora.
        path: Optional custom path to corpus file.
        samples_per_type: Samples per type for synthetic corpus.
        blind: If True, use generic column names (col_0, col_1, ...) to
            test classification from sample values alone.

    Returns:
        List of ``(ColumnInput, expected_entity_type)`` tuples.
    """
    if source == "synthetic":
        return load_synthetic_corpus(samples_per_type=samples_per_type)
    elif source == "nemotron":
        return load_nemotron_corpus(path=path, max_rows=max_rows, blind=blind)
    elif source == "secretbench":
        return load_secretbench_corpus(path=path, blind=blind)
    elif source == "gitleaks":
        return load_gitleaks_corpus(path=path, blind=blind)
    elif source == "detect_secrets":
        return load_detect_secrets_corpus(path=path, blind=blind)
    elif source == "gretel_en":
        return load_gretel_en_corpus(path=path, max_rows=max_rows, blind=blind)
    elif source == "gretel_finance":
        return load_gretel_finance_corpus(path=path, max_rows=max_rows, blind=blind)
    elif source == "all":
        corpus: list[tuple[ColumnInput, str | None]] = []
        corpus.extend(load_synthetic_corpus(samples_per_type=samples_per_type))
        corpus.extend(load_nemotron_corpus(max_rows=max_rows, blind=blind))
        corpus.extend(load_secretbench_corpus(blind=blind))
        corpus.extend(load_gitleaks_corpus(blind=blind))
        corpus.extend(load_detect_secrets_corpus(blind=blind))
        corpus.extend(load_gretel_en_corpus(max_rows=max_rows, blind=blind))
        corpus.extend(load_gretel_finance_corpus(max_rows=max_rows, blind=blind))
        return corpus
    else:
        msg = (
            f"Unknown corpus source: {source!r}. Valid: synthetic, "
            "nemotron, secretbench, gitleaks, detect_secrets, "
            "gretel_en, gretel_finance, all"
        )
        raise ValueError(msg)
