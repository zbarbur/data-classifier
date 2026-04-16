"""Generate JS assets for data_classifier/clients/browser from the Python source.

Emits six files into data_classifier/clients/browser/src/generated/:

  * constants.js           - scoring thresholds + PYTHON_LOGIC_VERSION SHA
  * patterns.js            - 77 patterns, examples stripped
  * secret-key-names.js    - 178 key-name entries
  * stopwords.js           - decoded stopwords set
  * placeholder-values.js  - placeholder-value set
  * fixtures.json          - seed-corpus expected findings, version-stamped

PYTHON_LOGIC_VERSION is the SHA-256 of the concatenated contents of the Python
logic files that matter for JS parity. A change in any of them invalidates the
JS fixtures and forces the port to follow.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BROWSER_DIR = REPO_ROOT / "data_classifier" / "clients" / "browser"
GENERATED_DIR = BROWSER_DIR / "src" / "generated"
SEED_PATH = BROWSER_DIR / "tester" / "corpus" / "seed.jsonl"

# Ensure the in-repo ``data_classifier`` package is importable regardless of
# how this script is invoked (e.g. ``python3 scripts/generate_browser_patterns.py``
# from the repo root, without having installed the library in editable mode).
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LOGIC_FILES = [
    REPO_ROOT / "data_classifier" / "engines" / "secret_scanner.py",
    REPO_ROOT / "data_classifier" / "engines" / "regex_engine.py",
    REPO_ROOT / "data_classifier" / "engines" / "validators.py",
    REPO_ROOT / "data_classifier" / "engines" / "parsers.py",
    REPO_ROOT / "data_classifier" / "engines" / "heuristic_engine.py",
    REPO_ROOT / "data_classifier" / "config" / "engine_defaults.yaml",
]

# Keep in sync with src/validators.js (PORTED dict keys). Names not listed here
# emit a warning and load as always-true stubs in JS.
PORTED_VALIDATORS = {"aws_secret_not_hex", "random_password", "not_placeholder_credential", ""}

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("generate_browser_patterns")


def python_logic_version() -> str:
    h = hashlib.sha256()
    for p in sorted(LOGIC_FILES):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def load_secret_scanner_config() -> dict:
    yaml_path = REPO_ROOT / "data_classifier" / "config" / "engine_defaults.yaml"
    data = yaml.safe_load(yaml_path.read_text())
    return data.get("secret_scanner", {})


def emit_constants(version: str) -> None:
    from data_classifier.engines.secret_scanner import _CONFIG_VALUES

    cfg = load_secret_scanner_config()
    scoring = cfg.get("scoring", {})
    rel = scoring.get("relative_entropy_thresholds", {})
    tiers = scoring.get("tier_boundaries", {})
    config_values_sorted = sorted(_CONFIG_VALUES)
    js = f"""// GENERATED - do not edit. Run: npm run generate
export const PYTHON_LOGIC_VERSION = {json.dumps(version)};

export const SECRET_SCANNER = {{
  minValueLength: {cfg.get("min_value_length", 8)},
  antiIndicators: {json.dumps(cfg.get("anti_indicators", []))},
  configValues: {json.dumps(config_values_sorted)},
  definitiveMultiplier: {scoring.get("definitive_multiplier", 0.95)},
  strongMinEntropyScore: {scoring.get("strong_min_entropy_score", 0.6)},
  relativeEntropyStrong: {rel.get("strong", 0.5)},
  relativeEntropyContextual: {rel.get("contextual", 0.7)},
  diversityThreshold: {scoring.get("diversity_threshold", 3)},
  proseAlphaThreshold: {scoring.get("prose_alpha_threshold", 0.6)},
  tierBoundaryDefinitive: {tiers.get("definitive", 0.9)},
  tierBoundaryStrong: {tiers.get("strong", 0.7)},
}};
"""
    (GENERATED_DIR / "constants.js").write_text(js)
    log.info("wrote constants.js (PYTHON_LOGIC_VERSION=%s)", version)


def emit_patterns() -> None:
    from data_classifier.patterns import load_default_patterns

    patterns = load_default_patterns()
    stub_report: set[str] = set()
    out = []
    for p in patterns:
        if p.validator and p.validator not in PORTED_VALIDATORS:
            stub_report.add(p.validator)
        out.append(
            {
                "name": p.name,
                "regex": p.regex,
                "entity_type": p.entity_type,
                "category": p.category,
                "sensitivity": p.sensitivity,
                "confidence": p.confidence,
                "validator": p.validator,
                "description": p.description,
                "context_words_boost": list(p.context_words_boost),
                "context_words_suppress": list(p.context_words_suppress),
                "stopwords": list(p.stopwords),
                "allowlist_patterns": list(p.allowlist_patterns),
                "requires_column_hint": p.requires_column_hint,
                "column_hint_keywords": list(p.column_hint_keywords),
            }
        )
    if stub_report:
        log.warning(
            "%d pattern(s) reference validators not ported to JS; "
            "they will load with stub validators that always return true: %s",
            len(stub_report),
            sorted(stub_report),
        )
    js = (
        "// GENERATED - do not edit. Run: npm run generate\n"
        "const RAW = " + json.dumps(json.dumps(out)) + ";\n"
        "export const PATTERNS = JSON.parse(RAW);\n"
    )
    (GENERATED_DIR / "patterns.js").write_text(js)
    log.info("wrote patterns.js (%d patterns)", len(out))


def emit_secret_key_names() -> None:
    src = REPO_ROOT / "data_classifier" / "patterns" / "secret_key_names.json"
    data = json.loads(src.read_text())
    entries = data["key_names"]
    js = (
        "// GENERATED - do not edit. Run: npm run generate\n"
        "const RAW = " + json.dumps(json.dumps(entries)) + ";\n"
        "export const SECRET_KEY_NAMES = JSON.parse(RAW);\n"
    )
    (GENERATED_DIR / "secret-key-names.js").write_text(js)
    log.info("wrote secret-key-names.js (%d entries)", len(entries))


def emit_stopwords() -> None:
    from data_classifier.patterns._decoder import decode_encoded_strings

    src = REPO_ROOT / "data_classifier" / "patterns" / "stopwords.json"
    raw = json.loads(src.read_text()).get("stopwords", [])
    decoded = decode_encoded_strings(raw)
    lower = sorted({s.lower() for s in decoded})
    js = f"// GENERATED - do not edit. Run: npm run generate\nexport const STOPWORDS = new Set({json.dumps(lower)});\n"
    (GENERATED_DIR / "stopwords.js").write_text(js)
    log.info("wrote stopwords.js (%d entries)", len(lower))


def emit_placeholder_values() -> None:
    src = REPO_ROOT / "data_classifier" / "patterns" / "known_placeholder_values.json"
    raw = json.loads(src.read_text()).get("placeholder_values", [])
    lower = sorted({s.lower() for s in raw})
    js = (
        "// GENERATED - do not edit. Run: npm run generate\n"
        f"export const PLACEHOLDER_VALUES = new Set({json.dumps(lower)});\n"
    )
    (GENERATED_DIR / "placeholder-values.js").write_text(js)
    log.info("wrote placeholder-values.js (%d entries)", len(lower))


def emit_fixtures(version: str) -> None:
    from data_classifier.core.types import ColumnInput
    from data_classifier.engines.regex_engine import RegexEngine
    from data_classifier.engines.secret_scanner import SecretScannerEngine
    from data_classifier.profiles import load_profile

    profile = load_profile()
    regex_engine = RegexEngine()
    regex_engine.startup()
    scanner_engine = SecretScannerEngine()
    scanner_engine.startup()

    fixtures = {"python_logic_version": version, "cases": []}
    if not SEED_PATH.exists():
        log.warning("seed corpus missing: %s", SEED_PATH)
    else:
        for raw_line in SEED_PATH.read_text().splitlines():
            line = raw_line.strip()
            if not line:
                continue
            case = json.loads(line)
            col = ColumnInput(column_id=case["id"], column_name="prompt", sample_values=[case["text"]])
            findings = []
            for f in regex_engine.classify_column(col, profile=profile, min_confidence=0.3):
                if f.category == "Credential":
                    findings.append({"entity_type": f.entity_type, "category": f.category, "engine": "regex"})
            for f in scanner_engine.classify_column(col, profile=profile, min_confidence=0.3):
                findings.append({"entity_type": f.entity_type, "category": f.category, "engine": "secret_scanner"})
            findings.sort(key=lambda f: (f["engine"], f["entity_type"]))
            fixtures["cases"].append({"id": case["id"], "text": case["text"], "findings": findings})

    (GENERATED_DIR / "fixtures.json").write_text(json.dumps(fixtures, indent=2))
    log.info("wrote fixtures.json (%d cases)", len(fixtures["cases"]))


def main() -> int:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    version = python_logic_version()
    emit_constants(version)
    emit_patterns()
    emit_secret_key_names()
    emit_stopwords()
    emit_placeholder_values()
    emit_fixtures(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
