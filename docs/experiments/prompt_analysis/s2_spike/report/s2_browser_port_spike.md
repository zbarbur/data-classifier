# S2 — Browser-port Feasibility Spike Findings

**Stage**: S2 from `docs/experiments/prompt_analysis/queue.md` §"Secret detection track"
**Date**: 2026-04-17
**Branch**: `research/prompt-analysis`
**Spec**: [`../SPEC.md`](../SPEC.md)
**Driver**: Browser PoC execution track (`sprint14/browser-poc-secret`) needs a
Path 1 vs Path 2 (re2-wasm) decision before committing to a regex implementation.

---

## TL;DR

We measured **77 content regex patterns** against an **11,000-prompt WildChat
corpus** (10K random + 1K longest) in headless Chrome via Playwright, ran ReDoS
audit via `recheck`, and measured esbuild+gzip bundle size.

**Headline numbers**:
- Per-prompt scan latency P99 = **0.70 ms** (all 77), **0.30 ms** (41 credential-only)
- Max latency = **2.50 ms** (all), **1.40 ms** (credential-only)
- ReDoS: **73 safe / 3 polynomial / 1 unknown** of 77 patterns
- Bundle gzipped: **2.44 KB** measured + **11.01 KB** projected validators =
  **13.45 KB** (target 200 KB)

**Path 1 (native JS RegExp) is a clear go.** 140x headroom under a 100ms budget
for all patterns, 333x for credential-only. No re2-wasm needed.

---

## Methodology

See [SPEC.md](../SPEC.md). Three reports drive this memo:
- [`perf.json`](./perf.json) — perf benchmark, full distribution + per-pattern max
- [`redos.json`](./redos.json) — recheck verdicts per pattern
- [`bundle.json`](./bundle.json) — esbuild + gzip + validator projection

**Corpus**: 11,000 prompts from WildChat-1M (local DVC parquet):
- 10,000 random (avg 420 chars, unbiased distribution)
- 1,000 longest (avg 3,318 chars, explicit tail stress)

**Pattern source**: `data_classifier/patterns/default_patterns.json` (77 patterns,
RE2-compatible syntax). 3 patterns used Python `(?i)` inline flags — extracted to
JS `"gi"` flags during translation. Zero patterns failed JS RegExp compilation.

**Three runs, representative = median-by-P99**. Cross-run stability: P99 =
(0.70, 0.70, 0.70) ms — fully deterministic.

---

## Perf results

### All 77 patterns

| Metric | Combined (11K) | Random (10K) | Long (1K) |
|---|---|---|---|
| P50 | 0.00 | 0.00 | 0.10 |
| P75 | 0.10 | 0.10 | 0.20 |
| P90 | 0.10 | 0.10 | 0.50 |
| P95 | 0.20 | 0.20 | 0.70 |
| P99 | **0.70** | 0.50 | 1.60 |
| P99.9 | 1.80 | 1.80 | 2.50 |
| max | **2.50** | 2.20 | 2.50 |
| mean | 0.07 | 0.05 | 0.22 |

### 41 credential patterns only (browser PoC scope)

| Metric | Combined (11K) | Random (10K) | Long (1K) |
|---|---|---|---|
| P50 | 0.00 | 0.00 | 0.10 |
| P75 | 0.00 | 0.00 | 0.10 |
| P90 | 0.10 | 0.10 | 0.20 |
| P95 | 0.10 | 0.10 | 0.40 |
| P99 | **0.30** | 0.20 | 0.70 |
| P99.9 | 1.00 | 0.90 | 1.40 |
| max | **1.40** | 1.30 | 1.40 |
| mean | 0.03 | 0.02 | 0.10 |

**Bundle parse time**: 0.10 ms to construct 77 RegExp instances (one-time cost).

**Heap delta**: 0 bytes reported (Chrome `performance.memory` returned 0 in this
Chromium build — informational, not a concern).

**Top 5 patterns by max latency**:

| # | Pattern | Category | Max ms |
|---|---|---|---|
| 1 | `random_password` | Credential | 0.60 |
| 2 | `us_ssn_formatted` | PII | 0.40 |
| 3 | `aws_secret_key` | Credential | 0.30 |
| 4 | `email_address` | PII | 0.30 |
| 5 | `credit_card_luhn` | Financial | 0.20 |

`random_password` is the slowest due to its broad character class (`\S{4,64}`),
but still sub-millisecond. It also has `requires_column_hint: true`, so it won't
fire in the browser PoC without a column-name context signal — effectively free
in the credential-only path.

**Long prompts are ~4x slower** (mean 0.22 ms vs 0.05 ms random), which is
expected — regex scan time is proportional to input length. But even the P99 of
the long bucket (1.60 ms) is 62x under a 100ms budget.

---

## ReDoS results

| Verdict | Count |
|---|---|
| safe | 73 |
| vulnerable (polynomial) | 3 |
| unknown | 1 |
| vulnerable (exponential) | 0 |

**No exponential patterns.** All 3 vulnerable patterns are polynomial:

| Pattern | Category | Complexity | Measured max ms | Attack string |
|---|---|---|---|---|
| `email_address` | PII | polynomial | 0.30 | `%_-%_-%_-...` (repeated) |
| `jwt_token` | Credential | polynomial | 0.10 | (long repeated token) |
| `discord_bot_token` | Credential | polynomial | 0.10 | (long repeated token) |

**Cross-reference with perf**: all 3 polynomial patterns are sub-0.3ms max on
real WildChat data. The polynomial complexity (O(n^k)) doesn't manifest at
real-world prompt lengths (~400-3,300 chars). The attack strings are synthetic
repeated patterns that don't appear in actual prompts.

**Unknown**: `us_ssn_formatted` (`\b\d{3}-\d{2}-\d{4}\b`) — `recheck` requires
a Java runtime for formal analysis, which wasn't installed. The pattern is
trivially safe by inspection (no quantifier nesting).

**Verdict**: no ReDoS risk in practice. The 3 polynomial patterns are candidates
for simplification as a code-quality measure, not a P1 fix.

---

## Bundle results

| Component | Raw (minified) | Gzipped | KB |
|---|---|---|---|
| Measured (patterns + entropy) | 12,581 bytes | 2,494 bytes | **2.44** |
| Projected validators (537 LOC × 0.7 × 30) | — | 11,277 bytes | **11.01** |
| **Projected total** | — | **13,771 bytes** | **13.45** |
| Target (queue.md) | — | 204,800 bytes | **200** |

**93% headroom** under the 200 KB budget. Even adding the full `secret_scanner`
dictionary (178 entries × ~50 bytes ≈ 9 KB) wouldn't approach the target.

---

## Cross-reference: perf-tail × ReDoS

The intersection of "top patterns by latency" and "recheck-flagged vulnerable" is:

| Pattern | In perf top-5? | In ReDoS vulnerable? |
|---|---|---|
| `random_password` | yes (0.60 ms) | no (safe) |
| `email_address` | yes (0.30 ms) | yes (polynomial) |
| `jwt_token` | no | yes (polynomial) |
| `discord_bot_token` | no | yes (polynomial) |

Only `email_address` appears in both lists, at 0.30 ms — a non-issue. The
slowest pattern (`random_password`) is ReDoS-safe.

**No pattern is both slow AND exponentially vulnerable.** This is the strongest
possible signal for Path 1 viability.

---

## Path decision support

Three threshold scenarios for the worker kill budget:

| Budget | Prompts killed (all 77) | Prompts killed (41 cred) | Verdict |
|---|---|---|---|
| 50 ms | 0 / 11K (0%) | 0 / 11K (0%) | Path 1 viable |
| 100 ms | 0 / 11K (0%) | 0 / 11K (0%) | Path 1 viable |
| 200 ms | 0 / 11K (0%) | 0 / 11K (0%) | Path 1 viable |

**At every tested threshold, zero prompts would be killed.** The maximum
observed latency (2.50 ms for all patterns, 1.40 ms for credential-only) is
orders of magnitude below any reasonable kill budget.

**Recommendation to execution track (sprint14/browser-poc-secret)**:

Ship **Path 1 — native JS RegExp** with the following:
1. All 77 patterns compile cleanly in JS with a trivial `(?i)` flag promotion.
2. No re2-wasm overhead needed (saves ~250 KB bundle + per-call marshaling cost).
3. Worker kill budget can be set generously (100ms) with zero expected kills.
4. The 3 polynomial patterns (`email_address`, `jwt_token`, `discord_bot_token`)
   can be optionally simplified as a code-quality measure — not required for v1.

---

## Filed follow-ups

### S2.5 — secret_scanner browser-port perf (backlog item)

Same harness, separate measurement. Port `parse_key_values` + entropy scoring +
178-entry `secret_key_names` dict lookup to JS, run on same 11K corpus, report
distribution. Given that regex scan takes <1ms, the overall budget question for
the worker is: "how much does secret_scanner add?"

### Polynomial pattern simplification (low priority)

The 3 polynomial patterns could be simplified to avoid theoretical ReDoS at
extreme input lengths:
- `email_address`: tighten the local-part regex
- `jwt_token`: anchor the base64 segments more strictly
- `discord_bot_token`: simplify alternation

Not blocking v1 — measured perf shows no real impact. File as Sprint 14+
code-quality item if desired.

---

## Artifact inventory

| File | Purpose |
|---|---|
| [`perf.json`](./perf.json) | Full latency distribution, per-pattern max, scatter |
| [`redos.json`](./redos.json) | recheck verdicts, attack strings for vulnerable patterns |
| [`bundle.json`](./bundle.json) | esbuild + gzip + validator projection |
| [`../corpus.jsonl`](../corpus.jsonl) | 11K-prompt corpus (gitignored, regenerable) |
| [`../patterns.js`](../patterns.js) | 77 JS-compiled patterns (committed) |
| [`../SPEC.md`](../SPEC.md) | S2 specification |
| [`../PLAN.md`](../PLAN.md) | Implementation plan |
