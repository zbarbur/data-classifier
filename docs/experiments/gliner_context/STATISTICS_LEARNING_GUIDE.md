# Statistics for ML research — a working intuition guide

> **Audience:** someone with a technical degree and ML background who took
> statistics years ago, remembers the concepts but not the day-to-day
> working tools. Not a first exposure; a refresher for operating confidently
> on the kind of questions this research track asks.
>
> **Goal:** after reading this, you should be able to pick up a research
> memo, see "BCa 95% CI [0.034, 0.078], McNemar p=0.003", and immediately
> know what each piece claims, what it doesn't claim, and what you'd
> double-check before believing it.
>
> **Shape:** concepts first, tactics second. The last section
> ("Developing intuition") is the one most people wish someone had given
> them early.

---

## 0. Why we need statistics at all

You almost certainly remember this from school, but it's worth re-grounding
because the whole edifice rests on it:

> **Any single measurement you make is one draw from a distribution
> you cannot see directly.** Statistics is the discipline of reasoning
> about that invisible distribution using the sample you actually have.

Every F1 number in every research memo is a *sample*. The truth — what F1
would be if you ran on the entire population of possible columns — is
never observable. You only have n=21, or n=200, or n=5000 rows. Everything
after that is about answering: *what does my sample let me say about the
truth, and how confident can I be?*

The parts that most working engineers half-forget and need to reinstall:

1. **Sampling variability** is larger than your intuition suggests. A single
   F1 run can wiggle by 0.05-0.10 purely from noise, and your brain will
   still want to interpret a 0.03 delta as "meaningful".
2. **Statistics doesn't tell you truth** — it tells you how much your
   data constrains your beliefs.
3. **Effect size and statistical significance are orthogonal.** Forgetting
   this is the single most common error I see in ML memos, including ones
   I've written. We'll come back to it.

---

## 1. The mental model: point estimates vs ranges

When your n=21 first run returned `baseline macro F1 = 0.4636`, that's a
**point estimate** — a single number summarizing the sample. It is true
*of the sample*. It is not necessarily close to the true F1.

The right mental replacement for `F1 = 0.4636` is:

> `F1 ≈ 0.46, plausibly anywhere in [0.38, 0.55], depending on luck`

Train yourself to *never see a point estimate without mentally appending a
range*. Every single research memo I've read that got publicly embarrassed
skipped this step.

The width of that range depends on three things:

| Lever | Effect on CI width |
|---|---|
| **n** (sample size) | CI shrinks like `1/√n`. 4× the data → 2× narrower CI. |
| **Variance of the statistic** | Heterogeneous data → wider CI. Ai4Privacy's PERSON_NAME column with 30 mixed values has higher variance than a column of 30 pure emails. |
| **Which statistic you chose** | Composite stats (F1, AUC) have wider CIs than raw rates (TPR, FPR). |

---

## 2. Variance, standard error, confidence interval — the tight triangle

The three terms are closely related but people mix them up constantly.

**Variance (σ²)**: how spread out are the *individual observations* in
the underlying population? If individual columns have F1 values scattered
from 0.1 to 0.9, population variance is large.

**Standard error (SE)**: how spread out is the *estimate of the mean*
(or F1) if you re-ran the experiment? This is the one that matters for
reasoning about your measurement.

> **The key magic**: SE of the mean = σ / √n. Standard error shrinks
> with sample size even when underlying variance doesn't budge.

**Confidence interval (CI)**: a standard error times a critical value
(1.96 for 95% under Normal assumptions) gives you an interval around
your estimate that would contain the truth with a specified frequency
under repeated sampling.

For the Normal case: `95% CI ≈ estimate ± 1.96 × SE`.

**The crucial reading of a 95% CI.** Say somebody writes "95% CI [0.38, 0.55]".
That does NOT mean "there's a 95% probability the true F1 is in [0.38, 0.55]".
That's the Bayesian credible interval, which uses a different machinery.
The frequentist CI means:

> "The procedure I used to construct this interval would contain the
> true F1 in 95% of hypothetical replications of the experiment."

For practical purposes both readings converge on the same gut-level
guidance: **treat the interval as your uncertainty band**. What matters
is whether the interval excludes values you care about (like 0 or the
ship gate 0.02).

---

## 3. Bootstrap — the move that saves you when the math is hard

Closed-form CIs require assumptions about the distribution of your
statistic (usually Normal, sometimes Student's t). For F1, precision,
recall, AUC, BLEU, and most compound ML metrics, the distribution is
**ugly** — non-symmetric, bounded between 0 and 1, non-linear in the
component counts. No clean formula exists.

The bootstrap is a brilliant trick that sidesteps the entire math
problem.

**The idea in three sentences:**
1. Your sample *is* a good approximation of the population (the
   "plug-in principle").
2. If you resample from your sample *with replacement* to make a fake
   "replication" of the experiment, the sampling variability of that
   resampled statistic approximates the sampling variability you'd see
   if you actually re-ran the experiment.
3. Repeat 1000+ times, take percentiles of the resulting distribution,
   and you have an empirical CI that makes no assumptions about shape.

**Concrete algorithm for paired F1 delta CI (what our harness will do):**

```python
def bootstrap_paired_f1_delta(
    baseline_results: list[PerColumnResult],
    variant_results: list[PerColumnResult],
    n_resamples: int = 1000,
    confidence: float = 0.95,
) -> tuple[float, float, float]:
    n = len(baseline_results)
    rng = random.Random(0)
    deltas = []
    for _ in range(n_resamples):
        # Resample INDICES with replacement — this preserves the pairing
        idxs = [rng.randrange(n) for _ in range(n)]
        b_sub = [baseline_results[i] for i in idxs]
        v_sub = [variant_results[i] for i in idxs]
        deltas.append(macro_f1(v_sub) - macro_f1(b_sub))
    deltas.sort()
    lo_idx = int((1 - confidence) / 2 * n_resamples)
    hi_idx = int((1 + confidence) / 2 * n_resamples)
    point_estimate = macro_f1(variant_results) - macro_f1(baseline_results)
    return point_estimate, deltas[lo_idx], deltas[hi_idx]
```

The critical thing is **resampling indices, not individual predictions**.
When column 5 is drawn, both baseline and variant's predictions for
column 5 come along. That preserves the pairing — the shared structure
between the two strategies — which is exactly what makes paired tests
more powerful than unpaired ones.

**Gotcha 1 — this is the naive percentile bootstrap.** It's fine for
well-behaved statistics on reasonable sample sizes, but it has two known
flaws:

- **Bias**: the bootstrap distribution's median may be systematically
  offset from the true value of the statistic, because your sample is
  finite.
- **Skew**: statistics bounded on [0, 1] (like F1) have asymmetric
  distributions near the edges. Symmetric percentile intervals
  under-cover on the compressed side.

Both are small when F1 is near 0.5 and n is large. Both matter when F1
is near 0 or 1, or n is small.

**Gotcha 2 — sample structure matters.** If your observations aren't
independent (e.g. multiple columns from the same table, multiple value
slices from the same corpus), naive bootstrap under-estimates variance.
The fix is **block bootstrap** or **cluster bootstrap** — resample
blocks/clusters as atoms rather than individual rows. For our research,
the columns are independent (different templates, different value
slices), so naive bootstrap is fine.

---

## 4. BCa bootstrap — the refinement for when the basic bootstrap isn't enough

**BCa** stands for **bias-corrected and accelerated**. It's a two-step
adjustment to the percentile bootstrap that corrects for bias and skew.
It's the default method in `scipy.stats.bootstrap` as of version 1.7
and has been the "use this unless you have a reason not to" method
in the bootstrap literature since Efron 1987.

**What it does, conceptually:**

1. **Bias correction (z₀)**: counts what fraction of bootstrap replicates
   are below the observed point estimate. If that fraction is 0.5, no
   correction; if it's 0.4, the bootstrap distribution is shifted high,
   and BCa nudges the intervals left.
2. **Acceleration (â)**: estimates how the standard error of the
   statistic changes as the true value changes (via jackknife). This
   accounts for skew — intervals become asymmetric in a principled way.

You don't need the formulas to use it; `scipy.stats.bootstrap(
data, statistic_fn, method='BCa')` handles everything. But knowing
**when BCa matters most** is useful:

| Situation | Naive percentile bootstrap | BCa bootstrap |
|---|---|---|
| n ≥ 100, F1 near 0.5, symmetric errors | equivalent | slightly tighter |
| n < 50, any F1 | under-coverage on one side | much better calibrated |
| F1 near 0 or 1 (e.g. SSN in our run) | badly skewed CI | materially better |
| Per-entity subsetting where some entities have 2-3 columns | often broken | still fragile but less so |

Rule of thumb: **always use BCa unless there's a clear reason not to.**
It costs marginally more compute (a jackknife pass) and strictly dominates
percentile in correctness.

**Where it still breaks.** BCa is not magic. With n < 20 or statistics that
are highly non-monotonic (e.g. F1 when both P and R can swing wildly), BCa
still gives you garbage. The fix at that point isn't a better bootstrap —
it's more data.

---

## 5. Hypothesis tests and p-values — the part where most people go wrong

A p-value is **not**:
- "The probability that the null hypothesis is true"
- "The probability that your result is due to chance"
- "The probability of replicating this finding"

A p-value **is**:

> "The probability of observing a result at least as extreme as the one
> I saw, assuming the null hypothesis is exactly true."

Let that sink in. It's a probability *under the assumption the null is
true*. If your p-value is 0.001, it means: **if S1 were genuinely no
better than baseline**, data like yours would appear 0.1% of the time.
That's unlikely enough that most people would doubt the null.

**What p-values can't tell you:**
- How big the effect is (that's effect size, separate question)
- Whether the result will replicate (that's power, also separate)
- Whether your model is correctly specified (that's validation)
- Whether the null is "true" (hypothesis testing cannot prove nulls, only
  reject them)

**The p-value threshold convention.** p < 0.05 is a historical accident
from R.A. Fisher's early writings, not a scientific law. Modern ML
research often targets p < 0.01 or stricter, especially in the
reproducibility-crisis era. Our research brief says p < 0.01, which is
a reasonable operational standard.

**Log-scale thinking for p-values.** `p=0.05` and `p=0.01` feel close but
differ by 5x. `p=0.05` and `p=0.0005` differ by 100x. Train yourself to
think in orders of magnitude:

| p-value | Interpretation |
|---|---|
| p < 0.001 | Very strong evidence against null; I will trust this pending replication |
| p < 0.01 | Strong evidence; ship-gate territory for this project |
| p < 0.05 | Suggestive; ok for preliminary findings, not for decisions |
| p < 0.1 | Weak; treat as directional, not conclusive |
| p ≥ 0.1 | No evidence against null; don't claim anything |

---

## 6. Paired vs unpaired tests — always pair when you can

When comparing two strategies on the same 200 columns, those are **paired
measurements**. Column 5 is hard for both strategies or easy for both —
the correlation between baseline and S1 on column 5 is very high. A
paired test exploits that correlation and cancels out the easy/hard axis,
leaving only the *strategy* axis.

An unpaired test would treat baseline's 200 F1 values and S1's 200 F1
values as two independent samples of 200 each, ignoring that they came
from the same columns. It would be wildly under-powered.

**The intuition:** if S1 beats baseline by 0.01 F1 on every single one
of 200 columns, that's devastating evidence for S1, even though the F1
delta is tiny. An unpaired test would see "two samples with means 0.52
vs 0.51, SE 0.1" and fail to detect the effect. A paired test sees "200
out of 200 wins, 0/200 losses" and crushes the null.

**Rule:** if you can pair, always pair. The only reason not to is when
the two conditions were genuinely measured on different subjects.

---

## 7. McNemar's test — the right tool for paired binary outcomes

McNemar is a **paired test for 2×2 contingency tables**. You build the
table like this:

|                | S1 correct | S1 wrong |
|---|---:|---:|
| **baseline correct** | a | b |
| **baseline wrong**   | c | d |

Where "correct" means "the strategy reported the ground-truth entity type
for that column". Four cells:

- `a`: both got it right (ignored — agreement doesn't tell us anything
  about which is better)
- `d`: both got it wrong (ignored — same reason)
- `b`: only baseline got it right (a *discordant pair against S1*)
- `c`: only S1 got it right (a *discordant pair for S1*)

**Null hypothesis:** the two strategies are equally good, so `b` and `c`
are the outcomes of independent fair coin flips. Under the null,
`c` follows a Binomial(b + c, 0.5) distribution.

**Exact McNemar (for small b+c):**
```python
from scipy.stats import binomtest
result = binomtest(k=c, n=b + c, p=0.5, alternative='two-sided')
p_value = result.pvalue
```

**χ² McNemar (for large b+c, ≥25 is the usual threshold):**
```python
statistic = (b - c) ** 2 / (b + c)  # χ²(1) under null
```

Both give you a p-value. The exact version is always correct and should
be preferred when b+c is small. The χ² version is an approximation that's
faster for large samples but adds nothing for ML-scale data.

**Why McNemar and not just comparing F1 numbers with a t-test?** Because
F1 is not a per-subject measurement — it's a pooled count ratio. You
can't do a paired t-test on "F1 per column" because each column only
produces one correct/wrong decision, not an F1 value. McNemar operates
directly on those binary per-column outcomes, which is exactly what you
have.

**The pitfall:** the "correct/wrong" collapse loses information. Two
strategies might both be "correct" on a column but differ in confidence
scores. If you care about confidence calibration, McNemar misses it and
you want a rank-based test like Wilcoxon signed-rank.

---

## 8. Effect size vs statistical significance — the most important distinction

This is the one I see people get wrong most often, including in published
papers and production research memos.

**Two strategies can differ "significantly" (p < 0.01) and still be
effectively identical in practice.** A large enough n will detect any
non-zero difference, no matter how trivial.

Conversely, **two strategies can differ by a huge effect (a +0.15 F1
improvement!) and fail significance testing** if n is too small or
variance too high.

A well-formed research claim reports **three numbers**:

1. **Effect size**: the point estimate of the thing you care about.
   For us: Δ macro F1.
2. **Confidence interval**: the range the true effect plausibly lies in.
   For us: BCa 95% CI on Δ.
3. **p-value**: evidence against the null of "no difference".
   For us: paired McNemar p.

Any claim that reports one without the others is either sloppy or
misleading.

**Example of the trap, from real project history.** Memory file
`project_active_research.md` documents the E10 correction:

> "Headline delta meta − live: Sprint 6 claimed +0.257. E10 honest
> measurement re-ran against the 5-engine baseline and got +0.191."

The +0.257 was **inside the original paper's stated CI** all along. The
claim at the time wasn't technically wrong, but it overstated the effect
size by privileging the point estimate over the interval. The E10 memo
went back and re-framed around the interval, and the new honest number
(+0.191) is now the standard citation. **The lesson: always report the
interval alongside the point estimate, and lean on the interval, not
the point, when making ship decisions.**

---

## 9. Power — how big n needs to be to detect what you care about

**Statistical power** = the probability of detecting a real effect, if
the effect exists, at your chosen significance level.

For a paired comparison of two strategies, power is a function of:
- **n**: sample size
- **δ**: the real effect size you want to detect
- **σ**: variability between observations
- **α**: significance threshold (0.01 in our case)

Rule of thumb for paired McNemar with a 0.05 detection target at α=0.01:

| δ (true effect) | n required for 80% power |
|---:|---:|
| +0.02 F1 | ~800 columns |
| +0.05 F1 | ~150 columns |
| +0.10 F1 | ~40 columns |
| +0.20 F1 | ~15 columns |

This is why our n=21 is OK-ish for detecting the S1 +0.055 effect but
useless for detecting a subtler +0.02 effect, and why our "scale to
n=200" plan targets the +0.05 range but leaves +0.02 under-powered.

**Practical takeaway:** before running an experiment, **decide what
effect size you need to detect, then compute the required n**. Running
an under-powered study is worse than running no study — you'll get
noise, not a conclusion, and worse, you'll *think* you have a conclusion.

---

## 10. Multiple comparisons — why testing 4 strategies at α=0.01 is really testing at α=0.04

You're comparing 4 strategies to baseline. That's 4 hypothesis tests.
Under the null, each has a 1% false-positive rate. But at least one
false positive across 4 tests has probability `1 − (1 − 0.01)⁴ ≈ 0.039`.
**Your effective family-wise error rate is ~4%, not 1%.**

**Bonferroni correction**: divide your α by the number of tests. For 4
strategies at a target family-wise α of 0.01, use per-test α of 0.0025.
Conservative, easy to apply, well-understood.

**Less conservative options (when n is small and you can't afford
Bonferroni's power loss):** Holm-Bonferroni (sequential, less punishing),
Benjamini-Hochberg (controls false discovery rate instead of family-wise
error rate, popular in genomics and ML).

**For this research**: we have 4 strategies and the project brief already
says p < 0.01. If I apply Bonferroni, the effective gate becomes p < 0.0025
per-strategy, which is stricter. I'll report both raw and corrected p-values
in the Pass 1 memo so you can see how much room there is.

---

## 11. The research brief's ship gate, re-read through this machinery

The brief says:

> - Macro F1 on Gretel-EN blind set lifts by ≥ +0.02
> - No entity-type regresses by more than -0.03 F1 individually
> - Latency penalty ≤ +20% per-column
> - McNemar p < 0.01 on the blind set
> - Result holds on at least TWO distinct corpora

In statistical language, each of those is a **combined effect-size + power
constraint**:

| Brief requirement | Statistical interpretation |
|---|---|
| Macro F1 delta ≥ +0.02 | Point estimate must exceed the clinical significance threshold |
| No entity regresses >−0.03 | For every entity type, CI of per-type delta must exclude −0.03 (hard — requires per-type n ≥ ~50 to be defensible) |
| Latency ≤ +20% | Measured directly, not statistical |
| McNemar p < 0.01 | Effect is unlikely under null |
| Holds on ≥2 corpora | External validation — robustness to dataset choice |

Reading this again, the **binding constraint** is the per-entity regression
gate. Macro-level significance is easy at n=200; per-type CI tightness
that can confidently exclude −0.03 needs n_type ≥ 50, which means total
corpus n ≥ 400 for a balanced design. That's a useful number to plan
around.

---

## 12. Developing intuition — the meta-skill

Textbooks give you formulas. Nobody teaches you how to notice when a
number is fishy before the formulas even come out. That instinct is the
real skill, and it comes from a few habits:

### 12.1 Simulate first, compute second

Before you run any analysis, generate **fake data where you know the
right answer** and run your pipeline on it. If the pipeline doesn't
recover the right answer, your pipeline is buggy, not your experiment.
This catches about 80% of bugs before they contaminate results.

For our research, that would look like: build a fake `CorpusRow` list
where by construction S1 has a +0.10 F1 advantage (you hand-crafted it
to), and run the harness. If it reports +0.00, you have a bug in the
evaluation, not a null result on S1.

### 12.2 Make predictions before you run

Every experiment, before running, write down what you expect the result
to be. Not "I expect S1 to help", but "I expect S1 to improve macro F1
by 0.03-0.06, with the biggest lift on empty context and smaller lifts
on helpful and misleading".

Then compare. There are three possible outcomes:

- **Matched**: you learn you understand the system (calibration increasing)
- **Direction right, magnitude off**: you learn what you didn't know
- **Direction wrong**: either you misunderstood the system, or there's a
  bug. Either way you learn a lot

The act of writing down predictions **forces you to externalize your
model**, which surfaces latent assumptions you'd otherwise never examine.

### 12.3 Treat every number as a range, not a point

Never let "0.5182" exist in your brain alone. Train yourself to
automatically append `± SE`. Over time you develop a gut feel for
"how shaky is this measurement?" that lets you reject bad claims
immediately.

Practical drill: when reading any paper, estimate a CI in your head
before looking at the reported one. If you can't estimate it, you're
missing key information; go find it before citing the paper.

### 12.4 The "could a random baseline beat this?" test

Before celebrating an improvement, ask: *could pure chance have produced
this delta on this n?* The bootstrap is literally a machine for
answering this question. If the bootstrap CI spans 0, the answer is
"yes, chance could produce it".

An even sneakier version of this test: **what if your "improvement" is
actually a bug in the baseline?** If baseline got worse (e.g. someone
disabled a feature in the baseline path), you'd see exactly the same
delta and it would have nothing to do with your improvement.

### 12.5 Visualize distributions, not summaries

Histograms beat summary stats for spotting bugs, outliers, bimodality,
and boundary effects. If you can't plot the distribution of your
statistic (e.g. F1 across bootstrap samples, or latency across columns,
or confidence scores across predictions), you don't understand it well
enough to report it.

For this research: before writing any memo, plot the 1000 bootstrap
F1 deltas as a histogram. If the histogram is bimodal, something is
structurally different between the modes (maybe helpful vs misleading
strata). If it has a long tail, your CI width is misleading. Looking
catches things numbers hide.

### 12.6 Seek disconfirmation actively

This is the hardest habit to build. Your brain wants confirmation. Your
research wants disconfirmation.

Every time you have an exciting result, spend 10 minutes actively trying
to break it:

- Re-run with a different seed
- Re-run on a different corpus
- Re-run at a different threshold
- Look at the individual cases where the "improvement" came from —
  are they all the same kind of column?
- Check whether the result disappears when you remove one outlier

If the result survives this attack, it's much more likely to be real.

### 12.7 Sleep on dramatic results

Results that seem dramatic rarely survive a day's consideration. If you
find yourself excited by an experiment, **wait 24 hours** before
reporting it to anyone. Re-read the memo cold the next morning. Ask
"what did I miss?". You'll catch at least one bug or overclaim ~30% of
the time, in my experience.

### 12.8 Log-scale intuition for effect sizes and p-values

Don't think of `0.03` and `0.05` F1 differences as "kinda close" — think
about them as *relative*: 0.05 is 66% bigger than 0.03. The distance
between a detection and a meaningful improvement is enormous in
practice even when the absolute numbers look small.

Similarly for p-values: p=0.04 and p=0.01 are an order of magnitude
apart. p=0.01 and p=0.0001 are two more orders of magnitude. Treat
"p < 0.05" and "p < 0.001" as categorically different evidence, not
slightly-different-intensity versions of the same thing.

### 12.9 Ask "what would disprove this?"

For any claim, ask yourself: *what data would convince me I'm wrong?*
If you can't name a specific observation that would flip your view, you
don't have a hypothesis, you have a belief. Hypotheses are testable;
beliefs are not.

For "S1 is better than baseline": what would disprove it? Answer
candidates:
- McNemar p > 0.1 at n=200
- Bootstrap CI on Δ spans 0
- S1 regresses any individual entity type by >0.03
- S1 loses on Gretel-EN when Ai4Privacy was a win

If none of those happen, I believe S1 is a real improvement.

### 12.10 Find one mentor-like text and re-read it annually

You'll never master stats by cramming. But re-reading one good book every
year or two is surprisingly effective because you pick up *different*
things each time depending on what you've done recently. Suggested:

- **"Statistical Rethinking"** by Richard McElreath — the best text for
  building working intuition. Bayesian-leaning but the concepts transfer.
- **"Introduction to the Bootstrap"** by Efron & Tibshirani — the
  bootstrap bible. Shorter than you'd expect, and the examples are
  unusually clear.
- **"Empirical Methods for Artificial Intelligence"** by Paul Cohen —
  an older book, but the ML-specific examples are directly relevant to
  what we do in this project.

---

## 13. A pre-publication rubric

Before quoting ANY number to a stakeholder, check:

1. [ ] Is the sample size n explicit in the report?
2. [ ] Is the confidence interval reported alongside the point estimate?
3. [ ] Is there an explicit significance test, with a p-value?
4. [ ] Are the discordant pair counts `(b, c)` reported for McNemar?
5. [ ] Is effect size discussed separately from significance?
6. [ ] Was this the pre-registered analysis, or did I look at the data first and pick the most flattering slice?
7. [ ] Have I checked the analysis pipeline on known-answer fake data?
8. [ ] Have I tried to break the result by varying seed/threshold/corpus?
9. [ ] If the result were 2x smaller, would I still claim it? (The "shrink test" — good results should survive conservative framing.)

Any "no" means you're not ready to publish.

---

## 14. Cheat sheet for this research specifically

| Question | Tool | Why |
|---|---|---|
| "Is S1 better than baseline overall?" | Paired McNemar on per-column correct/wrong | Paired binary outcome, exact test available |
| "How much better, with uncertainty?" | BCa bootstrap CI on Δ macro F1 (paired resampling of columns) | F1 is composite, closed-form CI not available |
| "Does S1 regress any entity type?" | Per-entity BCa bootstrap CI on Δ F1, flag any CI excluding +0.03 on the wrong side | Same tool at the sub-group level; n_type is the limiting factor |
| "Is the macro delta real or seed luck?" | Multi-seed runs + variance of point estimates across seeds | Gives a second layer of empirical uncertainty estimate |
| "Is the result robust to corpus choice?" | Run on Ai4Privacy + Nemotron-PII + Gretel-EN, check Δ sign and McNemar p on each | External validation gate |
| "Is latency OK?" | p50 and p95 in ms, directly measured; ratio to baseline | Direct measurement, no stats needed beyond percentiles |

---

## 15. Where to go next

This guide covers what you need to read and write memos on *this*
research track. Things deliberately left out for later deep dives:

- **Bayesian inference and credible intervals** — different machinery for
  the same questions. Worth learning when you're comfortable with the
  frequentist tools.
- **Mixed-effects models** — the right tool for data with hierarchical
  structure (multiple values per column, multiple columns per table).
  Overkill for our current design, relevant if we ever get real
  catalog data.
- **Causal inference** — how to distinguish correlation from causation
  beyond randomized experiments. Critical for production A/B testing.
- **Sequential testing and optional stopping** — why you can't just
  "peek" at your data and stop when significant, and what to do instead.
- **Model calibration and reliability diagrams** — how to check whether
  your classifier's confidence scores are meaningful.

If any of these come up in future research, ask for a focused primer
on just that topic. This guide is intentionally scoped to what's
immediately actionable on the gliner-context work.

---

*Written for the research/gliner-context track, 2026-04-13. This guide
is not a research memo — it's a durable learning reference. Treat it
as a knowledge base, not a frozen artifact; revise it as understanding
deepens.*

---

# Appendix A — Case study: cross-validation leakage (Q3 / M1 correction)

> **Source:** `research/meta-classifier` branch, Q3 experiment
> (2026-04-12), M1 fix applied in a subsequent session. Documented in
> project memory `project_active_research.md`.
>
> **Why this case matters:** it's the single best real-world illustration
> in this project's history of how a beautifully significant, well-framed
> result can still be catastrophically wrong. If you internalize this one
> case, you'll have instincts for the most common category of ML
> evaluation bug.

## The situation before the fix

The Sprint 6 meta-classifier shipped with this Cross-Validation result:

```
StratifiedKFold (baseline)
  best_c:            100.0
  cv_mean_macro_f1:  0.9160 ± 0.0072
  held_out_test_f1:  0.9185
```

Reading that table the way most people read it:

- Macro F1 of **0.916** on 5-fold CV. That's an excellent number for a
  messy multi-class PII classification problem.
- **Standard deviation 0.0072** across folds. The model is remarkably
  stable — different training subsets all yield nearly the same F1.
- The **held-out test** matches the CV mean almost exactly (0.9185),
  which is what you'd expect if the CV estimate is unbiased.
- The optimal regularization C of 100 (weak regularization, letting
  the model fit the data tightly) is consistent with a well-calibrated
  pipeline on high-quality data.

Every indicator said "this is working". The memo got written. The
model shipped as a shadow-mode component. Everyone moved on.

## The red flag nobody saw

A macro F1 of 0.916 on structured-PII classification is **genuinely
excellent** — probably too excellent. When a new model trained on noisy
multi-source corpora lands an F1 in the ballpark of hand-tuned
production detectors, that should trigger a specific reflex: *what am
I measuring that's easier than the real task?*

The other quieter flag: `cv_std = 0.0072` is **suspiciously low** for
5-fold CV on a ~7700-row training set with multiple source corpora.
Real cross-validation on heterogeneous data produces fold-to-fold
variance in the 0.02-0.05 range because folds legitimately differ.
Variance that tight means one of three things:

1. The task is trivially easy (not plausible for PII classification)
2. The folds are oddly homogeneous (leakage hint!)
3. Both folds are seeing the same "shortcut" and agreeing on it

None of these were investigated at the time.

## The Q3 experiment — what it predicted

Q3 went looking for leakage specifically. Its hypothesis:
`StratifiedKFold` was not respecting the corpus boundaries in the
training set. The ~7700 rows came from multiple source corpora
(Ai4Privacy, Nemotron-PII, SecretBench, gitleaks, detect-secrets,
synthetic). Each corpus has its **own distribution of surface features**
— average value length, character class mixtures, separator conventions.
If the model latched onto those corpus-level signatures as features, it
could "classify" columns by which corpus they came from instead of by
what entity type they held — and `StratifiedKFold` wouldn't catch it
because every fold contained rows from every corpus.

Q3's concrete prediction: **switching to `StratifiedGroupKFold` with
`groups=corpus_source` would make the cv_mean_macro_f1 fall by more
than 0.5 F1**, and best_c would change to a weaker value because the
model would need to generalize across corpora it had never seen.

Q3 memo filed the prediction, queued the M1 fix as a sprint item,
moved on.

## The M1 run — what actually happened

A later session implemented the fix: replaced `StratifiedKFold(5)` with
`StratifiedGroupKFold(5, groups=corpus_source_vector)` in
`tests/benchmarks/meta_classifier/evaluate.py` and re-ran the same
pipeline:

```
                    StratifiedKFold   StratifiedGroupKFold   Delta
best_c:                100.0               10.0              ✅ Q3 predicted
cv_mean_macro_f1:      0.9160 ± 0.0072     0.2539 ± 0.0956   −0.6621
held_out_test_f1:      0.9185              0.9123            −0.0062 (noise)
```

Four things happened at once, and each tells you something.

### 1. CV mean F1 collapsed from 0.916 to 0.254

That's a **66-percentage-point drop** just from changing the splitting
strategy. Nothing about the data or the model changed. Nothing about the
task definition or the features changed. The only thing that changed is
that GroupKFold makes it impossible for the model to see training
examples from the same corpus it's being tested on.

The honest reading: **the model was not learning "what is an SSN" — it
was learning "what does an Ai4Privacy SSN column look like vs a
Nemotron-PII SSN column". When the fix held out a whole corpus, the
model had no corpus fingerprint to latch onto and fell to ~25% F1.**

This is leakage in the statistical sense: information from the test
split was implicitly available during training (via rows from the same
corpus), and the model used it.

### 2. CV standard deviation jumped 13× (0.0072 → 0.0956)

The old std of 0.0072 now looks exactly like what it was: **proof of
leakage**. When every fold sees the same corpora at training time, the
model's "performance" on each fold is really just "how well does it
recognize this mix of corpora", which is trivial and stable. Once you
stop feeding it a balanced corpus mix, the fold-to-fold variance
explodes because each fold now holds out a different distribution.

**The lesson:** an unusually low CV variance is **not** a sign of a
well-behaved model. It's a sign you should check whether your folds
are actually independent. On messy, multi-source data, *some*
fold-to-fold variance is **required** for the CV to be honest.

### 3. `held_out_test_f1` barely moved (0.9185 → 0.9123)

Why? Because the held-out test set was **always fold-independent**.
The model always generalized to that specific held-out set — the
held-out set was part of the split before CV even ran. What was broken
was the CV estimate, not the held-out measurement. If you had only
trusted the held-out number (which stayed stable), you'd have been
fine. If you extrapolated the CV number (which was a lie) to predict
production performance, you'd be wildly off.

**The lesson:** when CV and held-out disagree dramatically after a
methodology change, **believe the held-out**. Held-out is typically
less contaminated because it's outside the k-fold loop. If held-out
shifts by 0.006 and CV shifts by 0.66, the 0.66 was the one that was
lying.

### 4. The top feature importance was `heuristic_avg_length` at 252

Feature importance tells you what the model is actually using. After
the M1 fix, the dominant feature was `heuristic_avg_length` — the
average length of values in the column. That's a **corpus-level
statistical property**, not an entity-level semantic property. An SSN
is an SSN regardless of whether its column contains 30 values or 300.
But an Ai4Privacy SSN column has a different avg_length than a
Nemotron SSN column because the corpora were constructed differently.

The model figured this out and used it as a shortcut. That's not the
model being clever; that's the model doing exactly what gradient
descent is supposed to do: **find the easiest signal that correlates
with the label**. If the easiest signal is a corpus fingerprint, and
corpus fingerprints correlate with label distribution, the model will
use them.

**The lesson:** always look at feature importances on the HONEST CV,
not the leaky CV. If your top feature is a corpus-level artifact, you
have a leakage problem regardless of what your F1 number says.

## What all four observations mean together

Putting the four threads in one picture:

1. **The CV estimate was ~0.66 F1 too optimistic** due to corpus
   fingerprint leakage.
2. **The held-out test was honest** and had been honest the entire time
   — it just wasn't the number being quoted.
3. **The model's top feature was the leakage vector itself**, so there
   was a direct mechanistic explanation for the inflated CV.
4. **The honest model is only 25% F1**, not 91%, on truly unseen
   corpora. That's a **completely different product** than what the
   memo described.

None of this was a bug in the model code. None of it was a bug in the
training loop. The bug was in the **evaluation methodology** — in the
specific choice of cross-validation splitter. One line changed:
`StratifiedKFold` → `StratifiedGroupKFold(groups=corpus_source)`.
Everything else stayed the same. And the honest F1 went from an
exciting research result to "we haven't actually made progress".

## What this case tells you about developing intuition

If you remember only one thing from this guide, remember this case.
It embeds several of the most important lessons in a single concrete
story:

### Lesson A: "Too good" is a signal, not a celebration

Macro F1 of 0.916 on messy multi-source PII data was an **alarm**, not
a victory lap. An exciting number from a new model pipeline on a
difficult task should trigger **additional scrutiny**, not publication.
The instinct to say "this must be correct because it looks great" is
exactly backwards. Strong evidence deserves *more* examination, not
less.

**Concrete reflex to build:** when you see a number that exceeds your
prior expectation by more than ~0.10 F1, freeze. Before writing a
memo, ask:
- What's the simplest shortcut the model could be using?
- Is there a leak between train and test I haven't ruled out?
- What does feature importance say, and is the top feature a
  legitimate signal?

### Lesson B: Low variance on messy data is suspicious, not reassuring

`cv_std = 0.0072` was not "the model is stable". It was "the folds are
seeing the same thing". On multi-source data, variance *should* be
noticeable because the sources differ. Near-zero fold variance is a
**leakage signature**, not a **reliability signature**.

**Concrete reflex to build:** when you see CV std < 0.01 on real ML
data, check the splitter choice before checking anything else.

### Lesson C: When CV and held-out disagree, trust held-out

The held-out test was stable (0.9185 → 0.9123). The CV exploded
(0.916 → 0.254). The held-out was always the honest number; the CV was
always the dishonest one. If you'd weighted held-out more heavily in
your decision-making, you would have been fine.

**Concrete reflex to build:** always report held-out alongside CV.
When they disagree, assume CV is the one at fault until you can prove
otherwise.

### Lesson D: Feature importances are a leakage detector

`heuristic_avg_length` as top feature should have been a hint. Column
avg_length is a corpus-level property — different corpora have
different avg_lengths by construction. If your model's dominant signal
is a corpus fingerprint rather than a task-level feature, you have a
leakage problem regardless of what F1 says.

**Concrete reflex to build:** after every training run, look at the
top 5 feature importances and ask, for each: "is this a
task-legitimate feature, or a dataset-specific artifact?". If the
top feature is an artifact, investigate before quoting F1.

### Lesson E: The validation design IS the experiment

You can have perfect data, a perfect model architecture, and perfect
training code, and still get a wildly wrong answer if your validation
strategy has the wrong assumption about what constitutes "independent"
splits. **CV is not a black box**; it encodes a specific claim about
exchangeability that you need to check against your actual data
structure.

In our case, the claim `StratifiedKFold` makes is: "rows are
interchangeable given the label". That claim was false because rows
from the same corpus are correlated in ways the label doesn't capture.
`StratifiedGroupKFold` makes a weaker, truer claim: "rows within the
same group are not interchangeable with rows from a different group".
The specific leakage vanishes as soon as you match the splitter to the
actual data structure.

**Concrete reflex to build:** before choosing a CV splitter, ask
"what are the sources of non-exchangeability in my data?". Corpora,
tables, users, time periods, patients — each is a plausible group-level
source of structure that a naive splitter will miss.

## The connection to how this guide's other tools would have caught it

Re-read section 8 (effect size vs significance). The Sprint 6 report
had a point estimate (0.9160) and a narrow variance (0.0072). It did
not have a **paired test against a stronger baseline** or a **bootstrap
CI on the generalization estimate** (because no one asked "what if the
splitter is wrong?" at the time). Those are the kind of sanity checks
that *might* have caught it, not because they directly diagnose leakage
but because they force you to state assumptions that leakage violates.

Section 12's "how to develop intuition" items 4 ("could a random
baseline beat this?") and 6 ("seek disconfirmation") are the moves that
would have caught it with high probability. Specifically: "could a
random baseline that just guesses the corpus source beat 0.254 on
GroupKFold?" If the answer is yes, you've found the shortcut. That
exact thought experiment is what Q3 ran.

## The final honest number

The Sprint 6 memo's 0.916 was wrong. The Sprint 8 handover was revised
to cite the M1-corrected numbers. The model is now classified as a
shadow-mode component that needs substantial more work before it can
make a ship decision. The "progress" claimed in Sprint 6 was partially
illusory, and the team is now rebuilding the training pipeline with
corpus-aware splitters from the start.

**That is the cost of skipping the intuition checks in Section 12.**
Not a paper retraction, not a production incident — just several
sprints of work that have to be re-done because the evaluation was
wrong, and everyone spent a lot of time believing a number that didn't
mean what they thought it meant.

## Summary of the Q3/M1 lesson in one sentence

> **A model that looks amazing on CV but tells a different story on a
> group-aware splitter was never learning the task you thought it was
> — and the fix is not to argue with the new number, it's to trust
> the honest splitter and go rebuild.**

File this under "things I wish somebody had told me before I shipped
my first ML research memo". Internalize it and you'll save yourself
at least one embarrassing retraction over the course of your career.

---

# Appendix B — Case study: when McNemar and bootstrap disagree (Pass 1)

> **Source:** `docs/experiments/gliner_context/runs/20260413-2300-pass1/`,
> produced minutes after this guide was written. Real, live output from
> the research track.
>
> **Why this case matters:** it's the simplest way to absorb the most
> common subtlety in paired hypothesis testing — that **a paired test
> is only as good as the per-subject statistic it collapses the data
> to**. Get that statistic wrong and your "definitive McNemar" gives
> you the wrong answer while your bootstrap on aggregate F1 gives you
> the right one. Or vice versa. The two tests are not redundant.

## The situation

Pass 1 of the research/gliner-context track ran 4 strategies against
fastino/gliner2-base-v1 on 315 Ai4Privacy-derived columns, measured
**both** a paired bootstrap 95% CI on macro F1 deltas **and** a paired
McNemar exact test on top-1 correctness. At threshold 0.7, comparing
S1 (NL prompt) to baseline, the two tests returned:

```
Bootstrap paired Δ F1:  +0.0887, BCa 95% CI [+0.058, +0.123]
                        → STRONG evidence S1 is +0.09 better
McNemar exact p-value:  1.000  (b=10, c=10)
                        → ZERO evidence of any difference
```

**Both of these statements are correct.** They are not contradictory.
They measure **different things**, and the difference is the whole
lesson of this appendix.

## Why they can both be true

My McNemar correctness vector was defined as:

> **"Did the strategy report the ground-truth entity type for this
> column?"**

Code: `ground_truth in r.predicted_entity_types`

For each column, baseline and S1 each get one "correct / wrong" bit.
The 2×2 discordance table counts how often exactly one of them is
right. The (10, 10) tie means: of the 20 columns where the two
strategies disagreed on this per-column correctness bit, exactly
10 favored baseline and 10 favored S1. Essentially zero net
difference.

But macro F1 is not just about getting the ground-truth type right.
It's:

```
macro F1 = average_over_types( 2 * P_t * R_t / (P_t + R_t) )
```

And `P_t` — precision for type t — is degraded by **any** column that
false-fires t, regardless of whether that column's ground-truth type
was also correctly reported.

Concretely: imagine column 5 has ground truth `EMAIL`. Baseline
reports `{EMAIL, PHONE}` — correctly identified EMAIL but spuriously
also fired PHONE. S1 reports `{EMAIL}` — correctly identified EMAIL
and didn't false-fire. Both get my McNemar correctness bit = 1
(both reported the ground-truth type). McNemar sees no difference
on this column. But baseline's PHONE report is a false positive
contributing to `P_phone` denominator, dragging down PHONE's
precision for baseline but not for S1. Macro F1 is lower for
baseline.

Multiply that across 300 columns and you get an S1 vs baseline
macro F1 delta of +0.09, invisible to McNemar.

## The aggregate shows the effect, the paired test hides it

This is the counterintuitive part. Usually paired tests are *more*
powerful than aggregate tests, because they cancel out between-subject
variance. Here it was the opposite:

- **Aggregate**: macro F1 aggregates across all 315 columns and 8
  entity types, summing false positives that my per-column correctness
  bit was blind to. The aggregate number is +0.09 and the paired
  bootstrap (which preserves column pairing AND keeps the same
  aggregate statistic) correctly confirms it.
- **Paired McNemar on my wrong per-column bit**: the per-column bit
  I chose to collapse the data to doesn't reflect the information
  macro F1 uses. The collapse throws away exactly the signal S1
  is improving on.

**The lesson is not "paired tests are weak"**. Paired tests are
still more powerful **on the statistic they're testing**. The lesson
is "a paired test is only as good as the per-subject statistic you
chose to pair on".

## The correct per-column statistic for macro F1

To make McNemar sensitive to the same improvements macro F1 captures,
the per-column correctness bit should be:

> **"Did the strategy produce EXACTLY {ground_truth} as its prediction
> set?"**

Code: `r.predicted_entity_types == {r.ground_truth}`

With that definition:
- A column reporting `{EMAIL, PHONE}` when GT is EMAIL → **wrong**
  (has an extra FP)
- A column reporting `{EMAIL}` when GT is EMAIL → **right** (clean)
- A column reporting `{PHONE}` when GT is EMAIL → **wrong** (missed GT)

Now McNemar measures exactly what macro F1 rewards: clean
per-column predictions with no false positives. If S1 reduces FPs,
McNemar will see it.

## What I'll do about it

Pass 1b will re-run the McNemar calculation on the same cached
per-column results with the corrected definition. No re-inference
needed — the raw `predicted_entity_types` sets are already saved
in `per_column_thr{0.5,0.7,0.8}.json`. The correction is a 2-line
code change and a few seconds of compute.

Expected outcome: the McNemar p-values for S1 will drop by at least
an order of magnitude once the correctness bit includes FP reduction.
The bootstrap Δ CI result won't change — it was already measuring the
right thing.

## The generalizable reflex

Any time you find yourself writing a paired test on ML results, ask:

1. **What's the per-subject statistic I'm collapsing the data to?**
2. **Does that statistic aggregate (sum / average / compose) into the
   effect size I actually care about?**
3. **If I ran the aggregate test on the same data, would I expect the
   same answer, or could the two disagree?**

If you can't answer (3) with confidence, stop and think through what
each test measures. The failure mode is usually that your per-subject
statistic throws away information the aggregate keeps.

**A rule of thumb that would have saved me here:**

> **Before running McNemar on "was the classifier correct?", ask
> whether "correct" means the same thing as the performance metric
> you'll quote in the memo. If the metric is multi-label or accounts
> for precision across types, binary "correct / wrong" will probably
> undermeasure.**

In our case, `GT in predictions` was a weaker correctness criterion
than macro F1 cares about, so the paired test was less sensitive than
the aggregate bootstrap. Swap in `predictions == {GT}` and the
sensitivity matches.

## What would have happened if I'd trusted McNemar alone

Imagine a version of this project where I'd only reported McNemar
p-values and not bootstrap CIs. The Pass 1 output would have been:

> "S1 shows no statistically significant improvement over baseline
> at any threshold. McNemar p=0.48, 1.00, 0.58 across thresholds
> 0.5, 0.7, 0.8. S1 is refuted."

This would be **factually wrong**. S1 really is +0.09 F1 better. The
confidence intervals say so with ~95% certainty. But a purely
McNemar-driven framing would have mis-concluded the research,
retired a winning strategy, and wasted the work.

The bootstrap on the aggregate statistic is the check that would
have caught it. **The lesson is to always report BOTH tests**, treat
disagreement between them as a signal to investigate the definitions
rather than a signal to trust one over the other.

## Pass 1 key-point summary

1. **McNemar and paired bootstrap on F1 measure different things
   whenever the per-column correctness statistic doesn't match the
   aggregate metric's decomposition.**
2. **Disagreement between tests is an alarm bell, not a selection
   opportunity.** Don't cherry-pick the test that gave you the
   answer you wanted.
3. **The right per-column bit for macro F1 is an exact-match check**,
   not a "did we detect GT" check. If you're doing paired tests
   against macro F1, use exact-match correctness or be prepared to
   explain why your paired test is less sensitive than your
   aggregate.
4. **The bootstrap on the aggregate is the safer default** because it
   directly measures the statistic you'll quote. Paired tests can
   be more powerful but only if the per-subject statistic is chosen
   correctly.
5. **The mistake is cheap to fix in post-hoc analysis** (re-run just
   the McNemar calculation with the corrected definition — no new
   inference required) but expensive if you ship the wrong verdict
   to stakeholders.

## The one-sentence lesson

> **A paired test is a compression of the data to per-subject
> decisions — if the compression throws away the thing your aggregate
> metric rewards, the paired test will report "no effect" on a real
> effect. Always pair on a statistic that decomposes into your
> metric.**

Read this appendix next to Appendix A (Q3/M1 cross-validation leakage).
Both are failure modes you'll hit if you don't carry a clear mental
model of what each statistical tool is measuring. Q3 was a leakage
problem in the data splitter. Pass 1 was a definitional problem in
the per-subject correctness statistic. Neither was visible from the
surface — both required stepping back and asking "what is this tool
actually testing?". That habit is the most important statistical
skill I can help you build.

