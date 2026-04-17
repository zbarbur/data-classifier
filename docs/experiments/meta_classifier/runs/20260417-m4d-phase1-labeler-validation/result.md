# M4d Phase 1 — LLM labeler validation vs M4c gold set
**Run date:** 2026-04-17T14:21:41Z
**Model:** `claude-opus-4-7`
**Gold-set rows scored:** 50 (human_reviewed only)
**API errors:** 0
**Invalid-label responses:** 0 columns emitted unknown label strings

## Quality gate
**Jaccard macro:** `0.7544` (gate: ≥ 0.8) → ❌ FAIL — iterate on LABELER_INSTRUCTIONS

## Metrics
| Metric | Value |
|---|---|
| jaccard_macro | `0.7544` |
| micro_precision | `0.7075` |
| micro_recall | `0.9259` |
| micro_f1 | `0.8021` |
| macro_precision | `0.7372` |
| macro_recall | `0.9664` |
| macro_f1 | `0.7578` |
| hamming_loss | `0.0285` |
| subset_accuracy | `0.5800` |
| n_columns | `50` |
| n_columns_empty_pred | `10` |
| n_columns_empty_true | `9` |

## Usage + cost telemetry
- Input tokens (uncached): **533,176**
- Output tokens: **1,732**
- Cache read tokens: **0** (served at ~0.1× price)
- Cache creation tokens: **0** (paid at 1.25× price, once)
- Cache-hit rate on input: **0.0%**
- ⚠️ Cache-hit rate near 0 suggests the system prompt is below Opus 4.7's 4096-token minimum cacheable prefix. Consider extending the few-shot examples or the instructions block, or accept the higher per-call cost.
- **Estimated total cost:** $2.7092

## Per-column disagreements
21 / 50 rows disagree. Sorted by per-column Jaccard ascending (worst agreement first).

| column_id | pred | true | FP (over-fire) | FN (missed) | Jaccard |
|---|---|---|---|---|---|
| `cfpb_narrative_debt_collection` | [FINANCIAL] | [] | [FINANCIAL] | [] | `0.000` |
| `cfpb_narrative_mortgage` | [FINANCIAL] | [] | [FINANCIAL] | [] | `0.000` |
| `cfpb_narrative_bank_account` | [ADDRESS, PERSON_NAME] | [PHONE, URL] | [ADDRESS, PERSON_NAME] | [PHONE, URL] | `0.000` |
| `cfpb_narrative_vehicle_loan` | [] | [URL] | [] | [URL] | `0.000` |
| `cfpb_narrative_money_transfers_legacy` | [] | [URL] | [] | [URL] | `0.000` |
| `cfpb_narrative_consumer_loan` | [] | [URL] | [] | [URL] | `0.000` |
| `sprint12_fixture_apache_access_log` | [IP_ADDRESS, PERSON_NAME, URL] | [IP_ADDRESS] | [PERSON_NAME, URL] | [] | `0.333` |
| `so_about_me_rep_10k_100k_a` | [URL, EMAIL, PERSON_NAME] | [URL] | [EMAIL, PERSON_NAME] | [] | `0.333` |
| `so_about_me_rep_100_1k_a` | [PERSON_NAME, EMAIL, URL, PHONE, ADDRESS] | [PERSON_NAME, URL] | [ADDRESS, EMAIL, PHONE] | [] | `0.400` |
| `hn_comments_2019` | [PERSON_NAME, EMAIL, PHONE, URL, IP_ADDRESS] | [URL, PERSON_NAME] | [EMAIL, IP_ADDRESS, PHONE] | [] | `0.400` |
| `so_about_me_rep_1k_10k_a` | [PERSON_NAME, URL, EMAIL, ADDRESS] | [PERSON_NAME, URL] | [ADDRESS, EMAIL] | [] | `0.500` |
| `so_about_me_rep_100k_plus_b` | [PERSON_NAME, URL, EMAIL, ADDRESS] | [PERSON_NAME, URL] | [ADDRESS, EMAIL] | [] | `0.500` |
| `so_about_me_rep_100_1k_b` | [URL, PERSON_NAME, EMAIL, ADDRESS, AGE] | [PERSON_NAME, URL, AGE] | [ADDRESS, EMAIL] | [] | `0.600` |
| `sprint12_fixture_kafka_event_stream` | [EMAIL, AGE, IP_ADDRESS, PHONE, URL] | [CREDIT_CARD, EMAIL, IP_ADDRESS, PHONE, URL] | [AGE] | [CREDIT_CARD] | `0.667` |
| `so_about_me_rep_0_100_a` | [EMAIL, URL, PERSON_NAME] | [EMAIL, URL] | [PERSON_NAME] | [] | `0.667` |
| `so_about_me_rep_0_100_b` | [URL, EMAIL, PERSON_NAME] | [PERSON_NAME, URL] | [EMAIL] | [] | `0.667` |
| `so_about_me_rep_1k_10k_b` | [PERSON_NAME, URL, EMAIL] | [PERSON_NAME, URL] | [EMAIL] | [] | `0.667` |
| `hn_comments_2018` | [PHONE, URL, PERSON_NAME] | [PHONE, URL] | [PERSON_NAME] | [] | `0.667` |
| `so_about_me_rep_10k_100k_b` | [URL, PERSON_NAME, ETHEREUM_ADDRESS, BITCOIN_ADDRESS] | [ETHEREUM_ADDRESS, PERSON_NAME, URL] | [BITCOIN_ADDRESS] | [] | `0.750` |
| `so_about_me_rep_100k_plus_a` | [URL, EMAIL, PERSON_NAME, ADDRESS] | [EMAIL, PERSON_NAME, URL] | [ADDRESS] | [] | `0.750` |
| `sprint12_fixture_original_q3_log` | [EMAIL, IP_ADDRESS, API_KEY, PHONE, CREDIT_CARD, SSN, ADDRESS, URL, DATE_OF_BIRTH, IBAN, BITCOIN_ADDRESS, MBI, VIN, MAC_ADDRESS, NPI, ABA_ROUTING, BANK_ACCOUNT, ETHEREUM_ADDRESS, DEA_NUMBER, SWIFT_BIC, EIN, CREDENTIAL] | [ABA_ROUTING, API_KEY, BITCOIN_ADDRESS, CREDIT_CARD, DATE_OF_BIRTH, DEA_NUMBER, EIN, EMAIL, ETHEREUM_ADDRESS, IBAN, IP_ADDRESS, MAC_ADDRESS, MBI, NPI, PHONE, SSN, URL, VIN] | [ADDRESS, BANK_ACCOUNT, CREDENTIAL, SWIFT_BIC] | [] | `0.818` |

## Labeler instructions used in this run
Captured verbatim from ``llm_labeler.py`` at run time, so memo diffs across iterations show which instruction change produced which Jaccard delta.

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
