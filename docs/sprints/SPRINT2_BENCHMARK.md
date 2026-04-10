# Sprint 2 — Benchmark Report

> **Generated:** 2026-04-10 20:28 UTC
> **Samples per type:** 500
> **Patterns:** 59
> **Entity types (patterns):** 22

## Summary

| Metric | Pattern-Level (regex only) | Column-Level (full pipeline) |
|---|---|---|
| Total samples | 12,500 | 18,500 |
| Positive / Negative | 11,000 / 1,500 | 27 cols / 10 cols |
| Precision | 0.828 | 0.605 |
| Recall | 0.756 | 0.963 |
| **F1** | **0.791** | **0.743** |
| TP / FP / FN | 8,318 / 1,726 / 2,682 | 26 / 17 / 1 |

## Performance

| Metric | Value |
|---|---|
| Throughput | 1,529 columns/sec \| 764,436 samples/sec |
| Per column (p50) | 0.654 ms |
| Per sample (p50) | 1.3 us |
| Warmup (RE2 compile) | 1.0 ms |

### Scaling

**Sample count scaling (per-column latency):**

| Samples/col | Latency (p50) |
|---|---|
| 10 | 0.021 ms |
| 50 | 0.074 ms |
| 100 | 0.128 ms |
| 500 | 0.568 ms |

**Input length scaling (RE2 linearity):**

| Input bytes | p50 (us) | Ratio |
|---|---|---|
| 51 | 2.1 | 1.0x |
| 101 | 2.2 | 1.1x |
| 501 | 3.6 | 1.7x |
| 1,001 | 6.7 | 3.2x |
| 5,001 | 18.3 | 8.8x |
| 10,001 | 32.3 | 15.5x |
| 50,001 | 146.7 | 70.4x |

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
ABA_ROUTING               500     30      0    0.943    1.000    0.971
ADDRESS                     0      0    500    0.000    0.000    0.000
BITCOIN_ADDRESS           500      0      0    1.000    1.000    1.000
CANADIAN_SIN                0     11    500    0.000    0.000    0.000
CREDIT_CARD               301      0    199    1.000    0.602    0.752
DATE_OF_BIRTH             500    500      0    0.500    1.000    0.667
DATE_OF_BIRTH_EU            0      0    500    0.000    0.000    0.000
DEA_NUMBER                500      0      0    1.000    1.000    1.000
EIN                       500      0      0    1.000    1.000    1.000
EMAIL                     500      0      0    1.000    1.000    1.000
ETHEREUM_ADDRESS          500      0      0    1.000    1.000    1.000
IBAN                      500      5      0    0.990    1.000    0.995
IP_ADDRESS                500      0      0    1.000    1.000    1.000
MAC_ADDRESS               500      0      0    1.000    1.000    1.000
MBI                       500      0      0    1.000    1.000    1.000
NPI                       500      0      0    1.000    1.000    1.000
PERSON_NAME                 0      0    500    0.000    0.000    0.000
PHONE                     193    500    307    0.278    0.386    0.324
SSN                       500    680      0    0.424    1.000    0.595
SWIFT_BIC                 500      0      0    1.000    1.000    1.000
URL                       500      0      0    1.000    1.000    1.000
VIN                       324      0    176    1.000    0.648    0.786
------------------------------------------------------------------------------
OVERALL                  8318   1726   2682    0.828    0.756    0.791

PER-PATTERN MATCH RATES (patterns with test data)
------------------------------------------------------------------------------
  Pattern                        Entity                Matched      Valid    ValFail
  ------------------------------ ------------------ ---------- ---------- ----------
  aba_routing                    ABA_ROUTING           500(100%)        500          0
  bitcoin_address                BITCOIN_ADDRESS       500(100%)        500          0
  canadian_sin                   CANADIAN_SIN          500(100%)          0        500
  credit_card_amex               CREDIT_CARD            41(8%)         41          0
  credit_card_discover           CREDIT_CARD             9(2%)          9          0
  credit_card_formatted          CREDIT_CARD           170(34%)        170          0
  credit_card_mastercard         CREDIT_CARD             3(1%)          3          0
  credit_card_visa               CREDIT_CARD            78(16%)         78          0
  date_iso_format                DATE_OF_BIRTH           0(0%)          0          0
  date_of_birth_format           DATE_OF_BIRTH         500(100%)        500          0
  dob_european                   DATE_OF_BIRTH         210(42%)        210          0
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
  us_phone_formatted             PHONE                 193(39%)        193          0
  us_ssn_formatted               SSN                   345(69%)        345          0
  us_ssn_no_dashes               SSN                   155(31%)        155          0
  vin                            VIN                   500(100%)        324        176

CROSS-PATTERN COLLISIONS (same value triggers multiple entity types)
------------------------------------------------------------------------------
  ABA_ROUTING            also triggers SSN                    (527 samples)
  CANADIAN_SIN           also triggers PHONE                  (3 samples)
  DEA_NUMBER             also triggers IBAN                   (5 samples)
  IBAN                   also triggers DEA_NUMBER             (5 samples)
  NPI                    also triggers PHONE                  (500 samples)
  PHONE                  also triggers CANADIAN_SIN           (3 samples)
  PHONE                  also triggers NPI                    (500 samples)
  SSN                    also triggers ABA_ROUTING            (527 samples)

MISSED SAMPLES (expected match, got nothing — up to 10 per type)
------------------------------------------------------------------------------
  ADDRESS (500 missed):
    '57122 Johnson Neck Suite 365\nEast Victoria, TN 91190'
    '581 Carrie Mission Apt. 512\nPorterton, MT 31706'
    '7140 Eric Mall\nSouth Andreamouth, GA 76494'
    '876 James Ramp\nGarrisonmouth, MO 65582'
    '60256 Anthony Cape\nNorth Jakestad, MP 33795'
  CANADIAN_SIN (500 missed):
    '177500139'
    '094-270-006'
    '085037166'
    '033-387-051'
    '527 065 015'
  CREDIT_CARD (199 missed):
    '213179032974078'
    '4664314078144755655'
    '30350211834968'
    '639042893672'
    '060435711464'
  DATE_OF_BIRTH_EU (500 missed):
    '24/03/1958'
    '03/01/1937'
    '29/11/1990'
    '10/12/1989'
    '09/02/1996'
  PERSON_NAME (500 missed):
    'Jacob Williams'
    'Tammy Villanueva'
    'Morgan Anderson'
    'Ms. Tamara Jones'
    'Katie Thompson'
  PHONE (307 missed):
    '889-377-5088x35741'
    '(859)417-4470x498'
    '001-560-366-0246x46987'
    '+1-386-747-0672x60370'
    '431.363.2265x361'
  VIN (176 missed):
    'WVWZZZ3CZWE123456'
    'WVWZZZ3CZWE123456'
    'WVWZZZ3CZWE123456'
    'WVWZZZ3CZWE123456'
    'WVWZZZ3CZWE123456'

FALSE POSITIVE EXAMPLES (up to 5 per type)
------------------------------------------------------------------------------
  ABA_ROUTING (30 FPs):
    '788357088' (expected=SSN)
    '491849906' (expected=SSN)
    '591746640' (expected=SSN)
    '152219354' (expected=SSN)
    '896186044' (expected=SSN)
  CANADIAN_SIN (11 FPs):
    '001-956-375-0893x63665' (expected=PHONE)
    '001-640-815-4868' (expected=PHONE)
    '001-791-939-3797x0141' (expected=PHONE)
    '001-386-759-9469' (expected=PHONE)
    '001-594-481-5138x87002' (expected=PHONE)
  DATE_OF_BIRTH (500 FPs):
    '24/03/1958' (expected=DATE_OF_BIRTH_EU)
    '03/01/1937' (expected=DATE_OF_BIRTH_EU)
    '29/11/1990' (expected=DATE_OF_BIRTH_EU)
    '10/12/1989' (expected=DATE_OF_BIRTH_EU)
    '09/02/1996' (expected=DATE_OF_BIRTH_EU)
  IBAN (5 FPs):
    'MV8146575' (expected=DEA_NUMBER)
    'PZ3846550' (expected=DEA_NUMBER)
    'RG9960801' (expected=DEA_NUMBER)
    'GB1812901' (expected=DEA_NUMBER)
    'BC1386982' (expected=DEA_NUMBER)
  PHONE (500 FPs):
    '2196677092' (expected=NPI)
    '1819369665' (expected=NPI)
    '1766778538' (expected=NPI)
    '1660305883' (expected=NPI)
    '1850627880' (expected=NPI)
  SSN (680 FPs):
    '433476531' (expected=ABA_ROUTING)
    '086608497' (expected=ABA_ROUTING)
    '089612121' (expected=ABA_ROUTING)
    '136274807' (expected=ABA_ROUTING)
    '647026515' (expected=ABA_ROUTING)

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
  SSN                        500(100%)        500        500    0.997        regex
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
NPI                       2    2    0    0.500    1.000    0.667
PERSON_NAME               1    0    0    1.000    1.000    1.000
PHONE                     2    2    0    0.500    1.000    0.667
SSN                       2    3    0    0.400    1.000    0.571
SWIFT_BIC                 1    0    0    1.000    1.000    1.000
URL                       1    0    0    1.000    1.000    1.000
VIN                       1    0    0    1.000    1.000    1.000
----------------------------------------------------------------------
OVERALL                  26   17    1    0.605    0.963    0.743

ENGINE CONTRIBUTIONS
----------------------------------------------------------------------
Column                            Column Name Eng          Regex Eng
----------------------------------------------------------------------
  SSN (test_ssn_column)                       SSN   SSN, ABA_ROUTING
  SSN (test_ssn_notes)                        SSN   SSN, ABA_ROUTING
  EMAIL (test_email_colu)                   EMAIL              EMAIL
  EMAIL (test_email_note)                   EMAIL              EMAIL
  PHONE (test_phone_colu)                   PHONE PHONE, CANADIAN_SIN, NPI
  PHONE (test_phone_note)                   PHONE PHONE, CANADIAN_SIN, NPI
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
  SSN                  matched=500/500 (100%)  validated=500/500  confidence=0.997
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
  CANADIAN_SIN         also triggers NPI                  (2 columns)
  CANADIAN_SIN         also triggers PHONE                (2 columns)
  CANADIAN_SIN         also triggers SSN                  (1 columns)
  CREDENTIAL           also triggers BITCOIN_ADDRESS      (1 columns)
  DEA_NUMBER           also triggers IBAN                 (1 columns)
  IBAN                 also triggers DEA_NUMBER           (1 columns)
  NPI                  also triggers CANADIAN_SIN         (2 columns)
  NPI                  also triggers PHONE                (4 columns)
  PHONE                also triggers CANADIAN_SIN         (2 columns)
  PHONE                also triggers NPI                  (4 columns)
  SSN                  also triggers ABA_ROUTING          (5 columns)
  SSN                  also triggers CANADIAN_SIN         (1 columns)

FALSE POSITIVES
----------------------------------------------------------------------
  corpus_SSN_0: predicted=ABA_ROUTING, expected=SSN, engines={'column_name': ['SSN'], 'regex': ['SSN', 'ABA_ROUTING']}
  corpus_SSN_embedded: predicted=ABA_ROUTING, expected=SSN, engines={'column_name': ['SSN'], 'regex': ['SSN', 'ABA_ROUTING']}
  corpus_CANADIAN_SIN_0: predicted=ABA_ROUTING, expected=CANADIAN_SIN, engines={'column_name': ['CANADIAN_SIN'], 'regex': ['CANADIAN_SIN', 'ABA_ROUTING', 'SSN']}
  corpus_none_numeric_ids_0: predicted=ABA_ROUTING, expected=None, engines={'column_name': [], 'regex': ['ABA_ROUTING', 'SSN']}
  corpus_none_hex_strings_0: predicted=BITCOIN_ADDRESS, expected=None, engines={'column_name': [], 'regex': ['CREDENTIAL', 'BITCOIN_ADDRESS']}
  corpus_PHONE_0: predicted=CANADIAN_SIN, expected=PHONE, engines={'column_name': ['PHONE'], 'regex': ['PHONE', 'CANADIAN_SIN', 'NPI']}
  corpus_PHONE_embedded: predicted=CANADIAN_SIN, expected=PHONE, engines={'column_name': ['PHONE'], 'regex': ['PHONE', 'CANADIAN_SIN', 'NPI']}
  corpus_none_hex_strings_0: predicted=CREDENTIAL, expected=None, engines={'column_name': [], 'regex': ['CREDENTIAL', 'BITCOIN_ADDRESS']}
  corpus_DATE_OF_BIRTH_EU_0: predicted=DATE_OF_BIRTH, expected=DATE_OF_BIRTH_EU, engines={'column_name': ['DATE_OF_BIRTH'], 'regex': ['DATE_OF_BIRTH']}
  corpus_DEA_NUMBER_0: predicted=IBAN, expected=DEA_NUMBER, engines={'column_name': ['DEA_NUMBER'], 'regex': ['DEA_NUMBER', 'IBAN']}
  corpus_PHONE_0: predicted=NPI, expected=PHONE, engines={'column_name': ['PHONE'], 'regex': ['PHONE', 'CANADIAN_SIN', 'NPI']}
  corpus_PHONE_embedded: predicted=NPI, expected=PHONE, engines={'column_name': ['PHONE'], 'regex': ['PHONE', 'CANADIAN_SIN', 'NPI']}
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
  Warmup:              0.97 ms

FULL PIPELINE LATENCY
----------------------------------------------------------------------
  Total (all columns)  p50=24.20 ms  p95=26.15 ms  p99=27.38 ms
  Per column           p50=0.654 ms
  Per sample           p50=1.3 us
  Throughput           1529 columns/sec  |  764436 samples/sec

PER-ENGINE BREAKDOWN
----------------------------------------------------------------------
  column_name          total_p50=0.13 ms  per_col=0.003 ms  (1% of pipeline)
  regex                total_p50=23.27 ms  per_col=0.629 ms  (96% of pipeline)

ENGINE TELEMETRY (single run)
----------------------------------------------------------------------
  column_name          calls=37  hits=24  misses=13  total=0.23ms  mean=0.006ms  max=0.030ms
  regex                calls=37  hits=28  misses=9  total=22.96ms  mean=0.621ms  max=1.690ms

SCALING: SAMPLE COUNT (per-column latency vs samples/column)
----------------------------------------------------------------------
     10 samples → 0.021 ms/col  ##
     50 samples → 0.074 ms/col  #######
    100 samples → 0.128 ms/col  ############
    500 samples → 0.568 ms/col  ########################################

SCALING: INPUT LENGTH (RE2 time vs string length, single sample)
----------------------------------------------------------------------
      51 bytes → p50=2.1 us  p99=3171.0 us  (1.0x)  ###
     101 bytes → p50=2.2 us  p99=31.2 us  (1.1x)  ###
     501 bytes → p50=3.6 us  p99=118.9 us  (1.7x)  #####
    1001 bytes → p50=6.7 us  p99=172.4 us  (3.2x)  #########
    5001 bytes → p50=18.3 us  p99=498.4 us  (8.8x)  ##########################
   10001 bytes → p50=32.3 us  p99=405.3 us  (15.5x)  ########################################
   50001 bytes → p50=146.7 us  p99=991.2 us  (70.4x)  ########################################

DIRECT PATTERN MATCHING (regex engine on mixed-PII text)
----------------------------------------------------------------------
  Patterns compiled:   59
  Input:               100 samples × 239 chars
  Total time:          0.61 ms
  Per sample:          6.1 us
  Findings:            3 (EMAIL, IP_ADDRESS, SWIFT_BIC)

======================================================================
```
