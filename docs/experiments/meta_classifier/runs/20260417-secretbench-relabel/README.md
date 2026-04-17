# SecretBench value-level relabel — 2026-04-17

## Problem

SecretBench (Basak & Neil, MSR 2023 — [arxiv:2303.06729](https://arxiv.org/abs/2303.06729)) labels candidate secrets based on whether they correspond to a real leak in the **source-code context** of the match. That's the right semantics for tool-alignment evaluation — it answers *"did the scanner's match correctly identify a leaked secret at these file coordinates?"* — but it's the wrong semantics for **column-value classification**, which asks *"is this value a secret?"*

The gap shows up as ~24% "mislabels" from our perspective on the 516 `is_secret=True` entries: prose sentences, empty `<Password></Password>` tags, bare `${VAR}` references, path fragments, and `case "Password":` code-syntax tokens all carry `is_secret=True` because a real secret existed *somewhere in the surrounding file*, not because the stored value string is one.

## What was done

Relabeled the 1,068-row fixture `tests/fixtures/corpora/secretbench_sample.json` at **value granularity** by flipping 178 `is_secret=True → False` where the value string itself is structurally unambiguous-not-a-secret.

No `False → True` flips — that direction would require evidence beyond what upstream had, and the first attempt produced 8/9 spurious hits.

## Outputs

- `../../../tests/fixtures/corpora/secretbench_sample_v2.json` — relabeled fixture. Each flipped row has `relabel_rule`, `relabel_notes`, and `upstream_is_secret` fields alongside the adjusted `is_secret`.
- `secretbench_sample_v1_upstream.json` — preserved upstream copy for reproducibility.
- `confident_relabels.jsonl` — 167 auto-flagged flips with rule name + per-row notes.
- `user_reviewed_flips.jsonl` — 11 flips confirmed by human review on 2026-04-17.
- `summary.json` — counts, rules, file paths.

## Rule breakdown (178 True→False flips)

| Rule | Count | Example |
|---|--:|---|
| `var_ref_only` | 88 | `PSWRD="${env.PSWRD}"` |
| `prose_sentence` | 38 | `Have you heard of the passwd application...` |
| `empty_cred_value` | 12 | `password =` |
| `key_equals_self` | 11 | `password = "password"` |
| `user_reviewed` | 11 | 11 edge cases confirmed by human review |
| `pem_header_only` | 5 | `-----BEGIN RSA PRIVATE KEY-----` (header only, no body) |
| `example_literal` | 3 | `AKIAI44QH8DHBEXAMPLE` |
| `trivial_short_value` | 3 | `"password": "a"` |
| `empty_xml_tag` | 3 | `<Password></Password>` |
| `xml_tag_fragment` | 2 | bare `<Password>` or `</Password>` |
| `func_call_getter` | 1 | `password=credentials.getPassword();` |
| `code_syntax_ref` | 1 | `case "Password":` |

## Before / after

| | is_secret=True | is_secret=False |
|---|--:|--:|
| upstream | 516 | 552 |
| v2 | 338 | 730 |

## Scope and caveats

- This is a **value-level** relabel. It does not contradict SecretBench's original labels under their intended semantics (tool-alignment) — it derives a different label for a different question.
- The `False → True` direction remains untouched. Upstream `is_secret=False` entries in v2 match upstream v1.
- Production code under `data_classifier/` still reads `secretbench_sample.json`. Adoption of v2 for benchmark gates is a separate sprint-14 decision — this run only produces the artifact.
- Reproduce with: `.venv/bin/python scripts/relabel_secretbench.py --input tests/fixtures/corpora/secretbench_sample.json --out-dir docs/experiments/meta_classifier/runs/20260417-secretbench-relabel`
