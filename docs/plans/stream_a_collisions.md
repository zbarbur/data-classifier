# Stream A: Collision Resolution + AWS Pattern Redesign

## Items
1. Three-way SSN/ABA/SIN collision resolution (P1, S)
2. NPI vs PHONE collision resolution (P1, S)
3. DEA vs IBAN collision resolution (P1, S)
4. Collision pair unit tests (P2, S)
5. AWS secret key pattern redesign (P2, S)

## Files Modified
- `data_classifier/orchestrator/orchestrator.py` — collision logic
- `data_classifier/patterns/default_patterns.json` — AWS pattern
- `tests/test_collision_resolution.py` — NEW dedicated test file
- `tests/test_patterns.py` — AWS pattern test updates

## Implementation Order

### Step 1: Three-way SSN/ABA/SIN Collision Resolution

Current state: `_COLLISION_PAIRS` has 3 pairwise entries for SSN/ABA/SIN. The problem is these run independently — if all three co-occur, pairwise resolution may remove the wrong one.

**Changes to `orchestrator.py`:**

1. Add a `_resolve_three_way_collisions()` method that runs BEFORE pairwise resolution.
2. Detection: check if all three of SSN, ABA_ROUTING, CANADIAN_SIN are present in findings.
3. Resolution strategy:
   - If heuristic engine contributed (check `finding.engine`): use cardinality signal
     - High cardinality (many unique values) → SSN (unique per person)
     - Low cardinality (few unique values) → ABA_ROUTING (reused routing numbers)
     - Canadian SIN: boost if column name contains "sin" or context is Canadian
   - If column name engine contributed: trust column name signal (it's the most reliable)
   - Fallback: keep highest confidence, suppress others with gap > threshold
4. Remove the two losers from findings dict.
5. Call this before `_resolve_collisions()` in `classify_column()`.

### Step 2: NPI vs PHONE Collision Resolution

Current state: NPI/PHONE is already in `_COLLISION_PAIRS` but uses only confidence gap. NPI often loses because PHONE regex fires with higher confidence on 10-digit numbers.

**Changes to `orchestrator.py`:**

1. Add resolver logic specific to NPI/PHONE inside `_resolve_collisions()`.
2. When NPI and PHONE collide:
   - Check if column name engine found NPI (column name contains "npi", "provider", "prescriber") → NPI wins regardless of confidence gap
   - Check if NPI finding has validator confirmation (Luhn) → boost NPI confidence
   - Otherwise: PHONE wins (it's far more common than NPI in general data)
3. This replaces the generic gap-based resolution for this specific pair.

### Step 3: DEA vs IBAN Collision Resolution

Current state: DEA/IBAN is in `_COLLISION_PAIRS` but uses only confidence gap.

**Changes to `orchestrator.py`:**

1. Add resolver logic specific to DEA/IBAN.
2. When DEA and IBAN collide:
   - DEA format: exactly 2 letters + 7 digits (9 chars total), with check digit
   - IBAN format: 2 letters + 2 digits + up to 30 alphanumeric (15-34 chars)
   - Length-based: if values are 9 chars → DEA; if values are 15+ chars → IBAN
   - Validator-based: if DEA check digit validates → DEA wins; if IBAN mod-97 validates → IBAN wins
   - Column name signal as tiebreaker

### Step 4: Collision Pair Unit Tests

Create `tests/test_collision_resolution.py` with:

1. **Fixtures**: Helper function to create mock `ClassificationFinding` objects with specific entity types, confidences, and engine names.
2. **Parameterized tests for each pair:**
   - SSN/ABA pairwise (existing, verify still works)
   - SSN/SIN pairwise
   - ABA/SIN pairwise
   - SSN/ABA/SIN three-way with high cardinality → SSN
   - SSN/ABA/SIN three-way with low cardinality → ABA
   - SSN/ABA/SIN three-way with column name "sin" → SIN
   - SSN/ABA/SIN three-way no signal → highest confidence
   - NPI/PHONE with NPI column name → NPI
   - NPI/PHONE without column name → PHONE
   - DEA/IBAN with 9-char values → DEA
   - DEA/IBAN with 20-char values → IBAN
   - CREDENTIAL suppression (existing, verify still works)
3. **Edge cases:**
   - Equal confidence for collision pair → both kept
   - Gap exactly at threshold → both kept
   - Gap just above threshold → loser suppressed
   - Single finding (no collision) → unchanged

### Step 5: AWS Secret Key Pattern Redesign

Current state: `aws_secret_key` pattern matches `[A-Za-z0-9/+=]{40}` which is too broad — matches git SHAs, checksums, any 40-char base64 string.

**Changes to `default_patterns.json`:**

1. Option A (preferred): Add context_words requirement to the pattern:
   - `context_words`: ["aws_secret", "secret_access_key", "AWS_SECRET_ACCESS_KEY", "AKIA"]
   - This means the pattern only fires when AWS context is nearby
2. Option B: Remove the standalone pattern entirely, rely on secret scanner's key-name matching
3. Update `examples` and `counter_examples` in the pattern definition

**Changes to `tests/test_patterns.py`:**
- Test: AWS secret with "aws_secret_access_key=" context → detected
- Test: Random 40-char base64 without context → NOT detected
- Test: Git SHA (40 hex chars) → NOT detected

## Acceptance Criteria Verification
After all changes:
- `pytest tests/ -v` — all green
- `ruff check . --exclude .claude/worktrees && ruff format --check . --exclude .claude/worktrees` — clean
- Run accuracy benchmark to verify FP reduction
