# M4c gold-set annotator guide

**Audience:** human reviewing Claude-prefilled labels in
`tests/benchmarks/meta_classifier/heterogeneous_gold_set.jsonl`.

**Time budget:** ≈ 3-5 minutes per row × 50 rows ≈ 2-4 focused hours.
Resumable — every `human_reviewed` flip writes atomically.

---

## Why this gold set matters

Every M4 metric eventually validates against this file. If the
labels here drift from reality, downstream M4b (gate vs downstream
harness), M4d (LLM-labeled scale corpus), and M4e (dual-report
harness) all inherit that drift silently. Be conservative and
explicit; when in doubt, leave a label out. Under-labeling is
recoverable (add it later); over-labeling by reflex is not.

## How to run the labeler

```bash
python -m tests.benchmarks.meta_classifier.gold_set_labeler \
    --annotator "your.name"
```

Per-row commands:

| Key | Action |
|---|---|
| `a` (or Enter) | Accept the pre-filled labels as-is |
| `e` | Edit — comma-separated new labels, confirmed before save |
| `s` | Skip — leaves `review_status=prefilled`, revisit later |
| `x` | Expand — show all values for this column (default shows 20) |
| `q` | Quit — progress saved |

The labeler refuses labels that aren't in the taxonomy. Valid entity
names are listed on the edit prompt.

## The entity vocabulary (25 types, 13 families)

Use these exact names. Case is normalized to uppercase.

| Family | Entity types |
|---|---|
| `CONTACT` | `EMAIL`, `PHONE`, `ADDRESS`, `PERSON_NAME` |
| `CREDENTIAL` | `CREDENTIAL`, `API_KEY`, `OPAQUE_SECRET`, `PRIVATE_KEY`, `PASSWORD_HASH` |
| `CRYPTO` | `BITCOIN_ADDRESS`, `ETHEREUM_ADDRESS` |
| `DATE` | `DATE_OF_BIRTH` |
| `DEMOGRAPHIC` | `AGE`, `DEMOGRAPHIC` |
| `FINANCIAL` | `ABA_ROUTING`, `IBAN`, `SWIFT_BIC`, `BANK_ACCOUNT`, `FINANCIAL` |
| `GOVERNMENT_ID` | `SSN`, `CANADIAN_SIN`, `EIN`, `NATIONAL_ID` |
| `HEALTHCARE` | `HEALTH`, `NPI`, `DEA_NUMBER`, `MBI` |
| `NETWORK` | `IP_ADDRESS`, `MAC_ADDRESS` |
| `PAYMENT_CARD` | `CREDIT_CARD` |
| `URL` | `URL` |
| `VEHICLE` | `VIN` |
| `NEGATIVE` | `NEGATIVE` (use when no PII present at all) |

When to reach for each:

- **Common entities** (`EMAIL`, `PHONE`, `ADDRESS`, `PERSON_NAME`,
  `URL`, `IP_ADDRESS`): reach for these when you can *see* the
  value in the displayed samples. "Probably present" is not enough.
- **Credential entities** (`API_KEY`, `OPAQUE_SECRET`, `PRIVATE_KEY`):
  use when the value has credential shape AND (optionally)
  credential-context hints like `api_key=`, `token=`, `bearer`.
  Base64-encoded payloads lacking semantic context are `OPAQUE_SECRET`.
- **Government IDs:** use only when you can verify the shape matches
  the spec (SSN = 9 digits with XXX-XX-XXXX formatting, SIN = 9
  digits with specific check digit).
- **`DATE_OF_BIRTH`:** only when the date is *labeled* as birth date.
  A timestamp is not DOB; `dob=1985-03-17` is.
- **`NEGATIVE`:** a column that is confidently non-sensitive
  (account IDs, status enums, counts). Keep the label list empty
  instead — do not add `NEGATIVE` literally unless the column is
  a pure negative control.

## Prevalence floor

From the M4c spec: **≥1 observed instance** of a label in the sample
is enough to include it. No "too rare to bother" filter.

Practical application: if you see exactly *one* phone number in 100
rows of Stack Overflow bios, `PHONE` goes in the labels. Set
`prevalence=0.01` in the `true_labels_prevalence` field (the labeler
edit flow doesn't yet set prevalence — edit the JSONL manually if
you want to populate it precisely; otherwise leave `{}` and M4b / M4e
will treat prevalence as unknown).

Why ≥1: the Sprint 13 router must catch rare-but-real PII without
relying on column-wide dominance. A single SSN in a support-chat
log is the classic hit the router must not miss.

## Granularity rule — top-level only

Use the entity types above. Do NOT invent sub-types like
`DOMAIN`, `LOCAL_PART`, `COUNTRY_CODE`. If it looks like a sub-type,
pick the parent entity (`EMAIL`, not `DOMAIN`).

## Ambiguous values — one label per value

If a value looks like both `PHONE` and `ADDRESS` (e.g., an address
block containing a phone number), pick the *primary* entity from the
annotator's perspective. The column can still carry multiple entity
types overall — different *values* contribute different labels.

## Placeholder / weak-signal values

Skip these unless you're ≥0.5 confident:

- `admin`, `password123`, `test` — don't label as `CREDENTIAL`
- `0.0.0.0`, `127.0.0.1` — localhost addresses, don't label as
  `IP_ADDRESS` unless they're real operational IPs
- `example.com` URLs — don't label as `URL` unless real domains
  elsewhere in the column establish it

The library's `stopwords.json` and `allowlist_patterns` already
filter many of these from regex hits; labeling reflects what a
careful human judges to be the actual entity class.

## CFPB redaction treatment

CFPB pre-redacts narratives with `XXXX` placeholders. Treat the
`XXXX` as evidence that a named entity *was* there, but:

- **Do NOT** count `XXXX` as a PII label (the *actual* PII is gone).
- **DO** include entities that survive redaction — money amounts
  like `{$72.00}` don't map to our taxonomy and are not labels,
  but phone numbers like `(XXX) XXX-XXXX` (rare — usually redacted)
  would qualify as `PHONE` if the numeric shape is fully visible.

In practice most CFPB rows will have empty or near-empty label
lists. That's informative — it establishes CFPB narratives as
near-negative-control columns for the router.

## If you disagree with the taxonomy

If you'd label something as an entity type not in the list, don't
jam it into a nearby type. Options:

1. Use the closest existing entity and leave a note in the
   `notes` field explaining why it's imperfect
2. Skip that value (don't contribute it to any label)
3. File a taxonomy-extension item in the research queue — the
   vocabulary is versioned and can grow

The goal of M4c is honest measurement against *today's* taxonomy,
not to perfect the taxonomy. Taxonomy evolution is a separate
research thread.

## Things the validator catches (so you don't have to)

Running `pytest tests/benchmarks/meta_classifier/test_gold_set_schema.py`
verifies:

- Every entity type you write is in `ENTITY_TYPE_TO_FAMILY`
- `true_labels_family` stays consistent with `true_labels`
- `true_labels_prevalence` values are in `[0, 1]`
- `true_shape` is one of the three Sprint 13 router branches
- `column_id` values are unique
- XOR-encoded values still decode

The labeler CLI runs the per-row checks at save time, so bad labels
can't land. But re-running the full test suite at end-of-session is
cheap insurance (< 2 seconds).

## M4d contamination note

This gold set's pre-fills were written by Claude Opus 4.6. M4d's
"measure LLM-vs-human Jaccard" validation requires a *different*
LLM family (GPT-4 class, Gemini, or materially different prompt) as
the M4d labeler. Using the same model for both pre-fill here and
scale-labeling there would produce an inflated agreement number that
measures model self-consistency, not human-ground-truth alignment.

This is documented in the M4c run-result memo
(`docs/experiments/meta_classifier/runs/20260416-m4c-gold-set/result.md`)
and will be enforced by M4d's task description when it's filed.
