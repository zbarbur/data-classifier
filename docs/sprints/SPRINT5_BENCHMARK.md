# Sprint 5 — Benchmark Report

> **Generated:** 2026-04-11 20:00 UTC
> **Samples per type:** 500
> **Patterns:** 71
> **Entity types (patterns):** 22
> **Corpus source:** ai4privacy

## Summary

| Metric | Pattern-Level (regex only) | Column-Level (full pipeline) |
|---|---|---|
| Total samples | 12,500 | 4,000 |
| Positive / Negative | 11,000 / 1,500 | 8 cols / 0 cols |
| Precision | 0.838 | 0.353 |
| Recall | 0.817 | 0.750 |
| **Micro F1** | **0.827** | **0.480** |
| **Macro F1** | — | **0.500** |
| **Primary-Label Accuracy** | — | **50.0%** |
| TP / FP / FN | 8,984 / 1,733 / 2,016 | 6 / 11 / 2 |

### Secret Detection

| Metric | Value |
|---|---|
| Precision | 0.377 |
| Recall | 0.304 |
| **F1** | **0.337** |

### Per-Entity F1 Breakdown (Column-Level)

| Entity Type | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| ADDRESS | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| CREDENTIAL | 0.000 | 0.000 | 0.000 | 0 | 0 | 1 |
| DATE_OF_BIRTH | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| EMAIL | 0.333 | 1.000 | 0.500 | 1 | 2 | 0 |
| IP_ADDRESS | 0.333 | 1.000 | 0.500 | 1 | 2 | 0 |
| ORGANIZATION | 0.000 | 0.000 | 0.000 | 0 | 2 | 0 |
| PERSON_NAME | 0.200 | 1.000 | 0.333 | 1 | 4 | 0 |
| PHONE | 0.500 | 1.000 | 0.667 | 1 | 1 | 0 |
| SSN | 0.000 | 0.000 | 0.000 | 0 | 0 | 1 |

### Corpus Metadata

| Property | Value |
|---|---|
| Source | ai4privacy |
| Pattern samples | 12,500 (11,000 positive, 1,500 negative) |
| Column corpus | 8 columns (4,000 total samples) |
| Entity types tested | 8 |

## Performance

| Metric | Value |
|---|---|
| Throughput | 0 columns/sec \| 150 samples/sec |
| Per column (p50) | 3333.820 ms |
| Per sample (p50) | 6667.6 us |
| Warmup (RE2 compile) | 2269.1 ms |

### Scaling

**Sample count scaling (per-column latency):**

| Samples/col | Latency (p50) |
|---|---|
| 10 | 147.596 ms |
| 50 | 395.901 ms |
| 100 | 700.518 ms |
| 500 | 3760.630 ms |

**Input length scaling (RE2 linearity):**

| Input bytes | p50 (us) | Ratio |
|---|---|---|
| 51 | 2.4 | 1.0x |
| 101 | 2.5 | 1.1x |
| 501 | 3.9 | 1.6x |
| 1,001 | 5.8 | 2.5x |
| 5,001 | 159.5 | 67.1x |
| 10,001 | 305.8 | 128.7x |
| 50,001 | 1585.1 | 667.4x |

## Pattern-Level Detail

```
==============================================================================
PATTERN MATCHING BENCHMARK (regex engine, per-sample)
==============================================================================

CORPUS
  Total samples:      12,500
  Positive samples:   11,000 (22 entity types)
  Negative samples:   1,500

SAMPLE-LEVEL DETECTION ACCURACY
------------------------------------------------------------------------------
Entity Type                TP     FP     FN     Prec   Recall       F1
------------------------------------------------------------------------------
ABA_ROUTING               500     27      0    0.949    1.000    0.974
ADDRESS                     0      0    500    0.000    0.000    0.000
BITCOIN_ADDRESS           500      0      0    1.000    1.000    1.000
CANADIAN_SIN              500     66      0    0.883    1.000    0.938
CREDIT_CARD               293      0    207    1.000    0.586    0.739
DATE_OF_BIRTH             500    500      0    0.500    1.000    0.667
DATE_OF_BIRTH_EU            0      0    500    0.000    0.000    0.000
DEA_NUMBER                500      0      0    1.000    1.000    1.000
EIN                       500      0      0    1.000    1.000    1.000
EMAIL                     500      0      0    1.000    1.000    1.000
ETHEREUM_ADDRESS          500      0      0    1.000    1.000    1.000
IBAN                      500      1      0    0.998    1.000    0.999
IP_ADDRESS                500      0      0    1.000    1.000    1.000
MAC_ADDRESS               500      0      0    1.000    1.000    1.000
MBI                       500      0      0    1.000    1.000    1.000
NPI                       500      0      0    1.000    1.000    1.000
PERSON_NAME                 0      0    500    0.000    0.000    0.000
PHONE                     191    500    309    0.276    0.382    0.321
SSN                       500    639      0    0.439    1.000    0.610
SWIFT_BIC                 500      0      0    1.000    1.000    1.000
URL                       500      0      0    1.000    1.000    1.000
VIN                       500      0      0    1.000    1.000    1.000
------------------------------------------------------------------------------
OVERALL                  8984   1733   2016    0.838    0.817    0.827

PER-PATTERN MATCH RATES (patterns with test data)
------------------------------------------------------------------------------
  Pattern                        Entity                Matched      Valid    ValFail
  ------------------------------ ------------------ ---------- ---------- ----------
  aba_routing                    ABA_ROUTING           500(100%)        500          0
  bitcoin_address                BITCOIN_ADDRESS       500(100%)        500          0
  canadian_sin                   CANADIAN_SIN          500(100%)        500          0
  credit_card_amex               CREDIT_CARD            46(9%)         46          0
  credit_card_discover           CREDIT_CARD            16(3%)         16          0
  credit_card_formatted          CREDIT_CARD           161(32%)        161          0
  credit_card_mastercard         CREDIT_CARD             5(1%)          5          0
  credit_card_visa               CREDIT_CARD            65(13%)         65          0
  date_iso_format                DATE_OF_BIRTH           0(0%)          0          0
  date_of_birth_format           DATE_OF_BIRTH         500(100%)        500          0
  dob_european                   DATE_OF_BIRTH         193(39%)        193          0
  dob_long_format                DATE_OF_BIRTH           0(0%)          0          0
  email_address                  EMAIL                 500(100%)        500          0
  ethereum_address               ETHEREUM_ADDRESS      500(100%)        500          0
  iban                           IBAN                  500(100%)        500          0
  international_phone            PHONE                   0(0%)          0          0
  ipv4_address                   IP_ADDRESS            500(100%)        500          0
  ipv6_address                   IP_ADDRESS              0(0%)          0          0
  mac_address                    MAC_ADDRESS           500(100%)        500          0
  swift_bic                      SWIFT_BIC             500(100%)        500          0
  url                            URL                   500(100%)        500          0
  us_dea                         DEA_NUMBER            500(100%)        500          0
  us_ein                         EIN                   500(100%)        500          0
  us_mbi                         MBI                   500(100%)        500          0
  us_npi                         NPI                   500(100%)        500          0
  us_phone_formatted             PHONE                 211(42%)        191         20
  us_ssn_formatted               SSN                   339(68%)        339          0
  us_ssn_no_dashes               SSN                   161(32%)        161          0
  vin                            VIN                   500(100%)        500          0

CROSS-PATTERN COLLISIONS (same value triggers multiple entity types)
------------------------------------------------------------------------------
  ABA_ROUTING            also triggers CANADIAN_SIN           (61 samples)
  ABA_ROUTING            also triggers SSN                    (521 samples)
  CANADIAN_SIN           also triggers ABA_ROUTING            (61 samples)
  CANADIAN_SIN           also triggers SSN                    (211 samples)
  DEA_NUMBER             also triggers IBAN                   (1 samples)
  IBAN                   also triggers DEA_NUMBER             (1 samples)
  NPI                    also triggers PHONE                  (500 samples)
  PHONE                  also triggers NPI                    (500 samples)
  SSN                    also triggers ABA_ROUTING            (521 samples)
  SSN                    also triggers CANADIAN_SIN           (211 samples)

MISSED SAMPLES (expected match, got nothing — up to 10 per type)
------------------------------------------------------------------------------
  ADDRESS (500 missed):
    '790 Mason Roads\nMarkside, NC 09520'
    '15082 William Flat\nRichardsonborough, GA 73419'
    '15186 Rodriguez Village Suite 152\nJesseport, CT 40126'
    '9972 Phillip Rue\nTimothyview, PR 67018'
    '8606 Osborn Ramp Suite 659\nLake Lori, NY 91070'
  CREDIT_CARD (207 missed):
    '4415013232887856326'
    '639086784514'
    '3507729523079511'
    '4875649191958418449'
    '502030370931'
  DATE_OF_BIRTH_EU (500 missed):
    '02/09/2021'
    '09/02/1931'
    '03/11/1926'
    '09/07/2023'
    '23/03/1948'
  PERSON_NAME (500 missed):
    'Noah Hicks'
    'Nathan Morales'
    'Megan Thornton'
    'Mary Edwards'
    'Samuel Warner'
  PHONE (309 missed):
    '+1-472-404-8014x26886'
    '273.810.0161x19921'
    '+1-518-303-4547x8231'
    '001-936-623-3065x30648'
    '(959)518-7410x0433'

FALSE POSITIVE EXAMPLES (up to 5 per type)
------------------------------------------------------------------------------
  ABA_ROUTING (27 FPs):
    '899753160' (expected=SSN)
    '455231686' (expected=SSN)
    '588106727' (expected=SSN)
    '224346906' (expected=SSN)
    '726959040' (expected=SSN)
  CANADIAN_SIN (66 FPs):
    '859874562' (expected=SSN)
    '446973331' (expected=SSN)
    '846214625' (expected=SSN)
    '650537624' (expected=SSN)
    '402977847' (expected=SSN)
  DATE_OF_BIRTH (500 FPs):
    '02/09/2021' (expected=DATE_OF_BIRTH_EU)
    '09/02/1931' (expected=DATE_OF_BIRTH_EU)
    '03/11/1926' (expected=DATE_OF_BIRTH_EU)
    '09/07/2023' (expected=DATE_OF_BIRTH_EU)
    '23/03/1948' (expected=DATE_OF_BIRTH_EU)
  IBAN (1 FPs):
    'PI0751809' (expected=DEA_NUMBER)
  PHONE (500 FPs):
    '2740961281' (expected=NPI)
    '2988776524' (expected=NPI)
    '2412066856' (expected=NPI)
    '1959672118' (expected=NPI)
    '1742676624' (expected=NPI)
  SSN (639 FPs):
    '271201418' (expected=ABA_ROUTING)
    '974285951' (expected=ABA_ROUTING)
    '438141434' (expected=ABA_ROUTING)
    '687958245' (expected=ABA_ROUTING)
    '890077667' (expected=ABA_ROUTING)

==============================================================================
```

## Column-Level Detail

```
======================================================================
ACCURACY BENCHMARK REPORT
======================================================================

KEY METRICS
----------------------------------------------------------------------
  Macro F1:                0.500
  Micro F1:                0.480
  Primary-Label Accuracy:  50.0%
  Corpus Source:           ai4privacy

CORPUS STATISTICS
  Total columns:      8
  Positive columns:   8 (8 entity types)
  Negative columns:   0
  Total samples:      4000
  Avg samples/column: 500

SAMPLE-LEVEL SUMMARY
----------------------------------------------------------------------
  Positive samples:     4,000
  Negative samples:     0
  Samples scanned:      4,000
  Samples matched:      2,077 (51.9%)
  Samples validated:    1,966 (94.7% of matched)

  Entity Type               Matched    Scanned      Valid     Conf          Via
  ---------------------- ---------- ---------- ---------- -------- ------------
  ADDRESS                    111(22%)        500        111    0.621        regex
  CREDENTIAL                   0(0%)        500          0    0.000       MISSED
  DATE_OF_BIRTH              253(51%)        500        253    0.630        regex
  EMAIL                      494(99%)        500        494    0.997        regex
  IP_ADDRESS                 499(100%)        500        499    0.945        regex
  PERSON_NAME                480(96%)        500        480    0.774        regex
  PHONE                      240(48%)        500        129    0.395        regex
  SSN                          0(0%)        500          0    0.000       MISSED

COLUMN-LEVEL ACCURACY (did the column get the correct entity label?)
----------------------------------------------------------------------
Entity Type              TP   FP   FN     Prec   Recall       F1
----------------------------------------------------------------------
ADDRESS                   1    0    0    1.000    1.000    1.000
CREDENTIAL                0    0    1    0.000    0.000    0.000
DATE_OF_BIRTH             1    0    0    1.000    1.000    1.000
EMAIL                     1    2    0    0.333    1.000    0.500
IP_ADDRESS                1    2    0    0.333    1.000    0.500
ORGANIZATION              0    2    0    0.000    0.000    0.000
PERSON_NAME               1    4    0    0.200    1.000    0.333
PHONE                     1    1    0    0.500    1.000    0.667
SSN                       0    0    1    0.000    0.000    0.000
----------------------------------------------------------------------
OVERALL                   6   11    2    0.353    0.750    0.480

ENGINE CONTRIBUTIONS
----------------------------------------------------------------------
Column                            Column Name Eng          Regex Eng
----------------------------------------------------------------------
  ADDRESS (col_0)                               -      DATE_OF_BIRTH
  CREDENTIAL (col_1)                            -                  -
  DATE_OF_BIRTH (col_2)                         - DATE_OF_BIRTH, EMAIL
  EMAIL (col_3)                                 -              EMAIL
  IP_ADDRESS (col_4)                            -         IP_ADDRESS
  PERSON_NAME (col_5)                           -                  -
  PHONE (col_6)                                 - PHONE, EMAIL, IP_ADDRESS
  SSN (col_7)                                   - PHONE, SSN, ABA_ROUTING, CANADIAN_SIN, NPI, IP_ADDRESS, HEALTH

SAMPLE-LEVEL DETECTION
----------------------------------------------------------------------
  ADDRESS              matched=111/500 (22%)  validated=111/111  confidence=0.621
  CREDENTIAL           NOT DETECTED
  DATE_OF_BIRTH        matched=253/500 (51%)  validated=253/253  confidence=0.630
  EMAIL                matched=494/500 (99%)  validated=494/494  confidence=0.997
  IP_ADDRESS           matched=499/500 (100%)  validated=499/499  confidence=0.945
  PERSON_NAME          matched=480/500 (96%)  validated=480/480  confidence=0.774
  PHONE                matched=240/500 (48%)  validated=129/240  confidence=0.395
  SSN                  NOT DETECTED

CROSS-PATTERN COLLISIONS (patterns that fire on the same column)
----------------------------------------------------------------------
  ADDRESS              also triggers ORGANIZATION         (1 columns)
  ADDRESS              also triggers PERSON_NAME          (1 columns)
  DATE_OF_BIRTH        also triggers EMAIL                (1 columns)
  EMAIL                also triggers DATE_OF_BIRTH        (1 columns)
  EMAIL                also triggers IP_ADDRESS           (1 columns)
  EMAIL                also triggers PERSON_NAME          (1 columns)
  EMAIL                also triggers PHONE                (1 columns)
  IP_ADDRESS           also triggers EMAIL                (1 columns)
  IP_ADDRESS           also triggers PERSON_NAME          (1 columns)
  IP_ADDRESS           also triggers PHONE                (2 columns)
  ORGANIZATION         also triggers ADDRESS              (1 columns)
  ORGANIZATION         also triggers PERSON_NAME          (2 columns)
  PERSON_NAME          also triggers ADDRESS              (1 columns)
  PERSON_NAME          also triggers EMAIL                (1 columns)
  PERSON_NAME          also triggers IP_ADDRESS           (1 columns)
  PERSON_NAME          also triggers ORGANIZATION         (2 columns)
  PERSON_NAME          also triggers PHONE                (1 columns)
  PHONE                also triggers EMAIL                (1 columns)
  PHONE                also triggers IP_ADDRESS           (2 columns)
  PHONE                also triggers PERSON_NAME          (1 columns)

FALSE POSITIVES
----------------------------------------------------------------------
  col_2: predicted=EMAIL, expected=DATE_OF_BIRTH, engines={'column_name': [], 'regex': ['DATE_OF_BIRTH', 'EMAIL']}
  col_6: predicted=EMAIL, expected=PHONE, engines={'column_name': [], 'regex': ['PHONE', 'EMAIL', 'IP_ADDRESS']}
  col_6: predicted=IP_ADDRESS, expected=PHONE, engines={'column_name': [], 'regex': ['PHONE', 'EMAIL', 'IP_ADDRESS']}
  col_7: predicted=IP_ADDRESS, expected=SSN, engines={'column_name': [], 'regex': ['PHONE', 'SSN', 'ABA_ROUTING', 'CANADIAN_SIN', 'NPI', 'IP_ADDRESS', 'HEALTH']}
  col_0: predicted=ORGANIZATION, expected=ADDRESS, engines={'column_name': [], 'regex': ['DATE_OF_BIRTH']}
  col_1: predicted=ORGANIZATION, expected=CREDENTIAL, engines={'column_name': [], 'regex': []}
  col_0: predicted=PERSON_NAME, expected=ADDRESS, engines={'column_name': [], 'regex': ['DATE_OF_BIRTH']}
  col_1: predicted=PERSON_NAME, expected=CREDENTIAL, engines={'column_name': [], 'regex': []}
  col_3: predicted=PERSON_NAME, expected=EMAIL, engines={'column_name': [], 'regex': ['EMAIL']}
  col_7: predicted=PERSON_NAME, expected=SSN, engines={'column_name': [], 'regex': ['PHONE', 'SSN', 'ABA_ROUTING', 'CANADIAN_SIN', 'NPI', 'IP_ADDRESS', 'HEALTH']}
  col_7: predicted=PHONE, expected=SSN, engines={'column_name': [], 'regex': ['PHONE', 'SSN', 'ABA_ROUTING', 'CANADIAN_SIN', 'NPI', 'IP_ADDRESS', 'HEALTH']}

FALSE NEGATIVES
----------------------------------------------------------------------
  col_1: expected=CREDENTIAL, got=['PERSON_NAME', 'ORGANIZATION']
  col_7: expected=SSN, got=['PHONE', 'PERSON_NAME', 'IP_ADDRESS']
```

## Secret Detection Detail

```
======================================================================
SECRET DETECTION BENCHMARK
======================================================================

CORPUS
  Total samples:      1347
  True positives:     586 samples (regex: 19, scanner_definitive: 13, scanner_strong: 7, scanner_contextual: 1, known_limitation: 1, external: 545)
  True negatives:     761 samples (ambiguous: 3, near_miss_keys: 16, word_boundary: 8, placeholder: 5, nonsecret: 10, high_entropy: 8, encoded: 5, plain: 8, edge: 6, external: 692)
  Sources:            builtin: 102, detect_secrets: 8, gitleaks: 170, secretbench: 1067

PER-LAYER RESULTS
----------------------------------------------------------------------
Layer                      TP   FP   FN      Prec  Recall        F1
----------------------------------------------------------------------
regex                      18    0    1     1.000   0.947     0.973
scanner_definitive         12    0    1     1.000   0.923     0.960
scanner_strong              7    0    0     1.000   1.000     1.000
scanner_contextual          1    0    0     1.000   1.000     1.000
known_limitation            0    0    1     0.000   0.000     0.000
external                  140  294  405     0.323   0.257     0.286
----------------------------------------------------------------------
OVERALL                   178  294  408     0.377   0.304     0.336

FALSE POSITIVE BREAKDOWN
----------------------------------------------------------------------
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench

FALSE NEGATIVE BREAKDOWN
----------------------------------------------------------------------
  AWS access key (detect-secrets)
  Password in connection URL (detect-secrets)
  MongoDB connection string with credentials — needs URI parser (Layer 3)
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: gitleaks
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench
  External: secretbench

PER-SOURCE BREAKDOWN
----------------------------------------------------------------------
Source                Total     TP     FP     FN     TN
----------------------------------------------------------------------
builtin                 102     33      0      1     68
detect_secrets            8      5      0      2      1
gitleaks                170     12     36     17    105
secretbench            1067    128    258    388    293
```

## Performance Detail

```
======================================================================
PERFORMANCE BENCHMARK REPORT
======================================================================

DATA PROCESSED
  Columns:             8
  Total samples:       4000
  Avg samples/column:  500
  Iterations:          30
  Warmup:              2269.13 ms

FULL PIPELINE LATENCY
----------------------------------------------------------------------
  Total (all columns)  p50=26670.56 ms  p95=40909.14 ms  p99=53697.81 ms
  Per column           p50=3333.820 ms
  Per sample           p50=6667.6 us
  Throughput           0 columns/sec  |  150 samples/sec

PER-ENGINE BREAKDOWN
----------------------------------------------------------------------
  column_name          total_p50=0.02 ms  per_col=0.002 ms  (0% of pipeline)
  heuristic_stats      total_p50=0.77 ms  per_col=0.097 ms  (0% of pipeline)
  regex                total_p50=12.88 ms  per_col=1.610 ms  (0% of pipeline)
  secret_scanner       total_p50=89.29 ms  per_col=11.162 ms  (0% of pipeline)

PER-ENGINE BY INPUT TYPE (ms, 100 samples)
----------------------------------------------------------------------
  Input Type             column_name           regex heuristic_stats  secret_scanner
  plain_digits                0.004ms          0.561ms          0.015ms          1.823ms
  plain_text                  0.003ms          0.045ms          0.018ms          1.867ms
  kv_json                     0.004ms          0.049ms          0.018ms          1.596ms
  kv_env                      0.003ms          0.050ms          0.017ms          7.582ms

ENGINE TELEMETRY (single run)
----------------------------------------------------------------------
  column_name          calls=8  hits=0  misses=8  total=0.16ms  mean=0.020ms  max=0.030ms
  regex                calls=8  hits=6  misses=2  total=13.18ms  mean=1.647ms  max=6.510ms
  heuristic_stats      calls=8  hits=0  misses=8  total=0.98ms  mean=0.122ms  max=0.140ms
  secret_scanner       calls=8  hits=0  misses=8  total=90.83ms  mean=11.354ms  max=12.620ms
  gliner2              calls=8  hits=5  misses=3  total=27053.61ms  mean=3381.701ms  max=6604.440ms

SCALING: SAMPLE COUNT (per-column latency vs samples/column)
----------------------------------------------------------------------
     10 samples → 147.596 ms/col  ########################################
     50 samples → 395.901 ms/col  ########################################
    100 samples → 700.518 ms/col  ########################################
    500 samples → 3760.630 ms/col  ########################################

SCALING: INPUT LENGTH (RE2 time vs string length, single sample)
----------------------------------------------------------------------
      51 bytes → p50=2.4 us  p99=5174.7 us  (1.0x)  ###
     101 bytes → p50=2.5 us  p99=50.8 us  (1.1x)  ###
     501 bytes → p50=3.9 us  p99=116.3 us  (1.6x)  ####
    1001 bytes → p50=5.8 us  p99=159.4 us  (2.5x)  #######
    5001 bytes → p50=159.5 us  p99=599.0 us  (67.1x)  ########################################
   10001 bytes → p50=305.8 us  p99=730.2 us  (128.7x)  ########################################
   50001 bytes → p50=1585.1 us  p99=2776.8 us  (667.4x)  ########################################

DIRECT PATTERN MATCHING (regex engine on mixed-PII text)
----------------------------------------------------------------------
  Patterns compiled:   71
  Input:               100 samples × 230 chars
  Total time:          2.05 ms
  Per sample:          20.5 us
  Findings:            3 (EMAIL, IP_ADDRESS, SWIFT_BIC)

======================================================================
```
