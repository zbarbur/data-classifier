# GLiNER fastino promotion — preserved draft

## What's here

- `fastino_promotion_draft_20260414.patch` — 412-line unified diff against `gliner_engine.py` + `tests/test_gliner_engine.py`, captured from the uncommitted state of agent worktree `agent-a3a8db1f` (HEAD `5a7b662`) on 2026-04-14.

## Scope of the patch

The infrastructure half of the fastino promotion already landed on `main` as commit `29db52c` ("feat(sprint9): v2 inference infrastructure — threshold plumbing fix + descriptions flag + ONNX guard"). This patch is the **minimal remaining delta** needed to complete the promotion:

1. `_MODEL_ID`: `urchade/gliner_multi_pii-v1` → `fastino/gliner2-base-v1`
2. `_DEFAULT_GLINER_THRESHOLD`: 0.5 → 0.80 (fastino optimal per Sprint 9 eval memo)
3. `ENTITY_LABEL_DESCRIPTIONS` label swaps: `"person"` → `"full name"`, `"national identification number"` → `"social security number"`
4. New test classes: `TestFastinoDefaults` (7 assertions on the defaults above) and `TestFastinoV2InferencePath` (2 tests verifying the list[str] vs dict[str, str] entity_spec codepath selection based on `descriptions_enabled`)

## Dependency — do NOT apply this patch directly

The `promote-gliner-tuning-fastino-base-v1` backlog item was blocked in Sprint 9 on blind-corpus regressions (-0.13 Gretel-EN, -0.19 Nemotron). The unblock path is `promote-s1-nl-prompt-wrapping-gliner-engine-...` (Sprint 10 P1 item) — S1 NL-prompt wrapping must land on `main` first. Research evidence is on the `research/gliner-context` branch @ `7b2ed91`, Pass 1 memo at `docs/experiments/gliner_context/runs/20260413-2300-pass1/result.md`.

## How to use this patch

When the fastino promotion item is picked up in a sprint:

1. Confirm S1 NL-prompt wrapping has already landed on `main`.
2. Cherry-pick or manually re-apply this patch against current `gliner_engine.py` — expect minor conflicts since the engine may have moved.
3. Run the acceptance criteria from the `promote-gliner-tuning-fastino-base-v1` backlog item (blind-corpus delta gates on Gretel-EN and Nemotron).
4. Delete this patch and the README after merge — the content will be on `main` at that point.
