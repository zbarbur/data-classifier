# S3-A: Secretlint Pattern Mine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract 9 net-new credential patterns + 5 quality upgrades from secretlint (MIT), translate to RE2-compatible format, validate against the S2 11K WildChat corpus, and output ready-to-merge proposals.

**Architecture:** Manual curation, not automated extraction — secretlint patterns are TypeScript RegExp literals embedded inline. We extract, translate to RE2, add test examples + provenance, validate against corpus, and document. All artifacts go in `docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/`.

**Tech Stack:** Python (corpus validation via data_classifier engines), JSON (pattern schema), Markdown (memo).

**Baseline patterns on `main`:** 79 patterns (77 on this branch + 2 from Sprint 13: `openai_legacy_key`, `anthropic_api_key`). Proposals must not duplicate anything on main.

**Secretlint provenance:** commit `3e58badf8f8b` (2026-04-14), MIT license.

---

## File Structure

All files under `docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/`:

| File | Purpose | Task |
|---|---|---|
| `s3a_proposed_patterns.json` | 9 net-new patterns in default_patterns.json schema | 1 |
| `s3a_proposed_upgrades.json` | 5 upgrade diffs to existing patterns | 2 |
| `s3a_provenance.json` | Per-pattern attribution (source rule, SHA, license) | 3 |
| `validate_proposals.py` | Script to run proposals against S2 corpus | 4 |
| `s3a_corpus_validation.json` | Hit counts + FP estimates | 4 |
| `s3a_gap_analysis.md` | Decision memo for each pattern | 5 |

---

## Task 1: Write 9 net-new proposed patterns

**Files:**
- Create: `docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/s3a_proposed_patterns.json`

- [ ] **Step 1: Create the proposed patterns file**

Write `s3a_proposed_patterns.json` with these 9 patterns. Each follows the `default_patterns.json` schema exactly — ready to copy-paste into the main file.

```json
{
  "_metadata": {
    "source": "secretlint (MIT)",
    "source_commit": "3e58badf8f8b",
    "pulled_date": "2026-04-17",
    "translator": "S3-A research session",
    "notes": "RE2-translated from secretlint TypeScript rule packages"
  },
  "patterns": [
    {
      "name": "grafana_cloud_api_token",
      "regex": "\\bglc_[A-Za-z0-9+/]{32,400}={0,2}",
      "entity_type": "API_KEY",
      "category": "Credential",
      "sensitivity": "CRITICAL",
      "confidence": 0.95,
      "description": "Grafana Cloud API token (glc_ prefix, base64 JWT body)",
      "validator": "",
      "examples_match": ["glc_eyJvIjoiOTk0NjQyIiwibiI6InRlc3Qtc3RhY2stMTIzIiwiayI6InRlc3QxMjM0NTY3ODkwIiwibSI6eyJyIjoicHJvZC11cy1lYXN0LTAifX0="],
      "examples_no_match": ["glc_short", "glc_"],
      "context_words_boost": ["grafana", "cloud", "api_key", "GRAFANA_API_KEY"],
      "context_words_suppress": [],
      "stopwords": [],
      "allowlist_patterns": [],
      "requires_column_hint": false,
      "column_hint_keywords": []
    },
    {
      "name": "grafana_service_account_token",
      "regex": "\\bglsa_[A-Za-z0-9]{32}_[A-Fa-f0-9]{8}\\b",
      "entity_type": "API_KEY",
      "category": "Credential",
      "sensitivity": "CRITICAL",
      "confidence": 0.95,
      "description": "Grafana service account token (glsa_ prefix, 32 alnum + 8 hex checksum)",
      "validator": "",
      "examples_match": ["glsa_HOGlSAQHRfpHijLw27eeNE38mR04Bf2abcdef12"],
      "examples_no_match": ["glsa_tooshort_abcdef12", "glsa_HOGlSAQHRfpHijLw27eeNE38mR04Bf_not8hex"],
      "context_words_boost": ["grafana", "service_account"],
      "context_words_suppress": [],
      "stopwords": [],
      "allowlist_patterns": [],
      "requires_column_hint": false,
      "column_hint_keywords": []
    },
    {
      "name": "docker_hub_pat",
      "regex": "\\bdckr_pat_[a-zA-Z0-9_-]{27}\\b",
      "entity_type": "API_KEY",
      "category": "Credential",
      "sensitivity": "CRITICAL",
      "confidence": 0.95,
      "description": "Docker Hub personal access token (dckr_pat_ prefix, 27 chars, fixed length)",
      "validator": "",
      "examples_match": ["xor:PjkxKAUqOy4FOzg5Pj88PTIzMDE2NzQ1KisoKS4vLC0iIyBq"],
      "examples_no_match": ["dckr_pat_short", "dckr_pat_"],
      "context_words_boost": ["docker", "registry", "DOCKER_TOKEN"],
      "context_words_suppress": [],
      "stopwords": [],
      "allowlist_patterns": [],
      "requires_column_hint": false,
      "column_hint_keywords": []
    },
    {
      "name": "linear_api_token",
      "regex": "\\blin_api_[a-zA-Z0-9_]{32,128}\\b",
      "entity_type": "API_KEY",
      "category": "Credential",
      "sensitivity": "CRITICAL",
      "confidence": 0.95,
      "description": "Linear API token (lin_api_ prefix)",
      "validator": "",
      "examples_match": ["lin_api_WKLAsLwFrFDHdFdFm03gdRafFNDJdVaH"],
      "examples_no_match": ["lin_api_short", "lin_oauth_something"],
      "context_words_boost": ["linear", "api_key", "LINEAR_API_KEY"],
      "context_words_suppress": [],
      "stopwords": [],
      "allowlist_patterns": [],
      "requires_column_hint": false,
      "column_hint_keywords": []
    },
    {
      "name": "groq_api_key",
      "regex": "\\bgsk_[a-zA-Z0-9]{52}\\b",
      "entity_type": "API_KEY",
      "category": "Credential",
      "sensitivity": "CRITICAL",
      "confidence": 0.95,
      "description": "Groq API key (gsk_ prefix, 52 alphanumeric, fixed length)",
      "validator": "",
      "examples_match": ["gsk_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwx"],
      "examples_no_match": ["gsk_short", "gsk_"],
      "context_words_boost": ["groq", "api_key", "GROQ_API_KEY"],
      "context_words_suppress": [],
      "stopwords": [],
      "allowlist_patterns": [],
      "requires_column_hint": false,
      "column_hint_keywords": []
    },
    {
      "name": "onepassword_service_token",
      "regex": "\\bops_ey[A-Za-z0-9+/=]{100,1280}",
      "entity_type": "API_KEY",
      "category": "Credential",
      "sensitivity": "CRITICAL",
      "confidence": 0.90,
      "description": "1Password service account token (ops_ prefix, base64 JSON body starting with ey)",
      "validator": "",
      "examples_match": ["ops_eyJvIjoiOTk0NjQyIiwibiI6InRlc3Qtc3RhY2stMTIzIiwiayI6InRlc3QxMjM0NTY3ODkwMTIzNDU2Nzg5MCIsIm0iOnsiciI6InByb2QtdXMtZWFzdC0wIiwidCI6InRlc3QifX0=abcdefghijklmnopqrstuvwxyz"],
      "examples_no_match": ["ops_notbase64", "ops_ey_short"],
      "context_words_boost": ["1password", "onepassword", "service_account", "OPS_TOKEN"],
      "context_words_suppress": [],
      "stopwords": [],
      "allowlist_patterns": [],
      "requires_column_hint": false,
      "column_hint_keywords": []
    },
    {
      "name": "notion_integration_token",
      "regex": "\\bntn_[0-9]{11}[A-Za-z0-9]{35}\\b",
      "entity_type": "API_KEY",
      "category": "Credential",
      "sensitivity": "CRITICAL",
      "confidence": 0.95,
      "description": "Notion integration token (ntn_ prefix, 11 digits + 35 alnum, fixed length)",
      "validator": "",
      "examples_match": ["ntn_12345678901ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg"],
      "examples_no_match": ["ntn_short", "ntn_notdigits_then_alnum"],
      "context_words_boost": ["notion", "integration", "NOTION_TOKEN"],
      "context_words_suppress": [],
      "stopwords": [],
      "allowlist_patterns": [],
      "requires_column_hint": false,
      "column_hint_keywords": []
    },
    {
      "name": "figma_pat",
      "regex": "\\bfigd_[A-Za-z0-9_-]{40,200}\\b",
      "entity_type": "API_KEY",
      "category": "Credential",
      "sensitivity": "CRITICAL",
      "confidence": 0.95,
      "description": "Figma personal access token (figd_ prefix)",
      "validator": "",
      "examples_match": ["figd_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop"],
      "examples_no_match": ["figd_short", "figd_"],
      "context_words_boost": ["figma", "FIGMA_TOKEN"],
      "context_words_suppress": [],
      "stopwords": [],
      "allowlist_patterns": [],
      "requires_column_hint": false,
      "column_hint_keywords": []
    },
    {
      "name": "basicauth_url",
      "regex": "https?://[a-zA-Z0-9_-]{2,256}:[a-zA-Z0-9_-]{4,256}@[a-zA-Z0-9%._+~#=-]{1,256}\\.[a-zA-Z0-9()]{1,6}",
      "entity_type": "API_KEY",
      "category": "Credential",
      "sensitivity": "HIGH",
      "confidence": 0.80,
      "description": "HTTP Basic Auth credentials embedded in URL (user:password@host)",
      "validator": "not_placeholder_credential",
      "examples_match": ["https://admin:s3cretP4ss@api.example.com"],
      "examples_no_match": ["https://user:password@example.com", "https://localhost:8080/path"],
      "context_words_boost": ["url", "endpoint", "connection"],
      "context_words_suppress": [],
      "stopwords": ["password", "YOUR_PASSWORD", "changeme", "xxx"],
      "allowlist_patterns": ["\\$\\{", "\\{\\{", "<%="],
      "requires_column_hint": false,
      "column_hint_keywords": []
    }
  ]
}
```

- [ ] **Step 2: Verify all patterns compile in RE2**

```bash
cd /Users/guyguzner/Projects/data_classifier-prompt-analysis
.venv/bin/python -c "
import json, re2
data = json.load(open('docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/s3a_proposed_patterns.json'))
for p in data['patterns']:
    try:
        re2.compile(p['regex'])
        print(f'  OK: {p[\"name\"]}')
    except Exception as e:
        print(f'FAIL: {p[\"name\"]}: {e}')
"
```

Expected: all 9 patterns print `OK`. If any fail, fix the RE2 syntax (likely lookahead/lookbehind issues).

**Fallback if re2 module not available:** use Python `re` — our patterns are RE2-compatible by policy, and `re` accepts a superset.

```bash
.venv/bin/python -c "
import json, re
data = json.load(open('docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/s3a_proposed_patterns.json'))
for p in data['patterns']:
    try:
        re.compile(p['regex'])
        print(f'  OK: {p[\"name\"]}')
    except Exception as e:
        print(f'FAIL: {p[\"name\"]}: {e}')
"
```

- [ ] **Step 3: Commit**

```bash
git add docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/s3a_proposed_patterns.json
git commit -m "research(s3a): 9 net-new credential patterns from secretlint (proposed)"
```

---

## Task 2: Write 5 quality upgrade proposals

**Files:**
- Create: `docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/s3a_proposed_upgrades.json`

- [ ] **Step 1: Read current patterns on main**

Run to get the exact current regexes from `main` (not this branch — Sprint 13 added 2 patterns):

```bash
cd /Users/guyguzner/Projects/data_classifier-prompt-analysis
git show origin/main:data_classifier/patterns/default_patterns.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
targets = ['github_token', 'slack_bot_token', 'slack_user_token', 'slack_webhook_url',
           'openai_api_key', 'openai_legacy_key', 'hashicorp_vault_token', 'huggingface_token']
for p in data['patterns']:
    if p['name'] in targets:
        print(f'{p[\"name\"]}: {p[\"regex\"][:120]}')
"
```

Record the output — you'll need it for the diffs.

- [ ] **Step 2: Create the upgrades file**

Write `s3a_proposed_upgrades.json`. Each entry has `name`, `current_regex` (from main), `proposed_regex`, `change_description`, and `secretlint_reference`.

```json
{
  "_metadata": {
    "source": "secretlint (MIT)",
    "source_commit": "3e58badf8f8b",
    "notes": "Proposed upgrades to existing patterns based on secretlint coverage gaps"
  },
  "upgrades": [
    {
      "name": "github_token",
      "current_regex": "\\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36}\\b",
      "proposed_regex": "\\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36}\\b|\\bgithub_pat_[A-Za-z0-9_]{82}\\b",
      "change_description": "Add fine-grained PAT format (github_pat_ prefix, 82-char body). Classic tokens unchanged.",
      "new_examples_match": ["github_pat_11ABCDEF0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ab"],
      "secretlint_reference": "secretlint-rule-github"
    },
    {
      "name": "slack_bot_token",
      "current_regex": "\\bxoxb-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,}\\b",
      "proposed_regex": "\\b(?:xoxb|xoxp|xapp|xoxa|xoxo|xoxr)-(?:[0-9]+-)?[a-zA-Z0-9]{1,40}(?:-[a-zA-Z0-9]{1,40})*\\b",
      "change_description": "Unify all Slack token prefixes (xoxb/xoxp/xapp/xoxa/xoxo/xoxr) into one pattern. Current patterns split bot/user and miss xapp/xoxa/xoxr entirely. Consider renaming to 'slack_token' and retiring 'slack_user_token'.",
      "new_examples_match": ["xapp-1-A0123456789-1234567890-abcdefabcdef", "xoxa-2-abcdef1234", "xoxr-refresh-token-value"],
      "secretlint_reference": "secretlint-rule-slack"
    },
    {
      "name": "openai_api_key",
      "current_regex": "\\bsk-proj-[a-zA-Z0-9\\-_]{80,}\\b",
      "proposed_regex": "\\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{58,80}T3BlbkFJ[A-Za-z0-9_-]{58,80}\\b",
      "change_description": "Add svcacct and admin prefixes + require T3BlbkFJ magic bytes (base64 of 'OpenAI') for new-format keys. Legacy sk-* already covered by openai_legacy_key (Sprint 13). Verify: current regex may already match svcacct/admin if they share the sk-proj format.",
      "new_examples_match": [],
      "secretlint_reference": "secretlint-rule-openai",
      "note": "VERIFY on main first — Sprint 13 may have broadened this. If sk-proj already matches svcacct/admin, only the T3BlbkFJ tightening is needed."
    },
    {
      "name": "hashicorp_vault_token",
      "current_regex": "\\bhvs\\.[A-Za-z0-9_-]{24,}\\b",
      "proposed_regex": "\\b(?:hvs|hvb|hvr)\\.[A-Za-z0-9_-]{24,}\\b",
      "change_description": "Add hvb (batch tokens, 138-300 chars) and hvr (recovery tokens, 90-120 chars) prefixes. Current regex only matches hvs (service tokens).",
      "new_examples_match": ["xor:Miw4dBsbGxsbCxAwAzcUMxdoDDYWDRNvFx4xLhQeMjEXM2pvAB0UMhYONjYDMD1qFzcMMRcgPW8UPRsbGxgyIwANHDECaGMvOBI2PAMCGC0CaRAsOB0MPDsNCw==", "xor:MiwodBkbHwkTChZqNzlvHD8AFxMUHBgvIA0L"],
      "secretlint_reference": "secretlint-rule-hashicorp-vault"
    },
    {
      "name": "huggingface_token",
      "current_regex": "\\bhf_[A-Za-z0-9]{20,}\\b",
      "proposed_regex": "\\bhf_[a-zA-Z]{34}\\b",
      "change_description": "Tighten: secretlint says HF tokens are exactly 34 alpha-only chars (no digits). Current regex is loose (20+ alphanumeric). Tighter regex reduces FPs. VERIFY: check real HF tokens to confirm alpha-only claim before adopting.",
      "new_examples_match": ["xor:MjwFOzg5Pj88PTIzMDE2NzQ1KisoKS4vLC0iIyAbGBkeHxwdEg=="],
      "secretlint_reference": "secretlint-rule-huggingface",
      "note": "VERIFY alpha-only claim. If real tokens include digits, keep current regex but add length constraint."
    }
  ]
}
```

- [ ] **Step 3: Commit**

```bash
git add docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/s3a_proposed_upgrades.json
git commit -m "research(s3a): 5 quality upgrades to existing patterns (proposed)"
```

---

## Task 3: Write provenance records

**Files:**
- Create: `docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/s3a_provenance.json`

- [ ] **Step 1: Create provenance file**

```json
{
  "source": {
    "name": "secretlint",
    "repo": "https://github.com/secretlint/secretlint",
    "license": "MIT",
    "commit_sha": "3e58badf8f8b",
    "commit_date": "2026-04-14",
    "pulled_date": "2026-04-17"
  },
  "patterns": [
    {"name": "grafana_cloud_api_token", "source_rule": "@secretlint/secretlint-rule-grafana", "type": "new"},
    {"name": "grafana_service_account_token", "source_rule": "@secretlint/secretlint-rule-grafana", "type": "new"},
    {"name": "docker_hub_pat", "source_rule": "@secretlint/secretlint-rule-docker", "type": "new"},
    {"name": "linear_api_token", "source_rule": "@secretlint/secretlint-rule-linear", "type": "new"},
    {"name": "groq_api_key", "source_rule": "@secretlint/secretlint-rule-groq", "type": "new"},
    {"name": "onepassword_service_token", "source_rule": "@secretlint/secretlint-rule-1password", "type": "new"},
    {"name": "notion_integration_token", "source_rule": "@secretlint/secretlint-rule-notion", "type": "new"},
    {"name": "figma_pat", "source_rule": "@secretlint/secretlint-rule-figma", "type": "new"},
    {"name": "basicauth_url", "source_rule": "@secretlint/secretlint-rule-basicauth", "type": "new"},
    {"name": "github_token", "source_rule": "@secretlint/secretlint-rule-github", "type": "upgrade"},
    {"name": "slack_bot_token", "source_rule": "@secretlint/secretlint-rule-slack", "type": "upgrade"},
    {"name": "openai_api_key", "source_rule": "@secretlint/secretlint-rule-openai", "type": "upgrade"},
    {"name": "hashicorp_vault_token", "source_rule": "@secretlint/secretlint-rule-hashicorp-vault", "type": "upgrade"},
    {"name": "huggingface_token", "source_rule": "@secretlint/secretlint-rule-huggingface", "type": "upgrade"}
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/s3a_provenance.json
git commit -m "research(s3a): provenance records for 14 proposed patterns"
```

---

## Task 4: Validate proposals against S2 corpus

**Files:**
- Create: `docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/validate_proposals.py`
- Output: `docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/s3a_corpus_validation.json`

- [ ] **Step 1: Create validation script**

```python
"""Validate S3-A proposed patterns against the S2 11K WildChat corpus.

For each proposed pattern: count hits, sample matches for manual FP review.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

from data_classifier.patterns._decoder import _XOR_KEY  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("s3a_validate")

SPIKE_DIR = Path(__file__).parent.parent.parent / "s2_spike"
CORPUS = SPIKE_DIR / "corpus.jsonl"
PROPOSALS = Path(__file__).parent / "s3a_proposed_patterns.json"
OUT = Path(__file__).parent / "s3a_corpus_validation.json"


def xor_decode(s: str) -> str:
    b64 = s.removeprefix("xor:")
    raw = base64.b64decode(b64)
    return bytes(b ^ _XOR_KEY for b in raw).decode("utf-8")


def main() -> None:
    corpus = [json.loads(line) for line in CORPUS.read_text().splitlines()]
    proposals = json.load(PROPOSALS.open())["patterns"]
    log.info("corpus: %d prompts, proposals: %d patterns", len(corpus), len(proposals))

    # Compile patterns
    compiled = []
    for p in proposals:
        try:
            compiled.append((p["name"], re.compile(p["regex"]), p))
        except re.error as e:
            log.error("SKIP %s: %s", p["name"], e)

    results = {}
    t0 = time.time()
    for name, regex, meta in compiled:
        hits = 0
        samples = []
        for rec in corpus:
            text = xor_decode(rec["text_xor"])
            matches = list(regex.finditer(text))
            if matches:
                hits += 1
                if len(samples) < 5:
                    samples.append({
                        "fingerprint": rec["sha256"],
                        "length": rec["length"],
                        "bucket": rec["bucket"],
                        "match_count": len(matches),
                        "first_match_snippet": text[max(0, matches[0].start()-20):matches[0].end()+20][:100],
                    })
        results[name] = {
            "hits": hits,
            "hit_rate_pct": round(hits / len(corpus) * 100, 4),
            "samples": samples,
        }
        log.info("  %s: %d hits (%.4f%%)", name, hits, hits / len(corpus) * 100)

    elapsed = time.time() - t0
    out = {
        "corpus_size": len(corpus),
        "pattern_count": len(compiled),
        "elapsed_seconds": round(elapsed, 1),
        "results": results,
    }
    OUT.write_text(json.dumps(out, indent=2))
    log.info("wrote %s in %.1fs", OUT, elapsed)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run validation**

```bash
cd /Users/guyguzner/Projects/data_classifier-prompt-analysis
.venv/bin/python docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/validate_proposals.py
```

Expected: prints per-pattern hit counts. Most credential patterns should have 0-5 hits on 11K random WildChat prompts (credentials are rare — S0 found 0.12% rate). If any pattern has >1% hit rate, it's likely a FP problem — investigate the samples.

**Key thresholds:**
- 0-10 hits: normal for credential patterns on 11K prompts
- 10-50 hits: review samples — could be real (common credential type) or FP
- 50+ hits: almost certainly FP — tighten the regex or add a validator
- `basicauth_url` may have more hits since it's a generic URL pattern — check if `not_placeholder_credential` validator would filter the FPs

- [ ] **Step 3: Review samples for any high-hit patterns**

If any pattern has >10 hits, manually inspect the `samples` in `s3a_corpus_validation.json`:
- Are the matches real credentials? (True positives — great)
- Are they placeholder values? (Add to stopwords or allowlist_patterns)
- Are they structural FPs? (Tighten regex)

Update `s3a_proposed_patterns.json` if needed based on review.

- [ ] **Step 4: Commit**

```bash
git add docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/validate_proposals.py docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/s3a_corpus_validation.json
git commit -m "research(s3a): corpus validation — N hits across 9 patterns on 11K WildChat (replace N)"
```

---

## Task 5: Write gap analysis memo

**Files:**
- Create: `docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/s3a_gap_analysis.md`

- [ ] **Step 1: Write the memo**

Structure:

```markdown
# S3-A — Secretlint Pattern Mine: Gap Analysis

**Date**: 2026-04-17
**Source**: secretlint (MIT), commit 3e58badf8f8b
**Branch**: research/prompt-analysis

## Summary

- Secretlint has 27 rule packages covering N credential types
- 16 services already covered by our 79 patterns (on main)
- **9 net-new patterns proposed** (see s3a_proposed_patterns.json)
- **5 quality upgrades proposed** (see s3a_proposed_upgrades.json)
- Corpus validation: N total hits on 11K WildChat corpus

## Net-new patterns (9)

[For each pattern: one paragraph explaining the service, the token format,
our regex translation, confidence level, and corpus validation result.]

### 1. grafana_cloud_api_token / grafana_service_account_token
[...]

### 2. docker_hub_pat
[...]

[...continue for all 9...]

## Quality upgrades (5)

[For each: what's currently on main, what we propose, why.]

### 1. github_token — add fine-grained PATs
[...]

[...continue for all 5...]

## Patterns NOT proposed (with rationale)

- **GCP JSON key detection**: file-level structural detection, not text regex.
  Out of scope for our regex engine.
- **secp256k1 private key**: requires cryptographic validation library.
  Not recommended preset in secretlint either.
- **K8s Secret manifests**: YAML structural detection. Out of scope.
- **Azure tenant_id / client_id**: GUIDs are identifiers not secrets.
  client_secret IS proposed (via basicauth_url or secret_scanner heuristic).

## Verification items for main PR

- [ ] Verify HuggingFace alpha-only claim with real token
- [ ] Verify OpenAI svcacct/admin prefix format matches proposed regex
- [ ] Check basicauth_url FP rate — may need tighter validator
- [ ] Decide: merge slack_bot_token + slack_user_token into unified slack_token?

## Next: S3-B (detect-secrets)
[Brief note on what detect-secrets might add beyond secretlint coverage.]
```

Fill all sections with real data from the corpus validation and pattern analysis. No `[...]` placeholders in the final document.

- [ ] **Step 2: Commit**

```bash
git add docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/s3a_gap_analysis.md
git commit -m "research(s3a): gap analysis memo — 9 new + 5 upgrades from secretlint"
```

---

## Task 6: Final commit + push

- [ ] **Step 1: Verify all artifacts exist**

```bash
ls -la docs/experiments/prompt_analysis/s3_pattern_mine/s3a_secretlint/
```

Expected files: `s3a_proposed_patterns.json`, `s3a_proposed_upgrades.json`, `s3a_provenance.json`, `validate_proposals.py`, `s3a_corpus_validation.json`, `s3a_gap_analysis.md`

- [ ] **Step 2: Push**

```bash
git push origin research/prompt-analysis
```

---

## Self-review checklist

- [ ] 9 patterns in proposed_patterns.json, all compile in RE2/Python re
- [ ] 5 upgrades in proposed_upgrades.json with current + proposed regex
- [ ] Provenance for all 14 entries (9 new + 5 upgrades)
- [ ] Corpus validation run, results in s3a_corpus_validation.json
- [ ] Gap analysis memo has zero `[...]` or `<placeholder>` strings
- [ ] No raw credential values in any committed file (XOR-encode if needed)
- [ ] All commits on research/prompt-analysis, pushed to origin
