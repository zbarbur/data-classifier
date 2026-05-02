# NEGATIVE Corpus — Source Provenance

> **Owner:** the diverse-NEGATIVE corpus introduced in Sprint 17.
>
> **Code:** `tests/benchmarks/negative_corpus.py`
>
> **Tests:** `tests/test_negative_corpus.py`
>
> **Decided:** 2026-04-28 (Sprint 17 item
> `source-diverse-negative-corpus-for-benchmark`).

The Sprint 14 binary-PII-gate research returned a RED verdict on the
existing NEGATIVE pool: 90 SecretBench values resampled into 450 shards
encoded only one structural shape (credential-style hard negatives).
The detector's NEGATIVE-F1 number on that pool was 1.000, but the
metric reflected corpus homogeneity rather than real FP-resistance.

This document captures the licensing and generation method for each of
the 5 NEGATIVE sources that replace the homogeneous baseline. **Adding
a 6th source must add an entry here.** A CI lint can be added later if
this drifts.

## Source posture summary

| Source | Generation | License | License origin |
|---|---|---|---|
| `config` | Synthesized templates | n/a (project-owned) | data_classifier code |
| `code` | Synthesized templates | n/a (project-owned) | data_classifier code |
| `business` | Faker (catch_phrase, bs, color_name) + synthesized SKUs | MIT (Faker) + project-owned | Faker LICENSE |
| `numeric` | Synthesized templates | n/a (project-owned) | data_classifier code |
| `prose` | Synthesized templates | n/a (project-owned) | data_classifier code |

License posture: clean by construction. No AGPL (per
`feedback_trufflehog_excluded`). No CC-BY-NC. No upstream redistribution
constraints.

## Per-source detail

### `config` — config-shaped strings without secrets

**Shape:** env-var assignments (`PORT=8080`), single-line JSON config
(`{"port": 8080}`), INI lines (`port = 5432`), YAML pairs
(`server.port: 8080`).

**Generator:** `_generate_config()` in `negative_corpus.py`. Mixes 4
config dialects with a key list of 22 neutral keys (`PORT`, `DEBUG`,
`MAX_CONNECTIONS`, ...) and value spaces appropriate per key (log
levels, tier names, booleans, bounded integers).

**Why it tests something real:** consumers' config files are a major
non-credential FP source for naive credential scanners. Strings like
`API_KEY=true` or `DEBUG_TOKEN=enabled` look credential-shaped but
aren't.

### `code` — code snippets without PII

**Shape:** function definitions (`def fn(arg: int) -> int:`), import
statements (`import json`, `from pathlib import Path`), short Python
expressions (`return result.strip()`), decorator lines (`@property`,
`@lru_cache(maxsize=42)`), lambda expressions.

**Generator:** `_generate_code()`. Synthesized from templates over a
combinatorial slot space — no source-file scraping, so no risk of
leaked author names, copyrighted strings, or company headers.

**Why it tests something real:** code is a common false-positive source
for any detector. A naive PERSON_NAME matcher can fire on
`fn(arg: int)`; a naive ADDRESS matcher can fire on `Path("/etc/...")`
patterns. Code-shaped negatives stress the detector's ability to
discriminate prose from program text.

### `business` — generic business data

**Shape:** Faker buzzword phrases (`Adaptive contextual ROI`),
synergy-bs (`drive viral platforms`), color names (`PaleVioletRed`),
synthesized SKUs (`PROD-X9F2K3M`).

**Generator:** `_generate_business()`. Uses `faker.Faker()` (MIT) for
the linguistic content, with a deterministic seed. Avoids
`faker.company()` (which generates names like "Adams, Howard and Brown"
that fire on PERSON_NAME) and `faker.name()` (literal person names).

**Why it tests something real:** product catalogs, order management
data, and marketing copy are the long-tail of NEGATIVE in real BQ
deployments. Detectors that fire on "Crimson Tide" as PERSON_NAME or
"PROD-X9F2K3M" as API_KEY produce noise.

### `numeric` — numeric non-PII values with units

**Shape:** measurements with units (`42 kg`, `100 mph`,
`32°C`), score lines (`score: 87.5`), counts (`count = 42`), ratings
(`rating: 4.2/5`), plain numbers and scientific notation.

**Generator:** `_generate_numeric()`. **Caps integer values at 6
digits** to avoid colliding with SSN-shape (9 digits), CC-shape
(13-19), or US-phone-shape (10). Always pairs with a unit or context
word.

**Why it tests something real:** detectors that lean on digit-density
heuristics (e.g., a Tier-1 credential gate looking at high-entropy
numeric strings) often misfire on long counts or measurements. This
source forces explicit handling.

### `prose` — documentation-style prose without PII

**Shape:** API/system documentation sentences using a 4-slot template:
`{subject} {verb} {object} {qualifier}`. Vocabulary is deliberately
generic (`The handler processes the staging buffer in deterministic
order.`) — no names, addresses, dates, or numerical identifiers.

**Generator:** `_generate_prose()`. Pure synthesis from a vocabulary
of 10 subjects × 10 verbs × 10 objects × 10 qualifiers (~10,000
combinations available; we draw 500).

**Why it tests something real:** every PII detector sees a long tail of
"prose-shaped non-PII" — README content, comments, error messages,
tutorial text. A detector that fires on `"The system processes the
incoming event"` as anything other than NEGATIVE is broken.

## Contamination guard

Every source is gated by `tests/test_negative_corpus.py::TestPIIContaminationSweep`,
which runs the regex engine over a 100-value random sample per source
and **asserts <5% positive-hit rate**. A source above the ceiling is
treated as a generator bug and must be fixed in `negative_corpus.py`,
not silenced.

Above the 5% ceiling, the failure message reports the first 10
offending values + their detected types so the regression is
diagnosable.

## Adding a 6th source

1. Add `_generate_<name>()` to `negative_corpus.py` with a docstring
   stating the shape, license posture, and the reason this source
   tests a structural property the existing 5 don't.
2. Register in `_SOURCE_GENERATORS` and `NEGATIVE_SOURCE_IDS`.
3. Add an entry to this document under "Per-source detail".
4. Run the existing test suite — the parametrize decorators pick up the
   new source automatically. All tests must pass, including the
   contamination sweep at <5%.
5. Re-run the family benchmark to capture before/after numbers in the
   sprint handover.
