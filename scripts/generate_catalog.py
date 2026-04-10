#!/usr/bin/env python3
"""Generate catalog markdown pages for mkdocs from library introspection.

Usage:
    python scripts/generate_catalog.py

Generates:
    docs-public/catalog/patterns.md
    docs-public/catalog/entity-types.md
    docs-public/catalog/profiles.md
    docs-public/catalog/validators.md
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).parent.parent / "docs-public" / "catalog"


def _escape_pipe(s: str) -> str:
    """Escape pipe characters for markdown table cells."""
    return s.replace("|", "\\|")


def generate_patterns() -> str:
    """Generate patterns.md from get_pattern_library()."""
    from data_classifier import get_pattern_library

    patterns = get_pattern_library()
    by_category: dict[str, list[dict]] = {}
    for p in patterns:
        by_category.setdefault(p["category"], []).append(p)

    lines = [
        "# Patterns",
        "",
        f"The library ships with **{len(patterns)} content patterns** for detecting sensitive data in sample values.",
        "",
        "Each pattern uses RE2-compatible regex (linear-time, no backtracking).",
        "",
    ]

    category_order = ["PII", "Financial", "Credential", "Health"]
    for cat in category_order:
        cat_patterns = by_category.get(cat, [])
        if not cat_patterns:
            continue
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| Pattern | Entity Type | Sensitivity | Confidence | Validator | Description |")
        lines.append("|---|---|---|---|---|---|")
        for p in sorted(cat_patterns, key=lambda x: x["name"]):
            validator = p.get("validator") or "--"
            description = _escape_pipe(p.get("description", "") or "--")
            lines.append(
                f"| `{p['name']}` | {p['entity_type']} | {p['sensitivity']} "
                f"| {p['confidence']:.2f} | {validator} | {description} |"
            )
        lines.append("")

    return "\n".join(lines)


def generate_entity_types() -> str:
    """Generate entity-types.md from get_supported_entity_types()."""
    from data_classifier import get_supported_entity_types

    entity_types = get_supported_entity_types()
    by_category: dict[str, list[dict]] = {}
    for et in entity_types:
        by_category.setdefault(et["category"], []).append(et)

    lines = [
        "# Entity Types",
        "",
        f"The library can detect **{len(entity_types)} entity types** across {len(by_category)} categories.",
        "",
    ]

    category_order = ["PII", "Financial", "Credential", "Health"]
    for cat in category_order:
        cat_types = by_category.get(cat, [])
        if not cat_types:
            continue
        lines.append(f"## {cat}")
        lines.append("")
        lines.append("| Entity Type | Sensitivity | Regulatory | Source |")
        lines.append("|---|---|---|---|")
        for et in sorted(cat_types, key=lambda x: x["entity_type"]):
            regulatory = ", ".join(et.get("regulatory", [])) or "--"
            lines.append(f"| `{et['entity_type']}` | {et['sensitivity']} | {regulatory} | {et['source']} |")
        lines.append("")

    return "\n".join(lines)


def generate_profiles() -> str:
    """Generate profiles.md from the standard profile."""
    from data_classifier import load_profile

    profile = load_profile("standard")

    lines = [
        "# Profiles",
        "",
        f"## {profile.name}",
        "",
        f"{profile.description}",
        "",
        f"This profile contains **{len(profile.rules)} rules**.",
        "",
        "| Entity Type | Category | Sensitivity | Confidence | Regulatory | Patterns |",
        "|---|---|---|---|---|---|",
    ]

    for rule in sorted(profile.rules, key=lambda r: (r.category, r.entity_type)):
        regulatory = ", ".join(rule.regulatory) or "--"
        pattern_count = len(rule.patterns)
        patterns_str = f"{pattern_count} pattern{'s' if pattern_count != 1 else ''}"
        lines.append(
            f"| `{rule.entity_type}` | {rule.category} | {rule.sensitivity} "
            f"| {rule.confidence:.2f} | {regulatory} | {patterns_str} |"
        )

    lines.append("")
    return "\n".join(lines)


def generate_validators() -> str:
    """Generate validators.md from the VALIDATORS registry."""
    from data_classifier.engines.validators import VALIDATORS

    descriptions = {
        "luhn": "Luhn algorithm checksum validation for credit card numbers. "
        "Rejects values that do not pass the Luhn check.",
        "luhn_strip": "Luhn check after stripping separators (dashes, spaces). "
        "Same as `luhn` but pre-processes the value.",
        "ssn_zeros": "Rejects SSNs with all-zeros in any group (area, group, or serial). "
        "Also rejects known test/advertising SSNs (078-05-1120, 219-09-9999).",
        "ipv4_not_reserved": "Rejects common non-PII IPv4 addresses: "
        "localhost (127.0.0.1), broadcast (255.255.255.255), and 0.0.0.0.",
        "iban_checksum": "IBAN mod-97 checksum validation. (Placeholder -- not yet implemented.)",
    }

    lines = [
        "# Validators",
        "",
        "Validators run after a regex pattern matches to reduce false positives. "
        "If a validator returns `False`, the match is discarded.",
        "",
        f"The library includes **{len(VALIDATORS)} validators**.",
        "",
        "| Validator | Description |",
        "|---|---|",
    ]

    for name in sorted(VALIDATORS.keys()):
        desc = descriptions.get(name, "No description available.")
        lines.append(f"| `{name}` | {desc} |")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    pages = {
        "patterns.md": generate_patterns,
        "entity-types.md": generate_entity_types,
        "profiles.md": generate_profiles,
        "validators.md": generate_validators,
    }

    for filename, generator in pages.items():
        content = generator()
        output_path = DOCS_DIR / filename
        output_path.write_text(content)
        line_count = content.count("\n")
        print(f"Generated {output_path} ({line_count} lines)")  # noqa: T201


if __name__ == "__main__":
    main()
