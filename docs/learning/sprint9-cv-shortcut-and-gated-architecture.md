# Sprint 9 Learning Memo — Shortcut Learning, Honest CV, and Gated Architectures

> **Scope:** Concepts and takeaways from the Sprint 9 investigation into the
> meta-classifier's cross-validation methodology. Worked example of how a
> "shortcut feature" can inflate reported ML metrics by ~60 F1 points without
> anyone noticing, and how the fix is usually at the data/measurement level
> rather than the model level.
>
> **Audience:** Anyone on the data_classifier project (or adjacent ML projects)
> who wants to understand *why* the M1 fix was necessary, what the honest
> numbers mean, and how to avoid the same trap next time.
>
> **Companion artifacts:**
> - M1 research memo: `docs/experiments/meta_classifier/runs/m1-2026-04-13/result.md` on `research/meta-classifier`
> - M1 promotion commits: `6b74da7` + `b331ab1` on `sprint9/main`
> - Sprint 8 license audit + dataset landscape: `docs/process/LICENSE_AUDIT.md` (Sprint 9), `docs/experiments/meta_classifier/dataset_landscape.md` on `research/meta-classifier @ cd3a5cc`

---

## The starting puzzle

Sprint 6 shipped a meta-classifier with a headline **CV macro F1 of 0.916** — which looked promising, since the rest of the cascade (regex, column name, heuristic, secret scanner, GLiNER2) was hovering around 0.65–0.75 on blind corpora. The meta-classifier seemed to be closing a huge gap.

Then Sprint 6 also reported a **LOCO macro F1 of ~0.30**. The same model. The same data. Evaluated two different ways. A 0.55-point gap between them.

That gap triggered Q3 (the LOCO investigation), which concluded the Sprint 6 headline was inflated by **corpus-fingerprint leakage across CV folds** — the model was learning which corpus a sample came from as a proxy for the label, and the random-split CV couldn't see the problem.

Sprint 9's M1 item was the code fix for that diagnosis. After M1 landed, sprint9/main's honest numbers are:

| Metric | Sprint 6 claim | M1 on sprint9/main (2026-04-13) |
|---|---:|---:|
| best_c | 100.0 | **1.0** |
| CV mean macro F1 | 0.9160 | **0.1940 ± 0.0848** |
| Held-out test F1 | ~0.92 | 0.8511 |
| Tertiary blind delta (meta − live) | +0.257 (Sprint 6) → +0.191 (E10) | **+0.2432** (post-Gretel ingest) |
| LOCO mean | ~0.30 | ~0.17 |

**The model didn't get worse. The measurement got honest.** Most of the 0.66 CV drop is the old CV metric lying; a smaller portion is the training data changing when we swapped ai4privacy for Gretel-EN. The new LOCO mean of ~0.17 is what the model *actually does* on held-out corpora — what would happen if a BigQuery customer ran this against a brand-new data source the model has never seen.

The rest of this memo explains why this happened, how to avoid it next time, and what it implies for the future architecture of the classifier.

---

## 1. Shortcut learning

**A shortcut feature is any signal in your training data that correlates with the target label for reasons unrelated to the causal mechanism you care about.** Classifiers are lazy — they find the easiest-to-compute feature that separates the classes on the training distribution, regardless of whether that feature would still work under a different distribution.

The classical example: an X-ray classifier trained to detect pneumonia learned to look at the *image metadata tag* rather than the lung shadows. Portable X-ray machines were used in the ICU for sick patients; the metadata tag for "portable" correlated with "pneumonia" in the training data. The classifier never learned what pneumonia looks like. It learned what ICU metadata looks like, and it looked great under random-split evaluation. Deployed on a new hospital's equipment, it fell apart.

**In data_classifier, the shortcut feature is `heuristic_avg_length`** — the average string length of the column's sample values.

Here's why it "works" in training and fails in deployment:

| Corpus | Label distribution | Avg string length | What the model learns |
|---|---|---:|---|
| gitleaks, secretbench, detect_secrets | ~100% CREDENTIAL | short (10–40 chars) | `heuristic_avg_length < 40 ⇒ CREDENTIAL` |
| ai4privacy (retired), nemotron | ~100% PII | medium (5–100 chars) | `heuristic_avg_length between 20–80 ⇒ PII family` |
| synthetic (Faker) | mixed PII/financial | varied | fallback |

`heuristic_avg_length` is *not* a causal feature. It's **a corpus identifier dressed up as a feature**. The model learns to predict corpus from length, then applies the corpus-specific label distribution.

This works great when the evaluation sample comes from one of these corpora (which a random-split CV guarantees). It fails when the evaluation sample is from a *new* corpus whose length distribution is different — exactly the BigQuery case.

**In our M1 training output, `heuristic_avg_length` had the highest absolute coefficient sum (131.4, ~1.8× the next feature) even after we retrained.** The shortcut survived Gretel-EN ingest, ai4privacy removal, and the CV methodology fix. It got *weaker* (coefficient dropped from 252 pre-Gretel to 131 post-Gretel) because Gretel's mixed-label documents disrupt the length→corpus correlation, but it didn't go away.

### Takeaway 1

**Classifiers find shortcuts whenever your training data has hidden structural correlations with the target.** The only reliable defense is evaluating on data that breaks the correlation — i.e., evaluation on a distribution different from training. Random splits don't achieve this because both halves share the same structural correlations.

---

## 2. What cross-validation is actually measuring

Cross-validation is a sampling-based estimator of model performance. Its promise is: "if you train on *some* of the data and test on *the rest*, I'll average across several splits and give you a stable estimate of accuracy."

The catch is in "some" vs "the rest" — specifically, **how do you decide which rows go in "some"?** Different splitters make different decisions, and those decisions encode different definitions of generalization.

### StratifiedKFold

```
Round 1:  train = rows {0, 1, 2, 4, 5, 7, 8, ...}    val = rows {3, 6, 9, ...}
Round 2:  train = different random subset             val = different random subset
...
```

Samples are assigned to folds **at random**, with the only constraint being that each label appears in each fold in roughly the same proportion as in the whole dataset. The "Stratified" part balances labels. The fold boundaries ignore any other structure — source, timestamp, author, corpus.

**A single fold contains samples from every corpus**, because the random assignment doesn't care about corpus boundaries. So from the model's perspective, train and val are drawn from the same distribution. If the model learns "this corpus has short strings → CREDENTIAL", that pattern transfers perfectly from train to val because both folds contain the same corpus.

### StratifiedGroupKFold

```
Round 1:  train = {gitleaks, secretbench, detect_secrets, ai4privacy, nemotron}  val = {synthetic}
Round 2:  train = {gitleaks, secretbench, detect_secrets, ai4privacy, synthetic}  val = {nemotron}
...
```

Samples are assigned to folds **by group identity** (in our case, corpus name). A single fold holds out a whole corpus; the rest of the corpora stay in training.

Now train and val are drawn from **different distributions**. The model has never seen any sample from the held-out corpus. It must rely on whatever signals *transfer* across corpora. If it only knew the `heuristic_avg_length` → corpus shortcut, it falls apart — the held-out corpus's length distribution won't match the training data's.

### What happened on our data

Pre-M1 CV (StratifiedKFold) reported 0.9160 — meaning "the model correctly predicts about 92% of the time when trained on some samples from every corpus and tested on different samples from the same corpora".

Post-M1 CV (StratifiedGroupKFold) reported 0.1940 — meaning "the model correctly predicts about 19% of the time when trained on 5 corpora and tested on the 6th that it's never seen".

**These are answers to different questions**. The first is "can the model re-produce patterns it was trained on?". The second is "can the model generalize to a corpus it's never seen?". For a library that ships to customers running on *their own* data sources, the second question is the one that matters. The first is marketing.

### Takeaway 2

**Your choice of CV splitter is part of your measurement instrument.** A random split tells you "how well does the model work on samples that look like training data". A group split tells you "how well does the model work on samples from a source it's never seen". Pick the one that matches the question you want to answer. If your product is deployed to new customers/sources/tenants, use group splits — not because they give nicer numbers (they don't), but because they measure the thing you actually care about.

---

## 3. The held-out test set trap

A common rebuttal to "CV is leaky" is "that's why we have a held-out test set". And it's true — keeping some data completely aside for final evaluation is good practice.

**But a held-out test set only works if it's separated in the *same way* as you care about generalization.**

Our current `train()` function in `scripts/train_meta_classifier.py` does an 80/20 **random stratified** split of the training data into train and test before CV happens. The "test" in this scheme is just another random subset — it has samples from every corpus, just like the CV folds under StratifiedKFold. So the held-out test set exhibits the *same leak* as the flawed CV.

Our M1 retrain shows this directly:

| Metric | Value |
|---|---:|
| Honest CV (GroupKFold) | **0.1940** |
| Held-out test (random split) | **0.8511** |

A 0.66 gap between CV and test *on the same model*. The CV number is correct; the test number is the leak still operating.

**This was the subtle trap in Sprint 6.** The team looked at "CV 0.916 and held-out test 0.918 — numbers agree, must be good". But the two numbers were measuring the same wrong thing. Consistency between broken metrics is not evidence that they're right; it's evidence that they're broken in the same way.

**Fix:** the outer split should also be by group. `GroupShuffleSplit` or leave-one-corpus-out would give a test set drawn from a corpus the model was never trained on. That's a proper held-out. It's in Sprint 10's follow-up list for this reason.

### Takeaway 3

**"Consistent numbers across two metrics" is not validation.** If both metrics are computed from the same flawed sampling procedure, they'll agree with each other but disagree with reality. The way to catch this is to deliberately introduce *different* sampling assumptions (random vs group, same-source vs cross-source) and check whether the numbers agree. If they do, your evaluation is robust. If they disagree, you've found a distribution shift in your problem that needs a decision — not a bug to smooth over.

---

## 4. Distribution shift and what it does to regularization

In LogisticRegression, `C` is the **inverse regularization strength**. Higher C means less regularization means more flexible decision boundaries means the model can fit sharper patterns (including memorization of specific feature combinations). Lower C forces smoother decision surfaces.

Our C_GRID is `{0.01, 0.1, 1.0, 10.0, 100.0}`. The training script picks the C that gives the best CV mean F1.

**Under StratifiedKFold, C=100 was the best.** Why? Because sharp memorized patterns generalize perfectly from train to val when both folds are drawn from the same distribution. The CV grid search rewarded the most flexible model because it could fit corpus-specific combinations in the training fold that also existed in the validation fold.

**Under StratifiedGroupKFold, C=1 was the best** — an order of magnitude more regularization. Sharper models can't exploit corpus-specific combinations when the held-out corpus has none of them; their memorized patterns evaporate. C=1 is the cross-validation sweet spot between "too constrained to learn anything" and "overfitting to training-corpus-specific quirks".

**Q3 predicted this exactly.** Q3's memo said "GroupKFold will pick C≈1–10 on the current feature schema". We hit C=1.0 to the decimal.

### Takeaway 4

**Regularization strength is metric-dependent, not data-dependent.** The same dataset will tell you to pick very different hyperparameters depending on how you evaluate them. If your evaluation rewards memorization, your grid search picks memorization-friendly settings. The cure is fixing the evaluation, not fine-tuning the hyperparameters. A "better hyperparameter" on a flawed metric is not an improvement.

---

## 5. The gated architecture / hybrid symbolic-statistical pattern

Once M1 exposed the shortcut, the natural question became: "can we stop the classifier from relying on `heuristic_avg_length` at all?"

There are two families of answers:

### (a) Fix the data so the shortcut stops existing

This is what Sprint 9's **Gretel-EN ingest + ai4privacy removal** tries to do. Gretel-EN contains documents where credentials co-occur with PII and health labels in the same rows, breaking the length→corpus correlation. Removing ai4privacy (a label-pure PII corpus) removes one source of the correlation.

It works — partially. The coefficient on `heuristic_avg_length` dropped from 252 to 131 (a 48% reduction), but it's still the #1 feature. More diverse corpora would help further, but "just add more data" has diminishing returns.

### (b) Fix the architecture so `heuristic_avg_length` is no longer the model's decision

Instead of a single flat classifier that sees all features at once, structure the decision as a hierarchy:

```
                    ┌──────────────────────────────────────┐
                    │ STAGE 1: classify column STRUCTURE   │
                    │ (hand-written deterministic rule)    │
                    └──────────┬───────────────────────────┘
                               │
           ┌───────────────────┼────────────────────┐
           ▼                   ▼                    ▼
    Homogeneous         Homogeneous          Heterogeneous
    credential          PII / other          (log-shaped,
    column              column               mixed content)
           │                   │                    │
           ▼                   ▼                    ▼
    Credential-subtype   PII multi-class    Per-value NER
    classifier           classifier          + multi-label
    (4 classes)          (19 classes)        output
```

**Stage 1 is a *gate*** — a deterministic rule that decides which downstream path to run. It doesn't need to be a classifier; it can be a few if-statements based on domain knowledge. Example:

```python
def is_opaque_secret_column(column, sample_stats):
    avg_entropy = shannon_entropy_per_char(column.sample_values)
    char_class_diversity = count_character_classes(column.sample_values)
    natural_language_score = dictionary_word_ratio(column.sample_values)
    
    return (
        avg_entropy > 4.5
        and char_class_diversity >= 3
        and natural_language_score < 0.1
        and not column_name_strongly_suggests_pii(column.column_name)
    )
```

**Stage 2 is whichever specialized classifier the gate routes to** — each trained only on its slice of the data, with features tuned to its sub-problem.

This is the **hybrid symbolic-statistical** pattern. Hand-coded rules handle the decisions where you have strong domain priors; ML handles the decisions where you don't. The division of labor is deliberate: put rules at the decision points where interpretability and safety guarantees matter; let ML do the pattern recognition inside the admissible spaces the rules define.

Almost every high-stakes ML deployment uses this pattern:

| Domain | Hand-coded roots | Learned leaves |
|---|---|---|
| Credit scoring | Age ≥ 18, valid SSN, income ≥ floor, not on watch-list | XGBoost credit score within admissible population |
| Self-driving cars | Emergency brake if obstacle; stay-in-lane constraint | Learned path planning under those constraints |
| Medical diagnosis | Drug allergy checks, dosage safety limits | Learned differential diagnosis |
| Spam filtering | Blocklist domains, DKIM verification | Learned content classifier for the gray area |
| data_classifier (proposed) | Credential-shape gate + heterogeneity gate | Multi-class classifier within each subset |

The common pattern is: **you can't trust ML with safety-critical routing decisions when you have better information from domain knowledge.** A neural net doesn't care that "passing age 18 is legally meaningful"; it just sees a number. A hand-coded rule gets it right every time.

### Why not just train a bigger model and let it figure out the gate?

A decision tree could theoretically discover the gated structure — a single split on `has_secret_indicators > 0.5` IS a gate, and a gradient-boosted forest of such trees could approximate the full architecture. But:

1. **The tree finds whatever gate fits the training metric.** Under our broken StratifiedKFold, the tree's root would split on `heuristic_avg_length` (the shortcut), not on `shannon_entropy` (the truth). Same trap as LogReg, more visibly expressed.
2. **Trees are not testable.** You can't write `assert tree.gate(entropy=5.0, column_name="password") == True` because "the gate" isn't a named thing in a gradient-boosted ensemble — it's implicit in the split structure, and that structure changes every retrain.
3. **Trees don't enforce safety invariants.** If your training data happens to omit a case where the gate should fire, the tree's root split may not include it. A hand-coded rule enforces the invariant whether or not the training data covers it.

The strongest case for tree-based models is **diagnostic**: train a shallow XGBoost specifically to inspect which features it picks at the root, and use that signal to design explicit hand-coded gates. The tree is the oracle; the production system is the hand-coded rules the oracle validates. This workflow is well-established in credit scoring and medical informatics.

### Takeaway 5

**Hand-coded routing at decision points + learned classifiers inside the admissible subsets outperforms a single flat classifier on every dimension that matters for production**: interpretability, testability, safety, debuggability. The trade-off you're making is "less flexibility to discover unexpected patterns" vs "more trust in the decisions the system makes". For high-stakes deployments, that trade-off is almost always worth it. For research prototypes, the flat classifier is faster to iterate.

---

## 6. The heterogeneous-column problem

A column in a structured database is usually homogeneous — `email_address` contains emails, `ssn` contains SSNs. Column-level classification works great for these: "this column is EMAIL" is a complete and correct statement.

But some columns contain **heterogeneous content**: log lines, notes, descriptions, JSON blobs, free-form text. A single row might contain an email, an API key, a URL, and free English prose. The column-level abstraction "this column is X" is structurally wrong — the column is multiple things at once.

**data_classifier today has no good answer for these columns.** The engines run per-value (which is the right granularity), aggregate to column-level (losing the per-value information), and the meta-classifier picks a single label (losing it further). Downstream consumers see one confident-looking label that doesn't match reality.

This is the limit of column-level classification. The fix is structural: the gate's first job is to classify the *column shape* before any entity-type decision:

- **Homogeneous columns** → return a single `ClassificationFinding` with one entity_type (current behavior)
- **Heterogeneous columns** → return a list of findings with match_ratios and a `column_shape: "heterogeneous_log"` sentinel

This requires a small API extension (a new `HeterogeneousColumnFinding` type or a list-valued variant of the existing type) but no retraining. Heterogeneity can be detected by per-value entropy variance, per-value length variance, generic column names, and partial regex match ratios — signals the engines already compute.

### Takeaway 6

**"Structure first, content second" is a general principle in information extraction.** Before you decide *what* something is, decide *how it's shaped*. Structured data → classifiers per column. Semi-structured → classifiers per field. Unstructured → NER per span. Forcing unstructured data into structured-output classifiers is a category error that loses information and produces misleadingly confident labels.

---

## 7. The M1 investigation arc as a worked example

Reconstructing what actually happened across sprints, so the pattern is visible:

| Sprint | Event | What it looked like | What was actually happening |
|---|---|---|---|
| Sprint 6 | Meta-classifier shipped | CV F1 = 0.916, "strong result, ship it" | Shortcut learning inflated the metric by ~0.66 F1 |
| Sprint 6 post-hoc | LOCO benchmarks added | LOCO F1 ≈ 0.30, "huge gap with CV" | The gap IS the shortcut being exposed by a proper OOD metric |
| Sprint 7 | Q3 investigation dispatched | "Why does CV disagree with LOCO?" | Finds `heuristic_avg_length` is a corpus identifier; StratifiedKFold can't detect it |
| Sprint 7–8 | Q5, Q6, E10 experiments | Multiple follow-up studies | Confirm: bias is structural, not a CV implementation bug |
| Sprint 8 | E10 honest baseline correction | Tertiary delta +0.257 → +0.191 | E10 runs evaluation against the live baseline *with* GLiNER enabled, instead of the hypothetical 4-engine baseline |
| Sprint 8 close | Ai4Privacy license finding | Non-OSI license in the dataset's custom license.md | Triggers a corpus-level fix (not just a model-level fix) |
| Sprint 9 | Gretel-EN ingest | +60k mixed-label rows | Disrupts the length→corpus correlation at the data source |
| Sprint 9 | ai4privacy removal | Retrained without ai4privacy | Changes the corpus composition again |
| Sprint 9 | M1 promoted | StratifiedKFold → StratifiedGroupKFold | Fixes the measurement; exposes honest ~0.19 CV |
| Sprint 9 | Fastino promotion blocked | Gretel-EN blind −0.13, Nemotron blind −0.19 | Fastino was evaluated on corpora *with* context; raw-value corpora break it — validates the GLiNER context-injection research thread |

The sequence has a shape that's worth recognizing: **metric inflation → honest metric → data fix → architectural follow-up**. Each step tightens the loop between what we think the model is doing and what it actually is. Sprint 10's gated-architecture item is the architectural follow-up implied by everything above.

**What wasn't obvious at the start of the investigation** — and became obvious only at M1:

1. The meta-classifier's headline number was dominated by one feature, not by the feature ensemble. The ensemble was theater; the actual decision was a length check.
2. Every other experiment (Q5, Q6, E10) was measuring variations on the same wrong thing. They were all correct in what they reported, but the question they were answering wasn't the one we thought we were asking.
3. Data diversification (Gretel, ai4privacy removal) and metric honesty (M1) are **complementary**, not substitutes. Gretel alone reduced the shortcut's strength from 252 → 131 coefficient. M1 alone wouldn't have reduced it at all, just exposed it. Both together move the needle in a durable way.
4. Architecture fixes (gated design) are the *structural* cure. Data and metric fixes are necessary but not sufficient — they reveal where the problem is without fully solving it.

---

## 8. Practical lessons you can carry to other ML systems

Crystallizing the "what to do differently next time" version:

### Before you trust an ML metric

1. **Identify your unit of generalization.** Is it rows? Columns? Users? Sources? Time periods? Whatever it is, your evaluation splitter should partition along that axis, not across it.
2. **Run at least two CV schemes in parallel.** Random split and group split (or random split and time-based split, depending on your unit). If they disagree, you have a distribution shift worth investigating. If they agree, your evaluation is robust on this data.
3. **Check the top feature importances.** If the most discriminative feature is something domain-weird (length, file-size, time-of-day, hostname), interrogate it. Is it a causal feature or a proxy? If it's a proxy, you have a shortcut.
4. **Don't chain evaluations that share assumptions.** A held-out test set drawn from the same distribution as CV is not an independent check. It's the same measurement with a different name.

### When you're designing an architecture

1. **Hand-code the decisions where you have strong priors.** Saving ML capacity for the decisions you don't know how to make.
2. **Keep decisions reversible.** If you ship a learned gate, make it a config flag so you can roll back to a rule-based gate if the learned version misbehaves in production.
3. **Structure-first.** Classify column shape (or document shape, or input type) before classifying content. It's cheaper, more interpretable, and often a no-op on homogeneous inputs.
4. **Let trees do architecture discovery.** Train a shallow GBT and inspect its splits. Use the splits as hypotheses for where to put hand-coded gates.

### When someone tells you "our model has F1=0.9"

Ask:

- "F1 on what split?"
- "Is the test set drawn from the same source as training, or from a new source?"
- "What's the top feature by importance, and is it a causal feature?"
- "How was the CV splitter chosen? Have you run any other CV schemes in parallel?"

If the answers are "random split, same source, feature X is important but it's actually a proxy for source identity, and we haven't tried anything else" — that's the Sprint 6 meta-classifier. You now know the shape of the problem.

---

## 9. Glossary

- **Cross-validation (CV)** — resampling technique that estimates model performance by training on subsets of data and testing on the held-out portion, averaged over multiple splits.
- **StratifiedKFold** — CV splitter that assigns samples to folds randomly but preserves per-label proportions across folds. Ignores all other structure.
- **StratifiedGroupKFold** — CV splitter that assigns samples to folds by *group identity* (corpus, user, time period) rather than randomly. A fold holds out a whole group. Tries to preserve label stratification subject to the group constraint.
- **LOCO (leave-one-corpus-out)** — a specific case of GroupKFold where `groups = corpus_name` and `n_splits = n_corpora`. Each fold holds out one whole corpus. This is the canonical "honest generalization" metric for a library that ships to new customers/sources.
- **Shortcut learning** — classifier-level failure mode where the model learns a spurious feature that correlates with the label on the training distribution but doesn't causally explain it. Invisible under same-distribution evaluation; catastrophic under distribution shift.
- **Distribution shift** — the test-time data is drawn from a different distribution than the training data. Random-split CV doesn't measure robustness to distribution shift; group-split CV does.
- **Gated architecture / hybrid symbolic-statistical** — decision-making pattern where hand-coded rules perform high-stakes routing decisions at the top of the pipeline and ML models perform fine-grained pattern recognition inside the admissible subsets the rules define.
- **Calibration** — the property that a model's reported confidence (e.g., "0.8") actually matches the frequency of being correct (e.g., "correct 80% of the time"). LogReg is calibrated by default; GBT is not unless you post-process.
- **Regularization (C parameter)** — strength of the constraint against sharp decision boundaries. Higher C = less regularization = more memorization capacity. Optimal C is metric-dependent; a "better C" on a flawed metric is not an improvement.

---

## 10. Concrete Sprint 10 implications

The investigation closes with three concrete follow-ups, all filed as Sprint 10 backlog items during the Sprint 9 discussion:

1. **`gated-meta-classifier-architecture-explicit-credential-gate-specialized-stage-2-classifiers-q8-continuation`** (P1) — the explicit gated architecture, including the heterogeneous-column sibling gate
2. **`meta-classifier-model-ablation-logreg-vs-xgboost-vs-lightgbm-on-honest-loco-metric`** (P2) — tree-vs-linear ablation on the honest LOCO metric, partly as performance comparison and partly as diagnostic (inspect the tree's root to confirm or refute the shortcut hypothesis)
3. **`hygiene-test-meta-classifier-training-py-env-leak-...`** (P2) — small cleanup, uncovered during the observability-gaps implementation

The gated-architecture item is the highest-leverage follow-up. The tree ablation is a cheap diagnostic that informs it. The hygiene fix is a test-infra paper cut.

---

## Acknowledgements / provenance

- **Q3 investigation** on `research/meta-classifier @ <q3-timestamp>` — diagnosed the shortcut, predicted best_c ≤ 10 under GroupKFold
- **Q5/Q6 follow-up experiments** — confirmed the bias is structural
- **E10 honest baseline correction** — moved the cited meta-classifier delta from +0.257 to +0.191
- **Sprint 8 dataset landscape survey** on `research/meta-classifier @ cd3a5cc` — identified Gretel as the mixed-label replacement, flagged ai4privacy's non-OSS license
- **M1 research-branch run** on `research/meta-classifier @ c33c7fc` — validated the CV fix against pre-Gretel training data
- **Sprint 9 fastino-promotion blocked finding** — provided independent empirical evidence that the eval-memo + raw-corpus transfer is broken, validating the gated-architecture direction
- **This memo** — written 2026-04-13 during Sprint 9, as a capstone learning deliverable to make the investigation's insights transferable to other projects and future sessions.

The "honest number to cite going forward" has shifted twice this project:
- Sprint 6 claim: +0.257
- E10 correction: +0.191
- Post-Gretel + M1 (this memo): **+0.2432 tertiary blind delta**, LOCO mean ~0.17

**Cite +0.2432 going forward**, and understand that the number may move again when the gated architecture lands and the outer split is group-level.
