"""Download and process external corpora for benchmarking.

Downloads real data from HuggingFace and GitHub, processes it into
our benchmark format, and saves to tests/fixtures/corpora/.

Usage:
    python3 scripts/download_corpora.py [--max-per-type 1000]
    python3 scripts/download_corpora.py --corpus nemotron
    python3 scripts/download_corpora.py --corpus secretbench
    python3 scripts/download_corpora.py --corpus gitleaks
    python3 scripts/download_corpora.py --corpus gretel_en
    python3 scripts/download_corpora.py --corpus gretel_finance
    python3 scripts/download_corpora.py --corpus all

Note: the ``ai4privacy`` choice is retained for CLI discoverability but
raises ``NotImplementedError`` at runtime — the corpus was retired in
Sprint 9 because its license is non-OSS (no commercial use, no
redistribution, no derivative works). See
``docs/process/LICENSE_AUDIT.md``.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "corpora"

# ── Entity type mappings ─────────────────────────────────────────────────────

# Actual Nemotron-PII label names (verified from 55 unique labels, 825K total spans)
NEMOTRON_TYPE_MAP: dict[str, str] = {
    # PII — direct maps
    "first_name": "PERSON_NAME",
    "last_name": "PERSON_NAME",
    "email": "EMAIL",
    "phone_number": "PHONE",
    "ssn": "SSN",
    "date_of_birth": "DATE",
    "street_address": "ADDRESS",
    "url": "URL",
    "ipv4": "IP_ADDRESS",
    "ipv6": "IP_ADDRESS",
    "mac_address": "MAC_ADDRESS",
    "credit_debit_card": "CREDIT_CARD",
    "swift_bic": "SWIFT_BIC",
    "bank_routing_number": "ABA_ROUTING",
    "password": "CREDENTIAL",
    "api_key": "CREDENTIAL",
    "pin": "CREDENTIAL",
    # Skip — not in our type system or too ambiguous
    "company_name": None,
    "date": None,  # Generic dates, not DOB
    "date_time": None,
    "time": None,
    "occupation": None,
    "country": None,
    "city": None,
    "state": None,
    "county": None,
    "postcode": None,
    "customer_id": None,
    "employee_id": None,
    "user_name": None,
    "biometric_identifier": None,
    "education_level": None,
    "account_number": None,
    "vehicle_identifier": None,  # Different from VIN format
    "coordinate": None,
    "certificate_license_number": None,
    "employment_status": None,
    "fax_number": None,
    "license_plate": None,
    "race_ethnicity": None,
    "medical_record_number": None,
    "language": None,
    "health_plan_beneficiary_number": None,
    "http_cookie": None,
    "device_identifier": None,
    "religious_belief": None,
    "blood_type": None,
    "gender": None,
    "age": None,
    "political_view": None,
}


# Gretel-PII-masking-EN label map (locked 2026-04-13, path-(d) decision).
#
# Only the 17 Gretel labels below are mapped to data_classifier types. Dropped
# Gretel labels (``date`` [generic], ``customer_id``, ``employee_id``,
# ``license_plate``, ``company_name``, ``device_identifier``,
# ``biometric_identifier``, ``unique_identifier``, ``time``, ``user_name``,
# ``coordinate``, ``country``, ``date_time``, ``city``, ``url``, ``cvv``,
# ``certificate_license_number``) will be revisited in a Sprint 10 taxonomy
# expansion item. Do not extend this map without updating the dispatcher
# decision. Target coverage: ~71% of labeled Gretel instances, by design.
GRETEL_EN_TYPE_MAP: dict[str, str] = {
    # PII
    "date_of_birth": "DATE",
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


# Gretel synthetic_pii_finance_multilingual label map (locked 2026-04-14,
# Sprint 10 dataset-landscape Tier-1 #2).
#
# The Gretel-finance dataset is the only open corpus where credential
# labels (``password``, ``api_key``, ``account_pin``) appear inside
# long-form financial document prose — loan agreements, SWIFT messages,
# insurance claims, MT940 statements, tax notices. It is the targeted
# intervention for the ``heuristic_avg_length`` corpus-fingerprint
# shortcut diagnosed in Sprint 9 M1 work (the other credential corpora
# all fingerprint as ``short avg-length`` because credentials live in
# isolated KV lines; Gretel-finance lets them live in prose).
#
# Schema surprise versus Gretel-EN: the ``pii_spans`` column is **JSON**
# (``json.loads``), not a Python ``repr`` string, and each span is
# ``{start, end, label}`` — the raw value must be sliced out of the
# ``generated_text`` column by offset, NOT read from the span payload.
#
# Coverage: 15 of the 27 raw labels present in the 100-row discovery
# sample are mapped. All 15 map to entity types already in the
# ``data_classifier`` production vocabulary (no net-new taxonomy). The
# 4 labels listed in the backlog item as Sprint 11 expansion candidates
# (``account_pin``, ``bban``, ``driver_license_number``,
# ``swift_bic_code``) -- note that ``swift_bic_code`` is intentionally
# mapped here to the existing ``SWIFT_BIC`` type (not net-new, and the
# Sprint 9 NEMOTRON_TYPE_MAP already maps ``swift_bic`` the same way).
# The remaining 3 + 8 generic-or-unmapped labels (``account_pin``,
# ``bban``, ``driver_license_number``, ``company``, ``customer_id``,
# ``employee_id``, ``user_name``, ``date``, ``date_time``, ``time``,
# ``credit_card_security_code``, ``local_latlng``) are surfaced as a
# Sprint 11 taxonomy expansion backlog item — do NOT add them here.
GRETEL_FINANCE_TYPE_MAP: dict[str, str] = {
    # Identity / PII
    "name": "PERSON_NAME",
    "first_name": "PERSON_NAME",
    "street_address": "ADDRESS",
    "phone_number": "PHONE",
    "email": "EMAIL",
    "date_of_birth": "DATE",
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


# ── Ai4Privacy (retired Sprint 9 — license non-OSS) ─────────────────────────


def download_ai4privacy(max_per_type: int = 1000) -> list[dict]:
    """Retired — Ai4Privacy license is non-OSS.

    Preserved as a stub so the CLI still surfaces the choice but refuses to
    re-download. Removed in Sprint 9; see ``docs/process/LICENSE_AUDIT.md``
    for the verification record.
    """
    raise NotImplementedError("ai4privacy retired — license non-OSS, see docs/process/LICENSE_AUDIT.md")


# ── Nemotron-PII ─────────────────────────────────────────────────────────────


def download_nemotron(max_per_type: int = 1000) -> list[dict]:
    """Download Nemotron-PII from HuggingFace and extract PII values."""
    try:
        from datasets import load_dataset
    except ImportError:
        logger.error("Install datasets: pip3 install datasets")
        return []

    logger.info("Downloading nvidia/Nemotron-PII from HuggingFace...")
    try:
        ds = load_dataset("nvidia/Nemotron-PII", split="train")
    except Exception as exc:
        logger.error("Could not find Nemotron-PII dataset: %s", exc)
        return []

    logger.info("Downloaded %d rows", len(ds))

    records_by_type: dict[str, list[str]] = {}
    for row in ds:
        # Nemotron format: spans field is a Python literal string (single quotes, not JSON)
        # ast.literal_eval is safe — only parses literals, no code execution
        spans_raw = row.get("spans", "[]")
        try:
            spans = ast.literal_eval(spans_raw) if isinstance(spans_raw, str) else spans_raw  # noqa: S307
        except (ValueError, SyntaxError):
            continue

        for span in spans:
            label = span.get("label", "")
            value = str(span.get("text", ""))
            if not label or not value or len(value) < 2:
                continue
            our_type = NEMOTRON_TYPE_MAP.get(label)
            if our_type is None:
                continue
            records_by_type.setdefault(our_type, []).append(value)

    records: list[dict] = []
    for entity_type, values in sorted(records_by_type.items()):
        unique = list(dict.fromkeys(values))
        if max_per_type is not None:
            unique = unique[:max_per_type]
        logger.info("  %s: %d unique values (from %d total)", entity_type, len(unique), len(values))
        for v in unique:
            records.append({"entity_type": entity_type, "value": v})

    return records


# ── SecretBench ──────────────────────────────────────────────────────────────


def download_secretbench(max_per_type: int = 1000) -> list[dict]:
    """Download SecretBench test battery from brendtmcfeeley/SecretBench on GitHub.

    SecretBench uses annotated lines: each line ends with >>pass (should detect)
    or >>fail (should not detect). Same content across multiple file extensions.
    We download passwords.txt (canonical) and one-per-file/ if available.
    """
    import urllib.request

    logger.info("Downloading SecretBench from GitHub (brendtmcfeeley/SecretBench)...")

    records: list[dict] = []
    seen_values: set[str] = set()

    # Download the main battery file (passwords.txt — same content as .json/.py/.yml)
    url = "https://raw.githubusercontent.com/brendtmcfeeley/SecretBench/main/battery/passwords.txt"
    try:
        content = urllib.request.urlopen(url, timeout=30).read().decode("utf-8")
    except Exception as e:
        logger.error("Could not download SecretBench: %s", e)
        return []

    # Parse annotated lines: "some code or secret>>pass" or "some text>>fail"
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        if ">>pass" in line:
            value = line.rsplit(">>pass", 1)[0].strip()
            is_secret = True
        elif ">>fail" in line:
            value = line.rsplit(">>fail", 1)[0].strip()
            is_secret = False
        else:
            continue

        if not value or len(value) < 3 or value in seen_values:
            continue
        seen_values.add(value)

        records.append(
            {
                "entity_type": "CREDENTIAL",
                "value": value,
                "source": "secretbench",
                "is_secret": is_secret,
            }
        )

    tp = sum(1 for r in records if r["is_secret"])
    tn = sum(1 for r in records if not r["is_secret"])
    logger.info("  Extracted %d samples from SecretBench (%d TP, %d TN)", len(records), tp, tn)

    return records


# ── Gitleaks fixtures ────────────────────────────────────────────────────────


def download_gitleaks(max_per_type: int = 1000) -> list[dict]:
    """Download gitleaks test fixtures from Go rule files on GitHub.

    Gitleaks rules are .go files in cmd/generate/config/rules/. Each file
    contains tps (true positive) and fps (false positive) string arrays
    with test secrets in backtick or quoted string literals.
    """
    import urllib.request

    logger.info("Downloading gitleaks test fixtures from GitHub (131 Go rule files)...")

    base_url = "https://api.github.com/repos/gitleaks/gitleaks/contents/cmd/generate/config/rules"
    try:
        req = urllib.request.Request(base_url, headers={"Accept": "application/vnd.github.v3+json"})
        response = urllib.request.urlopen(req, timeout=30)
        files = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        logger.error("Could not list gitleaks rules: %s", e)
        return []

    go_files = [f for f in files if f.get("name", "").endswith(".go")]
    logger.info("  Found %d Go rule files", len(go_files))

    records: list[dict] = []
    for file_info in go_files:
        raw_url = (
            f"https://raw.githubusercontent.com/gitleaks/gitleaks/master/cmd/generate/config/rules/{file_info['name']}"
        )
        try:
            content = urllib.request.urlopen(raw_url, timeout=15).read().decode("utf-8")
        except Exception:
            continue

        rule_id = file_info["name"].replace(".go", "")

        # Extract TP strings from tps := []string{ ... }
        for block_match in re.finditer(r"tps\s*:?=\s*\[\]string\{([^}]+)\}", content, re.DOTALL):
            block = block_match.group(1)
            # Backtick strings (multi-line literals)
            for val in re.findall(r"`([^`]+)`", block):
                val = val.strip()
                if len(val) > 10:
                    records.append(
                        {
                            "entity_type": "CREDENTIAL",
                            "value": val,
                            "source_type": rule_id,
                            "source": "gitleaks",
                            "is_secret": True,
                        }
                    )

        # Extract FP strings from fps := []string{ ... }
        for block_match in re.finditer(r"fps\s*:?=\s*\[\]string\{([^}]+)\}", content, re.DOTALL):
            block = block_match.group(1)
            for val in re.findall(r"`([^`]+)`", block):
                val = val.strip()
                if len(val) > 10:
                    records.append(
                        {
                            "entity_type": "CREDENTIAL",
                            "value": val,
                            "source_type": rule_id,
                            "source": "gitleaks",
                            "is_secret": False,
                        }
                    )

    tp = sum(1 for r in records if r.get("is_secret"))
    tn = sum(1 for r in records if not r.get("is_secret"))
    logger.info("  Extracted %d samples from gitleaks (%d TP, %d TN)", len(records), tp, tn)

    if not records:
        logger.error("No samples extracted from gitleaks — rule format may have changed")

    return records


# ── Gretel PII masking EN v1 ─────────────────────────────────────────────────


def download_gretel_en(max_per_type: int = 1000) -> list[dict]:
    """Download gretelai/gretel-pii-masking-en-v1 and extract PII values.

    Apache 2.0, 60k rows, 47 domains, mixed-label documents. Each row has
    an ``entities`` column that is a **Python repr** of a list of dicts
    (single quotes, not JSON -- use :func:`ast.literal_eval`, never
    :func:`json.loads`). Each span dict has keys ``entity`` (raw value)
    and ``types`` (list of one or more type strings, first element is the
    primary label).

    Transport preference:
    1. ``datasets`` library (fastest, streams locally via Arrow).
    2. HuggingFace datasets-server REST API (``/rows`` endpoint) --
       returns JSON directly in 100-row pages, no dependency beyond
       :mod:`urllib`. Used when ``datasets`` is not installed.

    Returns flattened records ``[{"entity_type": types[0], "value":
    entity}, ...]``, deduplicated and capped at ``max_per_type`` per
    mapped type. Labels not in :data:`GRETEL_EN_TYPE_MAP` are dropped.
    """
    logger.info("Downloading gretelai/gretel-pii-masking-en-v1...")

    records_by_type: dict[str, list[str]] = {}

    def _consume_row(row: dict) -> None:
        raw = row.get("entities", "")
        if not raw or not isinstance(raw, str):
            return
        try:
            spans = ast.literal_eval(raw)  # noqa: S307 -- literal parsing only
        except (ValueError, SyntaxError):
            return
        if not isinstance(spans, list):
            return
        for span in spans:
            if not isinstance(span, dict):
                continue
            value = span.get("entity", "")
            types = span.get("types") or []
            if not value or not types:
                continue
            label = str(types[0])
            our_type = GRETEL_EN_TYPE_MAP.get(label)
            if our_type is None:
                continue
            records_by_type.setdefault(our_type, []).append(str(value))

    # Attempt 1: native datasets library.
    try:
        from datasets import load_dataset  # type: ignore[import-not-found]

        ds = load_dataset("gretelai/gretel-pii-masking-en-v1", split="train")
        logger.info("Loaded %d rows via datasets library", len(ds))
        for row in ds:
            _consume_row(row)
    except ImportError:
        logger.info("datasets library not installed -- falling back to datasets-server REST API")
        _fetch_gretel_en_via_rest_api(_consume_row, max_per_type=max_per_type)
    except Exception as exc:
        logger.warning("datasets library failed (%s) -- falling back to REST API", exc)
        _fetch_gretel_en_via_rest_api(_consume_row, max_per_type=max_per_type)

    # Deduplicate and cap per type.
    records: list[dict] = []
    for entity_type, values in sorted(records_by_type.items()):
        unique = list(dict.fromkeys(values))
        if max_per_type is not None:
            unique = unique[:max_per_type]
        logger.info("  %s: %d unique values (from %d total)", entity_type, len(unique), len(values))
        for v in unique:
            records.append({"entity_type": entity_type, "value": v})

    return records


def _fetch_gretel_en_via_rest_api(consumer, *, max_per_type: int) -> None:
    """Page through the HuggingFace datasets-server ``/rows`` endpoint.

    Stops early once every mapped type has at least ``max_per_type``
    raw values queued -- the caller deduplicates and caps afterwards so
    we overshoot modestly to give dedup some slack.
    """
    import urllib.request

    base = (
        "https://datasets-server.huggingface.co/rows"
        "?dataset=gretelai/gretel-pii-masking-en-v1&config=default&split=train"
    )
    page_size = 100
    offset = 0
    # Target enough unique rows to cover max_per_type post-dedup without
    # slamming the API.  Each row contributes ~5-8 spans on average; we
    # cap total rows at 10x max_per_type as a safety upper bound.
    hard_cap_rows = max(500, max_per_type * 10) if max_per_type is not None else 100_000

    while offset < hard_cap_rows:
        url = f"{base}&offset={offset}&length={page_size}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            response = urllib.request.urlopen(req, timeout=30)
            payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            logger.error("datasets-server fetch failed at offset=%d: %s", offset, exc)
            return

        rows = payload.get("rows", [])
        if not rows:
            return

        for entry in rows:
            row = entry.get("row", {})
            consumer(row)

        if len(rows) < page_size:
            return
        offset += page_size


# ── Gretel synthetic_pii_finance_multilingual ───────────────────────────────


def download_gretel_finance(
    max_per_type: int = 1000,
    languages: list[str] | None = None,
) -> list[dict]:
    """Download ``gretelai/synthetic_pii_finance_multilingual`` and extract spans.

    Apache 2.0, 56k rows, 7 languages (English, Spanish, Italian, French,
    German, Dutch, Swedish), finance domain only. Each row has a
    ``generated_text`` column (prose financial document: loan agreement,
    MT940 statement, SWIFT message, insurance form, tax notice, ...) and
    a ``pii_spans`` column that is a **JSON** string (double quotes, use
    :func:`json.loads`, NOT :func:`ast.literal_eval` -- this diverges
    from Gretel-EN's Python-repr format despite the same publisher).
    Each span is ``{"start": int, "end": int, "label": str}`` and the
    raw value must be sliced out of ``generated_text`` using those
    offsets.

    Args:
        max_per_type: Maximum values kept per mapped entity type.
        languages: Optional allowlist of ``row["language"]`` strings.
            Gretel-finance values are ``{"English", "Spanish", "Italian",
            "France", "German", "Dutch", "Swedish"}`` — note ``"France"``
            is the raw dataset label, not ``"French"``.  ``None`` means
            all languages (default).

    Transport preference mirrors ``download_gretel_en``:
    1. ``datasets`` library if available.
    2. HuggingFace datasets-server REST ``/rows`` endpoint as fallback.

    Returns flattened records ``[{"entity_type": mapped_type, "value":
    sliced_value}, ...]``, deduplicated and capped at ``max_per_type``
    per mapped type. Labels not in :data:`GRETEL_FINANCE_TYPE_MAP` are
    dropped.
    """
    logger.info("Downloading gretelai/synthetic_pii_finance_multilingual...")
    if languages is not None:
        logger.info("  languages filter: %s", sorted(languages))

    records_by_type: dict[str, list[str]] = {}
    # CREDENTIAL records carry extra metadata (source_context, raw_label,
    # source_document_type) that the test suite verifies to confirm
    # credentials-in-prose provenance.  Store as list of dicts keyed by
    # value so we can deduplicate while preserving the metadata.
    credential_records: dict[str, dict] = {}  # value -> full record dict
    allowed_languages: set[str] | None = set(languages) if languages else None

    def _consume_row(row: dict) -> None:
        lang = row.get("language", "")
        if allowed_languages is not None and lang not in allowed_languages:
            return
        generated_text = row.get("generated_text", "") or ""
        if not generated_text or not isinstance(generated_text, str):
            return
        document_type = row.get("document_type", "") or ""
        raw_spans = row.get("pii_spans", "[]")
        if not raw_spans or not isinstance(raw_spans, str):
            return
        try:
            spans = json.loads(raw_spans)
        except (ValueError, TypeError):
            return
        if not isinstance(spans, list):
            return
        for span in spans:
            if not isinstance(span, dict):
                continue
            label = span.get("label", "")
            start = span.get("start")
            end = span.get("end")
            if not label or start is None or end is None:
                continue
            our_type = GRETEL_FINANCE_TYPE_MAP.get(label)
            if our_type is None:
                continue
            try:
                value = generated_text[int(start) : int(end)]
            except (TypeError, ValueError):
                continue
            if not value:
                continue
            value_str = str(value)
            if our_type == "CREDENTIAL":
                if value_str not in credential_records:
                    # Capture up to 200 chars of surrounding context centred on the span.
                    ctx_start = max(0, int(start) - 80)
                    ctx_end = min(len(generated_text), int(end) + 80)
                    source_context = generated_text[ctx_start:ctx_end]
                    credential_records[value_str] = {
                        "entity_type": "CREDENTIAL",
                        "value": value_str,
                        "raw_label": label,
                        "source_context": source_context,
                        "source_document_type": document_type,
                    }
            else:
                records_by_type.setdefault(our_type, []).append(value_str)

    # Attempt 1: native datasets library.
    try:
        from datasets import load_dataset  # type: ignore[import-not-found]

        ds = load_dataset("gretelai/synthetic_pii_finance_multilingual", split="train")
        logger.info("Loaded %d rows via datasets library", len(ds))
        for row in ds:
            _consume_row(row)
    except ImportError:
        logger.info("datasets library not installed -- falling back to datasets-server REST API")
        _fetch_gretel_finance_via_rest_api(_consume_row, max_per_type=max_per_type)
    except Exception as exc:
        logger.warning("datasets library failed (%s) -- falling back to REST API", exc)
        _fetch_gretel_finance_via_rest_api(_consume_row, max_per_type=max_per_type)

    # Deduplicate and cap per type.
    records: list[dict] = []

    # CREDENTIAL — already deduplicated by value in the dict; apply cap if set.
    cred_list = list(credential_records.values())
    if max_per_type is not None:
        cred_list = cred_list[:max_per_type]
    logger.info("  CREDENTIAL: %d unique values (from %d total)", len(cred_list), len(credential_records))
    records.extend(cred_list)

    for entity_type, values in sorted(records_by_type.items()):
        unique = list(dict.fromkeys(values))
        if max_per_type is not None:
            unique = unique[:max_per_type]
        logger.info("  %s: %d unique values (from %d total)", entity_type, len(unique), len(values))
        for v in unique:
            records.append({"entity_type": entity_type, "value": v})

    return records


def _fetch_gretel_finance_via_rest_api(consumer, *, max_per_type: int) -> None:
    """Page through the HuggingFace datasets-server for Gretel-finance.

    Same pagination shape as :func:`_fetch_gretel_en_via_rest_api` — the
    only difference is the dataset slug in the base URL.
    """
    import urllib.request

    base = (
        "https://datasets-server.huggingface.co/rows"
        "?dataset=gretelai/synthetic_pii_finance_multilingual&config=default&split=train"
    )
    page_size = 100
    offset = 0
    # Finance rows are longer than Gretel-EN rows (full prose documents)
    # and carry more spans per row on average, so we overshoot less.
    hard_cap_rows = max(500, max_per_type * 10) if max_per_type is not None else 100_000

    while offset < hard_cap_rows:
        url = f"{base}&offset={offset}&length={page_size}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            response = urllib.request.urlopen(req, timeout=30)
            payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            logger.error("datasets-server fetch failed at offset=%d: %s", offset, exc)
            return

        rows = payload.get("rows", [])
        if not rows:
            return

        for entry in rows:
            row = entry.get("row", {})
            consumer(row)

        if len(rows) < page_size:
            return
        offset += page_size


# ── OpenPII-1M (ai4privacy/pii-masking-openpii-1m, CC-BY-4.0) ───────────────

# Mirror of tests.benchmarks.corpus_loader.OPENPII_1M_TYPE_MAP — kept in sync
# manually.  The download script cannot reliably import from ``tests.*`` when
# invoked as a standalone script (sys.path does not include the project root in
# all invocation styles), so we duplicate the map here following the same
# pattern used for NEMOTRON_TYPE_MAP / GRETEL_EN_TYPE_MAP / GRETEL_FINANCE_TYPE_MAP.
#
# Schema verified 2026-04-22 against 200k rows of the actual dataset.
# The corpus_loader spec listed 19 raw labels; empirical survey found 19 labels
# but with different names than spec in 3 cases:
#   - PHONENUMBER does not exist; actual label is TELEPHONENUM
#   - ACCOUNTNUM does not exist (not present in any shard of 200k rows)
#   - USERNAME does not exist (not present in any shard of 200k rows)
#   - STATE and COUNTY do not exist (not present in 200k rows)
# The map below reflects actual dataset labels only.
OPENPII_1M_TYPE_MAP: dict[str, str] = {
    # Identity / PII
    "GIVENNAME": "PERSON_NAME",
    "SURNAME": "PERSON_NAME",
    # Address components — STATE/COUNTY/BUILDINGNUM not confirmed in train shard
    "BUILDINGNUM": "ADDRESS",
    "STREET": "ADDRESS",
    "CITY": "ADDRESS",
    "ZIPCODE": "ADDRESS",
    # Government-issued IDs
    "IDCARDNUM": "NATIONAL_ID",
    "DRIVERLICENSENUM": "NATIONAL_ID",
    "PASSPORTNUM": "NATIONAL_ID",
    # Tax / social security
    "TAXNUM": "SSN",
    "SOCIALNUM": "SSN",
    # Financial
    "CREDITCARDNUMBER": "CREDIT_CARD",
    # Contact
    "EMAIL": "EMAIL",
    "TELEPHONENUM": "PHONE",  # actual label name; spec said PHONENUMBER (wrong)
    # Date
    "DATE": "DATE",
}


def download_openpii_1m(max_per_type: int | None = None) -> list[dict]:
    """Download ai4privacy/pii-masking-openpii-1m and extract PII values.

    CC-BY-4.0, 1.4M rows, 23 languages, 19 entity labels.  The dataset
    is too large to stream in full; we use streaming=True and stop early
    once every mapped type has at least ``max_per_type`` unique values
    collected.  When ``max_per_type`` is None (unlimited) we still hard-cap
    at 50 000 unique values per type to keep the fixture to a manageable size.

    Dataset schema discovered 2026-04-21 (Sprint 15):
      - ``source_text``: raw text (str)
      - ``masked_text``: text with PII replaced by ``[LABEL_N]`` tokens (str)
      - ``privacy_mask``: list of span dicts, each with keys:
          ``label`` (str), ``start`` (int), ``end`` (int),
          ``value`` (str — the raw PII text), ``label_index`` (int).
      - ``language``, ``region``, ``script``, ``uid``, ``split``.

    Extraction uses ``privacy_mask[*].value`` directly — no offset slicing
    required.  Labels are mapped through
    :data:`tests.benchmarks.corpus_loader.OPENPII_1M_TYPE_MAP`.

    Returns ``[{"entity_type": <mapped type>, "value": <raw value>}, ...]``,
    deduplicated and capped at ``max_per_type`` (or 50 000) per mapped type.
    """
    try:
        from datasets import load_dataset  # type: ignore[import-not-found]
    except ImportError:
        logger.error("Install datasets: pip install datasets")
        return []

    effective_cap = max_per_type if max_per_type is not None else 50_000
    # Hard row cap prevents unbounded streaming when rare types (BANK_ACCOUNT,
    # PHONE) take much longer to saturate than common types (ADDRESS, DATE).
    # With 1.4M rows we accept partial coverage for rare types rather than
    # stream the entire dataset.  At ~15 spans/row average, 200k rows yields
    # ~3M span observations — enough to fill all 9 types at 50k per type.
    row_hard_cap = max(200_000, effective_cap * 40)
    logger.info(
        "Downloading ai4privacy/pii-masking-openpii-1m (streaming, cap=%d per type, row_hard_cap=%d)...",
        effective_cap,
        row_hard_cap,
    )

    records_by_type: dict[str, list[str]] = {}
    seen_by_type: dict[str, set[str]] = {}
    rows_processed = 0

    try:
        ds = load_dataset("ai4privacy/pii-masking-openpii-1m", split="train", streaming=True)
    except Exception as exc:
        logger.error("Could not load openpii-1m dataset: %s", exc)
        return []

    try:
        for row in ds:
            privacy_mask = row.get("privacy_mask") or []
            if not isinstance(privacy_mask, list):
                continue

            for span in privacy_mask:
                if not isinstance(span, dict):
                    continue
                label = span.get("label", "")
                value = str(span.get("value", "")).strip()
                if not label or not value or len(value) < 2:
                    continue
                our_type = OPENPII_1M_TYPE_MAP.get(label)
                if our_type is None:
                    continue
                seen = seen_by_type.setdefault(our_type, set())
                if value not in seen and len(seen) < effective_cap:
                    seen.add(value)
                    records_by_type.setdefault(our_type, []).append(value)

            rows_processed += 1
            if rows_processed % 10_000 == 0:
                counts = {t: len(v) for t, v in records_by_type.items()}
                logger.info("  processed %d rows — per-type counts: %s", rows_processed, counts)

            # Stop once every mapped type has reached the cap.
            if all(len(seen_by_type.get(t, set())) >= effective_cap for t in set(OPENPII_1M_TYPE_MAP.values())):
                logger.info("  All types at cap (%d) — stopping early at row %d", effective_cap, rows_processed)
                break

            # Hard row cap — stop regardless of per-type saturation.
            if rows_processed >= row_hard_cap:
                logger.info("  Row hard cap (%d) reached — stopping", row_hard_cap)
                break
    except RuntimeError as exc:
        # Breaking out of a HuggingFace streaming iterator can raise
        # "Cannot send a request, as the client has been closed." — this is
        # a known issue with the datasets library when the iterator is
        # abandoned mid-stream.  All collected records are intact; ignore
        # the error and continue to build the output.
        logger.debug("Streaming iterator closed after early stop (expected): %s", exc)

    logger.info("Processed %d rows total", rows_processed)

    records: list[dict] = []
    for entity_type, values in sorted(records_by_type.items()):
        logger.info("  %s: %d unique values", entity_type, len(values))
        for v in values:
            records.append({"entity_type": entity_type, "value": v})

    return records


# ── Main ─────────────────────────────────────────────────────────────────────


def save_corpus(records: list[dict], filename: str) -> Path:
    """Save processed corpus to fixtures directory."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / filename
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Saved %d records to %s (%.1f MB)", len(records), output_path, size_mb)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and process benchmark corpora")
    parser.add_argument(
        "--corpus",
        choices=[
            "ai4privacy",
            "nemotron",
            "secretbench",
            "gitleaks",
            "gretel_en",
            "gretel_finance",
            "openpii_1m",
            "all",
        ],
        default="all",
        help="Which corpus to download",
    )
    parser.add_argument(
        "--max-per-type", type=int, default=None, help="Maximum samples per entity type (default: no limit)"
    )
    args = parser.parse_args()

    corpora = (
        [args.corpus]
        if args.corpus != "all"
        else ["nemotron", "secretbench", "gitleaks", "gretel_en", "gretel_finance", "openpii_1m"]
    )
    total_records = 0

    for corpus_name in corpora:
        logger.info("=" * 60)
        logger.info("Processing: %s", corpus_name)
        logger.info("=" * 60)

        if corpus_name == "ai4privacy":
            # Retired in Sprint 9 — license non-OSS.  Stubbed to raise
            # NotImplementedError so the CLI still surfaces the choice
            # (discoverability) but refuses to re-download.
            download_ai4privacy(max_per_type=args.max_per_type)

        elif corpus_name == "nemotron":
            records = download_nemotron(max_per_type=args.max_per_type)
            if records:
                save_corpus(records, "nemotron_sample.json")
                total_records += len(records)

        elif corpus_name == "secretbench":
            records = download_secretbench(max_per_type=args.max_per_type)
            if records:
                save_corpus(records, "secretbench_sample.json")
                total_records += len(records)

        elif corpus_name == "gitleaks":
            records = download_gitleaks(max_per_type=args.max_per_type)
            if records:
                save_corpus(records, "gitleaks_fixtures.json")
                total_records += len(records)

        elif corpus_name == "gretel_en":
            records = download_gretel_en(max_per_type=args.max_per_type)
            if records:
                save_corpus(records, "gretel_en_sample.json")
                total_records += len(records)

        elif corpus_name == "gretel_finance":
            records = download_gretel_finance(max_per_type=args.max_per_type)
            if records:
                save_corpus(records, "gretel_finance_sample.json")
                total_records += len(records)

        elif corpus_name == "openpii_1m":
            records = download_openpii_1m(max_per_type=args.max_per_type)
            if records:
                save_corpus(records, "openpii_1m_sample.json")
                total_records += len(records)

    logger.info("=" * 60)
    logger.info("DONE — %d total records across %d corpora", total_records, len(corpora))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
