"""Build the M4c heterogeneous gold set.

Fetches samples from 6 BQ public datasets + Sprint 12 safety-audit
fixtures, applies per-source encoding policy, and emits one JSONL row
per column to

    tests/benchmarks/meta_classifier/heterogeneous_gold_set.jsonl

Per-source policy
-----------------

- **Structured-single anchors (14 rows):** plaintext. Already-public
  registry/reference data (addresses, Git commit metadata, ETH hex
  addresses). Content is the anchor here, encoding would just obscure
  labeler fidelity.
- **Anything with credential-shaped substrings (36 rows — Sprint 12
  synthetic fixtures + CFPB + SO about_me + HN comments):** XOR-encoded
  via ``data_classifier.patterns._decoder``. Two flavors of reason:
  Sprint 12 fixtures embed synthetic credentials that look real to
  GitHub's push-protection scanner; CFPB/SO/HN narratives are
  already-public user-contributed text that can contain credential-
  shaped substrings pasted by users. XOR is the established library
  pattern for this (see ``data_classifier.patterns._decoder``).
  Decoded at labeler display time.

Running
-------

Prerequisites: ``bq`` CLI available, ``gcloud auth login`` run.

    python -m scripts.m4c_build_gold_set

Caches raw query results under ``/tmp/m4c_staging/`` so re-runs are
fast (skip the BQ round-trip when a staging file exists). Delete the
staging dir to force a fresh fetch.

Pre-fill behavior (per user decision 2026-04-16: "A - I'll review")
-------------------------------------------------------------------

Each row ships with a best-guess ``true_labels`` based on the source's
expected entity shape. The labeler CLI paginates these for human
review. ``review_status`` starts as ``prefilled`` and flips to
``human_reviewed`` when the labeler marks the row accepted.

Contamination caveat for M4d: because Claude Opus pre-filled the
labels here, M4d's LLM-as-oracle validation loop cannot use the same
model family as its labeler without a contaminated yardstick. Use
GPT-4 class for M4d, or a materially different prompt shape.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

# Late import: script lives in scripts/, library lives in data_classifier/.
# Both are on PYTHONPATH when invoked via ``python -m``.
from data_classifier.core.taxonomy import family_for  # noqa: E402
from data_classifier.patterns._decoder import encode_xor  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "tests/benchmarks/meta_classifier/heterogeneous_gold_set.jsonl"
STAGING_DIR = Path("/tmp/m4c_staging")
SAMPLE_SIZE = 100  # values per column, per spec

# Allowed shape labels (Sprint 13 router branches).
SHAPE_STRUCTURED_SINGLE = "structured_single"
SHAPE_FREE_TEXT_HETEROGENEOUS = "free_text_heterogeneous"
SHAPE_OPAQUE_TOKENS = "opaque_tokens"


# --------------------------------------------------------------------------- #
# Gold-set row schema
# --------------------------------------------------------------------------- #


@dataclass
class GoldSetRow:
    """One gold-set entry — a column with ≤100 sample values + labels."""

    column_id: str
    source: str  # dataset/project name, e.g. "bigquery-public-data.cfpb_complaints"
    source_reference: str  # table.column or fixture name
    encoding: str  # "plaintext" or "xor"
    values: list[str]  # ≤SAMPLE_SIZE, encoded per policy
    true_shape: str  # one of SHAPE_*
    true_labels: list[str]  # fine-grained entity types (best-guess pre-fill)
    true_labels_family: list[str]  # derived from true_labels via family_for()
    true_labels_prevalence: dict[str, float]  # per-entity fraction; {} until labeled
    review_status: str  # "prefilled" / "human_reviewed" / "needs_review"
    annotator: str  # "claude-opus-4-6-prefill" or human name after review
    annotated_on: str  # ISO-8601 UTC
    notes: str = ""


# --------------------------------------------------------------------------- #
# BQ access
# --------------------------------------------------------------------------- #


def query_bq(sql: str, cache_key: str) -> list[dict]:
    """Run a bq query, caching the JSON response.

    Cache lives under /tmp/m4c_staging/<cache_key>.json — delete to
    force fresh fetch. Cache protects against flaky network and keeps
    re-runs fast during iterative pre-fill work.
    """
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = STAGING_DIR / f"{cache_key}.json"
    if cache_path.exists():
        log.info("cache hit: %s", cache_key)
        return json.loads(cache_path.read_text())

    log.info("cache miss: %s — querying BQ", cache_key)
    result = subprocess.run(
        [
            "bq",
            "query",
            "--nouse_legacy_sql",
            "--format=json",
            f"--max_rows={SAMPLE_SIZE}",
            sql,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        log.error("bq query failed for %s: %s", cache_key, result.stderr)
        return []
    rows = json.loads(result.stdout)
    cache_path.write_text(json.dumps(rows))
    return rows


def extract_column(rows: list[dict], column: str) -> list[str]:
    """Pull one column out of the BQ result list, dropping nulls/empties."""
    return [str(r[column]) for r in rows if r.get(column) is not None and str(r[column]).strip()]


# --------------------------------------------------------------------------- #
# Per-source fetchers
# --------------------------------------------------------------------------- #


def fetch_cfpb_narratives() -> list[GoldSetRow]:
    """15 rows: CFPB consumer_complaint_narrative sliced by product.

    CFPB pre-redacts PII in narratives (replaces with XXXX), so the
    pre-filled labels are conservative — only entities that plausibly
    survive redaction. Most rows will have empty or near-empty labels.
    """
    products = [
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
    rows_out: list[GoldSetRow] = []
    for slug, product_name in products:
        sql = f"""
        SELECT consumer_complaint_narrative
        FROM `bigquery-public-data.cfpb_complaints.complaint_database`
        WHERE consumer_complaint_narrative IS NOT NULL
          AND LENGTH(consumer_complaint_narrative) BETWEEN 100 AND 4000
          AND product = '{product_name}'
        LIMIT {SAMPLE_SIZE}
        """
        rows = query_bq(sql, f"cfpb_narrative_{slug}")
        values = extract_column(rows, "consumer_complaint_narrative")
        if not values:
            log.warning("cfpb: no rows for product=%s — skipping", product_name)
            continue
        rows_out.append(
            _row(
                column_id=f"cfpb_narrative_{slug}",
                source="bigquery-public-data.cfpb_complaints",
                source_reference=f"complaint_database.consumer_complaint_narrative[product={product_name}]",
                encoding="xor",
                values=values,
                true_shape=SHAPE_FREE_TEXT_HETEROGENEOUS,
                true_labels=[],  # CFPB XXXX-redacts — residual PII is rare
                true_labels_prevalence={},
                notes=(
                    "CFPB pre-redacts named PII with XXXX placeholders. "
                    "Expected residual entities: occasional PHONE, EMAIL, "
                    "ADDRESS, DATE_OF_BIRTH not caught by CFPB's redaction."
                ),
            )
        )
    return rows_out


def fetch_so_about_me() -> list[GoldSetRow]:
    """10 rows: Stack Overflow users.about_me sliced by reputation bucket."""
    buckets = [
        ("rep_0_100_a", 0, 100, 0),
        ("rep_0_100_b", 0, 100, 1),
        ("rep_100_1k_a", 100, 1000, 0),
        ("rep_100_1k_b", 100, 1000, 1),
        ("rep_1k_10k_a", 1000, 10000, 0),
        ("rep_1k_10k_b", 1000, 10000, 1),
        ("rep_10k_100k_a", 10000, 100000, 0),
        ("rep_10k_100k_b", 10000, 100000, 1),
        ("rep_100k_plus_a", 100000, 99999999, 0),
        ("rep_100k_plus_b", 100000, 99999999, 1),
    ]
    rows_out: list[GoldSetRow] = []
    for slug, lo, hi, mod_remainder in buckets:
        sql = f"""
        SELECT about_me
        FROM `bigquery-public-data.stackoverflow.users`
        WHERE about_me IS NOT NULL
          AND LENGTH(about_me) BETWEEN 100 AND 3000
          AND reputation BETWEEN {lo} AND {hi}
          AND MOD(id, 2) = {mod_remainder}
        LIMIT {SAMPLE_SIZE}
        """
        rows = query_bq(sql, f"so_about_me_{slug}")
        values = extract_column(rows, "about_me")
        if not values:
            log.warning("so_about_me: no rows for %s — skipping", slug)
            continue
        rows_out.append(
            _row(
                column_id=f"so_about_me_{slug}",
                source="bigquery-public-data.stackoverflow",
                source_reference=f"users.about_me[reputation∈[{lo},{hi}],mod2={mod_remainder}]",
                encoding="xor",
                values=values,
                true_shape=SHAPE_FREE_TEXT_HETEROGENEOUS,
                true_labels=["URL", "PERSON_NAME", "EMAIL"],  # typical bio content
                true_labels_prevalence={"URL": 0.3, "PERSON_NAME": 0.4, "EMAIL": 0.1},
                notes=(
                    "User-authored bios. HTML-wrapped. Typical entities: "
                    "URL to personal site, PERSON_NAME, occasional EMAIL. "
                    "Rare: PHONE."
                ),
            )
        )
    return rows_out


def fetch_hn_comments() -> list[GoldSetRow]:
    """5 rows: Hacker News comments sliced by year (2017-2021)."""
    rows_out: list[GoldSetRow] = []
    for year in (2017, 2018, 2019, 2020, 2021):
        sql = f"""
        SELECT text
        FROM `bigquery-public-data.hacker_news.full`
        WHERE type = 'comment'
          AND text IS NOT NULL
          AND LENGTH(text) BETWEEN 200 AND 4000
          AND EXTRACT(YEAR FROM timestamp) = {year}
        LIMIT {SAMPLE_SIZE}
        """
        rows = query_bq(sql, f"hn_comments_{year}")
        values = extract_column(rows, "text")
        if not values:
            log.warning("hn_comments: no rows for %d — skipping", year)
            continue
        rows_out.append(
            _row(
                column_id=f"hn_comments_{year}",
                source="bigquery-public-data.hacker_news",
                source_reference=f"full.text[type=comment, year={year}]",
                encoding="xor",
                values=values,
                true_shape=SHAPE_FREE_TEXT_HETEROGENEOUS,
                true_labels=["URL"],
                true_labels_prevalence={"URL": 0.3},
                notes=(
                    "Public HN comments. Typical entities: URL. "
                    "Rare residual: EMAIL, PHONE if users share contact info."
                ),
            )
        )
    return rows_out


def fetch_structured_anchors() -> list[GoldSetRow]:
    """14 rows covering structured_single + opaque_tokens shapes.

    Substitutes for FEC indiv20 (not in bigquery-public-data) and
    NPPES (not in bigquery-public-data) with github_repos commit
    metadata (real PERSON_NAME + EMAIL from commits — public Git
    history is already public).
    """
    rows_out: list[GoldSetRow] = []

    # SO users.location × 3 (reputation slices)
    for slug, lo, hi in (("low", 0, 1000), ("med", 1000, 10000), ("high", 10000, 99999999)):
        sql = f"""
        SELECT location
        FROM `bigquery-public-data.stackoverflow.users`
        WHERE location IS NOT NULL
          AND LENGTH(location) > 3
          AND reputation BETWEEN {lo} AND {hi}
        LIMIT {SAMPLE_SIZE}
        """
        rows = query_bq(sql, f"so_location_{slug}")
        values = extract_column(rows, "location")
        if values:
            rows_out.append(
                _row(
                    column_id=f"so_location_{slug}",
                    source="bigquery-public-data.stackoverflow",
                    source_reference=f"users.location[reputation∈[{lo},{hi}])",
                    encoding="plaintext",
                    values=values,
                    true_shape=SHAPE_STRUCTURED_SINGLE,
                    true_labels=["ADDRESS"],
                    true_labels_prevalence={"ADDRESS": 0.9},
                    notes="Free-form city/country location strings. Mostly ADDRESS-shape.",
                )
            )

    # austin_311 address × 3 (council districts — INT64)
    for slug, district in (("d1", 1), ("d5", 5), ("d9", 9)):
        sql = f"""
        SELECT incident_address
        FROM `bigquery-public-data.austin_311.311_service_requests`
        WHERE incident_address IS NOT NULL
          AND council_district_code = {district}
          AND LENGTH(incident_address) > 10
        LIMIT {SAMPLE_SIZE}
        """
        rows = query_bq(sql, f"austin311_{slug}")
        values = extract_column(rows, "incident_address")
        if values:
            rows_out.append(
                _row(
                    column_id=f"austin311_address_{slug}",
                    source="bigquery-public-data.austin_311",
                    source_reference=f"311_service_requests.incident_address[council_district={district}]",
                    encoding="plaintext",
                    values=values,
                    true_shape=SHAPE_STRUCTURED_SINGLE,
                    true_labels=["ADDRESS"],
                    true_labels_prevalence={"ADDRESS": 1.0},
                    notes="Street-address-shape. Public Austin 311 service requests.",
                )
            )

    # new_york_311 address × 2
    for slug, borough in (("manhattan", "MANHATTAN"), ("brooklyn", "BROOKLYN")):
        sql = f"""
        SELECT incident_address
        FROM `bigquery-public-data.new_york_311.311_service_requests`
        WHERE incident_address IS NOT NULL
          AND borough = '{borough}'
          AND LENGTH(incident_address) > 10
        LIMIT {SAMPLE_SIZE}
        """
        rows = query_bq(sql, f"ny311_{slug}")
        values = extract_column(rows, "incident_address")
        if values:
            rows_out.append(
                _row(
                    column_id=f"ny311_address_{slug}",
                    source="bigquery-public-data.new_york_311",
                    source_reference=f"311_service_requests.incident_address[borough={borough}]",
                    encoding="plaintext",
                    values=values,
                    true_shape=SHAPE_STRUCTURED_SINGLE,
                    true_labels=["ADDRESS"],
                    true_labels_prevalence={"ADDRESS": 1.0},
                    notes="Street-address-shape. Public NYC 311.",
                )
            )

    # github_repos commits: author name (2) + author email (1) — FEC/NPPES substitute
    # Query COUNT_STAR partition to cap scan cost.
    for slug, mod_val in (("a", 0), ("b", 1)):
        sql = f"""
        SELECT author.name as author_name
        FROM `bigquery-public-data.github_repos.commits`
        WHERE author.name IS NOT NULL
          AND LENGTH(author.name) BETWEEN 2 AND 60
          AND MOD(ABS(FARM_FINGERPRINT(commit)), 1000) = {mod_val}
        LIMIT {SAMPLE_SIZE}
        """
        rows = query_bq(sql, f"github_author_name_{slug}")
        values = extract_column(rows, "author_name")
        if values:
            rows_out.append(
                _row(
                    column_id=f"github_author_name_{slug}",
                    source="bigquery-public-data.github_repos",
                    source_reference=f"commits.author.name[FARM_FINGERPRINT mod 1000 = {mod_val}]",
                    encoding="plaintext",
                    values=values,
                    true_shape=SHAPE_STRUCTURED_SINGLE,
                    true_labels=["PERSON_NAME"],
                    true_labels_prevalence={"PERSON_NAME": 0.9},
                    notes="Git commit author names. Public Git history. Some usernames/aliases.",
                )
            )

    sql = """
    SELECT author.email as author_email
    FROM `bigquery-public-data.github_repos.commits`
    WHERE author.email IS NOT NULL
      AND author.email LIKE '%@%'
      AND MOD(ABS(FARM_FINGERPRINT(commit)), 1000) = 500
    LIMIT 100
    """
    rows = query_bq(sql, "github_author_email")
    values = extract_column(rows, "author_email")
    if values:
        rows_out.append(
            _row(
                column_id="github_author_email",
                source="bigquery-public-data.github_repos",
                source_reference="commits.author.email[FARM_FINGERPRINT mod 1000 = 500]",
                encoding="plaintext",
                values=values,
                true_shape=SHAPE_STRUCTURED_SINGLE,
                true_labels=["EMAIL"],
                true_labels_prevalence={"EMAIL": 1.0},
                notes="Git commit author emails. Public Git history.",
            )
        )

    # crypto_ethereum from_address × 3 (different block ranges)
    for slug, lo_block, hi_block in (
        ("early", 1000000, 1100000),
        ("mid", 8000000, 8100000),
        ("recent", 15000000, 15100000),
    ):
        sql = f"""
        SELECT from_address
        FROM `bigquery-public-data.crypto_ethereum.transactions`
        WHERE from_address IS NOT NULL
          AND block_number BETWEEN {lo_block} AND {hi_block}
        LIMIT {SAMPLE_SIZE}
        """
        rows = query_bq(sql, f"eth_from_{slug}")
        values = extract_column(rows, "from_address")
        if values:
            rows_out.append(
                _row(
                    column_id=f"eth_from_address_{slug}",
                    source="bigquery-public-data.crypto_ethereum",
                    source_reference=f"transactions.from_address[block∈[{lo_block},{hi_block}]]",
                    encoding="plaintext",
                    values=values,
                    true_shape=SHAPE_OPAQUE_TOKENS,
                    true_labels=["ETHEREUM_ADDRESS"],
                    true_labels_prevalence={"ETHEREUM_ADDRESS": 1.0},
                    notes="Hex-encoded 40-char ETH addresses. Opaque-token shape.",
                )
            )

    return rows_out


def fetch_sprint12_fixtures() -> list[GoldSetRow]:
    """6 rows from the Sprint 12 safety-audit fixture generator.

    Ground truth derived from the fixture docstrings — the fixture
    taxonomy explicitly describes which entity shapes appear in each.
    Pre-fills are high-confidence.
    """
    # Import lazily to avoid pulling ML deps into the default path.
    from tests.benchmarks.meta_classifier.sprint12_safety_audit import _build_heterogeneous_fixtures

    fixtures = _build_heterogeneous_fixtures()

    # Labels hand-extracted from the fixture definitions (lines 544-684
    # of sprint12_safety_audit.py). High-confidence because fixture
    # content is controlled; user review still recommended.
    fixture_labels: dict[str, tuple[list[str], dict[str, float]]] = {
        "original_q3_log": (
            [
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
            {
                "EMAIL": 0.95,
                "IP_ADDRESS": 0.6,
                "API_KEY": 0.1,
                "PHONE": 0.3,
                "URL": 0.1,
            },
        ),
        "apache_access_log": (
            ["IP_ADDRESS"],
            {"IP_ADDRESS": 1.0},
        ),
        "json_event_log": (
            ["EMAIL", "IP_ADDRESS"],
            {"EMAIL": 1.0, "IP_ADDRESS": 1.0},
        ),
        "base64_encoded_payloads": (
            ["OPAQUE_SECRET"],
            {"OPAQUE_SECRET": 1.0},
        ),
        "support_chat_messages": (
            ["EMAIL", "PHONE"],
            {"EMAIL": 0.3, "PHONE": 0.1},
        ),
        "kafka_event_stream": (
            ["EMAIL", "IP_ADDRESS", "PHONE", "CREDIT_CARD", "URL"],
            {"EMAIL": 0.3, "IP_ADDRESS": 0.2, "PHONE": 0.1, "CREDIT_CARD": 0.1, "URL": 0.1},
        ),
    }

    shape_map: dict[str, str] = {
        "original_q3_log": SHAPE_FREE_TEXT_HETEROGENEOUS,
        "apache_access_log": SHAPE_FREE_TEXT_HETEROGENEOUS,
        "json_event_log": SHAPE_FREE_TEXT_HETEROGENEOUS,
        "base64_encoded_payloads": SHAPE_OPAQUE_TOKENS,
        "support_chat_messages": SHAPE_FREE_TEXT_HETEROGENEOUS,
        "kafka_event_stream": SHAPE_FREE_TEXT_HETEROGENEOUS,
    }

    rows_out: list[GoldSetRow] = []
    for name, values in fixtures.items():
        labels, prevalence = fixture_labels[name]
        rows_out.append(
            _row(
                column_id=f"sprint12_fixture_{name}",
                source="data_classifier.tests.benchmarks.meta_classifier.sprint12_safety_audit",
                source_reference=f"_build_heterogeneous_fixtures()[{name!r}]",
                # XOR rather than plaintext: the fixture values embed synthetic
                # credential-shaped strings (Stripe test keys, GitHub PAT shapes,
                # AWS key shapes) that trip GitHub push protection. The source
                # file sprint12_safety_audit.py already XOR-encodes these at
                # source; when fetched via _build_heterogeneous_fixtures() they
                # come out plaintext, so re-encoding here keeps the committed
                # JSONL scanner-safe.
                encoding="xor",
                values=values[:SAMPLE_SIZE],
                true_shape=shape_map[name],
                true_labels=labels,
                true_labels_prevalence=prevalence,
                notes="Sprint 12 safety-audit fixture. Synthetic in-repo data.",
                review_status="prefilled",  # still flag for human review
            )
        )
    return rows_out


# --------------------------------------------------------------------------- #
# Row construction + encoding
# --------------------------------------------------------------------------- #


def _encode_values(values: list[str], encoding: str) -> list[str]:
    """Apply per-source encoding policy before commit.

    - plaintext: values pass through unchanged
    - xor: each value gets XOR-encoded via
      ``data_classifier.patterns._decoder.encode_xor``. Labeler CLI
      decodes at display time. Scanner-dodge only — anyone who clones
      can decode.
    """
    if encoding == "plaintext":
        return values
    if encoding == "xor":
        return [encode_xor(v) for v in values]
    raise ValueError(f"unknown encoding: {encoding}")


def _row(
    *,
    column_id: str,
    source: str,
    source_reference: str,
    encoding: str,
    values: list[str],
    true_shape: str,
    true_labels: list[str],
    true_labels_prevalence: dict[str, float],
    notes: str,
    review_status: str = "prefilled",
) -> GoldSetRow:
    """Wrap a fetched column into a GoldSetRow, deriving family labels."""
    encoded = _encode_values(values[:SAMPLE_SIZE], encoding)
    family_labels = sorted({family_for(e) for e in true_labels if family_for(e)})
    return GoldSetRow(
        column_id=column_id,
        source=source,
        source_reference=source_reference,
        encoding=encoding,
        values=encoded,
        true_shape=true_shape,
        true_labels=sorted(set(true_labels)),
        true_labels_family=family_labels,
        true_labels_prevalence=true_labels_prevalence,
        review_status=review_status,
        annotator="claude-opus-4-6-prefill",
        annotated_on=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def write_gold_set(rows: list[GoldSetRow], path: Path) -> None:
    """Atomically write JSONL — temp file + rename so Ctrl-C is safe."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        for row in rows:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
    tmp.replace(path)
    log.info("wrote %d rows → %s", len(rows), path)


def print_summary(rows: list[GoldSetRow]) -> None:
    """Counts + coverage summary to stdout — readable at script end."""
    by_shape: Counter[str] = Counter(r.true_shape for r in rows)
    by_source: Counter[str] = Counter(r.source.split(".")[-1] for r in rows)
    by_encoding: Counter[str] = Counter(r.encoding for r in rows)
    print()  # noqa: T201
    print("─" * 60)  # noqa: T201
    print("M4c gold-set summary")  # noqa: T201
    print("─" * 60)  # noqa: T201
    print(f"Total rows: {len(rows)}")  # noqa: T201
    print(f"By shape:    {dict(by_shape)}")  # noqa: T201
    print(f"By source:   {dict(by_source)}")  # noqa: T201
    print(f"By encoding: {dict(by_encoding)}")  # noqa: T201
    prefilled = sum(1 for r in rows if r.review_status == "prefilled")
    reviewed = sum(1 for r in rows if r.review_status == "human_reviewed")
    print(f"Review:      {prefilled} prefilled, {reviewed} human-reviewed")  # noqa: T201


def main() -> int:
    all_rows: list[GoldSetRow] = []
    all_rows.extend(fetch_sprint12_fixtures())  # 6
    all_rows.extend(fetch_cfpb_narratives())  # up to 15
    all_rows.extend(fetch_so_about_me())  # up to 10
    all_rows.extend(fetch_hn_comments())  # up to 5
    all_rows.extend(fetch_structured_anchors())  # up to 14

    write_gold_set(all_rows, OUTPUT_PATH)
    print_summary(all_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
