# GLiNER Reference Guide

**Purpose.** Consolidated ground truth on GLiNER — the upstream library, its API, its output semantics, and how we use it — so we don't re-read the upstream docs every time we touch this code. Treat this file as the authoritative pointer when designing features, debugging confidence scores, or evaluating alternative models.

**Last refreshed.** 2026-04-15 (from urchade/GLiNER main, HF model cards, and the GLiNER paper).

**Maintenance contract.** This file is **project-internal ground truth**. Upstream can change; this file documents what we've verified, with a date. If you re-verify something, update the "Last refreshed" date at the section level, not just this header. If you find a contradiction between this file and upstream, trust upstream and update this file.

---

## 1. What we ship today

| Component | Value |
|---|---|
| **Model** | `urchade/gliner_multi_pii-v1` |
| **Author** | urchade (original GLiNER author; has since moved to Fastino) |
| **Released** | April 2024 |
| **License** | Apache-2.0 |
| **Python package** | `gliner` (v1.x) — **not** `gliner2` |
| **Architecture** | Uni-encoder, span-based NER |
| **Base model** | multilingual DeBERTa-v3 |
| **Size** | ~200M parameters |
| **Context window** | ~384 tokens on the encoder |
| **ONNX available** | Yes, distributed separately (see Sprint 8 memory — model bundling decoupled via the AR Python repo wheel) |
| **In-repo path** | `data_classifier/engines/gliner_engine.py` |
| **Tests** | `tests/test_gliner_engine.py` |

### Entity types we prompt GLiNER for

From `ENTITY_LABEL_DESCRIPTIONS` in `gliner_engine.py`:

| Our `entity_type` | GLiNER label prompt | Description |
|---|---|---|
| `PERSON_NAME` | `"person"` | Names of people or individuals, including first and last names |
| `ADDRESS` | `"street address"` | Street names, roads, avenues, physical locations |
| `ORGANIZATION` | `"organization"` | Company names, institutions, agencies |
| `DATE_OF_BIRTH` | `"date of birth"` | Dates representing when a person was born |
| `PHONE` | `"phone number"` | International phone numbers, any format |
| `SSN` | `"national identification number"` | Government-issued ID numbers (SSN, NI, tax ID) |
| `EMAIL` | `"email"` | Email addresses |
| `IP_ADDRESS` | `"ip address"` | IPv4 or IPv6 addresses |

**Observations.**

- We prompt 8 labels. The bi-encoder could handle 50+; the uni-encoder comfortably handles ~25–30 before per-label quality starts degrading (labels share the encoder's input token budget).
- We do not prompt `CREDIT_CARD`, `IBAN`, `BITCOIN_ADDRESS`, `HEALTH`, `NEGATIVE`, or any credential-family subtype. These are carried by regex / secret-scanner / heuristic engines, not GLiNER.
- The descriptions are project-internal additions (not part of the urchade model's training), wired in via the Sprint 10 NL prompt-wrapping — see §5.

### Engine position in the cascade

GLiNER is engine **order 5** (after regex, column_name, heuristic, secret_scanner). It runs when:
- The `gliner` package is installed (otherwise the engine raises `ModelDependencyError` and the cascade skips it)
- `DATA_CLASSIFIER_DISABLE_ML=1` is **not** set in the environment
- The column's `data_type` is **not** in the Sprint 10 non-text allowlist (`INTEGER`, `FLOAT`, `BOOLEAN`, `TIMESTAMP`, `DATE`, `DATETIME`, `TIME`, `BYTES`, etc.)

---

## 2. API ground truth

**Source of truth.** `gliner/model.py` in https://github.com/urchade/GLiNER, specifically the `BaseEncoderGLiNER` class.

### Primary entry points

```python
def predict_entities(
    self,
    text: str,
    labels: list[str],
    flat_ner: bool = True,
    threshold: float = 0.5,
    multi_label: bool = False,
    return_class_probs: bool = False,
    **kwargs,
) -> list[dict]:
    ...
```

Per-text inference. Returns a list of span dicts, each with **exactly** these keys:

```python
{
    "start": int,        # character offset (start of span in `text`)
    "end": int,          # character offset (end of span, exclusive)
    "text": str,         # the span's surface form
    "label": str,        # which prompted label won
    "score": float,      # per-class sigmoid probability in [0, 1]
    "class_probs": dict, # ONLY if return_class_probs=True — {label: prob} for top-5
}
```

```python
def inference(
    self,
    texts: list[str],
    labels: list[str],
    flat_ner: bool = True,
    threshold: float = 0.5,
    multi_label: bool = False,
    ...,
) -> list[list[dict]]:
    ...
```

Batch inference. Same semantics, returns one span-list per input text.

### Bi-encoder variant (not in production, but relevant)

```python
# Pre-compute label embeddings once
label_embeds = model.encode_labels(labels)

# Re-use across many predictions without re-encoding labels
results = model.batch_predict_with_embeds(texts, label_embeds, threshold=0.5)
```

This is the throughput win when you want to prompt 50+ labels. `urchade/gliner_multi_pii-v1` is **not** a bi-encoder — for bi-encoder use you'd need `knowledgator/gliner-bi-*` variants.

### Score semantics — the most important thing to know

> **Scores are per-label sigmoid probabilities, NOT softmax.**

From `gliner/decoding/decoder.py`:

```python
# BaseSpanDecoder.decode_batch — docstring:
#     probs (torch.Tensor): Probability tensor of shape (B, L, K, C),
#         already sigmoided.

# _find_candidate_spans — filter:
torch.where(probs > threshold)
```

Consequences:

1. **Scores are not comparable across labels.** A `score=0.9` on `person` is not "10x more likely than" `score=0.09` on `email`. The sigmoids are independent per-label.
2. **Scores are not calibrated against your empirical label rate.** The model's 0.5 threshold is the "more likely than not under sigmoid" point, not "50% precision on your golden set."
3. **Softmax-normalizing downstream is information-destroying** for multi-label use. If you want a linear-model-friendly input, prefer the logit transform `log(p/(1-p))`, not softmax.

### Decoding mode — `flat_ner` vs `multi_label`

The decoder resolves span overlaps in one of two modes:

- **`flat_ner=True, multi_label=False`** (default): Greedy non-overlapping, **winner-take-all per span**. If a span has two labels above threshold, only the highest wins. **This loses information for feature extraction.**
- **`multi_label=True`**: Same `(start, end)` span can appear multiple times in the output, once per label that clears threshold.
- **`flat_ner=False`**: Nested spans allowed (less relevant for our column-level use case).

### Top-k runner-ups per span — `return_class_probs`

When `return_class_probs=True`, each returned span carries an extra `class_probs` key with a dict of the **top-5 label probabilities** for that span:

```python
# From BaseSpanDecoder._get_top_k_class_probs, k=5 by default
span["class_probs"] = {
    "person": 0.87,
    "organization": 0.41,
    "street address": 0.12,
    "phone number": 0.08,
    "email": 0.03,
}
```

This is the cheapest way to get runner-up label signal without re-running inference.

### What happens when nothing fires

If no span has any label with `score > threshold`, **`predict_entities` returns `[]`**. There is no "empty fallback" confidence scoring for non-matching inputs. A column that returns zero spans is feature-indistinguishable from a column GLiNER returned low-confidence spans for — **unless you drop the threshold near zero**.

This is the single biggest gotcha for using GLiNER as a feature provider — see §3.

---

## 3. Known gotchas

### 3.1. Threshold=0.5 silently drops the non-firing signal

**Problem.** At the default threshold, any label that scores below 0.5 on every span is invisible to your downstream code. You cannot distinguish "GLiNER is 40% sure this is a phone number" from "GLiNER has never heard of a phone number." Both return nothing.

**Fix.** Drop threshold to `~0.01` (effectively 0, but leave some headroom for numerical noise) when using GLiNER for feature extraction. Let the meta-classifier learn its own per-label cutoffs from the raw scores.

### 3.2. `" ; "`-joined values are out-of-distribution

**Problem.** `urchade/gliner_multi_pii-v1` was fine-tuned on `urchade/synthetic-pii-ner-mistral-v1`, a dataset of **full-sentence paragraphs in 6 languages**. Feeding it `"value1 ; value2 ; value3"` is OOD. The model was never trained on this shape and will produce unreliable scores — specifically, it tends to over-fire `ORGANIZATION` and `PERSON_NAME` on numeric-looking strings because it's grasping for natural-language anchors that aren't there.

**Fix.** The Sprint 10 NL prompt-wrapping already addresses this, wrapping each chunk in a sentence template that mentions column / table / description metadata. See `_build_ner_prompt()` in `gliner_engine.py` and the Sprint 10 research memo at `docs/research/gliner-context/`. The +0.0887 macro F1 lift on Ai4Privacy (95% BCa CI [+0.050, +0.131]) is empirical confirmation.

**Do not revert** NL prompt-wrapping. The shape of the input has been measured to matter more than any other knob.

### 3.3. Greedy winner-take-all hides the runner-ups

**Problem.** Default `flat_ner=True, multi_label=False` means that when a span has `person: 0.87` and `organization: 0.81`, only `person` is returned. The `organization` signal — which might be exactly the disambiguation feature you want — is silently dropped.

**Fix.** Set `multi_label=True` for feature-extraction inference. The same span can then appear in the output twice (or more), once per label that cleared threshold.

### 3.4. Spans not aligned to word boundaries are silently dropped

**Problem.** From `_convert_spans_to_word_indices` in `model.py`: *"Spans that don't align to word boundaries are silently dropped."* This means that if the model predicts `"411111-1"` inside a `"4111111111111111"` credit card string, and the span doesn't fall on a word boundary, the entire prediction is discarded.

**Implication.** For structured strings without whitespace (credit cards, SSNs, IBANs, hashes), GLiNER may silently emit no findings even when the model internally believed one. This is one of the reasons we keep regex + secret_scanner as first-class engines for structured identifiers — GLiNER shouldn't be the primary detector for them.

### 3.5. `urchade/gliner_multi_pii-v1` has zero published benchmarks

**Problem.** The HuggingFace model card for `urchade/gliner_multi_pii-v1` has **no performance section**. No F1, no precision, no recall on any published PII benchmark. The Sprint 5 "blind F1 0.87" number from our own benchmarks is the only measurement we can cite.

**Implication.** We cannot anchor "how good should GLiNER realistically be" against an external ground truth. If our internal numbers drop, we have no upstream comparison to decide whether the model or our usage is at fault.

### 3.6. PII v1 is effectively end-of-life from urchade

**Problem.** urchade (the original author) has moved to Fastino and is now working on the unrelated GLiNER2 line. There has been no `gliner_multi_pii-v2` release. The model has been unchanged since April 2024. Do not expect future upstream fixes.

**Implication.** Any improvements we want in the PII model come from one of three paths: (a) we fine-tune ourselves on Apache-2.0 data, (b) we switch to a third-party GLiNER-derived PII model (see §6), or (c) we accept the v1 model as the ceiling.

---

## 4. Feature-extraction patterns

**Warning.** This section is unguided territory. Neither urchade/GLiNER nor GLiNER2 documents "how to turn GLiNER outputs into features for a downstream classifier." The upstream framing is always "GLiNER is the classifier; use it directly." When we feed GLiNER into our meta-classifier, we're using it off-label. Treat everything in this section as a **search space**, not settled practice.

### 4.1. Per-span → per-column aggregation

A column has N sample values. You run GLiNER on each (or on an NL-wrapped chunk of them). You get a list of span findings. You need a fixed-width feature vector for the meta-classifier. How?

Candidate aggregations, ordered by how much of the signal they preserve:

| Aggregation | What it captures | Feature dim | Notes |
|---|---|---:|---|
| **Presence** (`label_X_present: 0/1`) | "Did GLiNER fire this label anywhere in the column?" | N_labels | Cheapest. Discards confidence. |
| **Max score** (`label_X_max`) | Best-case confidence for the label | N_labels | Robust to noise. Ignores prevalence. |
| **Mean score above threshold** (`label_X_mean_positive`) | Average confidence when the label does fire | N_labels | Undefined when nothing fires — use 0 or a sentinel. |
| **Count above threshold** (`label_X_count`) | How many of N values fired | N_labels | Captures prevalence. Sensitive to N. |
| **Rate above threshold** (`label_X_rate`) | Count / N | N_labels | Normalized version of count. |
| **Top-k runner-ups** (using `return_class_probs=True`) | Full per-span distribution | N_labels × k | Strictly more information. |

A reasonable starting set of features per prompted label is **max + rate + presence** (3 × 8 = 24 new features for our current 8-label prompt). The meta-classifier can learn which one matters per family.

### 4.2. Pre-processing: NL prompt wrapping

Already shipped in Sprint 10 via `_build_ner_prompt()` in `gliner_engine.py`. **Keep it.** The wrap shape:

```
Column '{column_name}' from table '{table_name}'. Description: {description}. Sample values: {comma_joined_values}
```

Fall-back shape (metadata-free columns): `_SAMPLE_SEPARATOR.join(chunk)` — the pre-Sprint-10 behavior, preserved for backward compatibility with connectors that don't populate context fields.

### 4.3. Prompting strategies — bare labels vs descriptions

Two techniques, both supported:

1. **Bare label.** `predict_entities(text, labels=["person", "organization", "email"])` — works, but the label string is the only semantic anchor.
2. **Label + description.** Prepend the description inside the NL-wrap itself, or (if using GLiNER2) pass a `{label: description}` dict natively.

The urchade README mentions: *"Most GLiNER models should work best when entity types are in lower case or title case."* The codebase currently uses lowercase descriptive phrases (`"person"`, `"street address"`, `"national identification number"`) rather than bare labels (`"PERSON_NAME"`). This is the right convention — the model is trained on natural-language text, not typed schema identifiers.

### 4.4. Concrete knobs for feature-extraction use

When calling GLiNER as a **feature provider** (not as the decision-maker), set these flags:

```python
spans = model.predict_entities(
    text=nl_wrapped_column_text,
    labels=prompted_label_list,
    threshold=0.01,          # ~0, let the meta-classifier decide cutoffs
    multi_label=True,         # keep all above-threshold labels per span
    return_class_probs=True,  # include top-5 runner-ups per surviving span
)
```

Then apply whatever aggregation (§4.1) you chose before emitting features.

### 4.5. Logit transform before feeding to logistic regression

Scores are sigmoids in [0, 1]. For a linear model like our meta-classifier's logistic regression, the natural input is **logits**:

```python
import numpy as np

def to_logit(p: float, eps: float = 1e-6) -> float:
    p = np.clip(p, eps, 1.0 - eps)
    return np.log(p / (1.0 - p))
```

This avoids saturation at 0 and 1 (where the linear model's coefficients lose meaning) and gives the model a more informative scale to learn from. Apply per-feature, after aggregation.

### 4.6. Negative-class decoy labels

A **documented-nowhere but cheap-to-try** technique: add decoy labels like `"miscellaneous text"`, `"ordinary noun"`, `"common phrase"`, `"filler"` to the prompted label list. The idea is to give the model an alternative to weakly matching a real PII label when it's genuinely seeing ambiguous content. If the decoy wins, the real labels' scores should suppress.

No upstream blueprint for this. Worth an ablation experiment if we see over-fire on ambiguous content.

---

## 5. Model alternatives

### 5.1. What's currently available

| Model | Publisher | License | Size | PII-tuned? | Our status |
|---|---|---|---:|---|---|
| `urchade/gliner_multi_pii-v1` | urchade (2024-04) | Apache-2.0 | ~200M | Yes | **In production** |
| `urchade/gliner_multi-v2.1` | urchade (2025-12) | Apache-2.0 | ~200M | No (general NER) | Not used |
| `urchade/gliner_medium-v2.1` | urchade | Apache-2.0 | ~150M | No | Not used |
| `knowledgator/gliner-bi-*` | Knowledgator | Apache-2.0 | various | No (general NER) | Not used |
| `info-wordcab/wordcab-pii` variants | Wordcab × Knowledgator | Apache-2.0 | various | **Yes** | Not evaluated |
| `fastino/gliner2-base-v1` | Fastino | Apache-2.0 | 205M | No (general extraction) | **Tried, reverted** (Sprint 10) |
| `fastino/gliner2-large-v1` | Fastino | Apache-2.0 | 340M | No | Not used |
| `gliner.pioneer.ai` XL | Fastino (hosted) | Proprietary API | 1B | No | N/A (paywalled) |

### 5.2. Why we're on v1 today

- `urchade/gliner_multi_pii-v1` is the only urchade model fine-tuned on PII specifically.
- Sprint 5 shipped it with blind F1 0.87 — good enough to deploy.
- Fastino GLiNER2 was attempted in Sprint 10 (see `backlog/promote-gliner-tuning-fastino-base-v1.yaml` and `docs/research/gliner_fastino/fastino_promotion_draft_20260414.patch`) and reverted due to a **structural issue** with the promotion path (Sprint 11 retry is filed; not yet executed).
- `wordcab-pii` and `knowledgator` bi-encoder PII variants have not been evaluated against our golden set.

### 5.3. When to revisit

Revisit the model choice if:

- The v3 meta-classifier plateau is traced to GLiNER's per-family confidence quality being the bottleneck (specifically on the CONTACT and CREDENTIAL families).
- A credible head-to-head F1 number for `wordcab-pii` against our golden set exists (we'd need to run that ourselves — no public comparison).
- Sprint 11 retry of the fastino promotion succeeds and shows a measurable lift.
- Fastino or urchade releases a new PII-specific model (currently nothing in the release pipeline).

**Do not** migrate purely because GLiNER2 is "newer." It's a different package with a different API and does not have a PII fine-tune.

### 5.4. GLiNER2 vs GLiNER — the package/API difference

If we ever migrate to GLiNER2, be aware:

| Aspect | `gliner` (v1.x, urchade) | `gliner2` (Fastino) |
|---|---|---|
| Import | `from gliner import GLiNER` | `from gliner2 import GLiNER2` |
| Entity extraction | `model.predict_entities(text, labels)` → list of span dicts | `model.extract_entities(text, labels)` → dict keyed by label |
| Label descriptions | Not native — emulate via NL wrapping | **Native** — pass `{label: description}` dict |
| Classification | Not first-class — use `multitask/classification.py` pipeline | **First-class** — `classify_text(text, classes, cls_threshold=0.4)` |
| Structured extraction | Not available | `extract_json(text, schema)` |
| PII fine-tune available | **Yes** (v1) | **No** |

A GLiNER2 migration is **not** a drop-in replacement — it's a rewrite of `gliner_engine.py`. Treat it as a research thread, not a Sprint 12 swap.

---

## 6. Concrete knob settings for feature-provider use

Consolidated checklist when using GLiNER as a meta-classifier feature provider (not as a decision-maker):

- [ ] `multi_label=True` — keep all above-threshold labels per span
- [ ] `return_class_probs=True` — include top-5 runner-ups per span
- [ ] `threshold=0.01` — effectively zero, let the meta-classifier decide cutoffs
- [ ] NL prompt wrapping (already via `_build_ner_prompt()`)
- [ ] Logit transform scores before feeding to logistic regression (`log(p/(1-p))` per feature after aggregation)
- [ ] Aggregate per-column via at least `{max, rate, presence}` per label
- [ ] Emit one feature per `(label, aggregation)` pair — don't collapse to argmax
- [ ] Keep the 8 currently-prompted labels as the starting set; experiment with adding `HEALTH` entities and `NEGATIVE` decoys as separate ablations
- [ ] Do **not** apply softmax across labels — it destroys independent sigmoid information
- [ ] Do **not** use the default `threshold=0.5` — you will lose runner-up signal that the meta-classifier needs

---

## 7. Source URLs

### Primary

- **urchade/GLiNER repo**: https://github.com/urchade/GLiNER
- **`gliner/model.py`** (predict_entities, inference, bi-encoder methods, ONNX export): https://github.com/urchade/GLiNER/blob/main/gliner/model.py
- **`gliner/decoding/decoder.py`** (sigmoid confirmation, Span dataclass, `class_probs`, multi-label semantics): https://github.com/urchade/GLiNER/blob/main/gliner/decoding/decoder.py
- **`gliner/multitask/classification.py`** (post-hoc softmax for classification use, "other" fallback): https://github.com/urchade/GLiNER/blob/main/gliner/multitask/classification.py

### Model cards

- **`urchade/gliner_multi_pii-v1`** (the model we ship): https://huggingface.co/urchade/gliner_multi_pii-v1
- **urchade HF org index** (all urchade models): https://huggingface.co/urchade

### Papers

- **GLiNER paper** (original): https://arxiv.org/abs/2311.08526
- **GLiNER multi-task paper**: https://arxiv.org/abs/2406.12925
- **Million-Label NER (bi-encoder)**: https://arxiv.org/abs/2602.18487

### Alternatives

- **Fastino GLiNER2**: https://github.com/fastino-ai/GLiNER2
- **Wordcab PII**: https://github.com/info-wordcab/wordcab-pii

### Internal references

- **Engine source**: `data_classifier/engines/gliner_engine.py`
- **Engine tests**: `tests/test_gliner_engine.py`
- **NL prompt-wrapping research**: `docs/research/gliner-context/` (Sprint 10 S1 thread)
- **Fastino promotion draft**: `docs/research/gliner_fastino/fastino_promotion_draft_20260414.patch` (Sprint 10 attempt, reverted)
- **Fastino promotion backlog item**: `backlog/promote-gliner-tuning-fastino-base-v1.yaml`
- **Meta-classifier feature schema**: `data_classifier/orchestrator/meta_classifier.py` (`FEATURE_NAMES`, `PRIMARY_ENTITY_TYPES`)
- **Training data extractor**: `tests/benchmarks/meta_classifier/extract_features.py`

---

## 8. Open research threads this file informs

1. **GLiNER as meta-classifier feature provider (Sprint 12+).** Concrete design starts from §4 and §6. Not yet filed as a backlog item; see the session discussion on 2026-04-15 for the motivation.
2. **Fastino GLiNER2 Sprint 11 retry.** Filed as `backlog/promote-gliner-tuning-fastino-base-v1.yaml`. Re-read §5 before attempting — the structural issue from Sprint 10 has not been root-caused.
3. **Wordcab-pii head-to-head evaluation.** Not filed. Worth a research item if the GLiNER-as-feature path hits a quality ceiling.
4. **HEALTH family GLiNER coverage.** The Sprint 11 family A/B result memo (`docs/research/meta_classifier/sprint11_family_ab_result.md`) shows the live path has **zero** HEALTH representation (no regex patterns). Adding HEALTH entity labels to the GLiNER prompt is the cheapest way to unlock that family in the live cascade — see §1 ("Entity types we prompt GLiNER for").
