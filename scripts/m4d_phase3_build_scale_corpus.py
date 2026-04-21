"""Build the M4d Phase 3a PILOT scale corpus (~45 cols / ~115 GB / ~$2.25).

Pilot stage: exercise the full fetcher → router → labeler → worksheet
pipeline on every source shape before committing to Phase 3b full scale.

Output schema matches the gold set (same fields, so downstream consumers
can treat scale + gold uniformly) but ``review_status`` is always
``"prefilled"`` and ``true_labels`` are the fetcher's pre-fills — the
authoritative Phase 3 labels come from the router-labeler pipeline run
in ``scripts/run_m4d_phase3_scale.py``.

Output
------
Writes to ``data/m4d_phase3_corpus/unlabeled.jsonl`` (DVC-tracked).
Post-run workflow:

    .venv/bin/python -m scripts.m4d_phase3_build_scale_corpus
    .venv/bin/dvc add data/m4d_phase3_corpus
    git add data/m4d_phase3_corpus.dvc data/.gitignore
    git commit -m "data(m4d-phase3a): add unlabeled pilot corpus"
    .venv/bin/dvc push

See ``docs/process/dataset_management.md`` for the full DVC workflow.

Caches BQ responses under ``/tmp/m4d_phase3_staging/``. Delete to force
a fresh fetch.

Phase 3b full-scale (next stage) bumps the ``PILOT_*`` constants — see
the inline comments next to each for the stage-2 target.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery

from data_classifier.patterns._decoder import encode_xor  # noqa: E402
from scripts.m4c_build_gold_set import (  # noqa: E402
    SHAPE_FREE_TEXT_HETEROGENEOUS,
    SHAPE_OPAQUE_TOKENS,
    SHAPE_STRUCTURED_SINGLE,
    GoldSetRow,
    extract_column,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
# DVC-tracked output directory (per docs/process/dataset_management.md).
# The data/ dir is gitignored; after running this fetcher, run
# ``dvc add data/m4d_phase3_corpus`` and commit the .dvc pointer.
OUTPUT_DIR = REPO_ROOT / "data" / "m4d_phase3_corpus"
OUTPUT_PATH = OUTPUT_DIR / "unlabeled.jsonl"
STAGING_DIR = Path("/tmp/m4d_phase3_staging")
SAMPLE_SIZE = 100  # values per column, same as gold set
BQ_PROJECT = "dag-bigquery-dev"


# --------------------------------------------------------------------------- #
# Pilot slice budgets — bump for Phase 3b (see inline comments per source)
# --------------------------------------------------------------------------- #

# CFPB:        3 × 3 =  9 cols / ~45 GB   (full: 15 × 10 = 150 / ~225 GB)
PILOT_CFPB_PRODUCTS = 3
PILOT_CFPB_MODS = 3
# SO about_me: 2 × 3 =  6 cols / ~14 GB   (full: 10 × 10 = 100 / ~45 GB)
PILOT_SO_ABOUT_BUCKETS = 2
PILOT_SO_ABOUT_MODS = 3
# HN:          1 × 2 =  2 cols / ~100 GB  (full: 5 × 10 = 50 / ~1275 GB; hacker_news.full isn't partitioned)
PILOT_HN_YEARS = 1
PILOT_HN_MODS = 2
# SO location: 1 × 5 =  5 cols / ~2 GB    (full: 3 × 10 = 30 / ~11 GB)
PILOT_SO_LOCATION_BUCKETS = 1
PILOT_SO_LOCATION_MODS = 5
# SO display:  2 × 3 =  6 cols / ~3 GB    (full: 4 × 5 = 20 / ~10 GB)
PILOT_SO_DISPLAY_BUCKETS = 2
PILOT_SO_DISPLAY_MODS = 3
# Austin311:   2 × 2 =  4 cols / ~0.2 GB  (full: 10 × 2 = 20 / ~1 GB)
PILOT_AUSTIN_DISTRICTS = 2
PILOT_AUSTIN_MODS = 2


_bq_client: bigquery.Client | None = None


def _get_bq_client() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=BQ_PROJECT)
    return _bq_client


def query_bq(sql: str, cache_key: str) -> list[dict]:
    """Run a BQ query and cache the result on disk.

    Uses Application Default Credentials via the Python BQ client (works
    in non-interactive tool subshells; the ``bq`` CLI prefers user creds
    which need interactive reauth).
    """
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = STAGING_DIR / f"{cache_key}.json"
    if cache_path.exists():
        log.info("cache hit: %s", cache_key)
        return json.loads(cache_path.read_text())

    log.info("cache miss: %s — querying BQ", cache_key)
    client = _get_bq_client()
    try:
        job = client.query(sql)
        rows = [dict(row.items()) for row in job.result(max_results=SAMPLE_SIZE)]
    except Exception as exc:
        log.error("bq query failed for %s: %s", cache_key, exc)
        return []
    cache_path.write_text(json.dumps(rows, default=str))
    return rows


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row(
    *,
    column_id: str,
    source: str,
    source_reference: str,
    encoding: str,
    values: list[str],
    true_shape: str,
    true_labels: list[str],
    true_labels_prevalence: dict[str, float] | None = None,
    notes: str = "",
) -> GoldSetRow:
    """Assemble one GoldSetRow for the scale corpus.

    Encoding policy matches m4c: XOR for any source that may contain
    credential-shaped substrings (user-authored text, synth fixtures),
    plaintext for public-registry structured data.
    """
    from data_classifier.core.taxonomy import family_for

    if encoding == "xor":
        # ``encode_xor`` already returns the ``xor:`` prefix — don't add another.
        values = [encode_xor(v) for v in values]
    families = sorted({family_for(label) or label for label in true_labels})
    return GoldSetRow(
        column_id=column_id,
        source=source,
        source_reference=source_reference,
        encoding=encoding,
        values=values[:SAMPLE_SIZE],
        true_shape=true_shape,
        true_labels=sorted(true_labels),
        true_labels_family=families,
        true_labels_prevalence=true_labels_prevalence or {},
        review_status="prefilled",
        annotator="phase3a-pilot-fetcher",
        annotated_on=_now_iso(),
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Source fetchers
# --------------------------------------------------------------------------- #


CFPB_PRODUCTS = [
    ("debt_collection", "Debt collection"),
    ("credit_card", "Credit card or prepaid card"),
    ("mortgage", "Mortgage"),
    ("student_loan", "Student loan"),
    ("bank_account", "Checking or savings account"),
    ("credit_report", "Credit reporting, credit repair services, or other personal consumer reports"),
    ("money_transfer", "Money transfer, virtual currency, or money service"),
    ("vehicle_loan", "Vehicle loan or lease"),
    ("payday_loan", "Payday loan, title loan, or personal loan"),
    ("credit_reporting_legacy", "Credit reporting"),
    ("money_transfers_legacy", "Money transfers"),
    ("virtual_currency", "Virtual currency"),
    ("prepaid_card", "Prepaid card"),
    ("other_financial_service", "Other financial service"),
    ("consumer_loan", "Consumer Loan"),
]


def fetch_cfpb_narratives_scale() -> list[GoldSetRow]:
    """Pilot: PILOT_CFPB_PRODUCTS × PILOT_CFPB_MODS columns."""
    out: list[GoldSetRow] = []
    for slug, product_name in CFPB_PRODUCTS[:PILOT_CFPB_PRODUCTS]:
        for mod in range(PILOT_CFPB_MODS):
            sql = f"""
            SELECT consumer_complaint_narrative
            FROM `bigquery-public-data.cfpb_complaints.complaint_database`
            WHERE consumer_complaint_narrative IS NOT NULL
              AND LENGTH(consumer_complaint_narrative) BETWEEN 100 AND 4000
              AND product = '{product_name}'
              AND MOD(ABS(FARM_FINGERPRINT(complaint_id)), 10) = {mod}
            LIMIT {SAMPLE_SIZE}
            """
            rows = query_bq(sql, f"cfpb_{slug}_mod{mod}")
            values = extract_column(rows, "consumer_complaint_narrative")
            if not values:
                continue
            out.append(
                _row(
                    column_id=f"cfpb_{slug}_m{mod}",
                    source="bigquery-public-data.cfpb_complaints",
                    source_reference=f"complaint_database[product={product_name}, mod10={mod}]",
                    encoding="xor",
                    values=values,
                    true_shape=SHAPE_FREE_TEXT_HETEROGENEOUS,
                    true_labels=[],
                    notes="CFPB pre-redacts named PII with XXXX — most columns are [].",
                )
            )
    return out


# SO about_me buckets, ordered high→low so pilot picks the richest reputations first.
_SO_ABOUT_BUCKETS = [
    ("r10k_30k", 10000, 30000),
    ("r100k_300k", 100000, 300000),
    ("r30k_100k", 30000, 100000),
    ("r1k_3k", 1000, 3000),
    ("r3k_10k", 3000, 10000),
    ("r500_1k", 500, 1000),
    ("r100_500", 100, 500),
    ("r0_100", 0, 100),
    ("r300k_1m", 300000, 1000000),
    ("r1m_plus", 1000000, 99999999),
]


def fetch_so_about_me_scale() -> list[GoldSetRow]:
    """Pilot: PILOT_SO_ABOUT_BUCKETS × PILOT_SO_ABOUT_MODS columns."""
    out: list[GoldSetRow] = []
    for slug, lo, hi in _SO_ABOUT_BUCKETS[:PILOT_SO_ABOUT_BUCKETS]:
        for mod in range(PILOT_SO_ABOUT_MODS):
            sql = f"""
            SELECT about_me
            FROM `bigquery-public-data.stackoverflow.users`
            WHERE about_me IS NOT NULL
              AND LENGTH(about_me) BETWEEN 100 AND 3000
              AND reputation BETWEEN {lo} AND {hi}
              AND MOD(id, 10) = {mod}
            LIMIT {SAMPLE_SIZE}
            """
            rows = query_bq(sql, f"so_about_me_{slug}_mod{mod}")
            values = extract_column(rows, "about_me")
            if not values:
                continue
            out.append(
                _row(
                    column_id=f"so_about_me_{slug}_m{mod}",
                    source="bigquery-public-data.stackoverflow",
                    source_reference=f"users.about_me[rep∈[{lo},{hi}], mod10={mod}]",
                    encoding="xor",
                    values=values,
                    true_shape=SHAPE_FREE_TEXT_HETEROGENEOUS,
                    true_labels=["URL", "PERSON_NAME", "EMAIL"],
                    true_labels_prevalence={"URL": 0.3, "PERSON_NAME": 0.4, "EMAIL": 0.1},
                    notes="User-authored bios; typical URL + PERSON_NAME + occasional EMAIL.",
                )
            )
    return out


def fetch_hn_comments_scale() -> list[GoldSetRow]:
    """Pilot: PILOT_HN_YEARS × PILOT_HN_MODS columns, time-bounded to Q1.

    Note: hacker_news.full is NOT partitioned by timestamp, so the Q1
    filter does not reduce bytes scanned. It's kept for sample-diversity
    hygiene (so stage 2 can use Q2/Q3/Q4 for structurally-independent
    slices of the same year).
    """
    years = (2021, 2020, 2019, 2018, 2017)
    out: list[GoldSetRow] = []
    for year in years[:PILOT_HN_YEARS]:
        for mod in range(PILOT_HN_MODS):
            sql = f"""
            SELECT text
            FROM `bigquery-public-data.hacker_news.full`
            WHERE type = 'comment'
              AND text IS NOT NULL
              AND LENGTH(text) BETWEEN 200 AND 4000
              AND EXTRACT(YEAR FROM timestamp) = {year}
              AND EXTRACT(MONTH FROM timestamp) BETWEEN 1 AND 3
              AND MOD(id, 10) = {mod}
            LIMIT {SAMPLE_SIZE}
            """
            rows = query_bq(sql, f"hn_{year}q1_mod{mod}")
            values = extract_column(rows, "text")
            if not values:
                continue
            out.append(
                _row(
                    column_id=f"hn_{year}q1_m{mod}",
                    source="bigquery-public-data.hacker_news",
                    source_reference=f"full[type=comment, year={year}, Q1, mod10={mod}]",
                    encoding="xor",
                    values=values,
                    true_shape=SHAPE_FREE_TEXT_HETEROGENEOUS,
                    true_labels=["URL"],
                    true_labels_prevalence={"URL": 0.3},
                    notes="HN comments; typical URL + occasional PERSON_NAME / EMAIL.",
                )
            )
    return out


def fetch_so_location_scale() -> list[GoldSetRow]:
    """Pilot: PILOT_SO_LOCATION_BUCKETS × PILOT_SO_LOCATION_MODS columns."""
    buckets = (("med", 1000, 10000), ("high", 10000, 99999999), ("low", 0, 1000))
    out: list[GoldSetRow] = []
    for slug, lo, hi in buckets[:PILOT_SO_LOCATION_BUCKETS]:
        for mod in range(PILOT_SO_LOCATION_MODS):
            sql = f"""
            SELECT location
            FROM `bigquery-public-data.stackoverflow.users`
            WHERE location IS NOT NULL
              AND LENGTH(location) > 3
              AND reputation BETWEEN {lo} AND {hi}
              AND MOD(id, 10) = {mod}
            LIMIT {SAMPLE_SIZE}
            """
            rows = query_bq(sql, f"so_location_{slug}_mod{mod}")
            values = extract_column(rows, "location")
            if not values:
                continue
            out.append(
                _row(
                    column_id=f"so_location_{slug}_m{mod}",
                    source="bigquery-public-data.stackoverflow",
                    source_reference=f"users.location[rep∈[{lo},{hi}], mod10={mod}]",
                    encoding="plaintext",
                    values=values,
                    true_shape=SHAPE_STRUCTURED_SINGLE,
                    true_labels=["ADDRESS"],
                    true_labels_prevalence={"ADDRESS": 0.9},
                    notes="Free-form city/country locations.",
                )
            )
    return out


def fetch_austin311_scale() -> list[GoldSetRow]:
    """Pilot: PILOT_AUSTIN_DISTRICTS × PILOT_AUSTIN_MODS columns."""
    out: list[GoldSetRow] = []
    for district in range(1, PILOT_AUSTIN_DISTRICTS + 1):
        for mod in range(PILOT_AUSTIN_MODS):
            sql = f"""
            SELECT incident_address
            FROM `bigquery-public-data.austin_311.311_service_requests`
            WHERE incident_address IS NOT NULL
              AND LENGTH(incident_address) > 10
              AND council_district_code = {district}
              AND MOD(ABS(FARM_FINGERPRINT(unique_key)), 2) = {mod}
            LIMIT {SAMPLE_SIZE}
            """
            rows = query_bq(sql, f"austin311_d{district}_m{mod}")
            values = extract_column(rows, "incident_address")
            if not values:
                continue
            out.append(
                _row(
                    column_id=f"austin311_d{district}_m{mod}",
                    source="bigquery-public-data.austin_311",
                    source_reference=f"311_service_requests.incident_address[district={district}, mod2={mod}]",
                    encoding="plaintext",
                    values=values,
                    true_shape=SHAPE_STRUCTURED_SINGLE,
                    true_labels=["ADDRESS"],
                    true_labels_prevalence={"ADDRESS": 1.0},
                    notes="Austin 311 street addresses.",
                )
            )
    return out


def fetch_so_display_name_scale() -> list[GoldSetRow]:
    """Pilot: PILOT_SO_DISPLAY_BUCKETS × PILOT_SO_DISPLAY_MODS columns."""
    buckets = (
        ("r0_1k", 0, 1000),
        ("r10k_100k", 10000, 100000),
        ("r1k_10k", 1000, 10000),
        ("r100k_plus", 100000, 99999999),
    )
    out: list[GoldSetRow] = []
    for slug, lo, hi in buckets[:PILOT_SO_DISPLAY_BUCKETS]:
        for mod in range(PILOT_SO_DISPLAY_MODS):
            sql = f"""
            SELECT display_name
            FROM `bigquery-public-data.stackoverflow.users`
            WHERE display_name IS NOT NULL
              AND LENGTH(display_name) > 2
              AND reputation BETWEEN {lo} AND {hi}
              AND MOD(id, 5) = {mod}
            LIMIT {SAMPLE_SIZE}
            """
            rows = query_bq(sql, f"so_display_{slug}_m{mod}")
            values = extract_column(rows, "display_name")
            if not values:
                continue
            out.append(
                _row(
                    column_id=f"so_display_{slug}_m{mod}",
                    source="bigquery-public-data.stackoverflow",
                    source_reference=f"users.display_name[rep∈[{lo},{hi}], mod5={mod}]",
                    encoding="plaintext",
                    values=values,
                    true_shape=SHAPE_STRUCTURED_SINGLE,
                    true_labels=["PERSON_NAME"],
                    true_labels_prevalence={"PERSON_NAME": 0.5},
                    notes="SO display names — mix of real names and handles.",
                )
            )
    return out


def fetch_eth_synthetic_pilot() -> list[GoldSetRow]:
    """3 columns of synthetic ETH-shaped addresses (0x + 40 hex).

    Replaces crypto_ethereum.transactions (dry-run estimated ~354 GB).
    The router and opaque-token branch classify on string shape, not on
    blockchain authenticity — so sha256-derived hex is structurally
    indistinguishable for pilot purposes. The one difference (ERC-55
    checksum case) is not enforced by the ETHEREUM_ADDRESS detector.
    """
    out: list[GoldSetRow] = []
    for shard in range(3):
        values = [f"0x{hashlib.sha256(f'shard{shard}_row{i}'.encode()).hexdigest()[:40]}" for i in range(SAMPLE_SIZE)]
        out.append(
            _row(
                column_id=f"eth_synth_s{shard}",
                source="synthetic.eth_addresses",
                source_reference=f"sha256('shard{shard}_row{{0..99}}').hexdigest()[:40]",
                encoding="plaintext",
                values=values,
                true_shape=SHAPE_OPAQUE_TOKENS,
                true_labels=["ETHEREUM_ADDRESS"],
                true_labels_prevalence={"ETHEREUM_ADDRESS": 1.0},
                notes="Synthetic ETH-shape hex addresses — replaces ~354 GB BQ scan.",
            )
        )
    return out


def fetch_sprint12_fixtures_scale() -> list[GoldSetRow]:
    """6 synth heterogeneous fixtures — anchor the het branch with fully-known ground truth."""
    from tests.benchmarks.meta_classifier.sprint12_safety_audit import _build_heterogeneous_fixtures

    fixtures = _build_heterogeneous_fixtures()
    fixture_labels = {
        "original_q3_log": [
            "EMAIL",
            "IP_ADDRESS",
            "API_KEY",
            "PHONE",
            "DATE_OF_BIRTH",
            "CREDIT_CARD",
            "SSN",
            "IBAN",
            "BITCOIN_ADDRESS",
            "ETHEREUM_ADDRESS",
            "MBI",
            "VIN",
            "MAC_ADDRESS",
            "URL",
            "ABA_ROUTING",
            "DEA_NUMBER",
            "EIN",
            "NPI",
        ],
        "apache_access_log": ["IP_ADDRESS"],
        "json_event_log": ["EMAIL", "IP_ADDRESS"],
        "base64_encoded_payloads": ["OPAQUE_SECRET"],
        "kafka_event_stream": ["EMAIL", "IP_ADDRESS", "PHONE", "CREDIT_CARD", "URL"],
        "support_chat_messages": ["EMAIL", "PHONE"],
    }
    out: list[GoldSetRow] = []
    for name, values in fixtures.items():
        labels = fixture_labels.get(name, [])
        shape = SHAPE_OPAQUE_TOKENS if name == "base64_encoded_payloads" else SHAPE_FREE_TEXT_HETEROGENEOUS
        out.append(
            _row(
                column_id=f"sprint12_{name}",
                source="tests.benchmarks.meta_classifier.sprint12_safety_audit",
                source_reference=f"_build_heterogeneous_fixtures()['{name}']",
                encoding="xor",
                values=values[:SAMPLE_SIZE],
                true_shape=shape,
                true_labels=labels,
                true_labels_prevalence={},
                notes="Sprint 12 synthetic fixture; ground truth from fixture definition.",
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def write_corpus(rows: list[GoldSetRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
    log.info("wrote %d rows → %s", len(rows), path)


def print_summary(rows: list[GoldSetRow]) -> None:
    by_shape = Counter(r.true_shape for r in rows)
    by_source = Counter(r.source.split(".")[-1] for r in rows)
    by_encoding = Counter(r.encoding for r in rows)
    print()  # noqa: T201
    print("─" * 60)  # noqa: T201
    print(f"M4d Phase 3a PILOT corpus — {len(rows)} columns")  # noqa: T201
    print("─" * 60)  # noqa: T201
    print(f"By shape:    {dict(by_shape)}")  # noqa: T201
    print(f"By source:   {dict(by_source)}")  # noqa: T201
    print(f"By encoding: {dict(by_encoding)}")  # noqa: T201


def main() -> int:
    all_rows: list[GoldSetRow] = []
    # Zero-cost sources first so an auth failure partway through doesn't
    # wipe the synthetic / fixture rows.
    all_rows.extend(fetch_sprint12_fixtures_scale())
    all_rows.extend(fetch_eth_synthetic_pilot())
    # BQ-backed sources.
    all_rows.extend(fetch_cfpb_narratives_scale())
    all_rows.extend(fetch_so_about_me_scale())
    all_rows.extend(fetch_hn_comments_scale())
    all_rows.extend(fetch_so_location_scale())
    all_rows.extend(fetch_austin311_scale())
    all_rows.extend(fetch_so_display_name_scale())
    # Pilot exclusions (re-enable for Phase 3b):
    #   - fetch_ny311_scale:         dry-run returned 400, needs investigation
    #   - fetch_github_author_scale: not selected for pilot, ~$$$ at full scale
    #   - fetch_btc_scale:           redundant with ETH synthetic for opaque coverage

    write_corpus(all_rows, OUTPUT_PATH)
    print_summary(all_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
