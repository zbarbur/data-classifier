# Schema Prior — Consumer Foundation

> **Status:** Spec draft, pending sprint allocation
> **Target sprint:** Sprint 10 (tentative)
> **Complexity:** M (7 person-days estimated)
> **Dependencies:** None — fully decoupled from BQ connector work

## Context

The column-name engine today uses a hand-curated dictionary of ~600 variants mapped to 35 entity types (`data_classifier/patterns/column_names.json`). Each entity type has a single curator-assigned confidence (0.70–0.95). Matching is normalization + abbreviation expansion + multi-token subsequence. Authority in the cascade is 10 — highest.

This plan introduces a **schema prior**: a per-column probability distribution over entity types, sourced from richer metadata (org / folder / dataset / table / column / data_type / table description), that content engines (starting with regex) consume to adjust their per-pattern thresholds at classification time. The prior is produced offline by a future LLM-based scanner and persisted as a YAML profile; this plan **only** builds the consumer side, not the scanner.

Consumer-first is a deliberate de-risking choice: the mechanism is validated against **hand-written priors** with zero LLM variance in the measurement, so a disappointing F1 result cleanly attributes to the mechanism rather than to noisy LLM output.

## Objective

Enable the regex engine to adjust its per-pattern confidence thresholds based on an optional `SchemaPrior` attached to each `ColumnInput`, without breaking any existing caller. Ship feature-flagged off by default. Produce a sprint benchmark report with an explicit go/no-go recommendation for the Sprint N+1 scanner investment.

## Scope

### In scope
- YAML profile format specification (v1) + loader + validator
- `ColumnInput.schema_prior` optional field
- `classify_columns(schema_profile=...)` optional parameter
- Transfer function module — core threshold-adjustment behavior
- Regex engine consumes prior; adjusts per-pattern thresholds
- Feature flag (env var + explicit parameter)
- Hand-written test priors covering the four benchmark cases
- Benchmark harness with four-case decomposition
- Sprint benchmark report with kill-switch decision
- BQ coordination doc (artifact only — no BQ code changes)

### Out of scope (deferred)
- LLM schema scanner (the producer) — Sprint N+1 candidate
- BQ connector integration — driven by BQ team's own timeline
- Heuristic / secret-scanner / GLiNER2 consumption of priors
- Profile versioning beyond v1 (version field present, no v2 yet)
- Column-name engine changes — priors complement, never replace

## Locked Design Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Consumer before producer** | Measurement purity; mechanism can be killed cheaply if transfer function doesn't move F1; hand-written priors remove LLM variance from measurement |
| 2 | **Regex engine only in v1** | Clean signal attribution; avoids ML-engine calibration rabbit hole; additive and expandable later |
| 3 | **Prior as per-pattern threshold adjustment (Option 3)** | Tunable via a single transfer function; no new merge logic; backwards-compatible |
| 4 | **Scanner will use HTTP-only OpenAI-compatible calls (no SDK, no extras)** | Decision fixed now so the YAML format and plumbing match; actual implementation is next sprint. Zero new core deps; works with Anthropic, OpenAI, Ollama, llama.cpp server, vLLM |
| 5 | **BQ coordination via doc only** | Library ships independently; BQ team drives their own integration timeline |

## The Four Benchmark Cases

Every benchmark result must be decomposed into these four cases. Aggregate F1 alone is not a valid sprint signal.

| Case | `column_name` engine | Schema prior | Intended effect | Value-add? |
|---|---|---|---|---|
| A | hits entity X | confident on X | reinforcement | low — authority 10 already wins |
| B | hits entity X | silent / ambiguous | graceful no-op | none expected |
| C | misses | confident on Y | **regex threshold for Y lowered → finding emerges** | **main ROI** |
| D | hits entity X | confident on Y (disagrees) | danger zone — new regex finding for Y gets suppressed by authority merge, but threshold was wasted | must not regress |

**Case C is the entire value hypothesis.** The feature is justified if and only if Case C shows meaningful improvement without Case D regression.

## YAML Profile Format (v1)

```yaml
version: 1
generated_at: 2026-04-13T14:30:00Z
generator: manual  # or llm-scanner-v1 in future
source_hash: sha256:ab12...  # for future invalidation

columns:
  - fqn: pharma.clinical.patients.enrollment.patient_ssn
    context_used:
      org: pharma
      folder: clinical
      dataset: patients
      table: enrollment
      column: patient_ssn
      data_type: STRING
    prior:
      SSN: 0.85
      NATIONAL_ID: 0.10
      OTHER: 0.05
    ambiguous: false
    rationale: "patient_ssn in US clinical context; very high prior"

  - fqn: pharma.clinical.patients.notes.content
    context_used:
      column: content
      data_type: STRING
    prior:
      FREE_TEXT: 0.40
      MEDICAL_NOTES: 0.35
      PERSON_NAME: 0.10
      OTHER: 0.15
    ambiguous: true
    rationale: "generic 'content' column in clinical notes; ambiguous"
```

**Rules:**
- `version: 1` required; loader rejects unknown versions
- `fqn` is dot-separated and unique within file
- `prior` values in `[0, 1]`, sum ≤ 1.0 (remainder is implicit OTHER)
- `ambiguous` boolean, explicit for auditability (derivable from entropy but not computed)
- `rationale` optional, strongly encouraged for human review
- Unknown entity types in `prior` warn but don't fail (forward-compat)
- Validator reports line numbers on malformed input

## Implementation Breakdown (10 items)

### 1. YAML profile format + loader + validator
**File:** `data_classifier/profiles/schema_profile.py` (new)
Define `SchemaProfile`, `SchemaPrior` dataclasses. Implement `load_schema_profile(path) → SchemaProfile`. Validator fails loudly on schema violations with line numbers.

**Acceptance criteria:**
- Loads 1000-column profile in <50 ms
- Rejects unknown `version` values
- Warns on unknown entity types in `prior`, does not fail
- Unit tests: valid, missing file, malformed YAML, unknown version, empty profile, invalid prior sums

### 2. Profile lookup module
Extend the profile object with an O(1) `get_prior(fqn) → SchemaPrior | None` lookup. Log debug on hit/miss.

**Acceptance criteria:**
- Returns None for unmatched fqn (graceful degradation)
- No exceptions on malformed lookup input

### 3. `ColumnInput.schema_prior` + API plumbing
**Files modified:** `data_classifier/core/types.py`, `data_classifier/orchestrator/orchestrator.py`, `data_classifier/__init__.py`
Add `schema_prior: SchemaPrior | None = None` to `ColumnInput`. Add `schema_profile: SchemaProfile | None = None` parameter to `classify_columns()`. Orchestrator attaches priors by fqn lookup before running engines.

**Acceptance criteria:**
- Default `None` → zero behavior change for all existing callers
- Full existing test suite passes unchanged with no diff
- `fqn` format documented explicitly: `{dataset}.{table_name}.{column_name}` (revisit if BQ connector passes different shape)
- Public API documented in `docs/CLIENT_INTEGRATION_GUIDE.md`

### 4. Transfer function module — **user contribution point**
**File:** `data_classifier/orchestrator/schema_prior.py` (new)

```python
MAX_THRESHOLD_DELTA: float = 0.2
PRIOR_NEUTRAL: float = 0.5

def adjust_threshold(base_threshold: float, prior_for_entity: float) -> float:
    """Adjust a pattern's confidence threshold based on the schema prior.

    Contract:
      - Must reduce to a no-op when prior_for_entity == PRIOR_NEUTRAL
      - Must clamp adjustment to [-MAX_THRESHOLD_DELTA, +MAX_THRESHOLD_DELTA]
      - Must be monotonic in prior_for_entity (higher prior → lower threshold)
      - Output clamped to [0.0, 1.0]
    """
    # TODO: implement
```

**Design decision (owner: user):** linear vs. non-linear (tanh/logistic), symmetric vs. asymmetric (penalize less than reward). Starting suggestion — linear symmetric with slope 0.4:

```python
delta = (prior_for_entity - PRIOR_NEUTRAL) * 0.4
delta = max(-MAX_THRESHOLD_DELTA, min(MAX_THRESHOLD_DELTA, delta))
return max(0.0, min(1.0, base_threshold - delta))
```

Simplest thing satisfying the contract; tunable via the slope constant; benchmarkable immediately. User may override with tanh/asymmetric if benchmarks justify.

**Acceptance criteria:**
- Contract reducible to: no-op at 0.5, clamped at extremes, monotonic
- Unit tests cover: neutral, max, min, out-of-range input, clamping edge cases
- Implementation choice documented inline with one-line rationale

### 5. Regex engine consumption
**File:** `data_classifier/engines/regex_engine.py`
For each pattern, if `column.schema_prior` present and flag enabled, look up the pattern's entity_type in the prior, call `adjust_threshold()`, use adjusted value in place of the base threshold. Otherwise behave unchanged.

**Acceptance criteria:**
- Prior-off behavior matches current regex engine bit-for-bit (regression-tested against existing test suite)
- Prior-on lowers thresholds for high-prior types; raises them for low-prior types
- Per-pattern per-column adjustment logged at debug level
- No other engines modified (explicit out-of-scope)

### 6. Feature flag
Two independent enables:
- Env var: `DATA_CLASSIFIER_SCHEMA_PRIOR=1` (default off)
- Parameter: `classify_columns(..., use_schema_prior=True)`

Parameter wins over env var. Both off → no consumption even if profile passed.

**Acceptance criteria:**
- Default OFF; existing callers unaffected
- State logged once at orchestrator init: source (env / parameter / default) and on/off
- Tests: flag-off + profile passed = no-op; flag-on + no profile = no-op; flag-on + profile = thresholds adjust

### 7. Hand-written test priors
**Directory:** `tests/fixtures/schema_profiles/`
Author 30–50 priors covering all four cases deliberately:

| Case | Min count |
|---|---|
| A — column_name hits + prior agrees | 8 |
| B — column_name hits + prior silent | 6 |
| C — column_name misses + prior confident (**main value-add**) | 10 |
| D — column_name hits entity X + prior says entity Y (danger zone) | 6 |

Plus adversarial priors in `tests/fixtures/schema_profiles/adversarial/`: deliberately wrong, malformed, empty. Used only in graceful-degradation tests.

**Acceptance criteria:**
- Each prior references an existing fixture column
- Each of the four cases has its minimum count
- Adversarial priors kept separate from main benchmark set

### 8. Benchmark harness with four-case decomposition
Extend existing benchmark runner to accept an optional schema profile and run twice (prior-off baseline, prior-on treatment). Report format:

```
Case | Precision | Recall | F1  | Δ from baseline
-----+-----------+--------+-----+-----------------
A    | ...       | ...    | ... | +0.xx
B    | ...       | ...    | ... | +0.xx
C    | ...       | ...    | ... | +0.xx  ← main signal
D    | ...       | ...    | ... | +0.xx  ← must not regress
All  | ...       | ...    | ... | +0.xx
```

Run against existing Ai4Privacy + blind eval fixtures from Sprint 7/8.

**Acceptance criteria:**
- Output committed as `docs/sprints/SPRINT10_SCHEMA_PRIOR_BENCHMARK.md` (sprint number TBD)
- Report lists exact corpora, fixture hashes, profiles used, and known limitations
- Methodology section follows the post-E10 baseline-correction convention

### 9. Sprint benchmark report with kill-switch decision
Explicit go/no-go criteria, written *before* running benchmarks to avoid post-hoc rationalization:

| Outcome | Action |
|---|---|
| Case C ≥ +0.03 F1, Case D regresses ≤ 0.01, aggregate ≥ +0.01 | **Go** — Sprint N+1 builds the LLM scanner |
| Case C +0.01 to +0.03, Case D OK, aggregate mixed | **Tune** — reduce slope, re-measure, decide next sprint |
| Case C < +0.01 OR Case D regresses > 0.02 OR aggregate regresses | **Kill** — feature stays behind flag indefinitely; scanner not built |

**Acceptance criteria:**
- Kill-switch thresholds written into the report before benchmarks run
- Recommendation section written before sprint retrospective
- If Kill: flag remains, mechanism stays in codebase as dormant code under flag for future reconsideration — no rip-out

### 10. BQ coordination doc
**File:** `docs/integrations/BQ_SCHEMA_PRIOR_COORDINATION.md` (new)

Contents:
- What the `SchemaProfile` YAML format looks like
- How `classify_columns()` accepts the profile
- BQ-owned responsibilities: scanner invocation, profile storage, DDL invalidation, fqn construction
- Library-owned responsibilities: format, validation, threshold adjustment
- Example integration code (~30 lines of connector-side pseudocode)
- Explicit non-commitment on BQ-side timeline

**Acceptance criteria:**
- Doc committed to library repo
- Reviewed by one person familiar with BQ connector architecture
- Does NOT modify any file outside the library repo

## Feature Flag Matrix

| Env var | Parameter | Behavior |
|---|---|---|
| unset | unset/None | OFF (default) |
| `0` | unset/None | OFF |
| `1` | unset/None | ON |
| any | `use_schema_prior=False` | OFF (parameter wins) |
| any | `use_schema_prior=True` | ON (parameter wins) |

Logged once at init:
```
INFO data_classifier.orchestrator: schema_prior=ON (source=env)
```

## Risks and Honest Concerns

These are real and should be weighed before sprint start, not after kill-switch fires.

1. **Overlap with existing sibling analysis.** `table_profile.py` already applies domain-based boosts/suppressions (healthcare / financial / customer_pii). The schema prior is a fancier version of this. If the LLM-generated prior doesn't significantly exceed what sibling analysis already achieves, the marginal value is small. **Mitigation:** the Case C benchmark explicitly measures columns where `column_name` misses — this is also where sibling analysis is weakest, so there's separation in theory. Reality TBD.

2. **Case-C addressable market may be small.** If the 600-variant dictionary already covers 90% of real-world column names, Case C is 10% of columns and the aggregate F1 delta will be bounded. The +0.01 aggregate kill-switch is deliberately low to account for this, but may still be unreachable.

3. **Option 3 (threshold adjustment) is the least principled of the Bayesian-ish options.** The transfer function has no theoretical basis; it's a tuned curve. If benchmarks are weak, the question will arise: "was it the mechanism or the transfer function?" The kill-switch should handle this by leaving the mechanism in place under a flag — no rip-out on one weak run.

4. **Hand-written priors are an upper bound, not a realistic estimate.** If hand-written priors move F1, LLM-generated priors will likely move it less. If hand-written priors don't move F1, we kill cleanly. The asymmetric information value is why consumer-first is correct.

5. **Surface area on a "stateless, simple" library.** This plan adds a new data type, a new loader, a new API parameter, a new behavior layer in regex engine, and a new coordination contract. It is net additive to the library's complexity. Acceptable only if the benchmark clearly justifies it.

6. **The fqn contract is a silent commitment to BQ.** Once `docs/integrations/BQ_SCHEMA_PRIOR_COORDINATION.md` ships with an example fqn format, BQ will build against it. Changing the fqn shape later is painful. Get this right on day one.

## Sprint Completion Gate (per CLAUDE.md)

1. `ruff check .` — zero warnings
2. `ruff format --check .` — zero diffs
3. `pytest tests/ -v` — all green (new schema_prior tests included)
4. GitHub Actions CI passing on main
5. Benchmark report committed with kill-switch decision
6. BQ coordination doc committed

## Effort Estimate

| Item | Estimate |
|---|---|
| 1. YAML format + loader + validator | 0.5 day |
| 2. Profile lookup module | 0.25 day |
| 3. ColumnInput field + API plumbing | 0.5 day |
| 4. Transfer function (user contribution) | 0.5 day |
| 5. Regex engine consumption | 1 day |
| 6. Feature flag | 0.25 day |
| 7. Hand-written priors | 1.5 days |
| 8. Benchmark harness extension | 1 day |
| 9. Benchmark run + report + kill-switch decision | 1 day |
| 10. BQ coordination doc | 0.5 day |
| **Total** | **~7 person-days** |

Fits a normal sprint with buffer.

## Next Actions

1. Review this spec
2. Confirm or override the `adjust_threshold` starting implementation (linear-symmetric-0.4)
3. Confirm the kill-switch thresholds (Case C +0.03, Case D ≤ 0.01 regression, aggregate +0.01)
4. When ready: use sprint-plan-next or sprint-start to convert this spec into individual backlog items for the target sprint
