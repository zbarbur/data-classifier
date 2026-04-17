# M4d Phase 1 — prompt iteration log (v1 → v2 → v3)

**Run date:** 2026-04-17
**Model:** `claude-opus-4-7` with adaptive thinking
**Gold set:** M4c heterogeneous 50 rows (post 2026-04-17 updates: +PERSON_NAME
on `hn_comments_2019`, +AGE on `so_about_me_rep_100_1k_b`)
**Canonical baseline artifact:** `result.md` + `predictions.jsonl` (v1
re-run against updated gold)

## Summary

Three prompt versions were tested on the full 50-row gold set. Jaccard
oscillated between 0.70 and 0.75 — no version reached the `≥ 0.8`
spec gate. **The plateau is architectural, not linguistic**: single-prompt
labeling on heterogeneous column types can't simultaneously satisfy
precision on SO/HN bios (which need strict PERSON_NAME / EMAIL rules)
and recall on CFPB narratives and location columns (which need loose
URL / ADDRESS rules). Tightening one rule set hurts the other.

Phase 2 (500-1000 column scale labeling) is **deferred pending a
router-labeler architecture** that picks different instructions per
column type. See queue.md M4d Phase 2 entry.

## Results table

| Version | Jaccard macro | micro P | micro R | micro F1 | macro F1 | Cost |
|---|---|---|---|---|---|---|
| v1 (original) | **0.7544** | 0.7075 | **0.9259** | 0.8021 | 0.7578 | $2.71 |
| v2 (tight all) | 0.7035 | **0.7907** | 0.8395 | **0.8144** | **0.8026** | $2.36 |
| v3 (tight partial) | 0.7220 | 0.7059 | 0.8889 | 0.7869 | 0.7692 | $2.38 |

Notes:
- v1 Jaccard improved from 0.7293 (initial run) to 0.7544 after the
  two gold-set updates — a precision win from aligning gold with the
  labeler's observations on 2 rows, not from code changes.
- v2 posts the best F1 (macro 0.803) and precision (0.791) but the
  stricter URL / ADDRESS rules caused 10 new 0.0-Jaccard rows where
  the labeler returned `[]` for columns the human annotator labeled
  with URL or ADDRESS.
- v3 relaxed URL and ADDRESS back toward v1's M4c convention, but
  introduced ADDRESS over-fire in 5 new rows and regressed an
  ETHEREUM_ADDRESS case.

## Stable failure patterns (across all three versions)

Persistent FPs the single-prompt approach could not resolve:

- **SO bio EMAIL over-fire** — 5-7 SO `about_me_*` rows consistently
  predict EMAIL when gold excludes it. The labeler treats "contact me"
  hints as evidence; human treats them as placeholders.
- **HN comment PERSON_NAME FP** — `hn_comments_2018` over-labels
  PERSON_NAME; human is conservative on borderline names.
- **Sprint 12 q3_log over-fire** — persistent BANK_ACCOUNT, CREDENTIAL,
  SWIFT_BIC FPs driven by IBAN collision and `secret=password123`
  placeholder interpretation.

Persistent FNs:

- **CFPB URL recall** — 3 CFPB rows have URL in gold; labeler returns
  `[]` on most runs, suggesting URLs are rare enough in the 50-value
  sample that the labeler isn't seeing them.
- **kafka CREDIT_CARD** — consistently missed by v1-v3.

## Why a router-labeler should do better

Each prompt iteration exposed the same structural conflict:

- **Free-text heterogeneous (SO / HN / CFPB)** wants strict precision
  rules — usernames are NOT PERSON_NAME, hint text is NOT EMAIL,
  redacted narratives are mostly empty.
- **Structured single-label (location columns, Sprint 12 fixtures)**
  wants permissive recall rules — city/state IS ADDRESS, log entries
  may contain every PII type at ≥1 prevalence.

A column's `true_shape` (already a gold-set field) tells us which
branch applies. A router-labeler would apply branch-specific
instructions + few-shot examples, which should lift Jaccard on both
ends of the column-type spectrum. Sprint 13's router architecture is
the consumer of this insight.

## Verbatim prompt versions

### v1 (canonical Phase 1 baseline — committed in result.md)

See `result.md` → "Labeler instructions used in this run" section at
the bottom, captured verbatim at run time.

### v2 (tight precision — macro F1 0.803)

```
Label this database column with every PII entity type that appears in at
least one sample value. Use entity names exactly from the allowed list
below — never invent types or use subcomponents (EMAIL, not DOMAIN).

Precision matters more than recall. When uncertain whether an entity is
real vs superficial, leave it out. Over-labeling skews downstream metrics
more than under-labeling.

Entity-specific precision rules (follow these strictly):

PERSON_NAME: only when a sample contains a first+last name written out
(e.g., "John Smith", "Tracy Wilson"). Usernames, handles, single first
names ("alice", "bob123", "kenliu"), GitHub/Twitter handles, and
company/product names are NOT PERSON_NAME.

URL: only external URLs with an explicit scheme (http://, https://,
ftp://). API endpoint paths ("/api/users", "/login"), relative paths, and
bare domain names are NOT URL.

ADDRESS: only when a sample contains a full street address with a house
number (e.g., "42 Main St, Springfield, IL"). City/state alone ("Houston,
TX"), country names, or zip-only are NOT ADDRESS.

FINANCIAL: do NOT label for dollar amounts, loan values, or currency
figures ($50, {$72.00}, "10K loan"). FINANCIAL is only for financial
account identifiers not covered by IBAN / SWIFT_BIC / BANK_ACCOUNT /
ABA_ROUTING.

DATE_OF_BIRTH: only when a date is explicitly marked as a birth date
(dob=1985-03-17, "born on 3/17/85"). Timestamps, log dates, transaction
dates, and issue dates are NOT DOB.

OPAQUE_SECRET vs API_KEY: base64/hex strings without explicit credential
context markers (api_key=, token=, bearer, secret=) are OPAQUE_SECRET,
NOT API_KEY. Column names like "encoded_payloads" do not promote the
entity to API_KEY.

Redaction handling: treat XXXX placeholders as evidence of a redacted
entity — do NOT label the redacted entity. But DO label real entities
that survive redaction (actual URLs, numeric phone shapes, etc.).

General rules:

1. Prevalence floor is 1 — one confident instance is enough, but the
   instance must pass the precision rules above.
2. One label per value; the column's label list is the union across values.
3. Return [] when no sample value carries real PII.
4. Skip placeholders and weak signals: admin, password123, test,
   0.0.0.0, 127.0.0.1, example.com, *.example.*, foo@example.com.
```

### v3 (tight partial — URL + ADDRESS relaxed from v2)

Identical to v2 except the URL and ADDRESS blocks were replaced with:

```
URL: label when a sample contains a web/external address — full URLs
with scheme ("https://example.com/path"), bare domain names with path
("example.com/signup", "github.com/user/repo"), or shortened URLs.
Exclude: API endpoint paths alone ("/api/users", "/login"), relative
paths, and file system paths.

ADDRESS: label when a sample contains geographic location data — full
street addresses (e.g., "42 Main St, Springfield, IL"), city+state
("Houston, TX"), or country-level. Do NOT label bare zip codes or
generic place references ("downtown", "home", "the office") alone.
```

## Gold-set updates applied 2026-04-17

Two rows were updated after the v1 initial run when the disagreement
analysis surfaced cases where the original human pre-fill was
conservative-to-a-fault:

- `hn_comments_2019`: added `PERSON_NAME` (value [7] contains
  "my name is tracy...")
- `so_about_me_rep_100_1k_b`: added `AGE` (value [1] "An 18 year-old
  developer...")

Both rows remain `review_status=human_reviewed`. See
`heterogeneous_gold_set.jsonl` for the updated records.
