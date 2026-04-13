"""Collect project statistics for the BigQuery connector dashboard.

Parses source files directly (no library import) so it runs without the
``[ml]`` extras installed. Emits a JSON snapshot consumed by the BQ DAG
connector project at ``vendor/classifier-stats.json``.

Usage:
    python scripts/collect_stats.py                 # writes stats.json
    python scripts/collect_stats.py --out foo.json  # custom path
    python scripts/collect_stats.py --pretty        # indented output
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PATTERNS_FILE = REPO_ROOT / "data_classifier" / "patterns" / "default_patterns.json"
PROFILES_DIR = REPO_ROOT / "data_classifier" / "profiles"
ENGINES_DIR = REPO_ROOT / "data_classifier" / "engines"
ENGINE_DEFAULTS = REPO_ROOT / "data_classifier" / "config" / "engine_defaults.yaml"
SRC_DIR = REPO_ROOT / "data_classifier"
TESTS_DIR = REPO_ROOT / "tests"


# Fixed-scope engines — engines whose entity set isn't enumerable from a single
# source file. regex and column_name are derived from their data files instead.
STATIC_ENGINE_SCOPE: dict[str, dict[str, Any]] = {
    "heuristic": {
        "status": "active",
        "description": "Signal-based profiler over cardinality, entropy, length, and char-class.",
        "entity_types": [],  # heuristic produces signals, not entity labels directly
    },
    "secret_scanner": {
        "status": "active",
        "description": "Two-tier credential detector over key names and value entropy.",
        "entity_types": ["API_KEY", "PRIVATE_KEY", "PASSWORD_HASH", "OPAQUE_SECRET"],
    },
    "gliner": {
        "status": "active",
        "description": "GLiNER2 ONNX zero-shot NER model for unstructured sample text.",
        "entity_types": [
            "PERSON_NAME",
            "EMAIL",
            "PHONE",
            "ADDRESS",
            "DATE_OF_BIRTH",
            "NATIONAL_ID",
            "CREDIT_CARD",
            "IBAN",
        ],
    },
}


def _load_patterns() -> list[dict[str, Any]]:
    data = json.loads(PATTERNS_FILE.read_text())
    return data.get("patterns", [])


def _load_profile(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def collect_engines(patterns: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
    regex_entities = sorted({p["entity_type"] for p in patterns})

    column_rules = profile["profiles"]["standard"]["rules"]
    column_entities = sorted({r["entity_type"] for r in column_rules})

    engines = [
        {
            "name": "regex",
            "status": "active",
            "description": "RE2 content-matching engine over value samples.",
            "entity_types": regex_entities,
            "entity_type_count": len(regex_entities),
        },
        {
            "name": "column_name",
            "status": "active",
            "description": "Profile-driven column-name classifier (first-match-wins).",
            "entity_types": column_entities,
            "entity_type_count": len(column_entities),
        },
    ]
    for name, meta in STATIC_ENGINE_SCOPE.items():
        engines.append(
            {
                "name": name,
                "status": meta["status"],
                "description": meta["description"],
                "entity_types": meta["entity_types"],
                "entity_type_count": len(meta["entity_types"]),
            }
        )
    return engines


def collect_entity_types(
    patterns: list[dict[str, Any]],
    profile: dict[str, Any],
    engines: list[dict[str, Any]],
) -> dict[str, Any]:
    category_by_entity: dict[str, str] = {}
    for rule in profile["profiles"]["standard"]["rules"]:
        category_by_entity[rule["entity_type"]] = rule["category"]
    for p in patterns:
        category_by_entity.setdefault(p["entity_type"], p.get("category", "PII"))

    engine_lookup = {e["name"]: set(e["entity_types"]) for e in engines}

    types: list[dict[str, Any]] = []
    by_category: dict[str, list[str]] = defaultdict(list)

    for entity in sorted(category_by_entity):
        category = category_by_entity[entity]
        methods = sorted(name for name, ents in engine_lookup.items() if entity in ents)
        types.append(
            {
                "name": entity,
                "category": category,
                "detection_methods": methods,
            }
        )
        by_category[category].append(entity)

    return {
        "total": len(types),
        "by_category": {cat: sorted(names) for cat, names in sorted(by_category.items())},
        "types": types,
    }


def collect_profiles() -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for path in sorted(PROFILES_DIR.glob("*.yaml")):
        doc = _load_profile(path)
        for profile_id, body in doc.get("profiles", {}).items():
            rules = body.get("rules", [])
            confidences = [r["confidence"] for r in rules if "confidence" in r]
            profiles.append(
                {
                    "name": profile_id,
                    "file": path.name,
                    "description": (body.get("description") or "").strip(),
                    "rule_count": len(rules),
                    "enabled_engines": ["regex", "column_name", "heuristic", "secret_scanner", "gliner"],
                    "confidence_thresholds": {
                        "min": min(confidences) if confidences else None,
                        "max": max(confidences) if confidences else None,
                        "avg": round(sum(confidences) / len(confidences), 3) if confidences else None,
                    },
                }
            )
    return profiles


def _count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open("rb"))
    except OSError:
        return 0


_TEST_DEF = re.compile(r"^\s*(async\s+)?def\s+test_\w+\s*\(", re.MULTILINE)


def collect_signals(patterns: list[dict[str, Any]]) -> dict[str, Any]:
    """Count every detection signal the engines can fire on.

    Signals are the atomic units of detection — a regex pattern, a column-name
    variant, a secret key-name hint, a heuristic threshold. The dashboard can
    sum these for a single headline number.
    """
    pattern_dir = REPO_ROOT / "data_classifier" / "patterns"

    col_doc = json.loads((pattern_dir / "column_names.json").read_text())
    col_variants = sum(len(e.get("variants", [])) for e in col_doc["entity_types"])
    col_entities = len(col_doc["entity_types"])

    sk_doc = json.loads((pattern_dir / "secret_key_names.json").read_text())
    secret_keys = len(sk_doc.get("key_names", []))

    ph_doc = json.loads((pattern_dir / "known_placeholder_values.json").read_text())
    placeholders = len(ph_doc.get("placeholder_values", []))

    sw_doc = json.loads((pattern_dir / "stopwords.json").read_text())
    stopwords = len(sw_doc.get("stopwords", []))

    heuristic_signals = 0
    if ENGINE_DEFAULTS.exists():
        eng_doc = yaml.safe_load(ENGINE_DEFAULTS.read_text()) or {}
        signals = (eng_doc.get("heuristic_engine", {}) or {}).get("signals", {})
        heuristic_signals = sum(len(v) for v in signals.values() if isinstance(v, dict))

    total = len(patterns) + col_variants + secret_keys + heuristic_signals
    return {
        "total": total,
        "regex_patterns": len(patterns),
        "column_name_variants": col_variants,
        "column_name_entities": col_entities,
        "secret_key_hints": secret_keys,
        "heuristic_signals": heuristic_signals,
        "placeholder_suppressors": placeholders,
        "stopwords": stopwords,
    }


def collect_quality(patterns: list[dict[str, Any]]) -> dict[str, int]:
    test_files = [p for p in TESTS_DIR.rglob("*.py") if "__pycache__" not in p.parts]
    test_count = 0
    test_loc = 0
    for path in test_files:
        text = path.read_text(errors="ignore")
        test_count += len(_TEST_DEF.findall(text))
        test_loc += text.count("\n") + 1

    src_loc = 0
    for path in SRC_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        src_loc += _count_lines(path)

    return {
        "tests": test_count,
        "test_files": len(test_files),
        "test_loc": test_loc,
        "loc": src_loc,
        "patterns": len(patterns),
    }


def build_stats() -> dict[str, Any]:
    patterns = _load_patterns()
    profile = _load_profile(PROFILES_DIR / "standard.yaml")
    engines = collect_engines(patterns, profile)
    return {
        "engines": engines,
        "entity_types": collect_entity_types(patterns, profile, engines),
        "profiles": collect_profiles(),
        "signals": collect_signals(patterns),
        "quality": collect_quality(patterns),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("stats.json"))
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    stats = build_stats()
    indent = 2 if args.pretty else None
    args.out.write_text(json.dumps(stats, indent=indent, sort_keys=False) + "\n")
    print(f"wrote {args.out} ({len(stats['entity_types']['types'])} entity types, "
          f"{stats['quality']['tests']} tests, {stats['quality']['patterns']} patterns)")


if __name__ == "__main__":
    main()
