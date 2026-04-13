# GLiNER2 Model Evaluation — Research Brief

> **Prepared by:** main session, 2026-04-13
> **For:** a fresh claude session that will run this experiment unattended in this worktree
> **Worktree:** `/Users/guyguzner/Projects/data_classifier-gliner-eval`
> **Branch:** `research/gliner-eval` (off main)
> **Backlog item:** `gliner2-model-evaluation-compare-gliner2-base-v1-vs-gliner-multi-pii-v1-test-pii-accuracy-confidence-score-alternatives-description-impact` (P2, M, unplanned)

## Why this experiment matters

The data_classifier currently ships `urchade/gliner_multi_pii-v1` as the default GLiNER2 model. Production blind macro F1 is **0.872 on Nemotron** and **0.667 on Ai4Privacy**. The Ai4Privacy 0.667 number is the worst real-corpus number we have, and lifting it is the highest-leverage accuracy win on the BQ-track roadmap (BigQuery is the only active consumer; HTTP/standalone-deployment infra is deprioritized indefinitely).

There are two possible reasons Ai4Privacy is stuck at 0.667:

1. **Configuration ceiling** — the existing model can do better with different thresholds, descriptions, or label names, but we haven't tuned exhaustively
2. **Model ceiling** — the model is at its limit; we'd need a different/complementary NER to lift it

**This experiment is the test for fork 1.** It does NOT add a new model. It exhaustively tunes the existing `urchade/gliner_multi_pii-v1` and the alternative `fastino/gliner2-base-v1` (which Sprint 5 rejected after a narrow test). The result determines whether we invest in a second NER model later, or whether we just ship a config change.

## What Sprint 5 already established

- `urchade/gliner_multi_pii-v1` is the default. PII-specific tuning, 205M params.
- `fastino/gliner2-base-v1` was tested in Sprint 5 and rejected — it dominated on partial addresses (descriptions helped) but **lost on PII detection** (classified person names as addresses). Test was narrow.
- Label name tuning matters: "person" beats "person name", "street address" beats "physical address", "national identification number" beats "social security number". These are documented in `data_classifier/engines/gliner_engine.py:43` (`ENTITY_LABEL_DESCRIPTIONS`).
- Default threshold is `_DEFAULT_GLINER_THRESHOLD = 0.5` (`gliner_engine.py:97`).
- Multi-model support exists — the engine can swap `_MODEL_ID` cleanly.

## The experiment

Create `scripts/evaluate_gliner_models.py` that runs a structured sweep:

### Models to test

1. `urchade/gliner_multi_pii-v1` (current production)
2. `fastino/gliner2-base-v1` (Sprint 5 reject — re-test with description tuning)

### Sweep dimensions

For each model:

| Dimension | Values | Why |
|---|---|---|
| **Threshold** | 0.3, 0.4, 0.5, 0.55, 0.6, 0.7, 0.8 | Default is 0.5; lower may catch more, higher may reduce FPs. The right threshold may differ per model. |
| **Description impact** | with descriptions / without descriptions | Sprint 5 said descriptions helped `gliner2-base-v1` more than `gliner_multi_pii-v1`. Quantify it per entity type. |
| **Label name variants** | the current "tuned" set in `ENTITY_LABEL_DESCRIPTIONS` AND the alternatives below | Label phrasing matters; document which phrasing wins per model per entity type. |

Label name alternatives to test (per entity type — at least the one we use plus one alternative):

| Entity type | Current label | Alternative(s) to test |
|---|---|---|
| PERSON_NAME | `person` | `person name`, `full name`, `individual name` |
| ADDRESS | `street address` | `physical address`, `mailing address`, `home address` |
| ORGANIZATION | `organization` | `company`, `institution`, `business name` |
| DATE_OF_BIRTH | `date of birth` | `birthday`, `birth date`, `birth_date` |
| PHONE | `phone number` | `telephone`, `phone`, `contact number` |
| SSN | `national identification number` | `social security number`, `government id`, `tax id` |
| EMAIL | `email` | `email address`, `e-mail` |
| IP_ADDRESS | `ip address` | `internet protocol address`, `ipv4 address` |

You don't need a full Cartesian product across labels — that's hundreds of combinations per model. **Strategy:** use the current label as the baseline, swap ONE label at a time per run, measure delta. This is O(N entity types × 2-3 alternatives × 2 models × 7 thresholds) ~ a few hundred combinations, manageable in 30-60 minutes.

### Corpora

- **Ai4Privacy blind** — `from tests.benchmarks.corpus_loader import load_ai4privacy_corpus; corpus = load_ai4privacy_corpus(blind=True)`
- **Nemotron blind** — `from tests.benchmarks.corpus_loader import load_nemotron_corpus; corpus = load_nemotron_corpus(blind=True)`

**`blind=True` is mandatory** — it strips column name hints so we measure pure value-based detection, which is what GLiNER actually contributes. Named-mode hides the GLiNER signal because column_name engine dominates.

For speed, use `max_rows=500` per corpus during the sweep. Once the best config is identified, do a full-corpus confirmation run on that single config.

### Metrics per run

- **Macro F1 per corpus** (blind mode)
- **Per entity type F1** (so you can see which types each config helps/hurts)
- **Latency per column** (a slower config that gains 0.02 F1 may not be worth it)
- **Total wall time for the sweep**

### Output

1. `scripts/evaluate_gliner_models.py` — the sweep script. Self-contained. Should accept a `--quick` flag for 100-row sanity runs and a `--full` flag for the actual experiment.
2. `docs/research/GLINER_MODEL_EVALUATION.md` — the result memo. Include:
   - Table of best config per model on each corpus
   - Per entity type breakdown for the winning config (which types lifted, which dropped)
   - **Recommendation:** ship a config change to production, OR proceed to fork 2 (complementary NER research). Justify with numbers.
   - Latency cost of the recommended config vs current
   - List of label alternatives that won/lost per entity type — useful for future tuning
3. A JSON results dump alongside the memo so future sessions can inspect raw numbers.

## How to run

This worktree has its own venv setup needs. Make sure GLiNER's optional dependencies are installed:

```bash
cd /Users/guyguzner/Projects/data_classifier-gliner-eval
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,gliner]"  # check pyproject.toml for the exact extra name
```

**Verify the venv is active** before running anything — there's a feedback memory `feedback_verify_venv_before_trusting_tests.md` about a Sprint 7 incident where the wrong python silently picked up missing extras. Run `python -c "import sys; print(sys.executable)"` and confirm it's the local `.venv`.

The `gliner2-base-v1` model needs to be downloaded the first time — that may take a few minutes. Don't optimize this away.

## Acceptance criteria for completion

- [ ] `scripts/evaluate_gliner_models.py` exists, is lint-clean (`ruff check . && ruff format --check .`), and runs end-to-end without errors
- [ ] Both models tested on both blind corpora at all threshold values
- [ ] Description impact measured per entity type per model
- [ ] At least the priority label alternatives tested (PERSON_NAME, ADDRESS, ORGANIZATION, SSN — these are the highest-error types per Sprint 5/6 numbers)
- [ ] `docs/research/GLINER_MODEL_EVALUATION.md` written with: config table, per-type breakdown, latency, recommendation
- [ ] JSON raw results dumped alongside the memo
- [ ] Commits land on `research/gliner-eval` branch (already created — just `git add` and commit)
- [ ] Final commit: `research(gliner-eval): structured eval results + recommendation`
- [ ] Push to origin: `git push -u origin research/gliner-eval`

## Decision matrix the recommendation should use

Based on the result, the memo should make ONE of these recommendations:

| If the best config lifts Ai4Privacy by... | Recommendation |
|---|---|
| **≥ 0.05 F1** (e.g., 0.667 → 0.72+) | **Ship the config change as a Sprint item.** The model isn't capped — we just need to tune it. Update `_DEFAULT_GLINER_THRESHOLD`, `ENTITY_LABEL_DESCRIPTIONS`, and possibly `_MODEL_ID` in `gliner_engine.py`. Run full benchmark to confirm. Skip fork 2. |
| **0.02–0.05 F1** | **Marginal lift — ship the easy wins, then proceed to fork 2.** Document which sub-tuning (threshold vs labels vs descriptions) gave the most lift. Fork 2 still worth pursuing but with lower urgency. |
| **< 0.02 F1** | **GLiNER is at its configuration ceiling.** Recommend kicking off fork 2: research a complementary NER (piiranha-v1, deberta_finetuned_pii, presidio underlying NER, etc.). Document which entity types are most stuck so fork 2 can target them. |

The decision matrix is the most important part of the memo. Don't bury it.

## Rules — do NOT touch

- **DO NOT modify** `data_classifier/engines/gliner_engine.py` from this experiment. The eval script must drive the model externally (instantiate GLiNER directly, not via the engine class) so production code stays untouched. If you find that the engine class is impossible to bypass, report it and stop — that's a finding worth knowing.
- **DO NOT touch** anything in other worktrees (`data_classifier-e10`, `data_classifier-research-ops`, `data_classifier-sprint7`, `data_classifier`). Each is owned by another session.
- **DO NOT push to `main`** or any other branch. Only `research/gliner-eval`.
- **DO NOT modify** the corpora loaders or fixtures. Use them read-only.

## When you're done

Push the branch and write a one-paragraph summary. The main session will pick it up, summarize for the user, and decide whether to merge to main as a productive engine improvement (Tier 1 winner case) or as research-only documentation (Tier 3 capped case).

## Self-test before starting

Before running the sweep, do a sanity check:
1. Activate the venv
2. `python -c "from gliner import GLiNER; m = GLiNER.from_pretrained('urchade/gliner_multi_pii-v1'); print(m)"` — confirms the production model loads
3. `python -c "from tests.benchmarks.corpus_loader import load_ai4privacy_corpus; c = load_ai4privacy_corpus(blind=True, max_rows=10); print(len(c.columns))"` — confirms the corpus loader works
4. Run a 10-column quick smoke at default config and verify the F1 is in the same ballpark as the production 0.667 number (it should be lower because of the small sample, but should not be near zero — if it is, something is wrong with the eval script).

If any of those four checks fail, fix the setup before running the sweep — wasted compute on a broken setup is the most common failure mode.
