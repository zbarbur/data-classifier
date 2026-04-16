# Sprint 11 — Family-Level A/B Result Memo

**Date:** 2026-04-15
**Branch:** `sprint11/scanner-tuning-batch`
**Scope:** Promote the benchmark metric from subtype-level macro F1 to
family-level cross-family error rate. Introduce the family taxonomy
as a public API field on ``ClassificationFinding``. Re-characterize
the Sprint 11 batch impact in family terms (the honest measure of
product quality).

> **⚠️ Sprint 12 follow-up (2026-04-16):** this memo recommends a
> Sprint 12 shadow→directive promotion on the strength of the
> family-level A/B evidence. That recommendation was **not executed.**
> The Sprint 12 Phase 5b safety audit (see
> `docs/research/meta_classifier/sprint12_safety_audit.md`) returned a
> RED verdict on heterogeneous columns — v5 collapses to confidently-
> wrong single-class predictions on log/chat/event-stream columns
> because softmax is the wrong primitive for multi-label input. Sprint
> 12 ships v0.12.0 shadow-only. The directive flip defers indefinitely
> pending structural reformulation (Sprint 13 column-shape router
> brief). The family-level A/B numbers in this memo remain valid for
> the subset of columns where mutual exclusivity holds (structured
> single-entity); they do not generalize to heterogeneous columns,
> which the Sprint 11 benchmark did not measure.

---

## Why family-level scoring

Prior sprints reported macro F1 over 26 subtype labels as the
classifier quality metric. That number conflates two qualitatively
different kinds of error:

* **Cross-family errors (Tier 1)** — labeling a credit card as a
  URL, or labeling a non-sensitive column as a credential. These
  change downstream handling, regulatory scope, and product
  behavior. They are real quality gaps.
* **Within-family mislabels (Tier 2)** — labeling an API_KEY as an
  OPAQUE_SECRET, or labeling a DATE_OF_BIRTH as a DATE_OF_BIRTH_EU.
  These share sensitivity tier, regulatory scope, and DLP handling.
  They are labeling choices that do not change what happens
  downstream.

Mixing these into one macro F1 number dilutes the real signal and
leads to misallocated sprint effort (e.g. "fix DOB_EU format
disambiguation" was a candidate Sprint 12 item until the family
view made it obvious that DOB_EU and DOB are structurally the same
concern).

The family taxonomy defined in
``data_classifier/core/taxonomy.py`` collapses the 26 subtypes
into 13 families designed around **downstream DLP handling**:

| Family | Members | Rationale |
|---|---|---|
| CONTACT | EMAIL, PHONE, ADDRESS, PERSON_NAME | Notice + opt-out + right-to-delete apply identically |
| CREDENTIAL | CREDENTIAL, API_KEY, OPAQUE_SECRET, PRIVATE_KEY, PASSWORD_HASH | Reject/rotate/audit policy |
| CRYPTO | BITCOIN_ADDRESS, ETHEREUM_ADDRESS | Chain-of-custody considerations |
| DATE | DATE_OF_BIRTH, DATE_OF_BIRTH_EU | Format ≠ jurisdiction; same regulatory scope |
| DEMOGRAPHIC | AGE, DEMOGRAPHIC | Weak personal identifiers, aggregation-first handling |
| FINANCIAL | ABA_ROUTING, IBAN, SWIFT_BIC, BANK_ACCOUNT, FINANCIAL | GLBA scope |
| GOVERNMENT_ID | SSN, CANADIAN_SIN, EIN, NATIONAL_ID | Per-country format, shared handling |
| HEALTHCARE | HEALTH, NPI, DEA_NUMBER, MBI | HIPAA 45 CFR 164 |
| NEGATIVE | NEGATIVE | Non-sensitive — singleton |
| NETWORK | IP_ADDRESS, MAC_ADDRESS | Network-layer identifiers |
| PAYMENT_CARD | CREDIT_CARD | **PCI-DSS** scope, distinct from FINANCIAL (GLBA) |
| URL | URL | Heterogeneous — kept its own family to score URL↔CONTACT as cross-family |
| VEHICLE | VIN | Singleton |

The taxonomy is a new **public API surface** exported as
``data_classifier.FAMILIES``, ``data_classifier.family_for``, and
populated automatically on every ``ClassificationFinding`` via a
``__post_init__`` hook. Downstream consumers (BQ connector, DLP
policy engines) can read ``finding.family`` without needing to know
the subtype-to-family mapping.

---

## Sprint 11 batch — family-level A/B result

Same 10,170-shard harness as the prior Phase 10 benchmark, run on
both sides with ``DATA_CLASSIFIER_DISABLE_ML=1`` (meta-classifier
shadow predictions captured via the event emitter):

| Path | N | cross_family_rate | family_macro_f1 | within_family_mislabels |
|---|---:|---:|---:|---:|
| **baseline LIVE** (main) | 10170 | 0.1571 | 0.8351 | 939 |
| **candidate LIVE** (batch) | 10170 | 0.1571 | 0.8351 | 961 |
| **baseline SHADOW** (v1) | 10170 | **0.4771** | **0.5451** | 695 |
| **candidate SHADOW** (v3) | 10170 | **0.0585** | **0.9286** | 322 |

### Headline

**Sprint 11 dropped the shadow cross-family error rate from 47.71% to 5.85%** — an 8.2× reduction in product-meaningful errors.

**The live path is unchanged** (cross-family rate 15.71% on both
sides). This confirms the batch is shadow-first by design: the
improvements (schema widening, Chao-1 cardinality, dictionary-word
ratio, v3 retrain) all flow through the meta-classifier, which
remains observability-only and does not modify
``classify_columns()`` return values.

### Per-family F1 on candidate shadow (sorted, worst first)

| Family | N | P | R | F1 |
|---|---:|---:|---:|---:|
| NEGATIVE | 450 | 0.787 | **0.478** | 0.595 |
| CREDENTIAL | 750 | 0.868 | 0.867 | 0.867 |
| VEHICLE | 450 | 0.995 | 0.833 | 0.907 |
| CONTACT | 2040 | 0.882 | 0.963 | 0.921 |
| FINANCIAL | 1470 | 0.952 | 0.937 | 0.945 |
| URL | 210 | 0.917 | 1.000 | 0.957 |
| HEALTHCARE | 1050 | 0.930 | 1.000 | 0.964 |
| GOVERNMENT_ID | 1110 | 0.996 | 0.987 | 0.991 |
| PAYMENT_CARD | 510 | 1.000 | 0.994 | 0.997 |
| CRYPTO | 600 | 1.000 | 1.000 | **1.000** |
| DATE | 810 | 1.000 | 1.000 | **1.000** |
| NETWORK | 720 | 1.000 | 1.000 | **1.000** |

Three families perfect (CRYPTO, DATE, NETWORK).
Two above 0.99 (GOVERNMENT_ID, PAYMENT_CARD).
Five in the 0.90–0.97 band (HEALTHCARE, URL, FINANCIAL, CONTACT, VEHICLE).
Two below 0.90 — CREDENTIAL (0.867) and NEGATIVE (0.595).

**The NEGATIVE family is the binding constraint.** Its precision is
already good (0.787) — the issue is *recall* (0.478). The v3
model is over-eager to commit to positive classes on genuinely
non-sensitive data; it doesn't defer to NEGATIVE often enough.

### Where NEGATIVE's 235 missed non-negatives went

| Misclassified as | N | Family | Cross-family? |
|---|---:|---|---|
| CREDENTIAL | 99 | CREDENTIAL | yes |
| PERSON_NAME | 75 | CONTACT | yes |
| SWIFT_BIC | 44 | FINANCIAL | yes |
| URL | 12 | URL | yes |
| EMAIL | 5 | CONTACT | yes |

All 235 are cross-family errors — by construction, since NEGATIVE
is a singleton family. The dominant confusion mode is
``NEGATIVE → CREDENTIAL`` (99 rows, 42% of all NEGATIVE misses),
driven by secretbench / gitleaks / detect_secrets placeholder
strings that structurally look like credentials but are
documentation test keys. The live-path
``not_placeholder_credential`` validator (Phase 6) rejects these
correctly, but the shadow meta-classifier does not have access to
validator decisions — it only sees the feature vector computed
from raw engine output.

**Sprint 12 Item 1 (``validator_rejected_credential`` feature)**
targets this specifically: expose validator rejection as a
feature, retrain v4, measure the NEGATIVE family recall movement.
Projected target: shadow cross-family rate from 5.85% to under
3% via this single change plus the Item 2 dictionary-name feature.

---

## Live path stability (15.71% cross-family on both sides)

The live cascade's cross-family error rate is carried by structural
gaps rather than classifier errors:

| Source | Rows | Reason |
|---|---:|---|
| NEGATIVE rows | 450 | Live cascade has no way to emit "NEGATIVE" — every row is a false positive by construction |
| HEALTH rows | 150 | No regex patterns for HEALTH in the profile; live cannot emit HEALTH |
| ADDRESS → PERSON_NAME | 145 | Real catch-all confusion |
| VIN → PERSON_NAME | 75 | Real catch-all confusion |
| BANK_ACCOUNT → PERSON_NAME | 59 | Real catch-all confusion |
| (other) | ~719 | Remaining live-path confusions |

NEGATIVE + HEALTH account for 600 of the 1598 live-path
cross-family errors (37.5%). These are *unrecoverable* in the live
cascade because the live pipeline has no representation for them —
only the shadow meta-classifier can emit those labels. This is
the strongest argument for eventually promoting the shadow path to
directive: **it unlocks labels the live cascade cannot produce**.

Live-path improvement is explicitly out-of-scope for Sprint 11.
The batch is a preparation sprint for a directive promotion in a
later sprint.

---

## Taxonomy decisions and tradeoffs

Four judgment calls worth documenting for future review:

### 1. DOB_EU stays as a subtype but is in the DATE family

Rationale: format (MM/DD vs DD/MM) does not determine jurisdiction;
data subjects' residency determines GDPR applicability, not the
storage format. Distinguishing "June 5" from "5 June" is
fundamentally unresolvable for dates where day ≤ 12, which is more
than half the year. Both variants stay as subtype labels (so
connectors that want to render the format can do so) but family
scoring collapses them.

### 2. CREDIT_CARD is its own family (PAYMENT_CARD)

Rationale: PCI-DSS is a distinct regulatory regime from GLBA.
Downstream handling differs materially — tokenization, scope
reduction, audit requirements. Flattening CREDIT_CARD into
FINANCIAL would hide a genuine product-relevant distinction.

### 3. PERSON_NAME is in the CONTACT family

Initial draft kept PERSON_NAME as its own singleton family to
preserve visibility on the catch-all confusion problem (ADDRESS,
VIN, BANK_ACCOUNT all getting misrouted to PERSON_NAME when v3
was uncertain). Final decision: merge into CONTACT so
ADDRESS↔PERSON_NAME is a within-family mislabel. Rationale: the
within-family vs cross-family split should reflect downstream
policy, not model-debugging priorities. Downstream DLP treats
PERSON_NAME and ADDRESS identically (notice + opt-out). The
catch-all problem is still visible in CONTACT's precision number
(0.882 on candidate shadow) — it's just not double-counted as a
Tier 1 error.

### 4. URL is its own singleton family

Rationale: URLs are heterogeneous — API endpoints, documentation
links, tracking URLs, personal homepages. They don't share
sensitivity with CONTACT. A CREDIT_CARD → URL misclassification
should count as cross-family (because URL handling is weaker),
and a URL → CREDIT_CARD misclassification likewise. The
singleton scoring cost is fair payment for catching those errors
correctly.

---

## Sprint 12 priorities (family-metric-anchored)

| # | Item | Target family | Projected impact |
|---|---|---|---|
| 1 | ``validator_rejected_credential`` feature + retrain | NEGATIVE | Recall 0.478 → ~0.75 |
| 2 | ``has_dictionary_name_match`` feature + retrain | CONTACT | Precision 0.882 → ~0.95 |
| 3 | Retire DATE_OF_BIRTH_EU subtype (merge into DATE_OF_BIRTH) | (taxonomy cleanup) | Reduces taxonomy surface |
| 4 | FINANCIAL family subtype audit (downstream need?) | (taxonomy review) | Reduces taxonomy surface if subtypes unneeded |
| 5 | Shadow → directive promotion gate (conditional on 1–2) | All | Unlocks HEALTH, CREDENTIAL, NEGATIVE in live path |

**Cumulative Sprint 12 target: shadow ``cross_family_rate < 0.030``** — a crisp, benchmark-measurable goal anchored in Tier 1 quality.

---

## Artifacts committed in this sprint

| File | Purpose |
|---|---|
| ``data_classifier/core/taxonomy.py`` | Canonical family mapping and ``family_for`` helper |
| ``data_classifier/core/types.py`` (modified) | ``ClassificationFinding.family`` field + ``__post_init__`` auto-populate |
| ``data_classifier/__init__.py`` (modified) | Public exports: ``FAMILIES``, ``family_for``, ``ENTITY_TYPE_TO_FAMILY`` |
| ``tests/test_family_taxonomy.py`` | 12 tests covering dispatch, auto-populate, profile coverage invariant |
| ``tests/benchmarks/family_accuracy_benchmark.py`` | Canonical benchmark harness producing Tier 1 + Tier 2 metrics |
| ``tests/benchmarks/README.md`` | Benchmark documentation and rationale |
| ``docs/CLIENT_INTEGRATION_GUIDE.md`` (modified) | v0.11.0 ``family`` field documentation |
| ``docs/research/meta_classifier/sprint11_family_benchmark.json`` | Committed baseline summary for future ``--compare-to`` deltas |
| ``docs/research/meta_classifier/sprint11_family_ab_result.md`` | This memo |
| ``CLAUDE.md`` (modified) | Sprint closure gate — attach family benchmark summary |

---

## Conclusion

Sprint 11's impact is best measured as **a 0.477 → 0.059 drop in
shadow cross-family error rate**, achieved with zero live-path
regression. The metric reframing (family F1 > subtype F1) is a
one-time quality methodology fix that will anchor every subsequent
sprint's quality gate. The batch is merge-ready under the new metric
and has two clear Sprint 12 targets (NEGATIVE recall, CONTACT
precision) with measurable success criteria.
