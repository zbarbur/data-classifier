"""Promote S3 pattern-mining proposals into the library.

Reads all s3*/proposed_*.json files, deduplicates, fills missing fields
with defaults, applies upgrades, and writes updated default_patterns.json
and secret_key_names.json.

Usage: python3 scripts/promote_s3_patterns.py [--dry-run]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PATTERNS_FILE = REPO_ROOT / "data_classifier" / "patterns" / "default_patterns.json"
KEYNAMES_FILE = REPO_ROOT / "data_classifier" / "patterns" / "secret_key_names.json"
S3_DIR = REPO_ROOT / "docs" / "experiments" / "prompt_analysis" / "s3_pattern_mine"

# Default values for fields missing in lean s3e proposals
PATTERN_DEFAULTS = {
    "sensitivity": "CRITICAL",
    "context_words_boost": [],
    "context_words_suppress": [],
    "stopwords": [],
    "allowlist_patterns": [],
    "requires_column_hint": False,
    "column_hint_keywords": [],
}

# Canonical field order for patterns
PATTERN_FIELD_ORDER = [
    "name", "regex", "entity_type", "category", "sensitivity", "confidence",
    "description", "validator", "examples_match", "examples_no_match",
    "context_words_boost", "context_words_suppress", "stopwords",
    "allowlist_patterns", "requires_column_hint", "column_hint_keywords",
]


def load_proposals(subdir: str, filename: str) -> list[dict]:
    """Load a proposals JSON file from an s3* subdirectory."""
    path = S3_DIR / subdir / filename
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data.get("patterns", data.get("upgrades", data.get("key_names", [])))


def normalize_pattern(p: dict) -> dict:
    """Fill missing fields with defaults and ensure canonical order."""
    out = {}
    for field in PATTERN_FIELD_ORDER:
        if field in p:
            out[field] = p[field]
        elif field in PATTERN_DEFAULTS:
            out[field] = PATTERN_DEFAULTS[field]
        # else: field like 'validator' should already be present
    # Copy any extra fields not in canonical order
    for k, v in p.items():
        if k not in out and k not in ("examples_match", "examples_no_match",
                                       "gitleaks_rules", "gitleaks_rule",
                                       "source", "note"):
            out[k] = v
    return out


def main():
    dry_run = "--dry-run" in sys.argv

    # --- Load current state ---
    patterns_data = json.loads(PATTERNS_FILE.read_text())
    existing_patterns = patterns_data["patterns"]
    existing_names = {p["name"] for p in existing_patterns}

    keynames_data = json.loads(KEYNAMES_FILE.read_text())
    existing_keynames = keynames_data["key_names"]
    existing_kn_patterns = {e["pattern"] for e in existing_keynames}

    print(f"Current state: {len(existing_patterns)} patterns, {len(existing_keynames)} key-names\n")

    # --- Collect new patterns from all streams ---
    new_pattern_sources = [
        ("s3a_secretlint", "s3a_proposed_patterns.json"),
        ("s3b_detect_secrets", "s3b_proposed_patterns.json"),
        ("s3c_provider_docs", "s3c_proposed_patterns.json"),
        ("s3e_gitleaks_completeness", "s3e_proposed_patterns.json"),
        ("s3f_remaining_sources", "s3f_proposed_patterns.json"),
        ("s3g_provider_keywords", "s3g_proposed_patterns.json"),
    ]

    all_new = []
    for subdir, filename in new_pattern_sources:
        proposals = load_proposals(subdir, filename)
        print(f"  {subdir}: {len(proposals)} proposed patterns")
        all_new.extend(proposals)

    # Dedup by name — keep first occurrence (earlier streams are higher quality)
    seen_names: set[str] = set()
    deduped: list[dict] = []
    dupes: list[str] = []
    for p in all_new:
        name = p["name"]
        if name in existing_names:
            dupes.append(f"  SKIP (exists): {name}")
            continue
        if name in seen_names:
            dupes.append(f"  SKIP (cross-stream dupe): {name}")
            continue
        seen_names.add(name)
        deduped.append(normalize_pattern(p))

    print(f"\n  New patterns after dedup: {len(deduped)}")
    if dupes:
        print(f"  Skipped ({len(dupes)}):")
        for d in dupes:
            print(d)

    # --- Collect upgrades ---
    upgrade_sources = [
        ("s3a_secretlint", "s3a_proposed_upgrades.json"),
        ("s3b_detect_secrets", "s3b_proposed_upgrades.json"),
    ]

    all_upgrades = []
    for subdir, filename in upgrade_sources:
        upgrades = load_proposals(subdir, filename)
        print(f"\n  {subdir} upgrades: {len(upgrades)}")
        all_upgrades.extend(upgrades)

    # Apply upgrades
    applied = 0
    skipped_upgrades = []
    for u in all_upgrades:
        name = u["name"]
        note = u.get("note", "")
        if "VERIFY" in note.upper():
            skipped_upgrades.append(f"  DEFERRED (needs verification): {name} — {note}")
            continue
        # Find existing pattern
        target = None
        for p in existing_patterns:
            if p["name"] == name:
                target = p
                break
        if target is None:
            skipped_upgrades.append(f"  SKIP (not found): {name}")
            continue
        target["regex"] = u["proposed_regex"]
        if u.get("new_examples_match"):
            target.setdefault("examples_match", []).extend(u["new_examples_match"])
        applied += 1
        print(f"  UPGRADED: {name} — {u.get('change_description', '')[:80]}")

    if skipped_upgrades:
        print(f"\n  Deferred upgrades ({len(skipped_upgrades)}):")
        for s in skipped_upgrades:
            print(s)

    # --- Collect new keywords ---
    new_kw_sources = [
        ("s3e_gitleaks_completeness", "s3e_proposed_keywords.json"),
        ("s3g_provider_keywords", "s3g_proposed_keywords.json"),
    ]

    all_new_kw = []
    for subdir, filename in new_kw_sources:
        path = S3_DIR / subdir / filename
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        kws = data.get("proposed_keywords", data.get("key_names", []))
        print(f"\n  {subdir} keywords: {len(kws)}")
        all_new_kw.extend(kws)

    # Dedup keywords by pattern
    seen_kw: set[str] = set()
    new_keywords: list[dict] = []
    kw_dupes: list[str] = []
    for kw in all_new_kw:
        pat = kw["pattern"]
        if pat in existing_kn_patterns:
            kw_dupes.append(f"  SKIP (exists): {pat}")
            continue
        if pat in seen_kw:
            kw_dupes.append(f"  SKIP (cross-stream dupe): {pat}")
            continue
        seen_kw.add(pat)
        # Ensure canonical fields
        new_keywords.append({
            "pattern": kw["pattern"],
            "score": kw["score"],
            "category": kw.get("category", "Credential"),
            "match_type": kw.get("match_type", "substring"),
            "tier": kw["tier"],
            "subtype": kw.get("subtype", "OPAQUE_SECRET"),
        })

    print(f"\n  New keywords after dedup: {len(new_keywords)}")
    if kw_dupes:
        print(f"  Keyword skips ({len(kw_dupes)}):")
        for d in kw_dupes:
            print(d)

    # --- Summary ---
    print(f"\n{'='*60}")
    print(f"SUMMARY:")
    print(f"  Patterns: {len(existing_patterns)} → {len(existing_patterns) + len(deduped)} (+{len(deduped)} new)")
    print(f"  Upgrades applied: {applied} (deferred: {len(skipped_upgrades)})")
    print(f"  Key-names: {len(existing_keynames)} → {len(existing_keynames) + len(new_keywords)} (+{len(new_keywords)} new)")
    print(f"{'='*60}")

    if dry_run:
        print("\n  --dry-run: no files written")
        return 0

    # --- Write updated files ---
    # Add new patterns (sorted alphabetically within credential category)
    existing_patterns.extend(deduped)
    # Sort: non-credential first (preserve order), then credential alphabetically
    non_cred = [p for p in existing_patterns if p["category"] != "Credential"]
    cred = sorted(
        [p for p in existing_patterns if p["category"] == "Credential"],
        key=lambda p: p["name"],
    )
    patterns_data["patterns"] = non_cred + cred
    PATTERNS_FILE.write_text(json.dumps(patterns_data, indent=2, ensure_ascii=False) + "\n")
    print(f"\n  Wrote {PATTERNS_FILE.name}: {len(patterns_data['patterns'])} patterns")

    # Add new keywords (sorted by pattern name)
    existing_keynames.extend(new_keywords)
    existing_keynames.sort(key=lambda e: e["pattern"])
    keynames_data["key_names"] = existing_keynames
    KEYNAMES_FILE.write_text(json.dumps(keynames_data, indent=2, ensure_ascii=False) + "\n")
    print(f"  Wrote {KEYNAMES_FILE.name}: {len(keynames_data['key_names'])} key-names")

    return 0


if __name__ == "__main__":
    sys.exit(main())
