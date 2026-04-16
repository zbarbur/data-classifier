# Sprint 12 Handover — data_classifier

> **Theme:** Feature lift + directive-promotion safety audit → shadow-only ship
> **Dates:** 2026-04-15 → 2026-04-16
> **Branch:** `sprint12/main` (24 commits, plus merged PR #14)
> **Test count:** 1520 → **1531** (+11 net-new, passing)
> **Released as:** TBD — `v0.12.0` tag planned after handover review; BQ consumer bump remains on the v0.8.0 line until v0.12.0 lands.

---

## Sprint theme in one paragraph

Sprint 12 was scoped as "promote the meta-classifier shadow path to directive" — Item #4 would turn v3/v4/v5 into THE classification decision and retire the 7-pass merge's subtype-ranking step. Items #1 (validator-rejected-credential feature) and #2 (dictionary-name-match feature) were the feature prerequisites for that promotion, and the mid-sprint PR #14 merge (safety-analysis-memo prep) added LOCO + heterogeneous acceptance criteria and a new Phase 5b safety-audit gate before Phase 6 could proceed. The features landed cleanly, the audit ran end-to-end, and the audit returned **RED**: v5 on heterogeneous columns (log lines, Apache access logs, JSON events, base64 tokens, chat messages, Kafka streams) produces high-confidence wrong-class predictions that no confidence threshold can separate from its in-distribution wins. The root cause is structural — softmax is the wrong primitive for a problem where a column can legitimately contain multiple entity types. Sprint 12 therefore ships v0.12.0 **shadow-only**: Items #1/#2 and the Phase 5a Option A train/serve skew fix land as shadow improvements, v5 observability continues, and directive promotion defers indefinitely pending a structural reformulation. The Sprint 13 brief reframes around a column-shape router (heuristic gate + existing-tool routing — cascade for structured, GLiNER per-value for heterogeneous, tuned `secret_scanner` for opaque tokens) rather than "build 3 specialized stage-2 classifiers."

---

## Timeline and scope evolution

Sprint 12 opened on 2026-04-15 with `52df7f3 chore: start Sprint 12 — v3 becomes the default, single path`. The initial scope was 3 items (Item #1, Item #2, Item #4 directive promotion) plus 2 cleanup items that landed independently (stopwords XOR decode support, DATE_OF_BIRTH_EU subtype retirement).

Mid-sprint the scope shifted twice:

1. **PR #14 (safety-audit-prep) merged 2026-04-16 morning** — added LOCO ≥ 0.30 and heterogeneous-regression acceptance criteria to Item #4, and filed a new `sprint12-shadow-directive-promotion-gate-safety-analysis-memo` item as a Phase 5b gate. This was a significant scope expansion: the original Item #4 AC were in-distribution only, and PR #14 made out-of-distribution (LOCO) and architecture-stress (heterogeneous) evaluations non-negotiable gates. Sprint 12 scope revised from ~6–9 days to ~9–12 days at PR merge.

2. **Phase 5a in-session bug discovery (2026-04-16 afternoon)** — the first directive A/B spike on v5 failed the Item #4 in-distribution AC with `cross_family_rate = 0.0652` (target < 0.040) and `CONTACT precision = 0.9250` (target ≥ 0.93). Root-cause analysis traced the failure to a train/serve skew in `extract_features`: the training harness calls `_run_all_engines` which preserves raw findings per engine, but the orchestrator's merge pipeline collapses duplicate-entity-type findings before handing the list to `predict_shadow`. Fix landed as Phase 5a "Option A" — `predict_shadow` takes an `engine_findings` kwarg that the orchestrator threads in; when provided, it is flattened and fed to `extract_features` in place of the post-merge list. Post-fix in-distribution AC: cross_family 0.0047, CONTACT precision 0.998 — all 4 gates PASS.

3. **Phase 5b safety audit (2026-04-16 evening)** — ran the 3-question audit (capacity / architecture / heterogeneous) on v5. Q1 (LR vs MLP vs LR+interactions) passed cleanly — MLP ties/loses LR, so capacity is not the bottleneck. Q2 (oracle-gate hard-gating delta) returned +0.1031, just over the YELLOW trigger. Q3 (heterogeneous, 6 fixtures) returned RED aggregate: 3/6 fixtures produced high-confidence wrong-class v5 predictions (base64 → VIN @ 0.934, chat → CREDENTIAL @ 1.000, Kafka → CREDENTIAL @ 0.999). Iteration 1 of the audit (single log fixture) had read YELLOW; iteration 2 with 5 additional fixtures invalidated both the YELLOW verdict and the proposed confidence-threshold mitigation.

4. **Phase 6 (orchestrator wiring) RETIRED** — directive promotion defers indefinitely. Phase 7 (this handover) documents the decision chain.

---

## Delivered — feature track (Phase 2 + Phase 3 + Phase 4)

### 1. Item #1 — `validator_rejected_credential_ratio` (P1 feature · M) — `6e1a562`, `9e301a4`

**Goal.** Close the Sprint 11 Phase 10 NEGATIVE family F1 gap (0.595 → 0.75 target). Add a column-level statistic that fires when the column's values are placeholder credentials (strings that `not_placeholder_credential` validator rejects during regex matching — things like `your_api_key_here`, `changeme`, `password123`).

**Design decision — Option A symmetric-by-construction.** The Phase 1 investigation memo (`fe31121`) laid out two design alternatives for threading validator decisions into the feature vector. Option A (pure column-level ratio, computed identically in both training and inference from `sample_values`) vs Option B (validator decisions as sidecar metadata on `ClassificationResult`, populated by the regex engine at emit/reject time). Option A was chosen because the same function called from both code paths cannot produce train/serve skew by construction — the same class of bug we then hit and fixed in Phase 5a. Option B is strictly additive and can be layered on later if the signal strength from Option A underperforms, but the measurement gate for that is a separate sprint item.

**What shipped.**
- New `compute_placeholder_credential_rejection_ratio(values: list[str]) -> float` in `data_classifier/engines/heuristic_engine.py`. Pure function, lazy-imports `not_placeholder_credential` from `validators.py` to avoid engine-package circular imports.
- Feature-schema bump v3 → v4: `validator_rejected_credential_ratio` added at feature index 47. `FEATURE_SCHEMA_VERSION = 4` bump; v3 artifact refused at load time with version-mismatch error (same refusal pattern as Sprint 11's v2 → v3).
- `_EXTRA_FEATURE_NAMES` list in `data_classifier/orchestrator/meta_classifier.py` appended.
- `predict_shadow` + `extract_features` signatures updated.
- Training harness (`tests/benchmarks/meta_classifier/extract_features.py::extract_training_row`) threaded the same kwarg through.
- 8 new tests in `TestComputePlaceholderCredentialRejectionRatio` covering the function itself + 2 new parity regression guards in `TestPredictShadowThreadsValidatorRejectionRatio` (pinning the train/serve contract at the Item #1 wiring level).

**Measured impact.** Post-v5 retrain, the feature appears as #7 in `top_5_feature_importances` analysis (not in top 5 but within the top-10). NEGATIVE family F1 lifted 0.595 → 0.963 (large lift, larger than target, but confounded by the concurrent Option A fix — the two effects cannot be cleanly separated from the family-benchmark numbers alone).

### 2. Item #2 — `has_dictionary_name_match_ratio` (P1 feature · M) — `1120352`, `2e62e7f`

**Goal.** Close the Sprint 11 Phase 10 CONTACT family precision gap (0.882 → 0.95 target). Add a column-level statistic that fires when column values contain dictionary-name tokens (first names from SSA baby-names + surnames from US Census 2010 top-5000 surnames).

**What shipped.**
- New `compute_dictionary_name_match_ratio(values: list[str]) -> float` in `heuristic_engine.py`, mirroring the Sprint 11 `compute_dictionary_word_ratio` loader pattern (lazy-loaded module-level `frozenset`, min_token_length from JSON config, case-insensitive matching).
- New `scripts/ingest_name_lists.py` — reads pre-downloaded Census 2010 surnames ZIP + SSA baby-names ZIP (via Internet Archive mirror since SSA direct download returns HTTP 403 for automated fetchers). Params: `TOP_N_SURNAMES=5000`, `TOP_N_FIRST_NAMES=5000`, `MIN_TOKEN_LENGTH=4`.
- New `data_classifier/patterns/name_lists.json` — 5000 first names + 5000 surnames, 817 in both, lowercase, min length 4. 143 KB committed (within the committed-patterns size policy).
- Feature-schema bump v4 → v5: `has_dictionary_name_match_ratio` added at feature index 48. `FEATURE_SCHEMA_VERSION = 5`; v4 was transient — Phase 2 trained v4 only as an intermediate measurement, not as a committed artifact.
- 11 new tests in `TestComputeDictionaryNameMatchRatio` + 2 new parity regression guards in `TestPredictShadowThreadsNameMatchRatio`.

**Measured impact.** Post-v5 retrain, `has_dictionary_name_match_ratio` is the **#4 feature by abs-coefficient sum** (14.83), above `top_overall_confidence` (14.28). CONTACT family precision lifted 0.882 → 0.998 (well above target, again confounded by Option A).

### 3. v5 meta-classifier retrain (P1 feature · S) — `b17d113`

**Goal.** Retrain the meta-classifier at schema v5 (49-feature schema, 47 kept features after `ALWAYS_DROP_REDUNDANT = ("has_column_name_hit", "engines_fired")`). Commit the artifact + metadata.

**What shipped.**
- Regenerated `tests/benchmarks/meta_classifier/training_data.jsonl` at schema v5 via `python -m tests.benchmarks.meta_classifier.build_training_data`. 9870 rows × 49 features. Not committed — regenerable locally per `.gitignore` policy.
- Trained `data_classifier/models/meta_classifier_v5.pkl` + sibling `.metadata.json`. `best_c=1.0`, `cv_mean_macro_f1=0.5625 ± 0.1022`, `held_out_test_macro_f1=0.9939`. Top 5 features by abs-coefficient: `heuristic_distinct_ratio (19.22)`, `heuristic_dictionary_word_ratio (17.37)`, `regex_match_ratio (17.36)`, `has_dictionary_name_match_ratio (14.83)`, `top_overall_confidence (14.28)`.
- `.gitignore` whitelist entries added for the v5 artifacts. Artifact size: 17KB pkl + 7.4KB metadata — within the committed-models policy (per-D5 decision).

---

## Delivered — infrastructure track (Phase 5a + Phase 5b)

### 4. Phase 5a — Option A train/serve skew fix (P0 bug · S) — `847f8df`

**Goal.** Phase 5a's first directive A/B spike on v5 failed the Item #4 in-distribution AC with `cross_family_rate = 0.0652` (target < 0.040). Root-cause analysis: for columns with duplicate-entity-type findings (regex SSN @ 0.9975 AND column_name SSN @ 0.8075), the training harness sees both (via `_run_all_engines` which flattens every engine's raw output) while `predict_shadow` sees only the winner of the orchestrator's authority-weighted merge. This produces a silently-different feature vector at inference time than the model was trained on, specifically on `regex_match_ratio`, `top_overall_confidence`, and the `primary_entity_type_*` one-hots — all high-weight features.

**What shipped.**
- `predict_shadow` takes a new `engine_findings: dict[str, list[ClassificationFinding]] | None = None` keyword-only argument. When provided, it is flattened into a raw list and fed to `extract_features` in place of the positional `findings` list. When `None`, the legacy path is preserved (the existing Sprint 11 Phase 7 parity tests construct synthetic `findings` lists directly and rely on this behavior).
- Orchestrator passes `engine_findings=engine_findings` (which it already tracks per-engine internally for the merge pipeline) to `predict_shadow`.
- 2 new parity tests in `TestPredictShadowAcceptsRawEngineFindings` — one pins the new engine_findings flattening contract, one pins the legacy fallback path.

**Measured impact on family benchmark (v5 shadow):**

| metric | pre-fix | post-fix | Sprint 11 baseline |
|---|---|---|---|
| cross_family_rate | 0.0652 | **0.0047** | 0.0585 |
| family_macro_f1 | 0.9321 | **0.9945** | 0.9286 |
| NEGATIVE F1 | 0.8643 | **0.963** | 0.595 |
| CONTACT precision | 0.9250 | **0.998** | 0.882 |
| SSN precision / recall | ~0.31 / ~0.31 | **1.000 / 0.9725** | — |

14× reduction in cross-family error rate on the in-distribution benchmark. The SSN win is the direct measurement of the bug — 219 SSN-ground-truth columns that pre-fix were predicted as CREDIT_CARD (because the column_name SSN finding won the authority merge but the model was trained on the regex SSN feature profile) now correctly predict SSN.

**Why the fix is a real bug fix, not a Sprint 12 artifact.** The bug has existed since Sprint 6 Phase 3 when the shadow path first shipped. Any sprint whose benchmark was run through `predict_shadow` (Sprint 6 through Sprint 11) was silently measuring a smaller-feature-vector model than the model that was trained. The Sprint 11 Phase 10 family benchmark numbers are in that class — they would improve under the Option A fix. That is the lift that took v5's cross_family_rate from the committed Sprint 11 baseline 0.0585 to the post-Sprint-12 0.0047. Sprint 12 Items #1 and #2 add features that contribute to the lift but are not the primary cause. The primary cause is that the shadow observability stream was reporting a degraded model for 6 sprints.

### 5. Phase 5b — Safety audit harness + RED verdict (P0 investigation · L) — `235447f`

**Goal.** Before Phase 6 (orchestrator wiring) executes, answer three questions via an evidence-generating spike: (Q1) is LR the capacity ceiling? (Q2) does v5 need hard gating for LOCO? (Q3) does flat v5 collapse on log-shaped columns? Return a GREEN / YELLOW / RED verdict per the Phase 1 investigation memo's thresholds.

**What shipped.**
- New `tests/benchmarks/meta_classifier/sprint12_safety_audit.py` — end-to-end harness running all 3 questions and emitting a verdict JSON.
  - Q1 arms: A0_LR (v5 baseline at C=1.0), A1_MLP (MLPClassifier(32,32) with early stopping, label-encoded for Python 3.14 compatibility), A2_LR_interactions (top-5 features by mutual_info + pairwise products).
  - Q2: oracle-gate partition (ground-truth family = CREDENTIAL vs other), per-branch LOCO on same config as A0_LR, support-weighted branch-sum vs single-model baseline.
  - Q3 (iteration 2): 6 heterogeneous fixtures — `original_q3_log`, `apache_access_log`, `json_event_log`, `base64_encoded_payloads`, `support_chat_messages`, `kafka_event_stream`. Per-fixture collapse verdict on two axes (confidence × shadow-in-live-entities), aggregate verdict is worst-case single-fixture verdict across all 6.
- New `docs/research/meta_classifier/sprint12_safety_audit.md` — full memo with RED verdict, per-fixture evidence, softmax-is-wrong-primitive structural finding, Sprint 13 column-shape-router reframe (§6).
- Lint per-file-ignore in `pyproject.toml` for the harness (sklearn-convention uppercase X identifiers).

**Verdict:** RED. Q1 passed (capacity is not the bottleneck). Q2 marginal at +0.1031 (just over YELLOW). Q3 aggregate RED: 3/6 fixtures produced `collapsed_high_confidence_wrong_class` (base64 → VIN @ 0.934, chat → CREDENTIAL @ 1.000, Kafka → CREDENTIAL @ 0.999).

**Key subsidiary finding — confidence-threshold mitigation failed.** Iteration 1 of the audit (single fixture, `original_q3_log` at 0.688) initially suggested YELLOW + a threshold mitigation at T=0.85 (which separated the family-benchmark "correct corrections" distribution from "both wrong" distribution cleanly). The 5 additional fixtures in iteration 2 invalidated that reasoning: the benchmark's "wrong" distribution was measured on in-distribution rows (which hedge at moderate confidence), but OOD heterogeneous fixtures produce v5 confidence *above* any reasonable threshold — OOD wrong-class collapses cluster at 0.934–1.000 and cannot be distinguished from v5's correct in-distribution wins by confidence alone. This is the well-documented "asymptotic overconfidence" property of softmax classifiers on OOD inputs.

**Structural finding.** The root cause of the Q3 failure is not tunable. v5's softmax architecture models the problem as "exactly one of K classes is true for this column," which is false for a meaningful fraction of BQ columns (log lines, event streams, chat, webhook payloads, JSON blobs). The cascade's `list[ClassificationFinding]` output already has the structurally-correct multi-label shape; v5 re-imposed mutual exclusivity on top of it. No amount of retraining, regularization tuning, or capacity adjustment fixes this — it requires a different problem formulation (multi-label training, span extraction, or routing-based handling).

---

## Delivered — scope-churn track (2 items landed independently)

### 6. Stopwords XOR decode support (P2 feature · S) — `812a0f9`, `4859421`, `c78df48`

**Goal.** Add XOR-obfuscated placeholder-string support to the stopwords/placeholder-credential validator so the fixture can include known-flagged strings without tripping GitHub push protection on the test repo.

**What shipped.** XOR-decoding loader in the placeholder validator's dict loader, matching the same pattern used in `data_classifier/patterns/__init__.py` for credential dictionaries. Fixture entries now use XOR-encoded form. No behavior change from the validator's perspective at runtime.

### 7. Retire DATE_OF_BIRTH_EU subtype (P2 chore · S) — `2e4a9d7`, `cb756f7`, `e6b8056`

**Goal.** Drop the `DATE_OF_BIRTH_EU` entity subtype from Sprint 12 active taxonomy, fold into `DATE_OF_BIRTH`. EU-specific subtype was filed in Sprint 9 as a speculative addition; Sprint 11 family-A/B analysis showed it had no production use case. Retired with a v3-compat alias so any external consumer still referencing the old name continues working.

**Follow-up filed.** Sprint 13 v4 retrain item to rebuild training data without the DOB_EU branch. Not blocking for v0.12.0 release since the runtime compat alias handles backward compatibility.

---

## Retired — directive promotion (Phase 6)

### Item #4 — `sprint12-shadow-directive-promotion-gate` — **retired**

Status change: `doing` → **`retired`** on 2026-04-16. Retirement reason written into the backlog YAML, points at the Phase 5b safety audit memo as the evidence chain.

**Why retired.** The Phase 5b safety audit returned RED on structural grounds: flat softmax is the wrong primitive for a problem where columns can contain multiple entity types. The 6-fixture heterogeneous evidence shows v5 emits high-confidence wrong-class predictions on a meaningful fraction of realistic BQ column shapes (log lines, event streams, chat, base64 tokens). Confidence-threshold mitigations fail because OOD wrong-class predictions are indistinguishable from in-distribution correct predictions by confidence alone. Directive promotion would actively regress BQ quality on log-shaped columns by replacing the cascade's correct multi-entity output with v5's wrong single-class output.

**Why "indefinitely" not "to Sprint 13."** Sprint 13's new brief is not "retry directive promotion with better training" — it is the column-shape router (§ Sprint 13 brief below). Within that brief, v5 keeps its role as the classifier for the `structured_single` branch (columns where mutual exclusivity holds). It is not reactivated as a replacement for the cascade. "Directive promotion of v5" as a concept is dead; what Sprint 13 builds is a different architecture that uses v5 as one component alongside other tools.

### Companion retirement — `gated-meta-classifier-architecture-q8-continuation`

Also retired on 2026-04-16. Retired as "wrong framing" with pointer to the Sprint 13 column-shape router reframe. The original item assumed the fix was to train 3 specialized stage-2 classifiers; the actual evidence says the fix is a heuristic routing layer that picks the right existing tool per shape. Simpler, less invasive, preserves Sprint 11 v5 wins on the subset of columns where they apply.

---

## Key decisions and lessons

### Decision 1 — Option A (symmetric-by-construction) over Option B (sidecar metadata)

The Phase 1 investigation memo (`fe31121` §8) laid out two design alternatives for Item #1. Option A computes the validator-rejection ratio as a pure function of `sample_values`, called identically from training and inference paths. Option B threads validator decisions through `ClassificationResult` as sidecar metadata populated at regex-engine emit/reject time.

Option A was chosen for zero-train-serve-skew-by-construction. The same class of bug (feature X computed one way at training, a different way at inference) has cost us 3 separate incidents in as many sprints: Sprint 11 Phase 7 dictionary-word-ratio, Sprint 12 Item #1 would have been the third if Option B had been picked, and Phase 5a's Option A fix (a structurally similar bug in how findings lists are passed to `extract_features`) was the third anyway. The Option A pattern — pure function, same inputs, called from both paths — is the durable fix for this bug class.

### Decision 2 — Phase 5a Option A fix as a real bug, not a Sprint 12 artifact

The Phase 5a fix turned the family benchmark's shadow `cross_family_rate` from 0.0652 (pre-fix) to 0.0047 (post-fix), well below the committed Sprint 11 baseline of 0.0585. This is a 14× reduction on the in-distribution benchmark. The temptation is to report this as "Sprint 12 delivered a massive quality lift," but the honest framing is different: **the shadow observability stream has been silently reporting a degraded model since Sprint 6 Phase 3**. Every sprint that measured shadow performance (6 through 11) saw a smaller-feature-vector model than the model that was actually trained. The Phase 5a fix removes that degradation. The correct statement is "the shadow numbers we reported in Sprints 6–11 understated the model's true in-distribution performance," not "Sprint 12 lifted the model."

This is the honest framing for Phase 5a and should be repeated in the BQ consumer bump communication if / when v0.12.0 ships.

### Decision 3 — Softmax is the wrong primitive (the structural finding)

The three audit questions surfaced three different symptoms of the same root cause. Q1 said LR is not the bottleneck (capacity is not the answer). Q2 said hard gating unlocks only +0.1031 LOCO (gating is at best a marginal improvement). Q3 said v5 collapses confidently-wrong on 3/6 heterogeneous fixtures (the flat architecture cannot represent multi-entity columns). The common cause: v5's softmax models "exactly one of K classes is true" for a problem where this is false on a meaningful fraction of inputs.

This reframes the Sprint 13 brief from "build a better softmax classifier" to "use the right tool per column shape." The cascade's `list[ClassificationFinding]` output is already multi-label — Sprint 13's job is to preserve that structure and pick the right tool to fill it per shape (cascade for structured, per-value GLiNER for free-text heterogeneous, tuned `secret_scanner` for opaque tokens). No new model training, no new training data, no new type system.

### Decision 4 — Iteration 1 YELLOW was wrong; iteration 2 RED is right

The safety audit ran twice. Iteration 1 had a single heterogeneous fixture (the `original_q3_log` at 0.688 confidence) and returned YELLOW with a proposed confidence-threshold mitigation at T=0.85. Iteration 2 added 5 more fixtures and found that 3 of them produce *high-confidence* wrong-class predictions (above T=0.85). The threshold mitigation is structurally broken for OOD input. Iteration 1's conclusion was wrong not because the math was wrong but because the fixture set was too narrow — N=1 told us the confidence distribution of ONE shape, not the confidence distribution of the heterogeneous failure surface.

**Lesson:** any time a safety audit runs a single adversarial fixture, assume the failure surface is larger than the fixture measures. Run 5+ fixtures minimum before trusting aggregate verdicts. The harness is now iteration-2-structured (6 fixtures, worst-case aggregation) so future safety audits inherit this lesson.

### Lesson 5 — Stack review before handoff catches quiet failures

The pre-handoff stack review (commit `e2742a2`) caught a YAML parse error in `sprint13-per-value-gliner-aggregation.yaml` — unquoted colons in bare-scalar acceptance criteria that silently broke `yaml.safe_load`. The error would have been invisible to casual reading and would have surfaced as an obscure CI failure when the next `yaml.safe_load` sweep ran. Catching it during stack-review took 2 minutes; catching it in CI would have cost an hour of investigation.

**Action:** the sprint-close ritual should include `yaml.safe_load` on every backlog YAML touched in the sprint. Filed as a meta-reminder for Sprint 13+.

---

## Test coverage

| Category | Pre-Sprint-12 | Post-Sprint-12 | Delta |
|---|---|---|---|
| Total passing | 1520 | **1531** | +11 |
| Skipped | 1 | 1 | 0 |
| xfailed | 1 | 1 | 0 |
| Feature track adds (Items #1 + #2) | — | **+19** | 8 placeholder-credential + 11 dictionary-name ratio tests |
| Parity track adds (Option A + Items #1/#2 wiring) | — | **+6** | 4 new parity regression guards + 2 engine-findings contract tests |
| Lint | clean | clean | — |
| Format | clean | clean | — |
| Total runtime | ~55s | ~48s | −7s (faster due to v5 artifact size reduction and parallel CV test improvements — incidental) |

**Family benchmark (v5 shadow, Sprint 11 baseline → post-Sprint-12):**

| metric | Sprint 11 baseline | Post-Sprint-12 | Delta |
|---|---|---|---|
| cross_family_rate | 0.0585 | **0.0047** | −0.0538 |
| family_macro_f1 | 0.9286 | **0.9943** | +0.0657 |
| NEGATIVE F1 | 0.595 | **0.963** | +0.368 |
| CONTACT precision | 0.882 | **0.998** | +0.116 |
| within_family_mislabels | 133 | **3** | −130 |

These are shadow-path numbers only — the live cascade is unchanged. BQ continues consuming the live cascade as source of truth for v0.12.0.

**Safety audit verdict:** RED (`collapsed_high_confidence_wrong_class` aggregate from 3/6 heterogeneous fixtures).

---

## Commits — 24 on `sprint12/main`

### Sprint-open and early scope (pre-Phase-1 prep)

1. `cb26e7d` — chore: fix Sprint 12 backlog YAML schema errors
2. `f5dd505` — chore: refresh credential pattern attribution dates to 2026-04-15
3. `52df7f3` — chore: start Sprint 12 — v3 becomes the default, single path

### Scope-churn items (landed independently of the Item #4 track)

4. `812a0f9` — feat(sprint12): stopwords XOR decode support + encoded placeholder batch
5. `4859421` — Merge worktree-agent-a639a863: stopwords XOR decode support
6. `c78df48` — chore(sprint12): mark stopwords XOR decode item phase=review
7. `2e4a9d7` — chore(sprint12): retire DATE_OF_BIRTH_EU subtype + v3 compat alias
8. `cb756f7` — Merge worktree-agent-abc04c9c: retire DATE_OF_BIRTH_EU subtype
9. `e6b8056` — chore(sprint12): flip DOB_EU retirement to review + file Sprint 13 v4 retrain

### PR #14 safety-audit-prep (merged from zbarbur)

10. `43740e4` — fix(meta_classifier): thread heuristic_dictionary_word_ratio into predict_shadow (Sprint 11 Phase 7 bug fix preceding Option A)
11. `2d71627` — chore(sprint12): add LOCO + heterogeneous safety criteria to promotion-gate
12. `9faab99` — docs(backlog): file Sprint 12 safety memo + flesh Sprint 9 gated-architecture P1
13. `1b9a557` — Merge pull request #14 from zbarbur/sprint12/safety-audit-prep
14. `05d1232` — Merge remote-tracking branch 'origin/main' into sprint12/main

### Item #4 track (Phases 1–5b and handover)

15. `fe31121` — docs(sprint12): Phase 1 Item #4 directive-promotion investigation memo
16. `6e1a562` — feat(heuristic_engine): add compute_placeholder_credential_rejection_ratio helper
17. `9e301a4` — feat(meta_classifier): schema v4 adds validator_rejected_credential_ratio (Sprint 12 Item #1)
18. `d549c95` — chore: refresh credential pattern attribution dates to 2026-04-16
19. `1120352` — feat(heuristic_engine): add compute_dictionary_name_match_ratio helper + name_lists.json
20. `2e62e7f` — feat(meta_classifier): schema v5 adds has_dictionary_name_match_ratio (Sprint 12 Item #2)
21. `b17d113` — feat(meta_classifier): train v5 model at schema v5 — Sprint 12 Items #1 + #2
22. `847f8df` — fix(meta_classifier): thread engine_findings into predict_shadow (Option A)
23. `235447f` — docs(sprint12): Phase 5b safety audit — RED verdict, defer directive promotion
24. `e2742a2` — fix(sprint12): stack-review pass — YAML parse + stale Sprint 11 memo pointers

(Phase 7 handover — this document — is commit 25, landing with this commit.)

---

## Sprint 13 recommendations

Priority-ordered:

1. **`sprint13-column-shape-router`** (P1 feature · M, ~1 week) — the foundational piece. Heuristic gate + routing to 3 existing tools (cascade+v5 for structured, per-value GLiNER for free-text, tuned `secret_scanner` for opaque). Preserves Sprint 11 v5 wins on homogeneous columns while defusing the Q3 heterogeneous failure mode. No new model training, no new types. Full brief in `docs/research/meta_classifier/sprint12_safety_audit.md` §6.

2. **`sprint13-per-value-gliner-aggregation`** (P1 feature · M, ~1 week, depends on Item A) — the heterogeneous-branch handler. Refactor `GLiNERInferenceEngine` to support per-value span extraction + column-level aggregation. Currently GLiNER is used as a column-level single-label classifier which throws away its native multi-span capability; this item unlocks it. Win condition: on all 6 Q3 fixtures, per-value GLiNER finds ≥ cascade entity types at comparable confidence, no wrong-class emissions.

3. **`sprint13-opaque-token-branch-tuning`** (P2 feature · S, ~3 days, depends on Item A, optional) — handler for the opaque_tokens branch. Audit `secret_scanner` on JWT / base64 / hex-hash fixtures, add entropy features if needed. Can defer to Sprint 14+ if the cascade-output fallback from Item A is "good enough" on these columns.

4. **`v0.12.0` release tagging + BQ consumer bump** (P1 release ops) — tag v0.12.0, publish the wheel to the internal AR Python repo, coordinate the BQ consumer bump (BQ is still on v0.8.0; Sprint 9, 10, 11, 12 all untagged in BQ production). The shadow-only nature of the v0.12.0 changes means the BQ bump is low-risk — live cascade output is unchanged; only internal shadow observability differs.

5. **Sprint 13 v4 training data retrain** (P2 chore, carried over from DOB_EU retirement) — rebuild `training_data.jsonl` without the `DATE_OF_BIRTH_EU` branch and retrain v5. Not blocking; runtime compat alias handles external references.

6. **Gretel-EN blind detection lift** (P2 feature, carried over from Sprint 11 recommendation #6) — the weakest real-corpus measurement (0.611 blind, flat across Sprint 9–11). Investigate whether a shape-partitioner analog (like the Sprint 11 Nemotron JWT partitioner) is feasible despite the post-ETL loader format. Unblocked if the Sprint 13 column-shape router's training-data side ingests Gretel-EN with explicit shape labels.

7. **Ai4privacy openpii-1m re-ingest** (P2 research, deferred from Sprint 12) — the multilingual training corpus was deferred from Sprint 12 to avoid scope bloat. Not reopened unless the Sprint 13 column-shape router's `free_text_heterogeneous` branch needs multilingual training data for non-English log / chat columns.

8. **Sprint-close YAML parse sweep** (P3 process, from Lesson 5) — add `yaml.safe_load` of all touched backlog YAMLs to the `/sprint-end` ritual. Prevents the quiet-failure class that iteration-1 stack-review caught.

---

## Known risks carried into Sprint 13

1. **`detect_secrets` LOCO catastrophic failure** — per Q1 per-corpus breakdown, the `detect_secrets` held-out corpus produces F1 = 0.0022–0.0044 on any v5 arm (LR / MLP / LR+interactions). The model has zero generalization to this corpus's specific shape. Aggregate LOCO numbers pass the 0.30 bar because the large corpora (gretel_en, gretel_finance, nemotron) drive the mean upward, but any BQ customer whose data distribution overlaps more with `detect_secrets` than with the larger training corpora would see catastrophic shadow quality. The column-shape router partly mitigates this (if these columns detect as `opaque_tokens` and route away from v5) but cannot fully eliminate it without either more training data from that shape or a model that doesn't overfit to corpus-specific priors.

2. **CREDENTIAL branch Q2 measurement is intrinsically noisy** — 750 training rows split across 4 corpora (150 per LOCO holdout). Per-corpus F1 inside the CREDENTIAL branch swings 0.026 (detect_secrets) to 1.000 (gitleaks) to 0.000 (gretel_finance — no in-branch training data there). The +0.1031 Q2 delta is at the boundary of measurement noise; a different random seed could push it to 0.09 or 0.12. Sprint 13 column-shape router does not need this number to be precise — it just needs to know the branch exists and is non-trivial.

3. **Per-value GLiNER latency unknown** — currently GLiNER runs once per column. Per-value mode is N× slower for N sample values; a 50-row column is 50× the inference cost. Only paid on the `free_text_heterogeneous` branch (expected 10–30% of columns), but total inference latency is a real concern for batch classification workloads. Sprint 13 Item B needs to characterize and document this latency.

4. **Real BQ column-shape distribution is unknown** — the Sprint 13 column-shape router's performance depends on what fraction of BQ real-world columns fall in each shape bucket. We have no measurement of this. Research-branch item: ask BQ integration team for anonymized column-shape statistics.

5. **Sprint 11 Phase 10 shadow A/B numbers in `docs/research/meta_classifier/sprint11_phase10_batch_result.md` are correct but narrow** — they measured in-distribution synthetic single-entity columns and extrapolated to "shadow beats live." The extrapolation holds for in-distribution data and breaks on out-of-distribution heterogeneous data. The two Sprint 11 research memos now carry a "Sprint 12 follow-up" callout pointing at the safety audit; future research should always caveat in-distribution vs out-of-distribution scoping explicitly.

---

## Handover signoff

Sprint 12 delivered Items #1 and #2 cleanly as shadow features, landed a real in-production bug fix (Phase 5a Option A train/serve skew that had been silently degrading the shadow observability stream since Sprint 6), ran a safety audit that caught a structural problem early enough to defer Phase 6 before it shipped a regression to BQ, and reframed the Sprint 13 brief from "build a specialized classifier" to "route to the right existing tool." The directive-promotion item that was the sprint's original headline is retired, not deferred — the work Sprint 13 will do is different enough in shape from the original Item #4 plan that calling it "directive promotion" would be misleading. Shadow-only v0.12.0 ships a real quality improvement on in-distribution BQ columns (via the Option A fix) while preserving the cascade's multi-label output on heterogeneous columns where v5 would regress.

**Total test delta:** 1520 → **1531** (+11). **Commits:** 24 on `sprint12/main`. **Benchmark wins (shadow, in-distribution):** `cross_family_rate` 0.0585 → **0.0047**, `family_macro_f1` 0.9286 → **0.9943**. **Safety verdict:** RED on heterogeneous columns → directive promotion retired. **Release status:** v0.12.0 pending tag after handover review; BQ bumps from v0.8.0 directly to v0.12.0.
