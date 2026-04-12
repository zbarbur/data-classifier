"""SecretBench False Negative Analysis — categorize missed secrets.

Loads the SecretBench corpus (downloaded via scripts/download_corpora.py),
runs our secret scanner on each sample, identifies false negatives, and
categorizes them into actionable buckets.

Usage:
    python3 scripts/analyze_secretbench_fns.py
    python3 scripts/analyze_secretbench_fns.py --verbose
    python3 scripts/analyze_secretbench_fns.py --output docs/research/SECRETBENCH_FN_ANALYSIS.md

Requires:
    python3 scripts/download_corpora.py --corpus secretbench
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from data_classifier import classify_columns, load_profile
from data_classifier.core.types import ColumnInput

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_CORPUS_FILE = Path(__file__).parent.parent / "tests" / "fixtures" / "corpora" / "secretbench_sample.json"

# ── FN Category Definitions ──────────────────────────────────────────────────

# Categories for false negatives (missed secrets)
FN_CATEGORIES = {
    "connection_string": "Connection string (JDBC, MongoDB, Redis, etc.) not parsed",
    "encoded_secret": "Base64-encoded or obfuscated secret value",
    "multiline_secret": "Secret spans multiple lines or is split across assignment",
    "embedded_in_url": "Secret embedded in URL (e.g. user:pass@host)",
    "non_standard_key": "Key name not in our dictionary (unusual naming)",
    "low_entropy": "Secret value has low entropy (dictionary words, short values)",
    "code_context": "Secret in code context our parsers do not handle (e.g. XML, TOML, function args)",
    "format_mismatch": "Value format does not match any known pattern",
    "out_of_scope": "Secret type is out of scope for our detector (e.g. private keys, certificates)",
    "other": "Uncategorized",
}

# ── Classification heuristics ────────────────────────────────────────────────
# These heuristics categorize FNs based on observable patterns in the sample.

_CONNECTION_STRING_RE = re.compile(
    r"(jdbc:|mongodb(\+srv)?://|redis://|mysql://|postgres(ql)?://|amqp://|"
    r"Server=.*Password=|Data Source=.*Password=)",
    re.IGNORECASE,
)
_URL_WITH_CREDS_RE = re.compile(r"https?://[^:]+:[^@]+@", re.IGNORECASE)
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]{20,}={0,2}$")
_MULTILINE_RE = re.compile(r"\\n|\\r|[\r\n]")
_XML_TOML_RE = re.compile(r"(<[a-zA-Z]|^\[.*\]$|\bvalue\s*=)", re.MULTILINE)
_PRIVATE_KEY_RE = re.compile(r"BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY", re.IGNORECASE)
_CERTIFICATE_RE = re.compile(r"BEGIN CERTIFICATE", re.IGNORECASE)

# Known key-name patterns in our dictionary (simplified check)
_KNOWN_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|auth|credential|private[_-]?key|"
    r"access[_-]?key|client[_-]?secret|db[_-]?pass|database[_-]?password)",
    re.IGNORECASE,
)


def categorize_fn(value: str) -> str:
    """Categorize a false negative into one of our defined buckets.

    Uses heuristic pattern matching to determine why the secret was missed.

    Args:
        value: The sample value that was a false negative.

    Returns:
        Category key from FN_CATEGORIES.
    """
    # Check for private keys / certificates (out of scope)
    if _PRIVATE_KEY_RE.search(value) or _CERTIFICATE_RE.search(value):
        return "out_of_scope"

    # Connection strings
    if _CONNECTION_STRING_RE.search(value):
        return "connection_string"

    # URL with embedded credentials
    if _URL_WITH_CREDS_RE.search(value):
        return "embedded_in_url"

    # Base64-encoded values (check if the whole value is base64-like)
    stripped = value.strip()
    if len(stripped) > 20 and _BASE64_RE.match(stripped):
        return "encoded_secret"

    # Multiline secrets
    if _MULTILINE_RE.search(value):
        return "multiline_secret"

    # XML/TOML or other config formats
    if _XML_TOML_RE.search(value):
        return "code_context"

    # Check if there's a recognizable key name — if not, it's a non-standard key
    if not _KNOWN_KEY_RE.search(value):
        return "non_standard_key"

    # Short or low-entropy values
    # Extract the value part after = or :
    parts = re.split(r"[=:]", value, maxsplit=1)
    if len(parts) == 2:
        val_part = parts[1].strip().strip("\"'")
        if len(val_part) < 8:
            return "low_entropy"

    return "format_mismatch"


@dataclass
class AnalysisResult:
    """Aggregated analysis of SecretBench false negatives."""

    total_samples: int = 0
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0
    fn_categories: Counter = field(default_factory=Counter)
    fn_examples: dict[str, list[str]] = field(default_factory=dict)


def load_secretbench_corpus() -> list[dict]:
    """Load SecretBench corpus from local file.

    Returns:
        List of sample dicts with 'value', 'is_secret', 'source' keys.

    Raises:
        FileNotFoundError: If the corpus has not been downloaded.
    """
    if not _CORPUS_FILE.exists():
        raise FileNotFoundError(
            f"SecretBench corpus not found at {_CORPUS_FILE}. "
            "Run: python3 scripts/download_corpora.py --corpus secretbench"
        )
    with open(_CORPUS_FILE) as f:
        return json.load(f)


def run_analysis(corpus: list[dict], *, verbose: bool = False) -> AnalysisResult:
    """Run our classifier on SecretBench samples and categorize FNs.

    Args:
        corpus: List of sample dicts from SecretBench.
        verbose: If True, log each FN with its category.

    Returns:
        AnalysisResult with aggregated statistics.
    """
    profile = load_profile("standard")
    result = AnalysisResult()
    result.total_samples = len(corpus)

    for sample in corpus:
        value = sample.get("value", "")
        expected_secret = sample.get("is_secret", False)

        # Create a column with this single sample
        column = ColumnInput(
            column_name="test_value",
            column_id=f"sb_{result.total_samples}",
            sample_values=[value],
        )

        findings = classify_columns(
            [column],
            profile,
            min_confidence=0.5,
            categories=["Credential"],
        )

        detected = len(findings) > 0

        if expected_secret and detected:
            result.true_positives += 1
        elif not expected_secret and detected:
            result.false_positives += 1
        elif expected_secret and not detected:
            result.false_negatives += 1
            category = categorize_fn(value)
            result.fn_categories[category] += 1
            if category not in result.fn_examples:
                result.fn_examples[category] = []
            if len(result.fn_examples[category]) < 3:
                # Truncate long values for display
                display = value[:120] + "..." if len(value) > 120 else value
                result.fn_examples[category].append(display)
            if verbose:
                logger.info("FN [%s]: %s", category, value[:100])
        else:
            result.true_negatives += 1

    return result


def format_report(result: AnalysisResult) -> str:
    """Format analysis results as a markdown report.

    Args:
        result: The analysis result to format.

    Returns:
        Markdown-formatted report string.
    """
    lines = [
        "# SecretBench False Negative Analysis",
        "",
        "## Overview",
        "",
        f"- **Total samples**: {result.total_samples}",
        f"- **True positives**: {result.true_positives}",
        f"- **False positives**: {result.false_positives}",
        f"- **False negatives**: {result.false_negatives}",
        f"- **True negatives**: {result.true_negatives}",
        "",
    ]

    if result.total_samples > 0:
        precision = result.true_positives / max(result.true_positives + result.false_positives, 1)
        recall = result.true_positives / max(result.true_positives + result.false_negatives, 1)
        lines.extend(
            [
                f"- **Precision**: {precision:.3f}",
                f"- **Recall**: {recall:.3f}",
                "",
            ]
        )

    lines.extend(
        [
            "## False Negative Categories",
            "",
            "| Category | Count | % of FNs | Description |",
            "|----------|-------|----------|-------------|",
        ]
    )

    total_fn = result.false_negatives or 1
    for category, count in result.fn_categories.most_common():
        pct = count / total_fn * 100
        desc = FN_CATEGORIES.get(category, "Unknown")
        lines.append(f"| {category} | {count} | {pct:.1f}% | {desc} |")

    lines.extend(["", "## Examples per Category", ""])

    for category, count in result.fn_categories.most_common():
        lines.append(f"### {category} ({count} FNs)")
        lines.append("")
        examples = result.fn_examples.get(category, [])
        for ex in examples:
            lines.append(f"- `{ex}`")
        lines.append("")

    lines.extend(
        [
            "## Recommendations",
            "",
            "Based on the FN categories above, the following improvements are suggested:",
            "",
            "1. **Connection string parsers**: Add JDBC, MongoDB, Redis URL parsing to `parsers.py`",
            "2. **URL credential extraction**: Parse `user:pass@host` patterns in URLs",
            "3. **Broader key-name dictionary**: Add entries from SecretBench's naming conventions",
            "4. **Code context parsers**: Handle XML config, TOML, function argument patterns",
            "5. **Base64 value detection**: Detect and decode base64-wrapped secrets",
            "",
            "---",
            "",
            "*Generated by `scripts/analyze_secretbench_fns.py`*",
        ]
    )

    return "\n".join(lines)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Analyze SecretBench false negatives")
    parser.add_argument("--verbose", action="store_true", help="Log each FN with its category")
    parser.add_argument("--output", type=str, help="Write report to file (default: stdout)")
    args = parser.parse_args()

    try:
        corpus = load_secretbench_corpus()
    except FileNotFoundError as e:
        logger.error("%s", e)
        sys.exit(1)

    logger.info("Loaded %d SecretBench samples", len(corpus))
    result = run_analysis(corpus, verbose=args.verbose)
    report = format_report(result)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report)
        logger.info("Report written to %s", args.output)
    else:
        print(report)  # noqa: T201 — CLI script, print is intentional


if __name__ == "__main__":
    main()
