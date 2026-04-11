# Sprint 4 — Benchmark Report

> **Generated:** 2026-04-11 17:10 UTC
> **Samples per type:** 100
> **Patterns:** 71
> **Entity types (patterns):** 22
> **Corpus source:** synthetic

## Summary

| Metric | Pattern-Level (regex only) | Column-Level (full pipeline) |
|---|---|---|
| Total samples | 2,500 | 3,700 |
| Positive / Negative | 2,200 / 300 | 27 cols / 10 cols |
| Precision | 0.837 | 0.893 |
| Recall | 0.819 | 0.926 |
| **Micro F1** | **0.827** | **0.909** |
| **Macro F1** | — | **0.870** |
| **Primary-Label Accuracy** | — | **92.6%** |
| TP / FP / FN | 1,801 / 352 / 399 | 25 / 3 / 2 |

### Secret Detection

| Metric | Value |
|---|---|
| Precision | 0.372 |
| Recall | 0.304 |
| **F1** | **0.335** |

### Per-Entity F1 Breakdown (Column-Level)

| Entity Type | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| ABA_ROUTING | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| ADDRESS | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| BITCOIN_ADDRESS | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| CANADIAN_SIN | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| CREDIT_CARD | 1.000 | 1.000 | 1.000 | 2 | 0 | 0 |
| DATE_OF_BIRTH | 0.500 | 1.000 | 0.667 | 1 | 1 | 0 |
| DATE_OF_BIRTH_EU | 0.000 | 0.000 | 0.000 | 0 | 0 | 1 |
| DEA_NUMBER | 0.000 | 0.000 | 0.000 | 0 | 0 | 1 |
| EIN | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| EMAIL | 1.000 | 1.000 | 1.000 | 2 | 0 | 0 |
| ETHEREUM_ADDRESS | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| IBAN | 0.500 | 1.000 | 0.667 | 1 | 1 | 0 |
| IP_ADDRESS | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| MAC_ADDRESS | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| MBI | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| NPI | 1.000 | 1.000 | 1.000 | 2 | 0 | 0 |
| PERSON_NAME | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| PHONE | 1.000 | 1.000 | 1.000 | 2 | 0 | 0 |
| SSN | 0.667 | 1.000 | 0.800 | 2 | 1 | 0 |
| SWIFT_BIC | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| URL | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |
| VIN | 1.000 | 1.000 | 1.000 | 1 | 0 | 0 |

### Corpus Metadata

| Property | Value |
|---|---|
| Source | synthetic |
| Pattern samples | 2,500 (2,200 positive, 300 negative) |
| Column corpus | 37 columns (3,700 total samples) |
| Entity types tested | 22 |

## Performance

| Metric | Value |
|---|---|
| Throughput | 312 columns/sec \| 31,213 samples/sec |
| Per column (p50) | 3.204 ms |
| Per sample (p50) | 32.0 us |
| Warmup (RE2 compile) | 2.7 ms |

### Scaling

**Sample count scaling (per-column latency):**

| Samples/col | Latency (p50) |
|---|---|
| 10 | 0.366 ms |
| 50 | 1.601 ms |
| 100 | 3.057 ms |
| 500 | 14.858 ms |

**Input length scaling (RE2 linearity):**

| Input bytes | p50 (us) | Ratio |
|---|---|---|
| 51 | 2.3 | 1.0x |
| 101 | 2.5 | 1.1x |
| 501 | 3.9 | 1.7x |
| 1,001 | 5.5 | 2.4x |
| 5,001 | 169.2 | 73.8x |
| 10,001 | 311.6 | 135.9x |
| 50,001 | 1616.5 | 705.3x |

## Pattern-Level Detail

```
==============================================================================
PATTERN MATCHING BENCHMARK (regex engine, per-sample)
==============================================================================

CORPUS
  Total samples:      2,500
  Positive samples:   2,200 (22 entity types)
  Negative samples:   300

SAMPLE-LEVEL DETECTION ACCURACY
------------------------------------------------------------------------------
Entity Type                TP     FP     FN     Prec   Recall       F1
------------------------------------------------------------------------------
ABA_ROUTING               100     12      0    0.893    1.000    0.943
ADDRESS                     0      0    100    0.000    0.000    0.000
BITCOIN_ADDRESS           100      0      0    1.000    1.000    1.000
CANADIAN_SIN              100     10      0    0.909    1.000    0.952
CREDIT_CARD                64      0     36    1.000    0.640    0.780
DATE_OF_BIRTH             100    100      0    0.500    1.000    0.667
DATE_OF_BIRTH_EU            0      0    100    0.000    0.000    0.000
DEA_NUMBER                100      0      0    1.000    1.000    1.000
EIN                       100      0      0    1.000    1.000    1.000
EMAIL                     100      0      0    1.000    1.000    1.000
ETHEREUM_ADDRESS          100      0      0    1.000    1.000    1.000
IBAN                      100      1      0    0.990    1.000    0.995
IP_ADDRESS                100      0      0    1.000    1.000    1.000
MAC_ADDRESS               100      0      0    1.000    1.000    1.000
MBI                       100      0      0    1.000    1.000    1.000
NPI                       100      0      0    1.000    1.000    1.000
PERSON_NAME                 0      0    100    0.000    0.000    0.000
PHONE                      37    100     63    0.270    0.370    0.312
SSN                       100    129      0    0.437    1.000    0.608
SWIFT_BIC                 100      0      0    1.000    1.000    1.000
URL                       100      0      0    1.000    1.000    1.000
VIN                       100      0      0    1.000    1.000    1.000
------------------------------------------------------------------------------
OVERALL                  1801    352    399    0.837    0.819    0.827

PER-PATTERN MATCH RATES (patterns with test data)
------------------------------------------------------------------------------
  Pattern                        Entity                Matched      Valid    ValFail
  ------------------------------ ------------------ ---------- ---------- ----------
  aba_routing                    ABA_ROUTING           100(100%)        100          0
  bitcoin_address                BITCOIN_ADDRESS       100(100%)        100          0
  canadian_sin                   CANADIAN_SIN          100(100%)        100          0
  credit_card_amex               CREDIT_CARD            15(15%)         15          0
  credit_card_discover           CREDIT_CARD             4(4%)          4          0
  credit_card_formatted          CREDIT_CARD            35(35%)         35          0
  credit_card_mastercard         CREDIT_CARD             1(1%)          1          0
  credit_card_visa               CREDIT_CARD             9(9%)          9          0
  date_iso_format                DATE_OF_BIRTH           0(0%)          0          0
  date_of_birth_format           DATE_OF_BIRTH         100(100%)        100          0
  dob_european                   DATE_OF_BIRTH          41(41%)         41          0
  dob_long_format                DATE_OF_BIRTH           0(0%)          0          0
  email_address                  EMAIL                 100(100%)        100          0
  ethereum_address               ETHEREUM_ADDRESS      100(100%)        100          0
  iban                           IBAN                  100(100%)        100          0
  international_phone            PHONE                   0(0%)          0          0
  ipv4_address                   IP_ADDRESS            100(100%)        100          0
  ipv6_address                   IP_ADDRESS              0(0%)          0          0
  mac_address                    MAC_ADDRESS           100(100%)        100          0
  swift_bic                      SWIFT_BIC             100(100%)        100          0
  url                            URL                   100(100%)        100          0
  us_dea                         DEA_NUMBER            100(100%)        100          0
  us_ein                         EIN                   100(100%)        100          0
  us_mbi                         MBI                   100(100%)        100          0
  us_npi                         NPI                   100(100%)        100          0
  us_phone_formatted             PHONE                  37(37%)         37          0
  us_ssn_formatted               SSN                    71(71%)         71          0
  us_ssn_no_dashes               SSN                    29(29%)         29          0
  vin                            VIN                   100(100%)        100          0

CROSS-PATTERN COLLISIONS (same value triggers multiple entity types)
------------------------------------------------------------------------------
  ABA_ROUTING            also triggers CANADIAN_SIN           (16 samples)
  ABA_ROUTING            also triggers SSN                    (110 samples)
  CANADIAN_SIN           also triggers ABA_ROUTING            (16 samples)
  CANADIAN_SIN           also triggers SSN                    (41 samples)
  DEA_NUMBER             also triggers IBAN                   (1 samples)
  IBAN                   also triggers DEA_NUMBER             (1 samples)
  NPI                    also triggers PHONE                  (100 samples)
  PHONE                  also triggers NPI                    (100 samples)
  SSN                    also triggers ABA_ROUTING            (110 samples)
  SSN                    also triggers CANADIAN_SIN           (41 samples)

MISSED SAMPLES (expected match, got nothing — up to 10 per type)
------------------------------------------------------------------------------
  ADDRESS (100 missed):
    '6384 Travis Manor Apt. 931\nShawnport, PR 12532'
    '06351 Donald Parkways Suite 502\nMatthewsfort, MD 19881'
    '856 Anna Union\nMonicamouth, CT 72507'
    '86040 King Camp\nEast Kimberlystad, AL 93383'
    '5223 Braun Dale Suite 414\nDanielmouth, KS 60899'
  CREDIT_CARD (36 missed):
    '588431713860'
    '2611795211366390'
    '30269331173687'
    '060410824357'
    '30442346651845'
  DATE_OF_BIRTH_EU (100 missed):
    '25/08/2001'
    '03/05/1930'
    '17/10/2004'
    '12/01/1966'
    '28/06/1976'
  PERSON_NAME (100 missed):
    'Mary Cochran'
    'Christopher Smith'
    'Michael Brown'
    'Tammy Shannon'
    'Parker Davis'
  PHONE (63 missed):
    '678-902-4436x52129'
    '(303)706-8630x6499'
    '(354)421-6437x96541'
    '658-570-7073x21983'
    '799-269-3587x70625'

FALSE POSITIVE EXAMPLES (up to 5 per type)
------------------------------------------------------------------------------
  ABA_ROUTING (12 FPs):
    '531662137' (expected=SSN)
    '453204576' (expected=SSN)
    '564784697' (expected=SSN)
    '387242743' (expected=SSN)
    '672948338' (expected=CANADIAN_SIN)
  CANADIAN_SIN (10 FPs):
    '020127098' (expected=SSN)
    '552701229' (expected=SSN)
    '915980163' (expected=ABA_ROUTING)
    '691420756' (expected=ABA_ROUTING)
    '403919905' (expected=ABA_ROUTING)
  DATE_OF_BIRTH (100 FPs):
    '25/08/2001' (expected=DATE_OF_BIRTH_EU)
    '03/05/1930' (expected=DATE_OF_BIRTH_EU)
    '17/10/2004' (expected=DATE_OF_BIRTH_EU)
    '12/01/1966' (expected=DATE_OF_BIRTH_EU)
    '28/06/1976' (expected=DATE_OF_BIRTH_EU)
  IBAN (1 FPs):
    'FQ9300233' (expected=DEA_NUMBER)
  PHONE (100 FPs):
    '1917552097' (expected=NPI)
    '2057127450' (expected=NPI)
    '2164167480' (expected=NPI)
    '1421367321' (expected=NPI)
    '1773977966' (expected=NPI)
  SSN (129 FPs):
    '268434492' (expected=ABA_ROUTING)
    '947960436' (expected=ABA_ROUTING)
    '309740650' (expected=ABA_ROUTING)
    '038200872' (expected=ABA_ROUTING)
    '822741408' (expected=ABA_ROUTING)

==============================================================================
```

## Column-Level Detail

```
======================================================================
ACCURACY BENCHMARK REPORT
======================================================================

KEY METRICS
----------------------------------------------------------------------
  Macro F1:                0.870
  Micro F1:                0.909
  Primary-Label Accuracy:  92.6%
  Corpus Source:           synthetic

CORPUS STATISTICS
  Total columns:      37
  Positive columns:   27 (22 entity types)
  Negative columns:   10
  Total samples:      3700
  Avg samples/column: 100

SAMPLE-LEVEL SUMMARY
----------------------------------------------------------------------
  Positive samples:     2,700
  Negative samples:     1,000
  Samples scanned:      2,700
  Samples matched:      2,500 (92.6%)
  Samples validated:    2,500 (100.0% of matched)

  Entity Type               Matched    Scanned      Valid     Conf          Via
  ---------------------- ---------- ---------- ---------- -------- ------------
  SSN                        100(100%)        100        100    0.950  column_name
  SSN                        100(100%)        100        100    0.950  column_name
  EMAIL                      100(100%)        100        100    0.997        regex
  EMAIL                      100(100%)        100        100    0.997        regex
  PHONE                      100(100%)        100        100    0.900  column_name
  PHONE                      100(100%)        100        100    0.900  column_name
  CREDIT_CARD                100(100%)        100        100    0.950  column_name
  CREDIT_CARD                100(100%)        100        100    0.950  column_name
  DATE_OF_BIRTH              100(100%)        100        100    0.900  column_name
  IP_ADDRESS                 100(100%)        100        100    0.945        regex
  URL                        100(100%)        100        100    0.945        regex
  PERSON_NAME                100(100%)        100        100    0.637  column_name
  ADDRESS                    100(100%)        100        100    0.800  column_name
  IBAN                       100(100%)        100        100    0.900  column_name
  SWIFT_BIC                  100(100%)        100        100    0.945        regex
  EIN                        100(100%)        100        100    0.850  column_name
  VIN                        100(100%)        100        100    0.892        regex
  BITCOIN_ADDRESS            100(100%)        100        100    0.945        regex
  ETHEREUM_ADDRESS           100(100%)        100        100    0.945        regex
  NPI                        100(100%)        100        100    0.900  column_name
  NPI                        100(100%)        100        100    0.900  column_name
  DEA_NUMBER                   0(0%)        100          0    0.000       MISSED
  MBI                        100(100%)        100        100    0.945        regex
  ABA_ROUTING                100(100%)        100        100    0.900  column_name
  CANADIAN_SIN               100(100%)        100        100    0.900  column_name
  MAC_ADDRESS                100(100%)        100        100    0.945        regex
  DATE_OF_BIRTH_EU             0(0%)        100          0    0.000       MISSED

COLUMN-LEVEL ACCURACY (did the column get the correct entity label?)
----------------------------------------------------------------------
Entity Type              TP   FP   FN     Prec   Recall       F1
----------------------------------------------------------------------
ABA_ROUTING               1    0    0    1.000    1.000    1.000
ADDRESS                   1    0    0    1.000    1.000    1.000
BITCOIN_ADDRESS           1    0    0    1.000    1.000    1.000
CANADIAN_SIN              1    0    0    1.000    1.000    1.000
CREDIT_CARD               2    0    0    1.000    1.000    1.000
DATE_OF_BIRTH             1    1    0    0.500    1.000    0.667
DATE_OF_BIRTH_EU          0    0    1    0.000    0.000    0.000
DEA_NUMBER                0    0    1    0.000    0.000    0.000
EIN                       1    0    0    1.000    1.000    1.000
EMAIL                     2    0    0    1.000    1.000    1.000
ETHEREUM_ADDRESS          1    0    0    1.000    1.000    1.000
IBAN                      1    1    0    0.500    1.000    0.667
IP_ADDRESS                1    0    0    1.000    1.000    1.000
MAC_ADDRESS               1    0    0    1.000    1.000    1.000
MBI                       1    0    0    1.000    1.000    1.000
NPI                       2    0    0    1.000    1.000    1.000
PERSON_NAME               1    0    0    1.000    1.000    1.000
PHONE                     2    0    0    1.000    1.000    1.000
SSN                       2    1    0    0.667    1.000    0.800
SWIFT_BIC                 1    0    0    1.000    1.000    1.000
URL                       1    0    0    1.000    1.000    1.000
VIN                       1    0    0    1.000    1.000    1.000
----------------------------------------------------------------------
OVERALL                  25    3    2    0.893    0.926    0.909

ENGINE CONTRIBUTIONS
----------------------------------------------------------------------
Column                            Column Name Eng          Regex Eng
----------------------------------------------------------------------
  SSN (test_ssn_column)                       SSN SSN, ABA_ROUTING, CANADIAN_SIN
  SSN (test_ssn_notes)                        SSN SSN, ABA_ROUTING, CANADIAN_SIN
  EMAIL (test_email_colu)                   EMAIL              EMAIL
  EMAIL (test_email_note)                   EMAIL              EMAIL
  PHONE (test_phone_colu)                   PHONE              PHONE
  PHONE (test_phone_note)                   PHONE              PHONE
  CREDIT_CARD (test_credit_car)        CREDIT_CARD        CREDIT_CARD
  CREDIT_CARD (test_credit_car)        CREDIT_CARD        CREDIT_CARD
  DATE_OF_BIRTH (test_dob_column)      DATE_OF_BIRTH      DATE_OF_BIRTH
  IP_ADDRESS (test_ip_column)          IP_ADDRESS         IP_ADDRESS
  URL (test_url_column)                       URL                URL
  PERSON_NAME (test_person_nam)        PERSON_NAME                  -
  ADDRESS (test_address_co)               ADDRESS            ADDRESS
  IBAN (test_iban_colum)                     IBAN               IBAN
  SWIFT_BIC (test_swift_colu)           SWIFT_BIC          SWIFT_BIC
  EIN (test_ein_column)                       EIN                EIN
  VIN (test_vin_column)                       VIN                VIN
  BITCOIN_ADDRESS (test_bitcoin_co)                  -    BITCOIN_ADDRESS
  ETHEREUM_ADDRESS (test_ethereum_c)                  -   ETHEREUM_ADDRESS
  NPI (test_npi_column)                       NPI         NPI, PHONE
  NPI (test_npi_notes)                        NPI         NPI, PHONE
  DEA_NUMBER (test_dea_column)         DEA_NUMBER   DEA_NUMBER, IBAN
  MBI (test_mbi_column)                       MBI                MBI
  ABA_ROUTING (test_aba_column)        ABA_ROUTING ABA_ROUTING, SSN, CANADIAN_SIN
  CANADIAN_SIN (test_sin_column)       CANADIAN_SIN CANADIAN_SIN, SSN, ABA_ROUTING
  MAC_ADDRESS (test_mac_column)                  -        MAC_ADDRESS
  DATE_OF_BIRTH_EU (test_dob_eu_col)      DATE_OF_BIRTH      DATE_OF_BIRTH

SAMPLE-LEVEL DETECTION
----------------------------------------------------------------------
  SSN                  via column name  confidence=0.950
  SSN                  via column name  confidence=0.950
  EMAIL                matched=100/100 (100%)  validated=100/100  confidence=0.997
  EMAIL                matched=100/100 (100%)  validated=100/100  confidence=0.997
  PHONE                via column name  confidence=0.900
  PHONE                via column name  confidence=0.900
  CREDIT_CARD          via column name  confidence=0.950
  CREDIT_CARD          via column name  confidence=0.950
  DATE_OF_BIRTH        via column name  confidence=0.900
  IP_ADDRESS           matched=100/100 (100%)  validated=100/100  confidence=0.945
  URL                  matched=100/100 (100%)  validated=100/100  confidence=0.945
  PERSON_NAME          via column name  confidence=0.637
  ADDRESS              via column name  confidence=0.800
  IBAN                 via column name  confidence=0.900
  SWIFT_BIC            matched=100/100 (100%)  validated=100/100  confidence=0.945
  EIN                  via column name  confidence=0.850
  VIN                  matched=100/100 (100%)  validated=100/100  confidence=0.892
  BITCOIN_ADDRESS      matched=100/100 (100%)  validated=100/100  confidence=0.945
  ETHEREUM_ADDRESS     matched=100/100 (100%)  validated=100/100  confidence=0.945
  NPI                  via column name  confidence=0.900
  NPI                  via column name  confidence=0.900
  DEA_NUMBER           NOT DETECTED
  MBI                  matched=100/100 (100%)  validated=100/100  confidence=0.945
  ABA_ROUTING          via column name  confidence=0.900
  CANADIAN_SIN         via column name  confidence=0.900
  MAC_ADDRESS          matched=100/100 (100%)  validated=100/100  confidence=0.945
  DATE_OF_BIRTH_EU     NOT DETECTED

FALSE POSITIVES
----------------------------------------------------------------------
  corpus_DATE_OF_BIRTH_EU_0: predicted=DATE_OF_BIRTH, expected=DATE_OF_BIRTH_EU, engines={'column_name': ['DATE_OF_BIRTH'], 'regex': ['DATE_OF_BIRTH']}
  corpus_DEA_NUMBER_0: predicted=IBAN, expected=DEA_NUMBER, engines={'column_name': ['DEA_NUMBER'], 'regex': ['DEA_NUMBER', 'IBAN']}
  corpus_none_numeric_ids_0: predicted=SSN, expected=None, engines={'column_name': [], 'regex': ['SSN', 'ABA_ROUTING', 'CANADIAN_SIN']}

FALSE NEGATIVES
----------------------------------------------------------------------
  corpus_DATE_OF_BIRTH_EU_0: expected=DATE_OF_BIRTH_EU, got=['DATE_OF_BIRTH']
  corpus_DEA_NUMBER_0: expected=DEA_NUMBER, got=['IBAN']
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
external                  140  300  405     0.318   0.257     0.284
----------------------------------------------------------------------
OVERALL                   178  300  408     0.372   0.304     0.335

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
gitleaks                170     12     37     17    104
secretbench            1067    128    263    388    288
```

## Performance Detail

```
======================================================================
PERFORMANCE BENCHMARK REPORT
======================================================================

DATA PROCESSED
  Columns:             37
  Total samples:       3700
  Avg samples/column:  100
  Iterations:          30
  Warmup:              2.75 ms

FULL PIPELINE LATENCY
----------------------------------------------------------------------
  Total (all columns)  p50=118.54 ms  p95=120.54 ms  p99=122.94 ms
  Per column           p50=3.204 ms
  Per sample           p50=32.0 us
  Throughput           312 columns/sec  |  31213 samples/sec

PER-ENGINE BREAKDOWN
----------------------------------------------------------------------
  column_name          total_p50=0.14 ms  per_col=0.004 ms  (0% of pipeline)
  heuristic_stats      total_p50=0.78 ms  per_col=0.021 ms  (1% of pipeline)
  regex                total_p50=15.72 ms  per_col=0.425 ms  (13% of pipeline)
  secret_scanner       total_p50=97.33 ms  per_col=2.630 ms  (82% of pipeline)

PER-ENGINE BY INPUT TYPE (ms, 100 samples)
----------------------------------------------------------------------
  Input Type             column_name           regex heuristic_stats  secret_scanner
  plain_digits                0.003ms          0.607ms          0.015ms          1.893ms
  plain_text                  0.003ms          0.049ms          0.019ms          1.951ms
  kv_json                     0.003ms          0.060ms          0.016ms          1.626ms
  kv_env                      0.003ms          0.051ms          0.017ms          7.954ms

ENGINE TELEMETRY (single run)
----------------------------------------------------------------------
  column_name          calls=37  hits=24  misses=13  total=0.46ms  mean=0.012ms  max=0.030ms
  regex                calls=37  hits=27  misses=10  total=16.24ms  mean=0.439ms  max=3.160ms
  heuristic_stats      calls=37  hits=1  misses=36  total=1.01ms  mean=0.027ms  max=0.050ms
  secret_scanner       calls=37  hits=0  misses=37  total=98.01ms  mean=2.649ms  max=6.750ms

SCALING: SAMPLE COUNT (per-column latency vs samples/column)
----------------------------------------------------------------------
     10 samples → 0.366 ms/col  ####################################
     50 samples → 1.601 ms/col  ########################################
    100 samples → 3.057 ms/col  ########################################
    500 samples → 14.858 ms/col  ########################################

SCALING: INPUT LENGTH (RE2 time vs string length, single sample)
----------------------------------------------------------------------
      51 bytes → p50=2.3 us  p99=3800.2 us  (1.0x)  ###
     101 bytes → p50=2.5 us  p99=39.2 us  (1.1x)  ###
     501 bytes → p50=3.9 us  p99=123.3 us  (1.7x)  #####
    1001 bytes → p50=5.5 us  p99=151.6 us  (2.4x)  #######
    5001 bytes → p50=169.2 us  p99=626.0 us  (73.8x)  ########################################
   10001 bytes → p50=311.6 us  p99=901.6 us  (135.9x)  ########################################
   50001 bytes → p50=1616.5 us  p99=2971.0 us  (705.3x)  ########################################

DIRECT PATTERN MATCHING (regex engine on mixed-PII text)
----------------------------------------------------------------------
  Patterns compiled:   71
  Input:               100 samples × 233 chars
  Total time:          2.28 ms
  Per sample:          22.8 us
  Findings:            3 (EMAIL, IP_ADDRESS, SWIFT_BIC)

======================================================================
```
