"""Shard builder — construct column-sized training rows from raw corpora.

Implements the sharding strategy from
``docs/research/meta_classifier/sharding_strategy.md``:

* 75 unique shards per ``(entity_type, real_corpus)`` combo
* M sample count stratified across three buckets:
    25% in ``[60, 120]``, 50% in ``[150, 300]``, 25% in ``[400, 800]``
* Sample values **without replacement** within ``(type, corpus)``
* Any shard that has to reuse values is tagged ``sampling="resampled"``
  so downstream bootstrap CI code can exclude it
* ``column_id`` invariant: ``{corpus}_{mode}_{type}_shard{k}`` — guaranteed
  unique across all shards emitted by a single build so that the 80/20
  train/test split can assert no overlap.
* Underfit-class fallback: types that do not exist in any real corpus
  fall back to 150 synthetic shards (§4.3 of the research doc).

This module is consumed by
``tests/benchmarks/meta_classifier/build_training_data.py`` — it does not
directly call engines, it only groups raw values into ``ColumnInput``
objects and returns a uniform ``ShardSpec`` for each one.  The caller is
responsible for running the engines and producing ``TrainingRow``s.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from data_classifier.core.types import ColumnInput
from tests.benchmarks.corpus_loader import (
    _FIXTURES_DIR,
    NEGATIVE_GROUND_TRUTH,
    NEMOTRON_TYPE_MAP,
    _classify_credential_value_shape,
)
from tests.benchmarks.corpus_loader import (
    _GRETEL_EN_POST_ETL_IDENTITY as _GRETEL_EN_POOL_IDENTITY,
)
from tests.benchmarks.corpus_loader import (
    _GRETEL_FINANCE_POST_ETL_IDENTITY as _GRETEL_FINANCE_POOL_IDENTITY,
)
from tests.benchmarks.corpus_loader import (
    _OPENPII_1M_POST_ETL_IDENTITY as _OPENPII_1M_POOL_IDENTITY,
)
from tests.benchmarks.negative_corpus import (
    flatten_negative_corpus,
    load_diverse_negative_corpus,
)

# ── Sharding parameters (Session A §7 TL;DR) ───────────────────────────────

#: Unique shards per ``(entity_type, real_corpus)`` combination.
SHARDS_PER_REAL_CORPUS: int = 75

#: Synthetic shards emitted for types that also appear in a real corpus
#: — keeps real:synthetic ratio tilted toward real without starving the
#: synthetic-only classes.
SYNTH_SHARDS_BACKED: int = 30

#: Synthetic shards emitted for types that exist only in the Faker
#: synthetic generator (IBAN, BITCOIN_ADDRESS, VIN, MBI, NPI, DEA, EIN,
#: CANADIAN_SIN, ETHEREUM_ADDRESS).
SYNTH_SHARDS_SYNTHETIC_ONLY: int = 150

#: Bucketed M distribution: (weight, lo, hi).
SHARD_SIZE_BUCKETS: tuple[tuple[float, int, int], ...] = (
    (0.25, 60, 120),
    (0.50, 150, 300),
    (0.25, 400, 800),
)

#: Named-mode shards emit a descriptive column name; blind-mode emits a
#: generic ``col_{idx}``.  The same shard values appear in both modes so
#: the caller's named/blind doubling stays invariant.
NAMED_COLUMN_NAME_FMT: str = "{corpus}_{type_lower}"

#: Credential corpora: CREDENTIAL positives + NEGATIVE rows.
_CREDENTIAL_CORPORA: tuple[str, ...] = ("secretbench", "gitleaks", "detect_secrets")


# ── Structural presence detection (multi-label ground truth) ──────────────

#: Lightweight regexes for detecting structurally present families in
#: shard sample values.  These are intentionally simple — we are NOT
#: reclassifying, just checking "does this text contain a URL/email/
#: credential substring?" to build honest multi-label ground truth.
_URL_RE = re.compile(r"https?://[a-zA-Z0-9]", re.ASCII)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.ASCII)
_CREDENTIAL_PREFIX_RE = re.compile(
    r"(?:"
    r"sk-[a-zA-Z0-9]{20}"  # OpenAI
    r"|ghp_[a-zA-Z0-9]{36}"  # GitHub PAT
    r"|ghs_[a-zA-Z0-9]{36}"  # GitHub app token
    r"|glpat-[a-zA-Z0-9\-]{20}"  # GitLab PAT
    r"|xox[baprs]-[a-zA-Z0-9\-]+"  # Slack
    r"|AKIA[A-Z0-9]{16}"  # AWS access key
    r"|AIzaSy[a-zA-Z0-9_\-]{33}"  # Google API key
    r"|ya29\.[a-zA-Z0-9_\-]+"  # Google OAuth
    r"|eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}"  # JWT
    r"|-----BEGIN\s(?:RSA\s|EC\s)?PRIVATE\sKEY-----"  # Private key (RSA/EC/generic)
    r"|sk-ant-[a-zA-Z0-9\-]{20}"  # Anthropic
    r"|glc_[a-zA-Z0-9]{20,}"  # Grafana cloud token
    r"|dapi[a-zA-Z0-9]{32}"  # Databricks token
    r"|ops_eyJ[a-zA-Z0-9]"  # 1Password service account
    r")",
    re.ASCII,
)

#: Values matching ``_CREDENTIAL_PREFIX_RE`` that also match this
#: pattern are considered placeholders/examples, NOT format-valid
#: credentials.  Used to avoid relabeling ``AIzaSyXXXXXXXXX...`` or
#: ``glc_111111111...`` as true positives.
_PLACEHOLDER_RE = re.compile(
    r"[Xx]{6,}"  # repeated X/x filler
    r"|[0]{6,}"  # repeated zeros
    r"|EXAMPLE"  # AWS example key marker
    r"|PUT_YOUR_"  # placeholder instruction
    r"|aaaa{4,}"  # repeated 'a' filler
    r"|1{10,}",  # repeated '1' filler (e.g. glc_1111...)
    re.ASCII,
)


def _detect_structural_families(values: list[str], primary_family: str) -> list[str]:
    """Scan sample values and return all families structurally present.

    Always includes ``primary_family`` (the single-label ground truth).
    Adds URL, CONTACT (for email), or CREDENTIAL when structural patterns
    are found in the values.  Only families *different* from the primary
    are scanned — no point confirming what we already know.

    Uses a low threshold: if >= 3 values match a pattern, the family is
    considered present.  This avoids noise from single-value coincidences
    (e.g. a URL appearing once in a 300-value CREDENTIAL shard is noise).
    """
    families = {primary_family}
    min_hits = 3

    # Only scan for families that differ from the primary
    if primary_family != "URL":
        hits = sum(1 for v in values if _URL_RE.search(v))
        if hits >= min_hits:
            families.add("URL")

    if primary_family != "CONTACT":
        hits = sum(1 for v in values if _EMAIL_RE.search(v))
        if hits >= min_hits:
            families.add("CONTACT")

    if primary_family != "CREDENTIAL":
        hits = sum(1 for v in values if _CREDENTIAL_PREFIX_RE.search(v))
        if hits >= min_hits:
            families.add("CREDENTIAL")

    return sorted(families)


# ── Shard specification ────────────────────────────────────────────────────


@dataclass
class ShardSpec:
    """One shard = one training row after engine extraction.

    Carries enough metadata for the training-data builder to stamp
    ``TrainingRow.column_id`` and for downstream evaluation code to slice
    on corpus/mode/resampled-ness.
    """

    column: ColumnInput
    ground_truth: str
    corpus: str
    mode: str  # "named" or "blind"
    source: str  # "real" or "synthetic"
    shard_index: int
    column_id: str
    sampling: str = "unique"  # "unique" | "resampled"
    extra_metadata: dict[str, object] = field(default_factory=dict)
    #: Multi-label ground truth: all families structurally present in
    #: the shard's sample values.  Always includes the primary
    #: ``ground_truth`` family.  Populated by :func:`annotate_shard_families`.
    ground_truth_families: list[str] = field(default_factory=list)


# ── Pool extraction ────────────────────────────────────────────────────────


def _load_raw_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return json.load(f)


# LLM-generated corpora (Nemotron, Gretel) produce CC/ABA values with
# correct format but random digits — ~90% fail Luhn/ABA checksum.
# Filter to valid-checksum values only across all pool functions.
def _passes_checksum(mapped_type: str, value: str) -> bool:
    """Return True if the value passes the checksum for its entity type,
    or if the entity type has no checksum requirement."""
    from data_classifier.engines.validators import aba_checksum_check, luhn_strip_check, vin_checkdigit_check

    if mapped_type == "CREDIT_CARD":
        return luhn_strip_check(value)
    if mapped_type == "ABA_ROUTING":
        return aba_checksum_check(value)
    if mapped_type == "VIN":
        return vin_checkdigit_check(value)
    return True


def _gretel_en_pool() -> dict[str, list[str]]:
    """Return ``{mapped_type: [values...]}`` for the Gretel-EN sample.

    The fixture is already flattened with post-ETL data_classifier labels
    (see ``corpus_loader.load_gretel_en_corpus``), so ``entity_type``
    values are passed through an identity map.
    """
    records = _load_raw_records(_FIXTURES_DIR / "gretel_en_sample.json")
    pool: dict[str, list[str]] = {}
    for rec in records:
        ext = rec.get("entity_type", rec.get("type", ""))
        value = rec.get("value", "")
        if not value or not ext:
            continue
        mapped = _GRETEL_EN_POOL_IDENTITY.get(ext)
        if mapped is None:
            continue
        if not _passes_checksum(mapped, str(value)):
            continue
        pool.setdefault(mapped, []).append(str(value))
    return pool


def _gretel_finance_pool() -> dict[str, list[str]]:
    """Return ``{mapped_type: [values...]}`` for the Gretel-finance sample.

    Parallels :func:`_gretel_en_pool`.  The fixture is flattened with
    post-ETL taxonomy labels (see
    ``corpus_loader.load_gretel_finance_corpus``) and carries credential
    records with additional ``source_context`` metadata — the pool only
    uses ``entity_type`` and ``value``.
    """
    records = _load_raw_records(_FIXTURES_DIR / "gretel_finance_sample.json")
    pool: dict[str, list[str]] = {}
    for rec in records:
        ext = rec.get("entity_type", rec.get("type", ""))
        value = rec.get("value", "")
        if not value or not ext:
            continue
        mapped = _GRETEL_FINANCE_POOL_IDENTITY.get(ext)
        if mapped is None:
            continue
        # Repartition CREDENTIAL into specific subtypes by value shape
        # so benchmark ground truth matches per-pattern detection output.
        if mapped == "CREDENTIAL":
            mapped = _classify_credential_value_shape(str(value))
        if not _passes_checksum(mapped, str(value)):
            continue
        pool.setdefault(mapped, []).append(str(value))
    return pool


def _nemotron_pool() -> dict[str, list[str]]:
    records = _load_raw_records(_FIXTURES_DIR / "nemotron_sample.json")
    pool: dict[str, list[str]] = {}
    for rec in records:
        ext = rec.get("entity_type", rec.get("type", ""))
        value = rec.get("value", "")
        if not value or not ext:
            continue
        # Repartition credential-bucket records by value shape before
        # applying the type map, matching corpus_loader.load_nemotron_corpus.
        if ext in ("password", "CREDENTIAL"):
            mapped = _classify_credential_value_shape(str(value))
        else:
            mapped = NEMOTRON_TYPE_MAP.get(ext)
        if mapped is None:
            continue
        if not _passes_checksum(mapped, str(value)):
            continue
        pool.setdefault(mapped, []).append(str(value))
    return pool


def _openpii_1m_pool() -> dict[str, list[str]]:
    """Return ``{mapped_type: [values...]}`` for the openpii-1m sample.

    The fixture is already flattened with post-ETL data_classifier labels
    (see ``corpus_loader.load_openpii_1m_corpus``), so ``entity_type``
    values are passed through an identity map.
    """
    records = _load_raw_records(_FIXTURES_DIR / "openpii_1m_sample.json")
    pool: dict[str, list[str]] = {}
    for rec in records:
        ext = rec.get("entity_type", rec.get("type", ""))
        value = rec.get("value", "")
        if not value or not ext:
            continue
        mapped = _OPENPII_1M_POOL_IDENTITY.get(ext)
        if mapped is None:
            continue
        if not _passes_checksum(mapped, str(value)):
            continue
        pool.setdefault(mapped, []).append(str(value))
    return pool


def _credential_corpus_pool(corpus_name: str) -> dict[str, list[str]]:
    """Return ``{subtype: [...], "NEGATIVE": [...]}`` for a credential corpus.

    Repartitions credential positives into specific subtypes (API_KEY,
    PRIVATE_KEY, OPAQUE_SECRET) so the benchmark ground truth matches
    the classifier's per-pattern detection output.

    * **detect_secrets**: uses ``_DETECT_SECRETS_TYPE_MAP`` to map each
      record's ``type`` field to the correct subtype.
    * **gitleaks**: uses ``_GITLEAKS_SOURCE_TYPE_MAP`` to map each
      record's ``source_type`` field to the correct subtype.
    * **secretbench**: uses ``_classify_credential_value_shape`` to
      infer subtype from the value itself (JWT → API_KEY,
      PEM → PRIVATE_KEY, everything else → OPAQUE_SECRET).
    """
    pool: dict[str, list[str]] = {NEGATIVE_GROUND_TRUTH: []}

    filename = {
        "secretbench": "secretbench_sample_v2.json",
        "gitleaks": "gitleaks_fixtures.json",
        "detect_secrets": "detect_secrets_fixtures.json",
    }[corpus_name]
    records = _load_raw_records(_FIXTURES_DIR / filename)

    if corpus_name == "detect_secrets":
        from tests.benchmarks.corpus_loader import _DETECT_SECRETS_TYPE_MAP

        for rec in records:
            value = rec.get("value")
            t = rec.get("type", "")
            if not value:
                continue
            subtype = _DETECT_SECRETS_TYPE_MAP.get(t)
            if subtype is not None:
                pool.setdefault(subtype, []).append(str(value))
            else:
                pool[NEGATIVE_GROUND_TRUTH].append(str(value))
        return _relabel_negative_by_regex(pool)

    if corpus_name == "gitleaks":
        from tests.benchmarks.corpus_loader import _GITLEAKS_SOURCE_TYPE_MAP

        for rec in records:
            value = rec.get("value")
            if not value:
                continue
            if rec.get("is_secret") is False:
                v_str = str(value)
                v_lower = v_str.lower()
                # Skip non-credential PII (URLs, emails) — detectable
                # but not truly NEGATIVE.
                if "http://" in v_lower or "https://" in v_lower:
                    continue
                if _EMAIL_RE.search(v_str):
                    continue
                # Relabel format-valid credentials by value shape.
                # Source corpora mark revoked/test/example keys as
                # "false positive", but for FORMAT detection these
                # are true positives.  Placeholder patterns (repeated
                # X, 0, example markers) stay NEGATIVE.
                if _CREDENTIAL_PREFIX_RE.search(v_str) and not _PLACEHOLDER_RE.search(v_str):
                    subtype = _classify_credential_value_shape(v_str)
                    pool.setdefault(subtype, []).append(v_str)
                else:
                    pool[NEGATIVE_GROUND_TRUTH].append(v_str)
            else:
                source_type = rec.get("source_type", "")
                subtype = _GITLEAKS_SOURCE_TYPE_MAP.get(source_type, "OPAQUE_SECRET")
                pool.setdefault(subtype, []).append(str(value))
        return _relabel_negative_by_regex(pool)

    # secretbench — no per-record metadata, classify by value shape.
    for rec in records:
        value = rec.get("value")
        if not value:
            continue
        if rec.get("is_secret") is False:
            v_str = str(value)
            v_lower = v_str.lower()
            # Skip non-credential PII (URLs, emails) — detectable
            # but not truly NEGATIVE.
            if "http://" in v_lower or "https://" in v_lower:
                continue
            if _EMAIL_RE.search(v_str):
                continue
            # Relabel format-valid credentials as their subtype.
            if _CREDENTIAL_PREFIX_RE.search(v_str) and not _PLACEHOLDER_RE.search(v_str):
                subtype = _classify_credential_value_shape(v_str)
                pool.setdefault(subtype, []).append(v_str)
            else:
                pool[NEGATIVE_GROUND_TRUTH].append(v_str)
        else:
            subtype = _classify_credential_value_shape(str(value))
            pool.setdefault(subtype, []).append(str(value))

    # Final pass: run the regex engine on remaining NEGATIVE values.
    # Prefix-based relabeling misses values detected via KV parsing
    # or patterns not in _CREDENTIAL_PREFIX_RE.  The regex engine is
    # the definitive detector — if it fires, the value is mislabeled.
    pool = _relabel_negative_by_regex(pool)

    return pool


def _relabel_negative_by_regex(pool: dict[str, list[str]]) -> dict[str, list[str]]:
    """Move NEGATIVE values to their detected subtype if the regex engine fires.

    Uses scan_text (same as the production text scanning API) to check
    each NEGATIVE value.  Values where a credential pattern matches are
    moved to the detected subtype pool.  Values with no detection stay
    NEGATIVE.
    """
    neg_values = pool.get(NEGATIVE_GROUND_TRUTH, [])
    if not neg_values:
        return pool

    from data_classifier.scan_text import TextScanner

    scanner = TextScanner()
    scanner.startup()

    keep_negative: list[str] = []
    for value in neg_values:
        result = scanner.scan(value, min_confidence=0.1)
        if result.findings:
            # Use the highest-confidence finding's entity_type
            top = max(result.findings, key=lambda f: f.confidence)
            subtype = top.entity_type
            pool.setdefault(subtype, []).append(value)
        else:
            keep_negative.append(value)

    pool[NEGATIVE_GROUND_TRUTH] = keep_negative
    return pool


# ── Shard assembly ─────────────────────────────────────────────────────────


def _bucketed_sizes(
    num_shards: int,
    rng: random.Random,
    buckets: tuple[tuple[float, int, int], ...] = SHARD_SIZE_BUCKETS,
) -> list[int]:
    """Return ``num_shards`` sample sizes drawn from ``buckets``."""
    sizes: list[int] = []
    for weight, lo, hi in buckets:
        share = int(round(weight * num_shards))
        for _ in range(share):
            sizes.append(rng.randint(lo, hi))
    # Top up / trim to exactly num_shards.
    while len(sizes) < num_shards:
        _, lo, hi = buckets[len(buckets) // 2]  # pad with middle bucket
        sizes.append(rng.randint(lo, hi))
    sizes = sizes[:num_shards]
    rng.shuffle(sizes)
    return sizes


def _slice_pool(
    values: list[str],
    num_shards: int,
    rng: random.Random,
    *,
    buckets: tuple[tuple[float, int, int], ...] = SHARD_SIZE_BUCKETS,
) -> list[tuple[list[str], str]]:
    """Slice a value pool into ``num_shards`` shards.

    Returns ``[(values, sampling_tag), ...]``. Primary strategy is
    **without replacement** at the value level (shards disjoint).  When
    the pool is too small to cover ``sum(bucketed_sizes)`` without
    reuse, the shortfall shards are filled with **replacement** and
    tagged ``"resampled"`` — never silently reused (per
    ``feedback_real_corpora`` and §6.3 of the sharding doc).
    """
    sizes = _bucketed_sizes(num_shards, rng, buckets=buckets)
    total_needed = sum(sizes)

    shuffled = list(values)
    rng.shuffle(shuffled)

    shards: list[tuple[list[str], str]] = []

    if len(shuffled) >= total_needed:
        # Happy path: disjoint slices.
        offset = 0
        for size in sizes:
            shards.append((shuffled[offset : offset + size], "unique"))
            offset += size
        return shards

    # Deficit: fill as many unique shards as we can, then fall back to
    # shard-level sampling with replacement (still draw-from-shuffled,
    # but the pool is replenished between shards so raw values repeat
    # across shards — tagged in metadata).
    offset = 0
    for size in sizes:
        if offset + size <= len(shuffled):
            shards.append((shuffled[offset : offset + size], "unique"))
            offset += size
        else:
            # Sample with replacement from the full pool for this shard.
            if not shuffled:
                shards.append(([], "resampled"))
                continue
            resampled = [rng.choice(shuffled) for _ in range(size)]
            shards.append((resampled, "resampled"))
    return shards


def _emit_shards_for_type(
    *,
    values: list[str],
    ground_truth: str,
    corpus: str,
    source: str,
    num_shards: int,
    rng: random.Random,
    include_named: bool = True,
    include_blind: bool = True,
    column_id_prefix: str | None = None,
    bucket_override: tuple[tuple[float, int, int], ...] | None = None,
) -> list[ShardSpec]:
    """Emit ``num_shards`` shards for one ``(corpus, ground_truth)`` combo.

    The resulting shards already include the named/blind doubling — each
    unique shard is emitted once per requested mode with the same
    underlying values but different column metadata, so the learner sees
    engine features both with and without column-name signal.
    """
    if num_shards <= 0 or not values:
        return []

    buckets = bucket_override if bucket_override is not None else SHARD_SIZE_BUCKETS
    slices = _slice_pool(values, num_shards, rng, buckets=buckets)
    type_lower = ground_truth.lower()
    shards: list[ShardSpec] = []

    prefix = column_id_prefix or f"{corpus}"

    for k, (chunk, sampling_tag) in enumerate(slices):
        if not chunk:
            continue

        if include_named:
            named_id = f"{prefix}_named_{type_lower}_shard{k}"
            named_col = ColumnInput(
                column_name=NAMED_COLUMN_NAME_FMT.format(corpus=corpus, type_lower=type_lower),
                column_id=named_id,
                data_type="STRING",
                sample_values=list(chunk),
            )
            shards.append(
                ShardSpec(
                    column=named_col,
                    ground_truth=ground_truth,
                    corpus=corpus,
                    mode="named",
                    source=source,
                    shard_index=k,
                    column_id=named_id,
                    sampling=sampling_tag,
                )
            )

        if include_blind:
            blind_id = f"{prefix}_blind_{type_lower}_shard{k}"
            blind_col = ColumnInput(
                column_name=f"col_{k}",
                column_id=blind_id,
                data_type="STRING",
                sample_values=list(chunk),
            )
            shards.append(
                ShardSpec(
                    column=blind_col,
                    ground_truth=ground_truth,
                    corpus=corpus,
                    mode="blind",
                    source=source,
                    shard_index=k,
                    column_id=blind_id,
                    sampling=sampling_tag,
                )
            )

    return shards


# ── Public builder entry points ────────────────────────────────────────────


def build_real_corpus_shards(
    *,
    shards_per_type: int = SHARDS_PER_REAL_CORPUS,
    seed: int = 20260412,
) -> list[ShardSpec]:
    """Emit shards for every ``(entity_type, real_corpus)`` combo.

    Covers Nemotron, Gretel-EN, Gretel-finance, openpii-1m, SecretBench,
    gitleaks, and detect_secrets (including each corpus's NEGATIVE rows
    where applicable).  A legacy 300k-row corpus was retired in Sprint 9
    due to a non-OSS license; see ``docs/process/LICENSE_AUDIT.md``.

    Returns a flat list of :class:`ShardSpec` objects.  The caller runs
    feature extraction against each spec to produce a training row.
    """
    rng = random.Random(seed)
    shards: list[ShardSpec] = []

    # Nemotron — bare-value corpus, positives only.
    pool_nemo = _nemotron_pool()
    for gt, values in sorted(pool_nemo.items()):
        shards.extend(
            _emit_shards_for_type(
                values=values,
                ground_truth=gt,
                corpus="nemotron",
                source="real",
                num_shards=shards_per_type,
                rng=rng,
            )
        )

    # Gretel-PII-masking-EN-v1 — mixed-label corpus (Sprint 9).  Schema
    # is already normalised via scripts/download_corpora.py:download_gretel_en,
    # so we treat it like nemotron: positives only, one ground-truth per
    # column shard.
    pool_gretel_en = _gretel_en_pool()
    for gt, values in sorted(pool_gretel_en.items()):
        shards.extend(
            _emit_shards_for_type(
                values=values,
                ground_truth=gt,
                corpus="gretel_en",
                source="real",
                num_shards=shards_per_type,
                rng=rng,
            )
        )

    # Gretel synthetic_pii_finance_multilingual — mixed-label corpus
    # (Sprint 10).  Same handling as Gretel-EN: already-normalised
    # schema, positives only, one ground-truth per shard.  The reason
    # it's an *additional* corpus rather than a replacement is that its
    # credential labels live inside long-form financial-document prose
    # (loan agreements, MT940 statements, insurance forms), which is
    # the targeted intervention for the ``heuristic_avg_length``
    # corpus-fingerprint shortcut diagnosed in M1 — credentials from
    # this corpus have *long* surrounding context, breaking the
    # ``short-text == credential`` correlation that dominated the
    # Sprint 9 meta-classifier.
    pool_gretel_finance = _gretel_finance_pool()
    for gt, values in sorted(pool_gretel_finance.items()):
        shards.extend(
            _emit_shards_for_type(
                values=values,
                ground_truth=gt,
                corpus="gretel_finance",
                source="real",
                num_shards=shards_per_type,
                rng=rng,
            )
        )

    # ai4privacy/openpii-1m — multilingual corpus (Sprint 15).
    # First real-corpus source for NATIONAL_ID.
    pool_openpii = _openpii_1m_pool()
    for gt, values in sorted(pool_openpii.items()):
        shards.extend(
            _emit_shards_for_type(
                values=values,
                ground_truth=gt,
                corpus="openpii_1m",
                source="real",
                num_shards=shards_per_type,
                rng=rng,
            )
        )

    # Credential corpora — emit subtype pools (API_KEY, PRIVATE_KEY,
    # OPAQUE_SECRET) plus NEGATIVE.
    # These pools are small (~500 positives / ~550 negatives for
    # SecretBench, ~30/141 for gitleaks, ~8/5 for detect_secrets), so
    # unique-without-replacement shards are impossible at
    # shards_per_type=75.  The slicer falls back to shard-level
    # with-replacement sampling and tags the affected shards
    # ``sampling="resampled"`` per §6.3.  We apply smaller shard-size
    # buckets for credential corpora so that even 30-row pools can
    # produce multiple distinct shards.
    credential_buckets: tuple[tuple[float, int, int], ...] = (
        (0.25, 20, 40),
        (0.50, 50, 100),
        (0.25, 120, 200),
    )
    # Track credential subtype shard counts across corpora to prevent
    # any single subtype from dominating.  OPAQUE_SECRET is the catch-all
    # and accumulates ~3× more shards than API_KEY or PRIVATE_KEY,
    # which causes the meta-classifier to over-predict it.
    max_credential_subtype_shards = shards_per_type * 2  # 150 from credential corpora
    credential_subtype_counts: dict[str, int] = {}
    for corpus in _CREDENTIAL_CORPORA:
        cpool = _credential_corpus_pool(corpus)
        for gt, values in sorted(cpool.items()):
            if not values:
                continue
            already = credential_subtype_counts.get(gt, 0)
            remaining = max(0, max_credential_subtype_shards - already)
            n = min(shards_per_type, remaining) if gt != NEGATIVE_GROUND_TRUTH else shards_per_type
            if n <= 0:
                continue
            shards.extend(
                _emit_shards_for_type(
                    values=values,
                    ground_truth=gt,
                    corpus=corpus,
                    source="real",
                    num_shards=n,
                    rng=rng,
                    bucket_override=credential_buckets,
                )
            )
            credential_subtype_counts[gt] = already + n

    # Sprint 17: source-diverse NEGATIVE corpus.  Five structurally-distinct
    # sources (config, code, business, numeric, prose) at 500 values each.
    # Replaces the homogeneous SecretBench-only NEGATIVE pool as the
    # primary FP-resistance signal while leaving the SecretBench/gitleaks/
    # detect_secrets NEGATIVE rows in place for credential-specific
    # contrast.  See tests/benchmarks/negative_corpus.py and
    # docs/research/negative_corpus_sources.md.
    diverse_neg = load_diverse_negative_corpus()
    diverse_neg_values = [value for _source, value in flatten_negative_corpus(diverse_neg)]
    if diverse_neg_values:
        shards.extend(
            _emit_shards_for_type(
                values=diverse_neg_values,
                ground_truth=NEGATIVE_GROUND_TRUTH,
                corpus="diverse_negative",
                source="real",
                num_shards=shards_per_type,
                rng=rng,
            )
        )

    return shards


# Types that do not exist in any real corpus — must come from synthetic.
SYNTHETIC_ONLY_TYPES: frozenset[str] = frozenset(
    {
        "IBAN",
        "BITCOIN_ADDRESS",
        "ETHEREUM_ADDRESS",
        "VIN",
        "MBI",
        "NPI",
        "DEA_NUMBER",
        "EIN",
        "CANADIAN_SIN",
    }
)


def build_synthetic_shards(
    *,
    synthetic_pool: dict[str, list[str]],
    shards_backed: int = SYNTH_SHARDS_BACKED,
    shards_only: int = SYNTH_SHARDS_SYNTHETIC_ONLY,
    seed: int = 20260412,
) -> list[ShardSpec]:
    """Emit shards from a synthetic-type → [values] pool.

    Real-backed types get ``shards_backed`` shards; synthetic-only types
    get ``shards_only`` shards.  The caller assembles the pool (e.g. by
    calling Faker-backed generators across multiple locales) and passes
    it in; this function knows nothing about Faker.
    """
    rng = random.Random(seed + 1)
    shards: list[ShardSpec] = []
    for gt in sorted(synthetic_pool.keys()):
        values = synthetic_pool[gt]
        if not values:
            continue
        num = shards_only if gt in SYNTHETIC_ONLY_TYPES else shards_backed
        shards.extend(
            _emit_shards_for_type(
                values=values,
                ground_truth=gt,
                corpus="synthetic",
                source="synthetic",
                num_shards=num,
                rng=rng,
            )
        )
    return shards


def build_shards(
    *,
    synthetic_pool: dict[str, list[str]] | None = None,
    shards_per_real: int = SHARDS_PER_REAL_CORPUS,
    synth_backed: int = SYNTH_SHARDS_BACKED,
    synth_only: int = SYNTH_SHARDS_SYNTHETIC_ONLY,
    seed: int = 20260412,
) -> list[ShardSpec]:
    """Full sharding pipeline — real corpora + synthetic augmentation.

    Returns a flat list of shards ready for feature extraction.
    Synthetic pool must be supplied by the caller (the shard builder
    does not depend on Faker).  The union of ``column_id`` values is
    guaranteed unique up to a best-effort assertion.
    """
    shards = build_real_corpus_shards(shards_per_type=shards_per_real, seed=seed)
    if synthetic_pool:
        shards.extend(
            build_synthetic_shards(
                synthetic_pool=synthetic_pool,
                shards_backed=synth_backed,
                shards_only=synth_only,
                seed=seed,
            )
        )

    # Invariant check: column_ids must be unique.  This is cheap and
    # catches any future refactor that accidentally reuses an id.
    seen: set[str] = set()
    for shard in shards:
        assert shard.column_id not in seen, f"duplicate column_id: {shard.column_id}"
        seen.add(shard.column_id)

    # Annotate multi-label ground truth families via structural
    # presence detection on sample values.
    annotate_shard_families(shards)

    return shards


def annotate_shard_families(shards: list[ShardSpec]) -> None:
    """Populate ``ground_truth_families`` on every shard in-place.

    Runs the lightweight structural presence scanner on each shard's
    sample values to detect URL, EMAIL (→ CONTACT), and CREDENTIAL
    patterns that co-occur alongside the primary ground truth.
    """
    from data_classifier.core.taxonomy import family_for

    for shard in shards:
        primary_family = family_for(shard.ground_truth)
        shard.ground_truth_families = _detect_structural_families(
            shard.column.sample_values,
            primary_family,
        )


def summarise_shards(shards: Iterable[ShardSpec]) -> dict[str, object]:
    """Return a lightweight summary for the build stats report."""
    from collections import Counter

    per_class: Counter[str] = Counter()
    per_corpus: Counter[str] = Counter()
    per_mode: Counter[str] = Counter()
    per_source: Counter[str] = Counter()
    resampled = 0
    total = 0
    m_values: list[int] = []

    for s in shards:
        total += 1
        per_class[s.ground_truth] += 1
        per_corpus[s.corpus] += 1
        per_mode[s.mode] += 1
        per_source[s.source] += 1
        if s.sampling == "resampled":
            resampled += 1
        m_values.append(len(s.column.sample_values))

    if m_values:
        m_mean = sum(m_values) / len(m_values)
        m_min = min(m_values)
        m_max = max(m_values)
    else:
        m_mean = m_min = m_max = 0

    return {
        "total": total,
        "per_class": dict(per_class),
        "per_corpus": dict(per_corpus),
        "per_mode": dict(per_mode),
        "per_source": dict(per_source),
        "resampled": resampled,
        "m_mean": m_mean,
        "m_min": m_min,
        "m_max": m_max,
    }


__all__ = [
    "NAMED_COLUMN_NAME_FMT",
    "SHARDS_PER_REAL_CORPUS",
    "SHARD_SIZE_BUCKETS",
    "SYNTHETIC_ONLY_TYPES",
    "SYNTH_SHARDS_BACKED",
    "SYNTH_SHARDS_SYNTHETIC_ONLY",
    "ShardSpec",
    "annotate_shard_families",
    "build_real_corpus_shards",
    "build_shards",
    "build_synthetic_shards",
    "summarise_shards",
]
