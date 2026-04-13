"""Download and process external corpora for benchmarking.

Downloads real data from HuggingFace and GitHub, processes it into
our benchmark format, and saves to tests/fixtures/corpora/.

Usage:
    python3 scripts/download_corpora.py [--max-per-type 1000]
    python3 scripts/download_corpora.py --corpus ai4privacy
    python3 scripts/download_corpora.py --corpus nemotron
    python3 scripts/download_corpora.py --corpus secretbench
    python3 scripts/download_corpora.py --corpus gitleaks
    python3 scripts/download_corpora.py --corpus gretel_en
    python3 scripts/download_corpora.py --corpus all
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

# Actual Ai4Privacy label names from the dataset (verified by inspection)
AI4PRIVACY_TYPE_MAP: dict[str, str] = {
    # PII — direct maps
    "EMAIL": "EMAIL",
    "TEL": "PHONE",
    "IP": "IP_ADDRESS",
    "SOCIALNUMBER": "SSN",
    "PASS": "CREDENTIAL",
    "BOD": "DATE_OF_BIRTH",
    "DATE": "DATE_OF_BIRTH",
    # PII — person names
    "GIVENNAME1": "PERSON_NAME",
    "GIVENNAME2": "PERSON_NAME",
    "LASTNAME1": "PERSON_NAME",
    "LASTNAME2": "PERSON_NAME",
    "LASTNAME3": "PERSON_NAME",
    # PII — address components
    "STREET": "ADDRESS",
    "SECADDRESS": "ADDRESS",
    "BUILDING": None,  # Skip — building numbers alone are too short
    "CITY": None,  # Skip — city names alone aren't PII
    "STATE": None,  # Skip
    "POSTCODE": None,  # Skip — would need separate entity type
    "COUNTRY": None,  # Skip
    # IDs
    "IDCARD": None,  # Skip — country-specific, no single pattern
    "PASSPORT": None,  # Skip — country-specific
    "DRIVERLICENSE": None,  # Skip — country-specific
    # Skip — not PII or not in our type system
    "USERNAME": None,
    "TIME": None,
    "SEX": None,
    "TITLE": None,  # Mr/Mrs/Dr
    "GEOCOORD": None,
    "CARDISSUER": None,
}

# Actual Nemotron-PII label names (verified from 55 unique labels, 825K total spans)
NEMOTRON_TYPE_MAP: dict[str, str] = {
    # PII — direct maps
    "first_name": "PERSON_NAME",
    "last_name": "PERSON_NAME",
    "email": "EMAIL",
    "phone_number": "PHONE",
    "ssn": "SSN",
    "date_of_birth": "DATE_OF_BIRTH",
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


# ── Ai4Privacy ───────────────────────────────────────────────────────────────


def download_ai4privacy(max_per_type: int = 1000) -> list[dict]:
    """Download Ai4Privacy pii-masking-300k from HuggingFace and extract PII values."""
    try:
        from datasets import load_dataset
    except ImportError:
        logger.error("Install datasets: pip3 install datasets")
        return []

    logger.info("Downloading ai4privacy/pii-masking-300k from HuggingFace...")
    ds = load_dataset("ai4privacy/pii-masking-300k", split="train")
    logger.info("Downloaded %d rows", len(ds))

    # Extract PII spans from each row
    records_by_type: dict[str, list[str]] = {}
    for row in ds:
        privacy_mask = row.get("privacy_mask", [])
        if not privacy_mask:
            continue
        for span in privacy_mask:
            label = span.get("label", "")
            value = span.get("value", "")
            if not label or not value or len(value) < 2:
                continue

            our_type = AI4PRIVACY_TYPE_MAP.get(label)
            if our_type is None:
                continue

            records_by_type.setdefault(our_type, []).append(value)

    # Deduplicate and cap per type
    records: list[dict] = []
    for entity_type, values in sorted(records_by_type.items()):
        unique = list(dict.fromkeys(values))[:max_per_type]
        logger.info("  %s: %d unique values (from %d total)", entity_type, len(unique), len(values))
        for v in unique:
            records.append({"entity_type": entity_type, "value": v})

    return records


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
    except Exception:
        # Try alternative dataset names
        logger.warning("nvidia/Nemotron-PII not found, trying alternatives...")
        try:
            ds = load_dataset("ai4privacy/pii-masking-300k", name="nemotron", split="train")
        except Exception:
            logger.error("Could not find Nemotron-PII dataset. Generating from Ai4Privacy subset instead.")
            return _generate_nemotron_fallback(max_per_type)

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
        unique = list(dict.fromkeys(values))[:max_per_type]
        logger.info("  %s: %d unique values (from %d total)", entity_type, len(unique), len(values))
        for v in unique:
            records.append({"entity_type": entity_type, "value": v})

    return records


def _generate_nemotron_fallback(max_per_type: int) -> list[dict]:
    """If Nemotron isn't available, use a second pass of Ai4Privacy with different dedup."""
    logger.info("Generating Nemotron-equivalent from Ai4Privacy (second slice)...")
    try:
        from datasets import load_dataset
    except ImportError:
        return []

    ds = load_dataset("ai4privacy/pii-masking-300k", split="train")
    records_by_type: dict[str, list[str]] = {}

    # Take from the second half of the dataset for different samples
    start = len(ds) // 2
    for row in ds.select(range(start, len(ds))):
        privacy_mask = row.get("privacy_mask", [])
        if not privacy_mask:
            continue
        for span in privacy_mask:
            label = span.get("label", "")
            value = span.get("value", "")
            if not label or not value or len(value) < 2:
                continue
            our_type = AI4PRIVACY_TYPE_MAP.get(label)
            if our_type is None:
                continue
            records_by_type.setdefault(our_type, []).append(value)

    records: list[dict] = []
    for entity_type, values in sorted(records_by_type.items()):
        unique = list(dict.fromkeys(values))[:max_per_type]
        logger.info("  %s: %d unique values", entity_type, len(unique))
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
        unique = list(dict.fromkeys(values))[:max_per_type]
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
    hard_cap_rows = max(500, max_per_type * 10)

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
        choices=["ai4privacy", "nemotron", "secretbench", "gitleaks", "gretel_en", "all"],
        default="all",
        help="Which corpus to download",
    )
    parser.add_argument(
        "--max-per-type", type=int, default=1000, help="Maximum samples per entity type (default: 1000)"
    )
    args = parser.parse_args()

    corpora = (
        [args.corpus] if args.corpus != "all" else ["ai4privacy", "nemotron", "secretbench", "gitleaks", "gretel_en"]
    )
    total_records = 0

    for corpus_name in corpora:
        logger.info("=" * 60)
        logger.info("Processing: %s", corpus_name)
        logger.info("=" * 60)

        if corpus_name == "ai4privacy":
            records = download_ai4privacy(max_per_type=args.max_per_type)
            if records:
                save_corpus(records, "ai4privacy_sample.json")
                total_records += len(records)

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

    logger.info("=" * 60)
    logger.info("DONE — %d total records across %d corpora", total_records, len(corpora))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
