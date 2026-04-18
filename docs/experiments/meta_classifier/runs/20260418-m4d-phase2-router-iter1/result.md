# M4d Phase 2 — router-labeler validation vs M4c gold set
**Run date:** 2026-04-18T10:32:45Z
**Model:** `claude-opus-4-7`
**Gold-set rows scored:** 50 (human_reviewed only)
**API errors:** 1
**Invalid-label responses:** 0 columns emitted unknown label strings

## Quality gates
- **Combined macro Jaccard:** `0.8200` (gate: ≥ 0.8) → ✅ PASS
- **Per-branch ≥ 0.7:** → ✅ PASS
  - `free_text_heterogeneous` (n=35): `0.7714` ✅
  - `opaque_tokens` (n=4): `0.7500` ✅
  - `structured_single` (n=11): `1.0000` ✅

## Per-branch metrics
| Shape | n | Jaccard | micro F1 | macro F1 | subset_acc |
|---|---|---|---|---|---|
| `free_text_heterogeneous` | 35 | `0.7714` | `0.6667` | `0.3111` | `0.6000` |
| `opaque_tokens` | 4 | `0.7500` | `0.7500` | `0.3333` | `0.7500` |
| `structured_single` | 11 | `1.0000` | `1.0000` | `1.0000` | `1.0000` |

## Overall metrics
| Metric | Value |
|---|---|
| jaccard_macro | `0.8200` |
| micro_precision | `0.7857` |
| micro_recall | `0.6790` |
| micro_f1 | `0.7285` |
| macro_precision | `0.8596` |
| macro_recall | `0.2603` |
| macro_f1 | `0.3504` |
| hamming_loss | `0.0373` |
| subset_accuracy | `0.7000` |
| n_columns | `50` |
| n_columns_empty_pred | `12` |
| n_columns_empty_true | `9` |

## Usage + cost telemetry
- Input tokens (uncached): **469,577**
- Output tokens: **3,265**
- Cache read tokens: **96,900** (served at ~0.1× price)
- Cache creation tokens: **0** (paid at 1.25× price)
- Cache-hit rate on input: **17.1%**
- **Estimated total cost:** $2.4780

## API errors
| column_id | error |
|---|---|
| `sprint12_fixture_original_q3_log` | `AttributeError: 'NoneType' object has no attribute 'labels'` |

## Per-column disagreements
15 / 50 rows disagree. Sorted by per-column Jaccard ascending (worst agreement first).

| column_id | shape | pred | true | FP | FN | Jaccard |
|---|---|---|---|---|---|---|
| `sprint12_fixture_original_q3_log` | `free_text_heterogeneous` | [] | [ABA_ROUTING, API_KEY, BITCOIN_ADDRESS, CREDIT_CARD, DATE_OF_BIRTH, DEA_NUMBER, EIN, EMAIL, ETHEREUM_ADDRESS, IBAN, IP_ADDRESS, MAC_ADDRESS, MBI, NPI, PHONE, SSN, URL, VIN] | [] | [ABA_ROUTING, API_KEY, BITCOIN_ADDRESS, CREDIT_CARD, DATE_OF_BIRTH, DEA_NUMBER, EIN, EMAIL, ETHEREUM_ADDRESS, IBAN, IP_ADDRESS, MAC_ADDRESS, MBI, NPI, PHONE, SSN, URL, VIN] | `0.000` |
| `sprint12_fixture_base64_encoded_payloads` | `opaque_tokens` | [EMAIL] | [OPAQUE_SECRET] | [EMAIL] | [OPAQUE_SECRET] | `0.000` |
| `cfpb_narrative_bank_account` | `free_text_heterogeneous` | [] | [PHONE, URL] | [] | [PHONE, URL] | `0.000` |
| `cfpb_narrative_vehicle_loan` | `free_text_heterogeneous` | [] | [URL] | [] | [URL] | `0.000` |
| `so_about_me_rep_10k_100k_a` | `free_text_heterogeneous` | [AGE, EMAIL, PERSON_NAME, URL] | [URL] | [AGE, EMAIL, PERSON_NAME] | [] | `0.250` |
| `so_about_me_rep_0_100_b` | `free_text_heterogeneous` | [EMAIL, URL] | [PERSON_NAME, URL] | [EMAIL] | [PERSON_NAME] | `0.333` |
| `hn_comments_2019` | `free_text_heterogeneous` | [PHONE, URL] | [URL, PERSON_NAME] | [PHONE] | [PERSON_NAME] | `0.333` |
| `so_about_me_rep_100_1k_b` | `free_text_heterogeneous` | [ADDRESS, PERSON_NAME, URL] | [PERSON_NAME, URL, AGE] | [ADDRESS] | [AGE] | `0.500` |
| `so_about_me_rep_100k_plus_b` | `free_text_heterogeneous` | [EMAIL, PERSON_NAME, URL, ADDRESS] | [PERSON_NAME, URL] | [ADDRESS, EMAIL] | [] | `0.500` |
| `sprint12_fixture_kafka_event_stream` | `free_text_heterogeneous` | [EMAIL, IP_ADDRESS, PHONE, URL, AGE] | [CREDIT_CARD, EMAIL, IP_ADDRESS, PHONE, URL] | [AGE] | [CREDIT_CARD] | `0.667` |
| `so_about_me_rep_0_100_a` | `free_text_heterogeneous` | [EMAIL, URL, ADDRESS] | [EMAIL, URL] | [ADDRESS] | [] | `0.667` |
| `so_about_me_rep_100_1k_a` | `free_text_heterogeneous` | [EMAIL, PERSON_NAME, URL] | [PERSON_NAME, URL] | [EMAIL] | [] | `0.667` |
| `so_about_me_rep_1k_10k_a` | `free_text_heterogeneous` | [EMAIL, PERSON_NAME, URL] | [PERSON_NAME, URL] | [EMAIL] | [] | `0.667` |
| `so_about_me_rep_1k_10k_b` | `free_text_heterogeneous` | [EMAIL, PERSON_NAME, URL] | [PERSON_NAME, URL] | [EMAIL] | [] | `0.667` |
| `so_about_me_rep_10k_100k_b` | `free_text_heterogeneous` | [URL, PERSON_NAME, BITCOIN_ADDRESS, ETHEREUM_ADDRESS] | [ETHEREUM_ADDRESS, PERSON_NAME, URL] | [BITCOIN_ADDRESS] | [] | `0.750` |

## Per-branch instructions used in this run
Captured verbatim from ``llm_labeler_router.py`` at run time.

### `structured_single`

```
Label this database column with every PII entity type that appears in at
least one sample value. Use entity names exactly from the allowed list
below — never invent new types or use subcomponents (use EMAIL, not
DOMAIN or LOCAL_PART).

Rules:
1. Prevalence floor is 1 — if a single value carries a confident entity,
   include that label. One SSN in 100 chat rows still yields SSN.
2. One label per value; the column's label list is the union across values.
   If a value could be two types, pick the primary one.
3. Return an empty list [] when no sample value carries real PII. CFPB
   narratives redacted to XXXX are the canonical empty case — XXXX is
   not evidence of a present entity.
4. Skip placeholders and weak signals unless surrounding values establish
   them as real: admin, password123, test, 0.0.0.0, 127.0.0.1,
   example.com, foo@example.com.
5. Label DATE_OF_BIRTH only when the date is explicitly a birth date
   (dob=1985-03-17). Generic timestamps are not DOB.
6. Base64-like payloads without semantic context are OPAQUE_SECRET, not
   API_KEY. Government IDs require visible shape match (SSN = 9 digits in
   XXX-XX-XXXX form), not just plausible length.

When genuinely uncertain, leave the label out — under-labeling is
recoverable, over-labeling skews downstream Jaccard.
```

### `opaque_tokens`

```
Label this database column with every PII entity type that appears in at
least one sample value. Use entity names exactly from the allowed list
below — never invent new types or use subcomponents (use EMAIL, not
DOMAIN or LOCAL_PART).

Rules:
1. Prevalence floor is 1 — if a single value carries a confident entity,
   include that label. One SSN in 100 chat rows still yields SSN.
2. One label per value; the column's label list is the union across values.
   If a value could be two types, pick the primary one.
3. Return an empty list [] when no sample value carries real PII. CFPB
   narratives redacted to XXXX are the canonical empty case — XXXX is
   not evidence of a present entity.
4. Skip placeholders and weak signals unless surrounding values establish
   them as real: admin, password123, test, 0.0.0.0, 127.0.0.1,
   example.com, foo@example.com.
5. Label DATE_OF_BIRTH only when the date is explicitly a birth date
   (dob=1985-03-17). Generic timestamps are not DOB.
6. Base64-like payloads without semantic context are OPAQUE_SECRET, not
   API_KEY. Government IDs require visible shape match (SSN = 9 digits in
   XXX-XX-XXXX form), not just plausible length.

When genuinely uncertain, leave the label out — under-labeling is
recoverable, over-labeling skews downstream Jaccard.
```

### `free_text_heterogeneous`

```
This column contains free-text values from user-generated content (bios,
chat, support narratives), log streams, or mixed-schema records. Multiple
entity types may coexist in one column. Precision matters more than
recall here — Phase 1 analysis showed that over-labeling was the dominant
failure mode on free-text columns.

Use entity names exactly from the allowed list below — never invent new
types or use subcomponents (use EMAIL, not DOMAIN or LOCAL_PART).

Hard precision rules (follow strictly):

EMAIL — only when a value contains an actual email-shaped literal
(``name@domain.tld`` or ``name@sub.domain.tld``). Paraphrases of how to
reach someone ("contact me at...", "DM me", "email me"), intent hints
without a literal address, and placeholders (``example.com`` addresses,
``test@test``, ``foo@bar``) are NOT EMAIL.

PERSON_NAME — only when a value contains a full first+last name as a
real reference to a person ("I'm Tracy Wilson", "spoke with John Smith").
Usernames, SO / Twitter / GitHub handles, single first names
("alice", "bob123", "kenliu"), company names, product names, and
log-identifier name-like strings (e.g., apache access-log user fields
like ``- alice -``) are NOT PERSON_NAME.

ADDRESS — only for explicit geographic specificity beyond a country or
vague region. Full street address, city+state ("Houston, TX"), or full
postal address qualifies. Bio mentions like "I'm from Boston", "work in
SF", "based in Europe", "California dev" do NOT qualify — these are
biographical context, not address data.

URL — label when a value contains an ``http(s)://`` URL OR a bare domain
embedded in narrative text. Bare-domain examples that DO qualify:
``Loanme.com``, ``Xoom.com``, ``github.com/user/repo``,
``example.co.uk/path``, ``carfinance.com``. Relative paths
("/api/users", "/login"), filesystem paths, and shell paths do NOT
qualify. When in doubt about a bare domain, lean toward labeling it.

FINANCIAL — do NOT label for narrative money mentions, loan amounts,
currency figures, or redacted money placeholders ("paid $500",
"{$500.00}", "10K loan", "$20000 balance"). FINANCIAL is an
account-identifier category; use IBAN / SWIFT_BIC / ABA_ROUTING /
BANK_ACCOUNT for specific account numbers and leave narrative monetary
mentions unlabeled.

BANK_ACCOUNT / CREDENTIAL / SWIFT_BIC — require structural shape match,
not keyword proximity. A string near "account:" that isn't a bank
account number structure is NOT BANK_ACCOUNT. A value like
"password123" or "admin" or "secret" is NOT CREDENTIAL — real
credentials have entropy AND a provider-shape anchor (e.g.,
``sk_live_``, ``ghp_``, ``AKIA``, long base64 payloads). IBAN-like
runs of alphanumerics that don't validate as IBAN should NOT be
SWIFT_BIC.

DATE_OF_BIRTH — only when a date is marked as a birth date (``dob=...``,
"born on ...", "birthday: ..."). Transaction dates, post dates, log
timestamps, and redacted dates (``XX/XX/XXXX``) are NOT DOB.

Redaction handling: ``XXXX`` / ``XX/XX/XXXX`` / ``{$...}`` placeholders
are evidence of a REDACTED entity — do NOT label the redacted entity on
the basis of the placeholder alone. An entire column of XXXX-redacted
narratives is correctly labeled ``[]``. Entities that survive redaction
in other values of the same column DO count at the column level.

Prevalence floor is 1 — one value carrying a confident entity that
passes the rules above yields that label at the column level. When
genuinely uncertain, leave the label out. Under-labeling is recoverable;
over-labeling dominates Jaccard loss on free-text columns.
```

