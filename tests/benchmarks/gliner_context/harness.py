"""Pluggable measurement harness for GLiNER context-injection strategies.

Design
------
Each strategy is a ``StrategyFn`` — a callable that takes a ``ColumnInput``
and returns a ``(text, entity_types)`` pair to pass into GLiNER2's
``extract_entities``. All strategies share the same entry point, differing
only in how they build the two arguments. This makes baseline / S1 / S2 /
S3 a uniform cross-product.

Corpus shape
------------
We build a ``CorpusRow`` = ``(ColumnInput, ground_truth_entity_type)`` where
the ``sample_values`` come from the Ai4Privacy value pool for that entity
type, and the ``(column_name, table_name, description)`` metadata comes from
a *context template*. Cross-product of N templates × K entity types gives
us a corpus whose size is controlled by the caller, and whose stratification
by "context helpfulness" (helpful / empty / misleading) is explicit.

Ground truth is the Ai4Privacy label — stable across context templates for
the same value pool. Top-1 correctness is therefore "did the model report
the ground-truth entity type as detected at confidence ≥ threshold?".

Not shipping
------------
This file is research-only. It does not modify the production engine, does
not install anything, does not push artifacts to main. Results land in
``docs/experiments/gliner_context/runs/<timestamp>/result.md``.
"""
from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from data_classifier.core.types import ColumnInput

logger = logging.getLogger(__name__)

# ── Type aliases ──────────────────────────────────────────────────────────

#: A pluggable strategy: (ColumnInput) -> (text, entity_types_for_extract_entities)
StrategyFn = Callable[[ColumnInput], tuple[str, "EntityTypes"]]

#: What extract_entities accepts: flat list, or dict of label -> description
EntityTypes = list[str] | dict[str, str]


# ── Ground-truth entity taxonomy used by this research ────────────────────
#
# Matches the 8 entity types production's GLiNER2 engine exposes today (see
# data_classifier/engines/gliner_engine.py:ENTITY_LABEL_DESCRIPTIONS), plus
# the Ai4Privacy label mapping. We deliberately keep the label set small and
# aligned with production so findings here translate cleanly to Sprint 10.

GLINER_LABELS_V2_BASELINE: dict[str, str] = {
    "person": "Names of people or individuals, including first and last names",
    "street address": "Street names, roads, avenues, physical locations with or without house numbers",
    "organization": "Company names, institutions, agencies, or other organizational entities",
    "date of birth": "Dates representing when a person was born, in any format",
    "phone number": (
        "Telephone numbers in any international format with country codes, dashes, dots, or spaces"
    ),
    "national identification number": (
        "Government-issued personal identification numbers such as SSN, national insurance, or tax ID"
    ),
    "email": "Email addresses including international domains and subdomains",
    "ip address": "IPv4 or IPv6 network addresses",
}

#: GLiNER2 label -> our canonical entity type
GLINER_LABEL_TO_ENTITY_TYPE: dict[str, str] = {
    "person": "PERSON_NAME",
    "street address": "ADDRESS",
    "organization": "ORGANIZATION",
    "date of birth": "DATE_OF_BIRTH",
    "phone number": "PHONE",
    "national identification number": "SSN",
    "email": "EMAIL",
    "ip address": "IP_ADDRESS",
}

#: Inverse — used when building column-name hints from ground truth
ENTITY_TYPE_TO_GLINER_LABEL: dict[str, str] = {
    v: k for k, v in GLINER_LABEL_TO_ENTITY_TYPE.items()
}


# ── Corpus construction ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ContextTemplate:
    """A synthetic (column_name, table_name, description) triple.

    ``kind`` is one of:
    - ``"helpful"`` — metadata strongly implies the ground-truth entity type
    - ``"empty"`` — metadata is missing or generic (col_42, t, "")
    - ``"misleading"`` — metadata implies a DIFFERENT entity type
    """

    kind: str
    column_name: str
    table_name: str
    description: str


#: Per-entity-type context template panels. Each entity type has templates
#: across three kinds (helpful / empty / misleading) which lets us
#: stratify the final F1 by "context helpfulness". Pass 1 expands this to
#: ~5 templates per kind to grow the corpus without more hand-authoring
#: bias per cell.
CONTEXT_TEMPLATES: dict[str, list[ContextTemplate]] = {
    "EMAIL": [
        # helpful
        ContextTemplate("helpful", "email_address", "users", "user's primary contact email, required, unique"),
        ContextTemplate("helpful", "contact_email", "crm_contacts", "primary email address for the contact"),
        ContextTemplate("helpful", "notification_email", "preferences", "email where user notifications are sent"),
        ContextTemplate("helpful", "work_email", "employees", "corporate email assigned to the employee"),
        ContextTemplate("helpful", "recovery_email", "auth", "secondary email used for account recovery"),
        # empty
        ContextTemplate("empty", "col_17", "t", ""),
        ContextTemplate("empty", "val", "raw", ""),
        ContextTemplate("empty", "c1", "staging", ""),
        ContextTemplate("empty", "data_field", "imports", ""),
        ContextTemplate("empty", "f42", "x", ""),
        # misleading
        ContextTemplate("misleading", "invoice_number", "billing", "sequential invoice identifier"),
        ContextTemplate("misleading", "tracking_code", "shipments", "parcel tracking identifier"),
        ContextTemplate("misleading", "sku", "inventory", "stock-keeping unit code"),
        ContextTemplate("misleading", "order_id", "orders", "unique order identifier"),
        ContextTemplate("misleading", "license_plate", "vehicles", "vehicle license plate number"),
    ],
    "PHONE": [
        ContextTemplate("helpful", "phone_number", "customers", "customer contact phone, E.164 format"),
        ContextTemplate("helpful", "mobile_number", "users", "user's mobile phone number"),
        ContextTemplate("helpful", "contact_phone", "leads", "primary phone number for the lead"),
        ContextTemplate("helpful", "emergency_contact_phone", "hr", "emergency contact phone on file"),
        ContextTemplate("helpful", "support_phone", "tickets", "phone number attached to the support ticket"),
        ContextTemplate("empty", "col_42", "t", ""),
        ContextTemplate("empty", "v7", "raw", ""),
        ContextTemplate("empty", "field_b", "staging", ""),
        ContextTemplate("empty", "value_col", "imports", ""),
        ContextTemplate("empty", "c12", "y", ""),
        ContextTemplate("misleading", "employee_id", "hr", "internal HR employee identifier"),
        ContextTemplate("misleading", "serial_number", "devices", "hardware serial number"),
        ContextTemplate("misleading", "zipcode", "addresses", "postal zip code"),
        ContextTemplate("misleading", "pin_code", "auth", "numeric PIN code"),
        ContextTemplate("misleading", "version_build", "releases", "build number for the release"),
    ],
    "SSN": [
        ContextTemplate("helpful", "national_id", "applicants", "applicant's national identification number"),
        ContextTemplate("helpful", "ssn", "patients", "patient social security number"),
        ContextTemplate("helpful", "tax_id", "vendors", "vendor's tax identification number"),
        ContextTemplate("helpful", "social_security", "payroll", "employee social security number for payroll"),
        ContextTemplate("helpful", "government_id", "kyc", "government-issued ID from KYC intake"),
        ContextTemplate("empty", "col_03", "t", ""),
        ContextTemplate("empty", "v_id", "raw", ""),
        ContextTemplate("empty", "num_col", "staging", ""),
        ContextTemplate("empty", "field_c", "imports", ""),
        ContextTemplate("empty", "data_11", "z", ""),
        ContextTemplate("misleading", "account_number", "accounts", "internal account reference"),
        ContextTemplate("misleading", "customer_id", "customers", "unique customer identifier"),
        ContextTemplate("misleading", "invoice_ref", "billing", "invoice reference number"),
        ContextTemplate("misleading", "routing_number", "banking", "bank routing number"),
        ContextTemplate("misleading", "employee_number", "hr", "corporate employee number"),
    ],
    "PERSON_NAME": [
        ContextTemplate("helpful", "full_name", "contacts", "contact's full name, first and last"),
        ContextTemplate("helpful", "customer_name", "customers", "customer's legal name on file"),
        ContextTemplate("helpful", "patient_name", "patients", "patient full name from admission record"),
        ContextTemplate("helpful", "employee_name", "hr", "employee full name for HR records"),
        ContextTemplate("helpful", "student_name", "enrollment", "student's legal name"),
        ContextTemplate("empty", "col_91", "t", ""),
        ContextTemplate("empty", "text_col", "raw", ""),
        ContextTemplate("empty", "string_val", "staging", ""),
        ContextTemplate("empty", "field_a", "imports", ""),
        ContextTemplate("empty", "val_8", "x", ""),
        ContextTemplate("misleading", "product_name", "catalog", "catalog product display name"),
        ContextTemplate("misleading", "city_name", "geography", "city name"),
        ContextTemplate("misleading", "brand_name", "brands", "brand display name"),
        ContextTemplate("misleading", "street_name", "addresses", "street name"),
        ContextTemplate("misleading", "project_codename", "projects", "project codename"),
    ],
    "ADDRESS": [
        ContextTemplate("helpful", "street_address", "shipping", "customer shipping street address"),
        ContextTemplate("helpful", "billing_address", "invoices", "billing street address"),
        ContextTemplate("helpful", "home_address", "customers", "customer's residential street address"),
        ContextTemplate("helpful", "delivery_address", "orders", "street address for order delivery"),
        ContextTemplate("helpful", "mailing_address", "contacts", "contact mailing street address"),
        ContextTemplate("empty", "col_55", "t", ""),
        ContextTemplate("empty", "text_field", "raw", ""),
        ContextTemplate("empty", "val_z", "staging", ""),
        ContextTemplate("empty", "field_d", "imports", ""),
        ContextTemplate("empty", "info_col", "y", ""),
        ContextTemplate("misleading", "department_name", "org_chart", "business unit department label"),
        ContextTemplate("misleading", "office_name", "facilities", "office location name"),
        ContextTemplate("misleading", "role_title", "hr", "employee role title"),
        ContextTemplate("misleading", "course_title", "enrollment", "academic course title"),
        ContextTemplate("misleading", "category_name", "catalog", "product category name"),
    ],
    "DATE_OF_BIRTH": [
        ContextTemplate("helpful", "date_of_birth", "patients", "patient's date of birth, YYYY-MM-DD"),
        ContextTemplate("helpful", "dob", "customers", "customer date of birth"),
        ContextTemplate("helpful", "birth_date", "enrollment", "student date of birth"),
        ContextTemplate("helpful", "birthday", "users", "user's birthday on file"),
        ContextTemplate("helpful", "date_born", "applicants", "applicant's date of birth from intake form"),
        ContextTemplate("empty", "col_08", "t", ""),
        ContextTemplate("empty", "date_col", "raw", ""),
        ContextTemplate("empty", "d1", "staging", ""),
        ContextTemplate("empty", "field_date", "imports", ""),
        ContextTemplate("empty", "v_date", "x", ""),
        ContextTemplate("misleading", "order_date", "orders", "order placement date"),
        ContextTemplate("misleading", "transaction_date", "ledger", "transaction posting date"),
        ContextTemplate("misleading", "last_login", "auth", "date of the last login"),
        ContextTemplate("misleading", "created_at", "events", "row creation timestamp"),
        ContextTemplate("misleading", "invoice_date", "billing", "invoice generation date"),
    ],
    "IP_ADDRESS": [
        ContextTemplate("helpful", "client_ip", "access_logs", "client IPv4/IPv6 address at request time"),
        ContextTemplate("helpful", "source_ip", "firewall", "source IP of the incoming request"),
        ContextTemplate("helpful", "remote_addr", "nginx_logs", "remote IP address from the load balancer"),
        ContextTemplate("helpful", "ip_address", "sessions", "session origin IP address"),
        ContextTemplate("helpful", "user_ip", "auth_events", "IP address of the authenticating user"),
        ContextTemplate("empty", "col_21", "t", ""),
        ContextTemplate("empty", "val", "raw", ""),
        ContextTemplate("empty", "str_col", "staging", ""),
        ContextTemplate("empty", "field_ip", "imports", ""),
        ContextTemplate("empty", "data_col", "z", ""),
        ContextTemplate("misleading", "version_string", "releases", "semver release version"),
        ContextTemplate("misleading", "host_tag", "inventory", "host label for inventory"),
        ContextTemplate("misleading", "vlan_id", "network", "VLAN identifier"),
        ContextTemplate("misleading", "machine_name", "hosts", "hostname of the machine"),
        ContextTemplate("misleading", "subnet_label", "network", "human label for the subnet"),
    ],
    "ORGANIZATION": [
        ContextTemplate("helpful", "company_name", "vendors", "legal business name of the vendor"),
        ContextTemplate("helpful", "employer_name", "employees", "employer's legal business name"),
        ContextTemplate("helpful", "organization_name", "accounts", "organization registered on the account"),
        ContextTemplate("helpful", "client_company", "projects", "client company sponsoring the project"),
        ContextTemplate("helpful", "institution_name", "education", "institution issuing the credential"),
        ContextTemplate("empty", "col_67", "t", ""),
        ContextTemplate("empty", "text_val", "raw", ""),
        ContextTemplate("empty", "label_col", "staging", ""),
        ContextTemplate("empty", "field_org", "imports", ""),
        ContextTemplate("empty", "v_col", "y", ""),
        ContextTemplate("misleading", "sku_code", "inventory", "stock-keeping unit code"),
        ContextTemplate("misleading", "product_sku", "catalog", "product SKU identifier"),
        ContextTemplate("misleading", "model_number", "hardware", "hardware model number"),
        ContextTemplate("misleading", "room_number", "facilities", "physical room number"),
        ContextTemplate("misleading", "serial_code", "manufacturing", "unique serial code"),
    ],
}


@dataclass(frozen=True)
class CorpusRow:
    """One measurement row: a ColumnInput + its expected ground truth."""

    column: ColumnInput
    ground_truth: str  # canonical entity type, e.g. "EMAIL"
    context_kind: str  # "helpful" / "empty" / "misleading"


def load_ai4privacy_value_pools(
    fixture_path: Path,
    *,
    min_pool_size: int = 50,
) -> dict[str, list[str]]:
    """Load Ai4Privacy records from the bundled JSON fixture and bucket
    values by canonical entity type.

    Returns:
        Mapping of canonical entity type -> list of string values. Only
        entity types with at least ``min_pool_size`` values are returned.
    """
    from tests.benchmarks.corpus_loader import AI4PRIVACY_TYPE_MAP

    records = json.loads(fixture_path.read_text())
    if not isinstance(records, list):
        raise ValueError(f"Expected list of records in {fixture_path}")

    pools: dict[str, list[str]] = {}
    for rec in records:
        raw = rec.get("entity_type", "")
        val = rec.get("value")
        if not val:
            continue
        canonical = AI4PRIVACY_TYPE_MAP.get(raw)
        if canonical is None:
            continue
        pools.setdefault(canonical, []).append(str(val))

    # Drop pools too small to build a column with
    return {k: v for k, v in pools.items() if len(v) >= min_pool_size}


def build_corpus(
    value_pools: Mapping[str, list[str]],
    *,
    samples_per_column: int = 30,
    rng_seed: int = 42,
) -> list[CorpusRow]:
    """Cross-product value pools × context templates to produce CorpusRows.

    Each entity type that has both (a) a value pool and (b) a template panel
    in :data:`CONTEXT_TEMPLATES` yields one column per template. Values are
    randomly sampled per-(type, template, seed) so the same template under
    two different seeds gets DIFFERENT 30-value slices — which is how we
    get multi-seed replication variance.

    Args:
        value_pools: output of :func:`load_ai4privacy_value_pools`
        samples_per_column: how many values to pack into each column's
            ``sample_values``. Must be ≥ 1.
        rng_seed: PRNG seed for reproducibility. Different seeds produce
            different value slices for the same templates, giving us an
            empirical variance estimate across seeds.

    Returns:
        List of CorpusRow, deterministically ordered by
        ``(ground_truth, context_kind, template_index)``.
    """
    rng = random.Random(rng_seed)
    rows: list[CorpusRow] = []
    for gt in sorted(value_pools):
        if gt not in CONTEXT_TEMPLATES:
            continue
        pool = value_pools[gt]
        for tmpl_idx, tmpl in enumerate(CONTEXT_TEMPLATES[gt]):
            # Each (gt, template, seed) gets an INDEPENDENT draw from the pool.
            # rng.sample preserves no replacement within a draw but consecutive
            # draws from the same rng will see different subsets.
            if len(pool) < samples_per_column:
                values = list(pool)
            else:
                values = rng.sample(pool, samples_per_column)
            col = ColumnInput(
                column_name=tmpl.column_name,
                column_id=f"{gt.lower()}_{tmpl.kind}_{tmpl_idx:02d}_seed{rng_seed}",
                data_type="STRING",
                table_name=tmpl.table_name,
                description=tmpl.description,
                sample_values=list(values),
            )
            rows.append(CorpusRow(column=col, ground_truth=gt, context_kind=tmpl.kind))
    return rows


def build_multi_seed_corpus(
    value_pools: Mapping[str, list[str]],
    *,
    samples_per_column: int = 30,
    rng_seeds: Iterable[int] = (42, 7, 101),
) -> list[CorpusRow]:
    """Concatenate multiple seed-replicated corpora into one list.

    Enables empirical variance estimation across value-slice draws while
    keeping template structure fixed. Each seed produces a fresh corpus
    with different value samples; concatenation triples (or more) the
    effective n without new template authoring.
    """
    all_rows: list[CorpusRow] = []
    for seed in rng_seeds:
        all_rows.extend(build_corpus(value_pools, samples_per_column=samples_per_column, rng_seed=seed))
    return all_rows


# ── Strategies ────────────────────────────────────────────────────────────
#
# Each strategy is a pure function (ColumnInput) -> (text, entity_types).
# No model invocation, no side effects — the harness calls extract_entities
# itself so strategies remain trivially testable.


_SAMPLE_SEPARATOR = " ; "


def strategy_baseline(column: ColumnInput) -> tuple[str, EntityTypes]:
    """Production-equivalent: ``" ; "``-joined values + frozen description dict.

    Matches what ``data_classifier/engines/gliner_engine.py`` does today
    when ``_is_v2`` is True (i.e. the Sprint 9 target config).
    """
    text = _SAMPLE_SEPARATOR.join(column.sample_values)
    return text, dict(GLINER_LABELS_V2_BASELINE)


def strategy_s1_nl_prompt(column: ColumnInput) -> tuple[str, EntityTypes]:
    """S1: natural-language context prompt prefix.

    Builds a single sentence describing the column, then appends the
    comma-separated values. Uses whatever metadata is present on the
    ``ColumnInput`` — gracefully degrades when fields are empty.
    """
    parts: list[str] = []
    if column.column_name:
        parts.append(f"Column '{column.column_name}'")
    if column.table_name:
        parts.append(f"from table '{column.table_name}'")
    prefix = " ".join(parts) if parts else "An unnamed column"
    if column.description:
        prefix += f". Description: {column.description}"

    body = ", ".join(column.sample_values)
    text = f"{prefix}. Sample values: {body}"
    return text, dict(GLINER_LABELS_V2_BASELINE)


def strategy_s2_per_column_descriptions(column: ColumnInput) -> tuple[str, EntityTypes]:
    """S2: per-column dynamic label descriptions.

    Injects the column's own (column_name, table_name, description)
    context into every label description, so GLiNER sees "e.g. for a
    column named 'email_address' in table 'users': Email addresses..."
    instead of a frozen, column-agnostic description.
    """
    text = _SAMPLE_SEPARATOR.join(column.sample_values)
    ctx = ""
    if column.column_name:
        ctx = f"In a column named '{column.column_name}'"
        if column.table_name:
            ctx += f" in table '{column.table_name}'"
        ctx += ": "
    labels: dict[str, str] = {
        label: f"{ctx}{desc}" for label, desc in GLINER_LABELS_V2_BASELINE.items()
    }
    return text, labels


def strategy_s3_label_narrowing(column: ColumnInput) -> tuple[str, EntityTypes]:
    """S3: narrow labels by column-name hint + small safety net.

    If the column name contains a strong hint for a specific entity type,
    pass only that type plus EMAIL / PERSON_NAME / PHONE as a safety net.
    Otherwise pass the full label set. This is the hook that should fix
    the Sprint 8 ``gliner2-over-fires-organization-on-numeric-dash-inputs``
    bug by construction.
    """
    text = _SAMPLE_SEPARATOR.join(column.sample_values)

    # Very simple keyword-based hint — production would use column_name_engine
    name = (column.column_name or "").lower()
    hint_map = [
        ("email", "email"),
        ("phone", "phone number"),
        ("ssn", "national identification number"),
        ("national_id", "national identification number"),
        ("dob", "date of birth"),
        ("birth", "date of birth"),
        ("address", "street address"),
        ("street", "street address"),
        ("ip", "ip address"),
        ("name", "person"),
        ("company", "organization"),
        ("vendor", "organization"),
        ("org", "organization"),
    ]
    hinted: str | None = None
    for token, gliner_label in hint_map:
        if token in name:
            hinted = gliner_label
            break

    if hinted is None:
        return text, dict(GLINER_LABELS_V2_BASELINE)

    # Narrow to hinted + safety net
    safety_net = {"email", "person", "phone number"}
    keep = {hinted} | safety_net
    labels = {
        label: desc for label, desc in GLINER_LABELS_V2_BASELINE.items() if label in keep
    }
    return text, labels


STRATEGIES: dict[str, StrategyFn] = {
    "baseline": strategy_baseline,
    "s1_nl_prompt": strategy_s1_nl_prompt,
    "s2_per_column_descriptions": strategy_s2_per_column_descriptions,
    "s3_label_narrowing": strategy_s3_label_narrowing,
}


# ── Evaluation loop ───────────────────────────────────────────────────────


@dataclass
class PerColumnResult:
    """One strategy × one column → which entity types did GLiNER report?"""

    column_id: str
    ground_truth: str
    context_kind: str
    strategy: str
    predicted_entity_types: set[str] = field(default_factory=set)
    top_confidence_by_type: dict[str, float] = field(default_factory=dict)
    latency_s: float = 0.0
    raw_result: dict | None = None


def run_strategy_on_corpus(
    *,
    model,
    strategy_name: str,
    strategy_fn: StrategyFn,
    corpus: list[CorpusRow],
    threshold: float = 0.5,
) -> list[PerColumnResult]:
    """Run one strategy over every column in the corpus, collect results."""
    results: list[PerColumnResult] = []
    for row in corpus:
        text, entity_types = strategy_fn(row.column)
        t0 = time.perf_counter()
        raw = model.extract_entities(
            text,
            entity_types,
            threshold=threshold,
            include_confidence=True,
        )
        latency = time.perf_counter() - t0

        predicted: set[str] = set()
        top_conf: dict[str, float] = {}
        for gliner_label, matches in raw.get("entities", {}).items():
            canonical = GLINER_LABEL_TO_ENTITY_TYPE.get(gliner_label)
            if canonical is None:
                continue
            confs: list[float] = []
            for m in matches:
                if isinstance(m, dict):
                    confs.append(float(m.get("confidence", 0.0)))
                else:
                    confs.append(0.5)
            if not confs:
                continue
            predicted.add(canonical)
            top_conf[canonical] = max(confs)

        results.append(
            PerColumnResult(
                column_id=row.column.column_id,
                ground_truth=row.ground_truth,
                context_kind=row.context_kind,
                strategy=strategy_name,
                predicted_entity_types=predicted,
                top_confidence_by_type=top_conf,
                latency_s=latency,
                raw_result=None,  # drop raw to keep memory small; re-enable for debugging
            )
        )
    return results


# ── Metrics ───────────────────────────────────────────────────────────────


@dataclass
class EntityTypeMetrics:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def compute_per_entity_metrics(
    results: Iterable[PerColumnResult],
) -> dict[str, EntityTypeMetrics]:
    """Per-entity-type precision/recall/F1.

    Semantics: for each column, the "ground truth positive" is the single
    entity type Ai4Privacy assigns. A prediction is a TP for that type if
    the model reports it (at any confidence above threshold). All OTHER
    reported types for that column count as FP for those types. If the
    ground-truth type is NOT reported, it's an FN.
    """
    metrics: dict[str, EntityTypeMetrics] = {}
    for r in results:
        gt = r.ground_truth
        metrics.setdefault(gt, EntityTypeMetrics())
        if gt in r.predicted_entity_types:
            metrics[gt].tp += 1
        else:
            metrics[gt].fn += 1
        for pred in r.predicted_entity_types:
            if pred != gt:
                metrics.setdefault(pred, EntityTypeMetrics()).fp += 1
    return metrics


def macro_f1(metrics: Mapping[str, EntityTypeMetrics]) -> float:
    if not metrics:
        return 0.0
    return sum(m.f1 for m in metrics.values()) / len(metrics)


def summarize(results: list[PerColumnResult]) -> dict:
    metrics = compute_per_entity_metrics(results)
    per_type = {
        t: {"p": round(m.precision, 4), "r": round(m.recall, 4), "f1": round(m.f1, 4),
            "tp": m.tp, "fp": m.fp, "fn": m.fn}
        for t, m in sorted(metrics.items())
    }
    latencies = [r.latency_s for r in results]
    latencies.sort()
    n = len(latencies)
    p50 = latencies[n // 2] if n else 0.0
    p95 = latencies[min(n - 1, int(n * 0.95))] if n else 0.0
    return {
        "macro_f1": round(macro_f1(metrics), 4),
        "column_count": n,
        "latency_p50_ms": round(p50 * 1000, 1),
        "latency_p95_ms": round(p95 * 1000, 1),
        "per_entity": per_type,
    }


def stratify_by_context_kind(
    results: list[PerColumnResult],
) -> dict[str, dict]:
    """Per-context-kind summary (helpful / empty / misleading)."""
    by_kind: dict[str, list[PerColumnResult]] = {}
    for r in results:
        by_kind.setdefault(r.context_kind, []).append(r)
    return {kind: summarize(rows) for kind, rows in sorted(by_kind.items())}


# ── Statistical tests ─────────────────────────────────────────────────────
#
# Paired comparisons between baseline and each variant strategy. The
# strategies are evaluated on IDENTICAL CorpusRows, so every result index
# i in strategy_a.results corresponds to the SAME column_id as index i in
# strategy_b.results. That pairing is what McNemar and the paired bootstrap
# exploit.


def _column_correct_vector(results: list[PerColumnResult]) -> list[bool]:
    """Per-column correctness: did the strategy report the ground-truth
    entity type for this column?

    Returns a list of bool in the same order as ``results``. This is the
    input McNemar needs.
    """
    return [r.ground_truth in r.predicted_entity_types for r in results]


def mcnemar_exact(
    baseline_correct: list[bool],
    variant_correct: list[bool],
) -> dict:
    """Exact McNemar's test for paired binary classifier outcomes.

    Given two correctness vectors over the SAME ordered columns, builds
    the 2×2 discordance table and returns the exact two-sided binomial
    p-value on the discordant pairs.

    Returns:
        dict with keys:
          - ``b`` (baseline right, variant wrong)
          - ``c`` (baseline wrong, variant right)
          - ``both_right``, ``both_wrong`` (ignored cells, for sanity)
          - ``p_value`` — exact two-sided via scipy.stats.binomtest
          - ``favors_variant`` — True if c > b
    """
    if len(baseline_correct) != len(variant_correct):
        raise ValueError(f"Length mismatch: {len(baseline_correct)} vs {len(variant_correct)}")
    b = sum(1 for a, v in zip(baseline_correct, variant_correct) if a and not v)
    c = sum(1 for a, v in zip(baseline_correct, variant_correct) if v and not a)
    both_right = sum(1 for a, v in zip(baseline_correct, variant_correct) if a and v)
    both_wrong = sum(1 for a, v in zip(baseline_correct, variant_correct) if not a and not v)

    if b + c == 0:
        # No discordant pairs — the two strategies agree on every column.
        # p-value is undefined in the traditional sense; convention: p=1.0.
        p_value = 1.0
    else:
        from scipy.stats import binomtest
        result = binomtest(k=c, n=b + c, p=0.5, alternative="two-sided")
        p_value = float(result.pvalue)

    return {
        "b": b,
        "c": c,
        "both_right": both_right,
        "both_wrong": both_wrong,
        "discordant_total": b + c,
        "p_value": round(p_value, 6),
        "favors_variant": c > b,
    }


def bootstrap_f1_ci(
    results: list[PerColumnResult],
    *,
    n_resamples: int = 1000,
    confidence: float = 0.95,
    rng_seed: int = 0,
) -> dict:
    """BCa 95% CI on the macro F1 of a single strategy, via bootstrap.

    Uses ``scipy.stats.bootstrap`` with method='BCa'. Each bootstrap
    replicate resamples columns with replacement and recomputes macro F1
    on the resampled set. Columns are treated as independent observations
    (safe for our synthetic corpus; would need cluster bootstrap for real
    catalog data with nested structure).

    Returns:
        dict with ``point``, ``ci_low``, ``ci_high``, ``ci_width``, ``n``.
    """
    import numpy as np
    from scipy.stats import bootstrap

    if len(results) < 2:
        point = macro_f1(compute_per_entity_metrics(results))
        return {
            "point": round(point, 4),
            "ci_low": round(point, 4),
            "ci_high": round(point, 4),
            "ci_width": 0.0,
            "n": len(results),
            "note": "bootstrap requires n≥2",
        }

    indices = np.arange(len(results))

    def _f1_from_indices(idx: np.ndarray) -> float:
        sub = [results[int(i)] for i in idx]
        return macro_f1(compute_per_entity_metrics(sub))

    # scipy.stats.bootstrap wants a 1D data array and a statistic fn that
    # operates on resampled versions of it. We bootstrap over the INDICES
    # so that resampling produces valid reindexings.
    res = bootstrap(
        (indices,),
        _f1_from_indices,
        n_resamples=n_resamples,
        confidence_level=confidence,
        method="BCa",
        random_state=rng_seed,
        vectorized=False,
    )
    point = macro_f1(compute_per_entity_metrics(results))
    return {
        "point": round(point, 4),
        "ci_low": round(float(res.confidence_interval.low), 4),
        "ci_high": round(float(res.confidence_interval.high), 4),
        "ci_width": round(float(res.confidence_interval.high - res.confidence_interval.low), 4),
        "n": len(results),
    }


def bootstrap_paired_delta_ci(
    baseline_results: list[PerColumnResult],
    variant_results: list[PerColumnResult],
    *,
    n_resamples: int = 1000,
    confidence: float = 0.95,
    rng_seed: int = 0,
) -> dict:
    """BCa 95% CI on (variant macro F1 − baseline macro F1), paired by column.

    Preserves pairing by resampling INDICES once per bootstrap iteration
    and applying the SAME indices to both baseline and variant result
    lists. This is the paired bootstrap — cancels out column-level
    difficulty variance the same way a paired t-test does in the Normal
    case, and is the right move for comparing two strategies on the
    same corpus.

    Returns:
        dict with ``point`` (delta), ``ci_low``, ``ci_high``, ``ci_width``,
        ``excludes_zero`` (True if CI strictly on one side of 0),
        ``excludes_plus_02`` (True if CI strictly above +0.02, the ship gate).
    """
    import numpy as np
    from scipy.stats import bootstrap

    if len(baseline_results) != len(variant_results):
        raise ValueError("Paired bootstrap requires equal-length result lists")
    if len(baseline_results) < 2:
        point = (
            macro_f1(compute_per_entity_metrics(variant_results))
            - macro_f1(compute_per_entity_metrics(baseline_results))
        )
        return {
            "point": round(point, 4),
            "ci_low": round(point, 4),
            "ci_high": round(point, 4),
            "ci_width": 0.0,
            "excludes_zero": False,
            "excludes_plus_02": False,
            "note": "bootstrap requires n≥2",
        }

    indices = np.arange(len(baseline_results))

    def _delta_from_indices(idx: np.ndarray) -> float:
        idx_int = [int(i) for i in idx]
        b_sub = [baseline_results[i] for i in idx_int]
        v_sub = [variant_results[i] for i in idx_int]
        return (
            macro_f1(compute_per_entity_metrics(v_sub))
            - macro_f1(compute_per_entity_metrics(b_sub))
        )

    res = bootstrap(
        (indices,),
        _delta_from_indices,
        n_resamples=n_resamples,
        confidence_level=confidence,
        method="BCa",
        random_state=rng_seed,
        vectorized=False,
    )
    point = (
        macro_f1(compute_per_entity_metrics(variant_results))
        - macro_f1(compute_per_entity_metrics(baseline_results))
    )
    lo = float(res.confidence_interval.low)
    hi = float(res.confidence_interval.high)
    return {
        "point": round(point, 4),
        "ci_low": round(lo, 4),
        "ci_high": round(hi, 4),
        "ci_width": round(hi - lo, 4),
        "excludes_zero": lo > 0 or hi < 0,
        "excludes_plus_02": lo > 0.02,
    }


def compare_strategies(
    baseline_results: list[PerColumnResult],
    variant_results: list[PerColumnResult],
    *,
    variant_name: str,
    n_resamples: int = 1000,
    rng_seed: int = 0,
) -> dict:
    """Full paired comparison of a variant strategy against baseline.

    Runs McNemar exact test + paired BCa bootstrap CI on the macro F1
    delta, and returns a single dict suitable for JSON serialization.
    """
    base_correct = _column_correct_vector(baseline_results)
    var_correct = _column_correct_vector(variant_results)
    return {
        "variant": variant_name,
        "mcnemar": mcnemar_exact(base_correct, var_correct),
        "delta_ci": bootstrap_paired_delta_ci(
            baseline_results,
            variant_results,
            n_resamples=n_resamples,
            rng_seed=rng_seed,
        ),
    }
