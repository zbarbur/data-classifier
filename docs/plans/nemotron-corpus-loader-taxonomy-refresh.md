# Plan — Corpus loader taxonomy refresh (Sprint 11 Item #1)

**Backlog item:** `nemotron-corpus-loader-taxonomy-refresh-map-legacy-credential-to-4-subtypes`
**Sprint:** 11 | **Priority:** P1 | **Category:** chore | **Complexity:** S (scope expanded from Nemotron-only to 3 loaders, still S)
**Branch:** `sprint11/main` | **Worktree:** `/Users/guyguzner/Projects/data_classifier-sprint11-cleanup`

## Context

Sprint 8 split the `CREDENTIAL` entity type into 4 deterministic subtypes (`API_KEY`, `PRIVATE_KEY`, `PASSWORD_HASH`, `OPAQUE_SECRET`). The corpus loaders in `tests/benchmarks/corpus_loader.py` were never refreshed — they continue to emit the flat `CREDENTIAL` label, which is no longer a valid entity type per `data_classifier/profiles/standard.yaml`.

Sprint 10 Item #4 (secret-key dict expansion, 88→178 entries) surfaced this drift as a fake Nemotron blind F1 regression (`0.821 → 0.774, -0.047`). The secret scanner correctly fires `API_KEY` on Nemotron's `col_2` samples, but the benchmark scores `predicted=API_KEY vs expected=CREDENTIAL` as FP+FN. Real detection quality held or improved; the measurement is the problem.

**Scope audit** (performed during planning, not in the original spec): Three loaders carry identical drift. Item #1's scope is EXPANDED to fix all three in one atomic commit so item #3's "drift lint baseline green" guarantee holds.

## Authoritative taxonomy

Source: `data_classifier/profiles/standard.yaml` (NOT `data_classifier/entity_types.py` — the spec originally referenced a file that doesn't exist).

| Subtype | Regex pattern set (from standard.yaml) | Semantics |
|---|---|---|
| `PRIVATE_KEY` | private_key, privatekey, pem_key, rsa_private_key, ssh_private_key, pgp_private_key | Cryptographic private keys |
| `PASSWORD_HASH` | password_hash, hashed_password, pwd_hash, pass_hash, password_digest, bcrypt_hash, argon2_hash, scrypt_hash, crypt | **Hashed** passwords only |
| `API_KEY` | api_key, apikey, api_secret, api_token, access_key, access_token, auth_token, bearer_token, client_secret, oauth_token, oauth_secret, refresh_token, service_account_key, secret_token | Tokens used as API credentials |
| `OPAQUE_SECRET` | password, passwd, passcode, pwd, passphrase, secret, credential, credentials, token | Catch-all: plaintext passwords, generic secrets |

**Key subtlety:** plaintext `password` → `OPAQUE_SECRET`, NOT `PASSWORD_HASH`. `PASSWORD_HASH` is specifically for hashed passwords.

## Drift table — current → target mappings

### Loader 1: `NEMOTRON_TYPE_MAP` (lines 134–174 of `tests/benchmarks/corpus_loader.py`)

| Raw label | Line | Current | Target | Rationale |
|---|---|---|---|---|
| `password` | 155 | CREDENTIAL | **OPAQUE_SECRET** | Plaintext password, matches OPAQUE_SECRET catch-all pattern |
| `api_key` | 156 | CREDENTIAL | **API_KEY** | Direct match for API_KEY `api_key` pattern |
| `pin` | 157 | CREDENTIAL | **OPAQUE_SECRET** | PIN is a numeric passcode; `passcode` is in OPAQUE_SECRET patterns |
| `CREDENTIAL` (identity) | 170 | CREDENTIAL | **OPAQUE_SECRET** | Legacy passthrough — any residual `CREDENTIAL` labels route to the catch-all |

### Loader 2: `GRETEL_EN_TYPE_MAP` (lines 98–128 of `tests/benchmarks/corpus_loader.py`)

| Raw label | Line | Current | Target | Rationale |
|---|---|---|---|---|
| `password` | 125 | CREDENTIAL | **OPAQUE_SECRET** | Same as Nemotron |
| `api_key` | 126 | CREDENTIAL | **API_KEY** | Same as Nemotron |

### Loader 3: `_DETECT_SECRETS_TYPE_MAP` (lines 367–376 of `tests/benchmarks/corpus_loader.py`)

This map is shared by three loaders: SecretBench, gitleaks, detect_secrets. All 9 entries are currently stale.

| Raw label | Current | Target | Rationale |
|---|---|---|---|
| `aws_access_key` | CREDENTIAL | **API_KEY** | AWS access keys match `access_key` pattern |
| `slack_token` | CREDENTIAL | **API_KEY** | Token used as API credential |
| `stripe_key` | CREDENTIAL | **API_KEY** | API credential |
| `basic_auth` | CREDENTIAL | **OPAQUE_SECRET** | Encoded `user:pass` — not a pure API_KEY; catch-all fits better |
| `jwt` | CREDENTIAL | **API_KEY** | Matches `bearer_token`/`auth_token` patterns in API_KEY |
| `private_key` | CREDENTIAL | **PRIVATE_KEY** | Direct pattern match |
| `generic_secret` | CREDENTIAL | **OPAQUE_SECRET** | Catch-all by definition |
| `password_in_url` | CREDENTIAL | **OPAQUE_SECRET** | Embedded plaintext password |
| `github_token` | CREDENTIAL | **API_KEY** | GitHub personal/OAuth tokens match API_KEY patterns |

## Implementation order (TDD)

**Step 1 — Red: Write failing tests first**

Create `tests/test_corpus_loader.py::TestLoaderTaxonomyRefresh` with:

```python
class TestLoaderTaxonomyRefresh:
    def test_nemotron_map_no_stale_credential(self):
        from tests.benchmarks.corpus_loader import NEMOTRON_TYPE_MAP
        stale = {k: v for k, v in NEMOTRON_TYPE_MAP.items() if v == "CREDENTIAL"}
        assert stale == {}, f"Stale CREDENTIAL entries: {stale}"

    def test_gretel_en_map_no_stale_credential(self):
        from tests.benchmarks.corpus_loader import GRETEL_EN_TYPE_MAP
        stale = {k: v for k, v in GRETEL_EN_TYPE_MAP.items() if v == "CREDENTIAL"}
        assert stale == {}

    def test_detect_secrets_map_no_stale_credential(self):
        from tests.benchmarks.corpus_loader import _DETECT_SECRETS_TYPE_MAP
        stale = {k: v for k, v in _DETECT_SECRETS_TYPE_MAP.items() if v == "CREDENTIAL"}
        assert stale == {}
```

Also add the authoritative-vocabulary lint (this is the baseline for Item #3):

```python
def _load_valid_entity_types() -> set[str]:
    """Extract the set of valid entity_type names from standard.yaml."""
    import yaml, pathlib
    path = pathlib.Path(__file__).parent.parent / "data_classifier/profiles/standard.yaml"
    profile = yaml.safe_load(path.read_text())
    entity_types: set[str] = set()
    for entity in profile.get("profile", {}).get("entity_types", []):
        entity_types.add(entity["entity_type"])
    return entity_types

def test_all_loader_maps_emit_only_valid_entity_types():
    """Every value in any *_TYPE_MAP must be a valid entity_type."""
    from tests.benchmarks import corpus_loader
    valid = _load_valid_entity_types()
    valid.add("NEGATIVE")  # NEGATIVE_GROUND_TRUTH is the non-positive class

    # Walk every module-level dict that looks like a type map
    for name in dir(corpus_loader):
        obj = getattr(corpus_loader, name)
        if not isinstance(obj, dict):
            continue
        if not name.endswith("_TYPE_MAP") and name != "_DETECT_SECRETS_TYPE_MAP":
            continue
        invalid = {k: v for k, v in obj.items() if v not in valid}
        assert invalid == {}, f"{name} has invalid entity types: {invalid}"
```

Plus 2 positive spot-check tests (per spec test plan):
- `test_nemotron_password_maps_to_opaque_secret`
- `test_detect_secrets_private_key_maps_to_private_key`

**Run the new tests — they must FAIL** (red).

**Step 2 — Green: apply the mapping edits**

Edit `tests/benchmarks/corpus_loader.py`:
1. Lines 155–157 (NEMOTRON): `password→OPAQUE_SECRET`, `api_key→API_KEY`, `pin→OPAQUE_SECRET`
2. Line 170 (NEMOTRON identity): `"CREDENTIAL": "OPAQUE_SECRET"`
3. Lines 125–126 (GRETEL_EN): `password→OPAQUE_SECRET`, `api_key→API_KEY`
4. Lines 368–376 (_DETECT_SECRETS): all 9 entries per the drift table above

**Run the new tests — they must PASS** (green).

**Step 3 — Refactor + verify no regression**

Run the full `pytest tests/ -v` suite. Specifically watch:
- `test_secret_scanner.py` — should stay green (no code changes there)
- `test_corpus_loader.py` — existing tests should stay green, new tests green
- `test_meta_classifier_training.py` — should stay green (may be touched by parallel scanner-tuning batch; but that's their problem to rebase)
- `test_regex_engine.py` — should stay green

Expected test count: previous 1374 passed + 7 new tests = **1381 passing, 1 skipped**.

**Step 4 — Benchmark verification**

Run the two blind benchmarks:
```bash
python -m tests.benchmarks.accuracy_benchmark --corpus nemotron --samples 50 --blind
python -m tests.benchmarks.accuracy_benchmark --corpus gretel_en --samples 50 --blind
```

Record results in `docs/benchmarks/history/sprint_11.json` (create file if needed).

**Acceptance thresholds:**
- Nemotron blind F1 >= **0.82** (Sprint 9 baseline 0.821, Sprint 10 measured 0.774 due to drift — recovery expected)
- Nemotron named F1 >= **0.92** (non-regression)
- Gretel-EN blind F1 >= **0.60** (Sprint 10 baseline 0.611 — number may shift up or down as drift fix reveals real detection quality)

If Nemotron blind doesn't recover to ≥0.82, the root cause is not just taxonomy drift — stop and investigate before committing.

## Out of scope (explicit — do NOT expand here)

- **SecretBench/gitleaks/detect_secrets benchmark runs** — their loaders use `_DETECT_SECRETS_TYPE_MAP` which this item fixes, but they aren't in the `accuracy_benchmark.py --corpus` CLI yet. Running them would require either the fixture being present or the CLI being extended. Not in item #1 scope.
- **Item #3 drift lint implementation** — the `test_all_loader_maps_emit_only_valid_entity_types` test here IS the drift lint's baseline, but the full lint (CI integration, fake-loader regression test) is item #3's scope.
- **Gretel-finance corpus loader** — its type map was built in Sprint 10 with the new subtypes already, not the flat CREDENTIAL label. No refresh needed.
- **Nemotron taxonomy additions** (e.g., net-new ACCOUNT_PIN, BBAN) — Sprint 11 item `gretel-finance-taxonomy-expansion-net-new-entity-types` is the home for that work.

## Risks

1. **Gretel-EN blind number may MOVE** — Sprint 10's 0.611 was measured against stale `CREDENTIAL` labels. The fix changes the measurement. Acceptance threshold is ≥0.60 (non-catastrophic-regression); the actual delta could be positive (revealing previously-invisible wins) or slightly negative (revealing previously-invisible losses). Either is fine as long as it stays ≥0.60. Record whichever value comes out.
2. **Parallel scanner-tuning batch may touch `secret_key_names.json`** — confirmed NOT in their scope per earlier coordination. No collision risk expected.
3. **Meta-classifier feature vectors** — if the meta-classifier was trained with `CREDENTIAL` as an emitted class, changing the loader labels could cascade into training-data mismatches. The meta-classifier is currently in shadow-mode (Sprint 6) and the parallel scanner-tuning batch is retraining it anyway. This drift fix is the correct pre-training step.

## Commit message template

```
fix(sprint11): refresh corpus loader taxonomy maps to post-Sprint-8 4-subtype

Item: nemotron-corpus-loader-taxonomy-refresh-map-legacy-credential-to-4-subtypes

Scope expanded from Nemotron-only to 3 loaders (Sprint 10 lesson 1 audit
surface): NEMOTRON_TYPE_MAP, GRETEL_EN_TYPE_MAP, and _DETECT_SECRETS_TYPE_MAP
all emitted the stale flat CREDENTIAL label after Sprint 8's split into
API_KEY/PRIVATE_KEY/PASSWORD_HASH/OPAQUE_SECRET.

Mappings (authoritative taxonomy from profiles/standard.yaml):
- plaintext password/passcode/pin -> OPAQUE_SECRET
- api_key/access_key/slack/stripe/github/jwt tokens -> API_KEY
- private_key -> PRIVATE_KEY
- basic_auth/generic_secret/password_in_url -> OPAQUE_SECRET

Nemotron blind F1: 0.774 (Sprint 10) -> TBD (target >= 0.82)
Gretel-EN blind F1: 0.611 (Sprint 10) -> TBD (target >= 0.60)

Added static drift check (test_all_loader_maps_emit_only_valid_entity_types)
as baseline for Sprint 11 item #3 (corpus-loader-entity-taxonomy-drift-lint).
```
