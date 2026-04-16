# Presidio ↔ data_classifier entity type mapping

Sprint 7 added a side-by-side comparator between data_classifier and Microsoft Presidio.
Presidio uses its own entity taxonomy (`US_SSN`, `PERSON`, `DATE_TIME`, etc.) which
does not overlap 1:1 with ours. This document defines how we translate Presidio's
output into our vocabulary so precision/recall/F1 can be computed on the same
ground truth.

The mapping lives in
[`tests/benchmarks/comparators/presidio_comparator.py`](../../tests/benchmarks/comparators/presidio_comparator.py).
**Keep this doc and that file in lockstep** — if a mapping changes, update both.

## Two modes

| Mode | Intent | Use when |
| --- | --- | --- |
| **Strict** | Only 1:1 semantic matches. No cross-category drift. | Reporting like-for-like F1. |
| **Aggressive** | Strict + looser adjacent mappings (PERSON→PERSON_NAME, LOCATION→ADDRESS, DATE_TIME→DATE_OF_BIRTH). | Maximum overlap. Useful when a lot of Presidio's output would otherwise be discarded as "not comparable." |

`AGGRESSIVE_MAPPING` is always a superset of `STRICT_MAPPING` — strict entries
are carried over verbatim; aggressive only adds.

## Strict mapping

| Presidio entity | Our entity | Rationale |
| --- | --- | --- |
| `US_SSN` | `SSN` | Same concept. |
| `CREDIT_CARD` | `CREDIT_CARD` | Same concept. |
| `EMAIL_ADDRESS` | `EMAIL` | Same concept. |
| `PHONE_NUMBER` | `PHONE` | Same concept. |
| `IP_ADDRESS` | `IP_ADDRESS` | Same concept. |
| `IBAN_CODE` | `IBAN` | Same concept. |
| `URL` | `URL` | Same concept. |
| `US_DRIVER_LICENSE` | `DRIVERS_LICENSE` | Same concept. |
| `MEDICAL_LICENSE` | `DEA_NUMBER` | Both identify medical practitioners. Closest strict match; not perfect (DEA is US-specific, Presidio's is broader), but any `MEDICAL_LICENSE` hit under a DEA ground-truth column is a true positive for the purposes of comparison. |

## Aggressive-only additions

| Presidio entity | Our entity | Rationale |
| --- | --- | --- |
| `PERSON` | `PERSON_NAME` | Presidio's `PERSON` is a PII name; we use `PERSON_NAME`. Always-on addition. |
| `LOCATION` | `ADDRESS` | Presidio's `LOCATION` is broader (cities, regions, landmarks) than our `ADDRESS` (street-level). Aggressive because some Presidio hits won't be full addresses. |
| `DATE_TIME` | `DATE_OF_BIRTH` | Presidio's `DATE_TIME` covers any date or time, while our `DATE_OF_BIRTH` is specifically a birth date. Most benchmark corpora that label columns as DOB contain values Presidio would flag as `DATE_TIME`, so the aggressive mapping treats them as matches. Will cause Presidio FPs on timestamp columns in strict-negative scenarios — acceptable under aggressive mode. |
| `US_BANK_NUMBER` | `BANK_ACCOUNT` | Presidio's `US_BANK_NUMBER` covers US account numbers; our `BANK_ACCOUNT` is generic. |
| `US_ITIN` | `NATIONAL_ID` | ITIN is a US tax ID issued to non-residents; we lump it with `NATIONAL_ID` since we don't have a dedicated ITIN entity. |
| `US_PASSPORT` | `NATIONAL_ID` | Passports are national IDs. Same lumping as ITIN. |
| `UK_NHS` | `MEDICAL_ID` | NHS number is the UK national health ID. |

## Entities intentionally not mapped

Presidio supports entities we don't track, or that have no useful counterpart:

- `CRYPTO` — wallet addresses. We don't track crypto.
- `NRP` — Nationality, Religion, Political affiliation. Too broad for our categorical taxonomy; would generate noise.
- `AU_ABN`, `AU_ACN`, `AU_TFN`, `AU_MEDICARE` — Australian IDs, not in our current entity set (tracked in backlog as `country-specific-ids-phase-1`).
- `ES_NIF`, `ES_NIE`, `IT_VAT_CODE`, `IT_FISCAL_CODE`, `IT_DRIVER_LICENSE`, `IT_IDENTITY_CARD`, `IT_PASSPORT`, `PL_PESEL`, `SG_NRIC_FIN`, `SG_UEN`, `IN_AADHAAR`, `IN_PAN`, `IN_PASSPORT`, `IN_VEHICLE_REGISTRATION`, `IN_VOTER`, `KR_RRN`, `FI_PERSONAL_IDENTITY_CODE` — non-US national IDs. Same as above — backlogged.
- `DATE_TIME` under strict mode — too broad to guarantee DOB. See above.

## Updating the mapping

When you change `STRICT_MAPPING` or `AGGRESSIVE_MAPPING`:

1. Update `tests/benchmarks/comparators/presidio_comparator.py`.
2. Update the relevant table above.
3. Add a parametrized case to `tests/test_presidio_comparator.py` so the new pair is pinned by a test.
4. Re-run `pytest tests/test_presidio_comparator.py -v` to confirm the pair is picked up by `translate_entities`.
5. Re-run the consolidated benchmark with `--compare presidio` to confirm the new pair affects comparison metrics as expected.
