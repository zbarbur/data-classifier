# Sprint 2 — Benchmark Report

> **Generated:** 2026-04-10 20:47 UTC
> **Samples per type:** 500
> **Patterns:** 59
> **Entity types (patterns):** 22

## Summary

| Metric | Pattern-Level (regex only) | Column-Level (full pipeline) |
|---|---|---|
| Total samples | 12,500 | 18,500 |
| Positive / Negative | 11,000 / 1,500 | 27 cols / 10 cols |
| Precision | 0.831 | 0.634 |
| Recall | 0.758 | 0.963 |
| **F1** | **0.793** | **0.765** |
| TP / FP / FN | 8,336 / 1,690 / 2,664 | 26 / 15 / 1 |

## Performance

| Metric | Value |
|---|---|
| Throughput | 726 columns/sec \| 362,837 samples/sec |
| Per column (p50) | 1.378 ms |
| Per sample (p50) | 2.8 us |
| Warmup (RE2 compile) | 1.6 ms |

### Scaling

**Sample count scaling (per-column latency):**

| Samples/col | Latency (p50) |
|---|---|
| 10 | 0.051 ms |
| 50 | 0.184 ms |
| 100 | 0.320 ms |
| 500 | 1.479 ms |

**Input length scaling (RE2 linearity):**

| Input bytes | p50 (us) | Ratio |
|---|---|---|
| 51 | 2.3 | 1.0x |
| 101 | 2.4 | 1.1x |
| 501 | 4.7 | 2.0x |
| 1,001 | 5.7 | 2.5x |
| 5,001 | 26.6 | 11.6x |
| 10,001 | 46.9 | 20.5x |
| 50,001 | 216.5 | 94.4x |

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
CANADIAN_SIN                0     10    500    0.000    0.000    0.000
CREDIT_CARD               301      0    199    1.000    0.602    0.752
DATE_OF_BIRTH             500    500      0    0.500    1.000    0.667
DATE_OF_BIRTH_EU            0      0    500    0.000    0.000    0.000
DEA_NUMBER                500      0      0    1.000    1.000    1.000
EIN                       500      0      0    1.000    1.000    1.000
EMAIL                     500      0      0    1.000    1.000    1.000
ETHEREUM_ADDRESS          500      0      0    1.000    1.000    1.000
IBAN                      500      3      0    0.994    1.000    0.997
IP_ADDRESS                500      0      0    1.000    1.000    1.000
MAC_ADDRESS               500      0      0    1.000    1.000    1.000
MBI                       500      0      0    1.000    1.000    1.000
NPI                       500      1      0    0.998    1.000    0.999
PERSON_NAME                 0      0    500    0.000    0.000    0.000
PHONE                     182    500    318    0.267    0.364    0.308
SSN                       500    649      0    0.435    1.000    0.606
SWIFT_BIC                 500      0      0    1.000    1.000    1.000
URL                       500      0      0    1.000    1.000    1.000
VIN                       353      0    147    1.000    0.706    0.828
------------------------------------------------------------------------------
OVERALL                  8336   1690   2664    0.831    0.758    0.793

PER-PATTERN MATCH RATES (patterns with test data)
------------------------------------------------------------------------------
  Pattern                        Entity                Matched      Valid    ValFail
  ------------------------------ ------------------ ---------- ---------- ----------
  aba_routing                    ABA_ROUTING           500(100%)        500          0
  bitcoin_address                BITCOIN_ADDRESS       500(100%)        500          0
  canadian_sin                   CANADIAN_SIN          500(100%)          0        500
  credit_card_amex               CREDIT_CARD            28(6%)         28          0
  credit_card_discover           CREDIT_CARD            20(4%)         20          0
  credit_card_formatted          CREDIT_CARD           181(36%)        181          0
  credit_card_mastercard         CREDIT_CARD             3(1%)          3          0
  credit_card_visa               CREDIT_CARD            69(14%)         69          0
  date_iso_format                DATE_OF_BIRTH           0(0%)          0          0
  date_of_birth_format           DATE_OF_BIRTH         500(100%)        500          0
  dob_european                   DATE_OF_BIRTH         201(40%)        201          0
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
  us_phone_formatted             PHONE                 204(41%)        182         22
  us_ssn_formatted               SSN                   364(73%)        364          0
  us_ssn_no_dashes               SSN                   136(27%)        136          0
  vin                            VIN                   500(100%)        353        147

CROSS-PATTERN COLLISIONS (same value triggers multiple entity types)
------------------------------------------------------------------------------
  ABA_ROUTING            also triggers SSN                    (521 samples)
  DEA_NUMBER             also triggers IBAN                   (3 samples)
  IBAN                   also triggers DEA_NUMBER             (3 samples)
  NPI                    also triggers PHONE                  (501 samples)
  PHONE                  also triggers NPI                    (501 samples)
  SSN                    also triggers ABA_ROUTING            (521 samples)

MISSED SAMPLES (expected match, got nothing — up to 10 per type)
------------------------------------------------------------------------------
  ADDRESS (500 missed):
    '870 Cummings Hills Apt. 603\nGallagherstad, NC 27495'
    '916 Kramer Loaf\nSouth Annburgh, IL 59072'
    '61316 Christie Glens\nPeterview, TX 25938'
    '28388 Whitehead Forge Apt. 770\nNorth Thomas, OH 43687'
    '081 Jesse Islands\nNorth Timothyside, MT 74051'
  CANADIAN_SIN (500 missed):
    '480 279 702'
    '352-868-814'
    '109172478'
    '511143091'
    '410 217 384'
  CREDIT_CARD (199 missed):
    '4603344197898702366'
    '180061722226440'
    '30556673267303'
    '30019713377913'
    '4153558867498128116'
  DATE_OF_BIRTH_EU (500 missed):
    '18/01/1999'
    '09/09/1951'
    '22/12/1955'
    '29/10/1939'
    '26/10/1981'
  PERSON_NAME (500 missed):
    'Leroy Brooks'
    'Stephen Suarez'
    'Melissa Hansen'
    'Taylor Davis'
    'Peggy Guerrero'
  PHONE (318 missed):
    '001-506-347-9207'
    '001-893-652-6392x141'
    '(317)785-8414x4768'
    '+1-279-456-4393x25559'
    '001-879-850-4391x1536'
  VIN (147 missed):
    'WVWZZZ3CZWE123456'
    'WVWZZZ3CZWE123456'
    'WVWZZZ3CZWE123456'
    'WVWZZZ3CZWE123456'
    'WVWZZZ3CZWE123456'

FALSE POSITIVE EXAMPLES (up to 5 per type)
------------------------------------------------------------------------------
  ABA_ROUTING (27 FPs):
    '440721392' (expected=SSN)
    '184300299' (expected=SSN)
    '869929717' (expected=SSN)
    '291865494' (expected=SSN)
    '279429917' (expected=SSN)
  CANADIAN_SIN (10 FPs):
    '001-402-328-4368' (expected=PHONE)
    '001-345-901-6518x931' (expected=PHONE)
    '001-986-968-2911x828' (expected=PHONE)
    '001-817-776-6431x38502' (expected=PHONE)
    '001-327-896-9533' (expected=PHONE)
  DATE_OF_BIRTH (500 FPs):
    '18/01/1999' (expected=DATE_OF_BIRTH_EU)
    '09/09/1951' (expected=DATE_OF_BIRTH_EU)
    '22/12/1955' (expected=DATE_OF_BIRTH_EU)
    '29/10/1939' (expected=DATE_OF_BIRTH_EU)
    '26/10/1981' (expected=DATE_OF_BIRTH_EU)
  IBAN (3 FPs):
    'GE8691734' (expected=DEA_NUMBER)
    'PY4547254' (expected=DEA_NUMBER)
    'MZ0390928' (expected=DEA_NUMBER)
  NPI (1 FPs):
    '2168744573' (expected=PHONE)
  PHONE (500 FPs):
    '2425634641' (expected=NPI)
    '2900616089' (expected=NPI)
    '1343535799' (expected=NPI)
    '2221173992' (expected=NPI)
    '2871848778' (expected=NPI)
  SSN (649 FPs):
    '577722183' (expected=ABA_ROUTING)
    '940803561' (expected=ABA_ROUTING)
    '357842610' (expected=ABA_ROUTING)
    '599749102' (expected=ABA_ROUTING)
    '798617705' (expected=ABA_ROUTING)

==============================================================================
```

## Column-Level Detail

```
======================================================================
ACCURACY BENCHMARK REPORT
======================================================================

CORPUS STATISTICS
  Total columns:      37
  Positive columns:   27 (22 entity types)
  Negative columns:   10
  Total samples:      18500
  Avg samples/column: 500

SAMPLE-LEVEL SUMMARY
----------------------------------------------------------------------
  Positive samples:     13,500
  Negative samples:     5,000
  Samples scanned:      13,500
  Samples matched:      13,000 (96.3%)
  Samples validated:    13,000 (100.0% of matched)

  Entity Type               Matched    Scanned      Valid     Conf          Via
  ---------------------- ---------- ---------- ---------- -------- ------------
  SSN                        500(100%)        500        500    0.950  column_name
  SSN                        500(100%)        500        500    0.950  column_name
  EMAIL                      500(100%)        500        500    0.997        regex
  EMAIL                      500(100%)        500        500    0.997        regex
  PHONE                      500(100%)        500        500    0.900  column_name
  PHONE                      500(100%)        500        500    0.900  column_name
  CREDIT_CARD                500(100%)        500        500    0.950  column_name
  CREDIT_CARD                500(100%)        500        500    0.950  column_name
  DATE_OF_BIRTH              500(100%)        500        500    0.900  column_name
  IP_ADDRESS                 500(100%)        500        500    0.945        regex
  URL                        500(100%)        500        500    0.945        regex
  PERSON_NAME                500(100%)        500        500    0.637  column_name
  ADDRESS                    500(100%)        500        500    0.800  column_name
  IBAN                       500(100%)        500        500    0.900  column_name
  SWIFT_BIC                  500(100%)        500        500    0.945        regex
  EIN                        500(100%)        500        500    0.850  column_name
  VIN                        500(100%)        500        500    0.850  column_name
  BITCOIN_ADDRESS            500(100%)        500        500    0.945        regex
  ETHEREUM_ADDRESS           500(100%)        500        500    0.945        regex
  NPI                        500(100%)        500        500    0.900  column_name
  NPI                        500(100%)        500        500    0.900  column_name
  DEA_NUMBER                 500(100%)        500        500    0.900  column_name
  MBI                        500(100%)        500        500    0.945        regex
  ABA_ROUTING                500(100%)        500        500    0.900  column_name
  CANADIAN_SIN               500(100%)        500        500    0.900  column_name
  MAC_ADDRESS                500(100%)        500        500    0.945        regex
  DATE_OF_BIRTH_EU             0(0%)        500          0    0.000       MISSED

COLUMN-LEVEL ACCURACY (did the column get the correct entity label?)
----------------------------------------------------------------------
Entity Type              TP   FP   FN     Prec   Recall       F1
----------------------------------------------------------------------
ABA_ROUTING               1    4    0    0.200    1.000    0.333
ADDRESS                   1    0    0    1.000    1.000    1.000
BITCOIN_ADDRESS           1    1    0    0.500    1.000    0.667
CANADIAN_SIN              1    2    0    0.333    1.000    0.500
CREDENTIAL                0    1    0    0.000    0.000    0.000
CREDIT_CARD               2    0    0    1.000    1.000    1.000
DATE_OF_BIRTH             1    1    0    0.500    1.000    0.667
DATE_OF_BIRTH_EU          0    0    1    0.000    0.000    0.000
DEA_NUMBER                1    0    0    1.000    1.000    1.000
EIN                       1    0    0    1.000    1.000    1.000
EMAIL                     2    0    0    1.000    1.000    1.000
ETHEREUM_ADDRESS          1    0    0    1.000    1.000    1.000
IBAN                      1    1    0    0.500    1.000    0.667
IP_ADDRESS                1    0    0    1.000    1.000    1.000
MAC_ADDRESS               1    0    0    1.000    1.000    1.000
MBI                       1    0    0    1.000    1.000    1.000
NPI                       2    0    0    1.000    1.000    1.000
PERSON_NAME               1    0    0    1.000    1.000    1.000
PHONE                     2    2    0    0.500    1.000    0.667
SSN                       2    3    0    0.400    1.000    0.571
SWIFT_BIC                 1    0    0    1.000    1.000    1.000
URL                       1    0    0    1.000    1.000    1.000
VIN                       1    0    0    1.000    1.000    1.000
----------------------------------------------------------------------
OVERALL                  26   15    1    0.634    0.963    0.765

ENGINE CONTRIBUTIONS
----------------------------------------------------------------------
Column                            Column Name Eng          Regex Eng
----------------------------------------------------------------------
  SSN (test_ssn_column)                       SSN   SSN, ABA_ROUTING
  SSN (test_ssn_notes)                        SSN   SSN, ABA_ROUTING
  EMAIL (test_email_colu)                   EMAIL              EMAIL
  EMAIL (test_email_note)                   EMAIL              EMAIL
  PHONE (test_phone_colu)                   PHONE PHONE, CANADIAN_SIN
  PHONE (test_phone_note)                   PHONE PHONE, CANADIAN_SIN
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
  ABA_ROUTING (test_aba_column)        ABA_ROUTING   ABA_ROUTING, SSN
  CANADIAN_SIN (test_sin_column)       CANADIAN_SIN CANADIAN_SIN, ABA_ROUTING, SSN
  MAC_ADDRESS (test_mac_column)                  -        MAC_ADDRESS
  DATE_OF_BIRTH_EU (test_dob_eu_col)      DATE_OF_BIRTH      DATE_OF_BIRTH

SAMPLE-LEVEL DETECTION
----------------------------------------------------------------------
  SSN                  via column name  confidence=0.950
  SSN                  via column name  confidence=0.950
  EMAIL                matched=500/500 (100%)  validated=500/500  confidence=0.997
  EMAIL                matched=500/500 (100%)  validated=500/500  confidence=0.997
  PHONE                via column name  confidence=0.900
  PHONE                via column name  confidence=0.900
  CREDIT_CARD          via column name  confidence=0.950
  CREDIT_CARD          via column name  confidence=0.950
  DATE_OF_BIRTH        via column name  confidence=0.900
  IP_ADDRESS           matched=500/500 (100%)  validated=500/500  confidence=0.945
  URL                  matched=500/500 (100%)  validated=500/500  confidence=0.945
  PERSON_NAME          via column name  confidence=0.637
  ADDRESS              via column name  confidence=0.800
  IBAN                 via column name  confidence=0.900
  SWIFT_BIC            matched=500/500 (100%)  validated=500/500  confidence=0.945
  EIN                  via column name  confidence=0.850
  VIN                  via column name  confidence=0.850
  BITCOIN_ADDRESS      matched=500/500 (100%)  validated=500/500  confidence=0.945
  ETHEREUM_ADDRESS     matched=500/500 (100%)  validated=500/500  confidence=0.945
  NPI                  via column name  confidence=0.900
  NPI                  via column name  confidence=0.900
  DEA_NUMBER           via column name  confidence=0.900
  MBI                  matched=500/500 (100%)  validated=500/500  confidence=0.945
  ABA_ROUTING          via column name  confidence=0.900
  CANADIAN_SIN         via column name  confidence=0.900
  MAC_ADDRESS          matched=500/500 (100%)  validated=500/500  confidence=0.945
  DATE_OF_BIRTH_EU     NOT DETECTED

CROSS-PATTERN COLLISIONS (patterns that fire on the same column)
----------------------------------------------------------------------
  ABA_ROUTING          also triggers CANADIAN_SIN         (1 columns)
  ABA_ROUTING          also triggers SSN                  (5 columns)
  BITCOIN_ADDRESS      also triggers CREDENTIAL           (1 columns)
  CANADIAN_SIN         also triggers ABA_ROUTING          (1 columns)
  CANADIAN_SIN         also triggers PHONE                (2 columns)
  CANADIAN_SIN         also triggers SSN                  (1 columns)
  CREDENTIAL           also triggers BITCOIN_ADDRESS      (1 columns)
  DEA_NUMBER           also triggers IBAN                 (1 columns)
  IBAN                 also triggers DEA_NUMBER           (1 columns)
  NPI                  also triggers PHONE                (2 columns)
  PHONE                also triggers CANADIAN_SIN         (2 columns)
  PHONE                also triggers NPI                  (2 columns)
  SSN                  also triggers ABA_ROUTING          (5 columns)
  SSN                  also triggers CANADIAN_SIN         (1 columns)

FALSE POSITIVES
----------------------------------------------------------------------
  corpus_SSN_0: predicted=ABA_ROUTING, expected=SSN, engines={'column_name': ['SSN'], 'regex': ['SSN', 'ABA_ROUTING']}
  corpus_SSN_embedded: predicted=ABA_ROUTING, expected=SSN, engines={'column_name': ['SSN'], 'regex': ['SSN', 'ABA_ROUTING']}
  corpus_CANADIAN_SIN_0: predicted=ABA_ROUTING, expected=CANADIAN_SIN, engines={'column_name': ['CANADIAN_SIN'], 'regex': ['CANADIAN_SIN', 'ABA_ROUTING', 'SSN']}
  corpus_none_numeric_ids_0: predicted=ABA_ROUTING, expected=None, engines={'column_name': [], 'regex': ['ABA_ROUTING', 'SSN']}
  corpus_none_hex_strings_0: predicted=BITCOIN_ADDRESS, expected=None, engines={'column_name': [], 'regex': ['CREDENTIAL', 'BITCOIN_ADDRESS']}
  corpus_PHONE_0: predicted=CANADIAN_SIN, expected=PHONE, engines={'column_name': ['PHONE'], 'regex': ['PHONE', 'CANADIAN_SIN']}
  corpus_PHONE_embedded: predicted=CANADIAN_SIN, expected=PHONE, engines={'column_name': ['PHONE'], 'regex': ['PHONE', 'CANADIAN_SIN']}
  corpus_none_hex_strings_0: predicted=CREDENTIAL, expected=None, engines={'column_name': [], 'regex': ['CREDENTIAL', 'BITCOIN_ADDRESS']}
  corpus_DATE_OF_BIRTH_EU_0: predicted=DATE_OF_BIRTH, expected=DATE_OF_BIRTH_EU, engines={'column_name': ['DATE_OF_BIRTH'], 'regex': ['DATE_OF_BIRTH']}
  corpus_DEA_NUMBER_0: predicted=IBAN, expected=DEA_NUMBER, engines={'column_name': ['DEA_NUMBER'], 'regex': ['DEA_NUMBER', 'IBAN']}
  corpus_NPI_0: predicted=PHONE, expected=NPI, engines={'column_name': ['NPI'], 'regex': ['NPI', 'PHONE']}
  corpus_NPI_embedded: predicted=PHONE, expected=NPI, engines={'column_name': ['NPI'], 'regex': ['NPI', 'PHONE']}
  corpus_ABA_ROUTING_0: predicted=SSN, expected=ABA_ROUTING, engines={'column_name': ['ABA_ROUTING'], 'regex': ['ABA_ROUTING', 'SSN']}
  corpus_CANADIAN_SIN_0: predicted=SSN, expected=CANADIAN_SIN, engines={'column_name': ['CANADIAN_SIN'], 'regex': ['CANADIAN_SIN', 'ABA_ROUTING', 'SSN']}
  corpus_none_numeric_ids_0: predicted=SSN, expected=None, engines={'column_name': [], 'regex': ['ABA_ROUTING', 'SSN']}

FALSE NEGATIVES
----------------------------------------------------------------------
  corpus_DATE_OF_BIRTH_EU_0: expected=DATE_OF_BIRTH_EU, got=['DATE_OF_BIRTH']
```

## Performance Detail

```
======================================================================
PERFORMANCE BENCHMARK REPORT
======================================================================

DATA PROCESSED
  Columns:             37
  Total samples:       18500
  Avg samples/column:  500
  Iterations:          30
  Warmup:              1.59 ms

FULL PIPELINE LATENCY
----------------------------------------------------------------------
  Total (all columns)  p50=50.99 ms  p95=52.11 ms  p99=54.60 ms
  Per column           p50=1.378 ms
  Per sample           p50=2.8 us
  Throughput           726 columns/sec  |  362837 samples/sec

PER-ENGINE BREAKDOWN
----------------------------------------------------------------------
  column_name          total_p50=0.13 ms  per_col=0.004 ms  (0% of pipeline)
  regex                total_p50=50.56 ms  per_col=1.366 ms  (99% of pipeline)

ENGINE TELEMETRY (single run)
----------------------------------------------------------------------
  column_name          calls=37  hits=24  misses=13  total=0.30ms  mean=0.008ms  max=0.020ms
  regex                calls=37  hits=28  misses=9  total=49.96ms  mean=1.350ms  max=8.430ms

SCALING: SAMPLE COUNT (per-column latency vs samples/column)
----------------------------------------------------------------------
     10 samples → 0.051 ms/col  #####
     50 samples → 0.184 ms/col  ##################
    100 samples → 0.320 ms/col  ################################
    500 samples → 1.479 ms/col  ########################################

SCALING: INPUT LENGTH (RE2 time vs string length, single sample)
----------------------------------------------------------------------
      51 bytes → p50=2.3 us  p99=3299.3 us  (1.0x)  ###
     101 bytes → p50=2.4 us  p99=32.4 us  (1.1x)  ###
     501 bytes → p50=4.7 us  p99=117.3 us  (2.0x)  ######
    1001 bytes → p50=5.7 us  p99=205.2 us  (2.5x)  #######
    5001 bytes → p50=26.6 us  p99=853.2 us  (11.6x)  ##################################
   10001 bytes → p50=46.9 us  p99=450.3 us  (20.5x)  ########################################
   50001 bytes → p50=216.5 us  p99=1179.5 us  (94.4x)  ########################################

DIRECT PATTERN MATCHING (regex engine on mixed-PII text)
----------------------------------------------------------------------
  Patterns compiled:   59
  Input:               100 samples × 223 chars
  Total time:          0.78 ms
  Per sample:          7.8 us
  Findings:            3 (EMAIL, IP_ADDRESS, SWIFT_BIC)

======================================================================
```
