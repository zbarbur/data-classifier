# Zone Detection in Mixed-Content Text — Prior Art Research Survey

**Date:** 2026-04-21
**Branch:** `research/prompt-analysis`
**Author:** research session (S4 zone detection)

---

## 1. Problem Statement

Detecting code blocks, structured language zones (JSON, YAML, SQL, etc.),
and error output within free-form LLM prompts. The input is a single string
containing a mix of natural language prose and embedded non-prose content,
without reliable structural markers (96.9% of blocks are unfenced per our
WildChat scan). The output is a set of labeled spans with zone type,
boundary positions, and confidence.

This is harder than file-level language detection (one language per file)
and harder than within-language code/comment separation (known language,
just classify lines). Our problem is **within-document, cross-language zone
segmentation** in text where the language is unknown and zones are unmarked.

### Our baseline (heuristic v1)

| Metric | Value | Note |
|---|---|---|
| Detection accuracy | 90% | Whether a code block exists at all |
| Boundary recall | 70% | What fraction of user-marked lines we include |
| Median block size (heuristic) | 26 lines | |
| Median block size (human) | 66 lines | Heuristic fragments at blank/comment lines |
| Total FPs (reviewed) | 35/564 reviewed | 6.2% FP rate |
| Total FNs (reviewed) | 2/564 reviewed | 0.4% FN rate |

The primary gap is boundary recall — the heuristic detects code presence
well but fragments blocks at blank lines, comments, and ambiguous interior
lines.

---

## 2. Academic Research

### 2.1 Island Grammar Parsing

**Source:** Bacchelli et al., ASE 2011
([paper](https://sback.it/publications/ase-short2011.pdf)),
extended in
[ScienceDirect 2017](https://www.sciencedirect.com/science/article/pii/S0167642317301302)

**Approach:** Island grammars define detailed grammar productions for
"islands" (code constructs of interest) and liberal productions for
"water" (everything else — natural language). The parser recognizes
structured fragments embedded in unstructured text without requiring
the entire document to parse.

**Key results:** High precision and recall for extracting code fragments,
stack traces, and log output from developer emails and issue tracker
content. Handles nested islands (code within code).

**Implementation:** Scanner-less Generalized LR (SGLR) parsing with the
Syntax Definition Formalism (SDF). Parsing Expression Grammars (PEGs) are
a faster alternative with comparable accuracy.

**Relevance:** The island/water paradigm maps directly to zone detection —
code blocks are islands, prose is water. **However, island grammars require
per-language grammar definitions**, which is heavyweight for 50+ languages
and impractical for a lightweight scanner.

**Lesson:** The conceptual model (island/water) is right. The
implementation strategy (formal grammars) is too heavy.

### 2.2 Code-Text Alignment in Stack Overflow

**Source:** Yao et al., MSR 2018
([paper](https://cmustrudel.github.io/papers/msr18so.pdf))

**Approach:** Treats code-text alignment as a classification problem.
Uses structural features (language-independent syntactic validity
estimation) combined with automatically learned correspondence features.

**Key insight:** Structural features alone — not requiring
language-specific knowledge — provide strong signal for identifying
code vs. prose boundaries. Language-independent surface features
generalize across programming languages.

**Relevance:** Validates our approach of using language-agnostic features
(syntax character density, alpha ratio, indentation) rather than
per-language parsers.

### 2.3 SCC: Automatic Classification of Code Snippets

**Sources:**
- SCC (Khasnabish et al., 2018, [arXiv](https://arxiv.org/abs/1809.07945))
- SCC++ ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0164121219302791))
- SCC-GPT ([MDPI 2024](https://www.mdpi.com/2227-7390/12/13/2128))

**Results:**

| Model | Accuracy | Approach |
|---|---|---|
| SCC (Naive Bayes) | 75% on 21 languages | Token n-gram bag-of-words |
| PLI (proprietary) | 55.5% on snippets | Claimed 99.4% on full files |
| SCC++ (Random Forest + XGBoost) | 88.9% | Title + body + code features |
| SCC-GPT (Transformer) | +6-31% F1 over SCC++ | Pre-trained language model |

**Key findings:**

1. **Code snippets (few lines) are much harder to classify than full
   files.** PLI dropped from 99.4% to 55.5% on snippets. This matches
   our challenge — prompt-embedded code is often snippet-length.

2. **Bag-of-tokens Naive Bayes is a surprisingly strong baseline.**
   75% accuracy with minimal complexity.

3. **Combining surrounding context (title/body) with code features
   gives the biggest lift.** SCC++ gained 13.9% by adding context.
   This validates our sliding-window approach — considering neighboring
   lines provides context analogous to title/body.

### 2.4 Code-Switching and Language Identification

The NLP community has extensive work on **code-switching** (mixing
multiple human languages in one text), which is structurally analogous
to code-prose mixing:

- **Token-level language ID:** RoBERTa/mBERT fine-tuned for per-token
  language tagging
  ([ACL 2023 survey](https://aclanthology.org/2023.findings-acl.185.pdf))
- **TongueSwitcher:** Enhanced boundary detection in mixed-language text
- **CMX:** Fast, compact feed-forward network predicting language per
  token

**Key insight:** The BIO (Begin / Inside / Outside) tagging framework
used for NER transfers directly to zone boundary detection. CRF
(Conditional Random Field) layers on top of per-token classifiers
improve boundary predictions by modeling transition constraints
(e.g., I-CODE can only follow B-CODE or I-CODE).

**Relevance:** Sequence labeling with CRF is the natural ML formulation
for our problem. The transition modeling directly addresses our boundary
fragmentation issue.

### 2.5 Text Segmentation

**Source:** Segment Any Text
([arXiv 2406.16678](https://arxiv.org/html/2406.16678v2))

Universal approach outperforming baselines across 8 corpora, especially
on poorly formatted text. Uses transformer-based boundary prediction.

CRF-based segmentation approaches use features like: prefixes, suffixes,
capitalization, numeric content, context words, and character n-gram
distributions. Modern variants combine pre-trained transformers with
CRF layers for boundary prediction.

---

## 3. Open-Source Tools and Libraries

### 3.1 GitHub Linguist

**Source:** [github/linguist](https://github.com/github-linguist/linguist),
[how-linguist-works.md](https://github.com/github-linguist/linguist/blob/main/docs/how-linguist-works.md)

**Detection pipeline (in order):**

1. Vim/Emacs modeline
2. Known filename patterns
3. Shell shebang (`#!`)
4. File extension
5. XML header
6. Man page section
7. **Heuristics** — regexp-based rules in `heuristics.yml`
   (e.g., `^[^#]+:-` for Prolog, `@interface` for Obj-C)
8. **Naive Bayesian classifier** trained on `samples/` directory

**Key architectural lesson:** **Cascade of cheap-to-expensive strategies.**
Extension handles 80%+ of cases. Heuristics handle ambiguous extensions.
Bayesian classifier is the last resort. This cascade pattern is directly
applicable to zone detection.

**Limitation:** File-level only. Does not handle mixed-content documents
or within-file zone boundaries.

### 3.2 go-enry

**Source:** [go-enry/go-enry](https://github.com/go-enry/go-enry)

Go port of Linguist with 2x performance. Same cascade: filename →
extension → first line → full content → classifier. **Used by The Stack
v2** for language identification across 658 languages.

### 3.3 Guesslang

**Source:** [yoeo/guesslang](https://github.com/yoeo/guesslang)

Deep learning TensorFlow model trained on 1.9M source files from 170K
GitHub projects. 50+ languages, >90% accuracy.

**Used by The Stack v2** for Jupyter notebooks when language metadata
is unavailable (probability threshold >0.5).

**Limitation:** Expects a complete code snippet as input. Not designed
for mixed content or within-document segmentation.

### 3.4 Pygments

**Source:** [pygments.org](https://pygments.org/docs/api/)

`guess_lexer()` calls `analyse_text()` on every registered lexer, each
returning 0.0-1.0 confidence. Highest score wins. Individual lexers check
for shebangs, modelines, and language-specific keyword patterns.

**Key insight:** The **per-lexer multi-voter pattern** — each language
"votes" on how well the text matches — is a practical approach for
language identification within detected code blocks. We adopt this for
our secondary language probability output.

### 3.5 Tree-sitter Language Injection

**Source:** [tree-sitter/tree-sitter](https://github.com/tree-sitter/tree-sitter),
[Discussion #793](https://github.com/tree-sitter/tree-sitter/discussions/793)

`@injection.content` and `@injection.language` queries specify nodes
whose content should be parsed as a different language. Handles
HTML+JS+CSS, PHP+HTML, JSX.

**Key mechanism:** `ts_parser_set_included_ranges` allows parsing
non-contiguous ranges of a document as a single language.

**Relevance:** Tree-sitter solves multi-language for files with known
structure (`<script>` tags). Our problem is harder — we don't have
structural markers telling us where languages switch. However, the
concept of "language injection" via structural markers (`<script>`,
`<style>`) informs our Pass 0 bracket-matching approach.

### 3.6 Line-Counting Tools (CLOC, SCC, Ohcount)

These solve a related subproblem: classifying each line in a
known-language file as code, comment, or blank.

- **CLOC** ([AlDanial/cloc](https://github.com/AlDanial/cloc)):
  Language-specific comment patterns, handles multi-line comments
- **SCC** ([boyter/scc](https://github.com/boyter/scc)):
  Ragel state machine, very fast
- **Ohcount**: Per-language state machines for code/comment/blank

**Key lesson:** Even the "simple" problem of code vs. comment
classification within a known language requires per-language state
machines. The cross-language, mixed-content problem is strictly harder.

### 3.7 CommonMark Specification

**Source:** [spec.commonmark.org](https://spec.commonmark.org/0.29/)

Critical boundary rules for our use case:

- **Indented code blocks:** 4-space indent required; **cannot interrupt
  a paragraph** (blank line required before)
- **Fenced code blocks:** Can interrupt a paragraph; matching fence
  chars required for closing
- **List item precedence:** When indentation is ambiguous between code
  block and list item, list wins

**Key lesson for boundary recall:** The CommonMark rule that indented
code blocks cannot interrupt paragraphs explains part of our
fragmentation — our detector splits at blank lines because that's
correct CommonMark behavior. But embedded code in prompts often has
blank lines within the code.

---

## 4. Industry Approaches (LLM Training Pipelines)

### 4.1 The Stack v2 / StarCoder 2

**Source:** [arXiv 2402.19173](https://arxiv.org/abs/2402.19173)

**Language identification:** go-enry (Linguist port), 658 languages.

**Mixed document handling:**
- **Jupyter notebooks:** Dual pathway — Jupytext script conversion +
  structured code-text pair extraction. Guesslang fallback for language
  when metadata absent.
- **GitHub issues:** Bot removal, quality thresholds (2+ users or <7K
  chars), comment cleaning
- **Code quality signals:** Long-line filters (>100K lines), alphabetic
  content (>25%), encoded data detection (base64/hex >1024 chars)

**Relevance:** Even at billion-scale, the pipeline uses file-level
language detection, not within-file segmentation. For mixed documents
(notebooks), they rely on structural markers (cell types). This
confirms that within-document segmentation in unstructured text is an
unsolved problem at scale.

### 4.2 Dolma (AI2 / OLMo)

**Source:** [arXiv 2402.00159](https://arxiv.org/abs/2402.00159)

**Approach:** Deliberately avoids model-based quality filtering. Uses
heuristic rules and regex:
- Gopher/C4 heuristic rules for quality
- FastText for natural language ID
- Code subset from The Stack with heuristic filters

**Key finding:** At 3T-token scale, **heuristic rules outperform
model-based classifiers** for binary code/text separation. The signal
is in surface features, not deep semantics.

### 4.3 FineWeb / RedPajama

**Source:** [FineWeb paper](https://arxiv.org/html/2406.17557v1)

50+ candidate heuristic filters tested, small set of effective ones
selected:
- C4-style: Drop lines without terminal punctuation, lines mentioning
  "javascript", cookie/ToS statements
- Drop documents with curly braces (`{`)
- RedPajama: 40+ quality annotations, MinHash deduplication, FastText
  language classification

**Key insight:** FineWeb/C4 *removes* code from prose datasets. They're
solving the inverse of our problem, but their feature choices validate
the same surface signals we use (curly braces, terminal punctuation,
alpha ratio).

### 4.4 Code Completion Tools

Code completion tools (Copilot, Cursor, etc.) implicitly handle mixed
content by relying on the language model itself to understand zone
boundaries — no explicit pre-segmentation.

**Relevance:** These tools operate within known-language files, not
arbitrary mixed text. Their approach (LLM understands everything) works
with a large model but is too expensive for our per-prompt scanning use
case.

---

## 5. ML Approaches

### 5.1 Granularity Comparison

| Granularity | Pros | Cons | Used by |
|---|---|---|---|
| Character-level | Finest boundaries, inline code | Noisy, slow, large context | CLD2/3 (n-grams) |
| Token-level | Good for BIO tagging, mixed lines | Requires tokenizer, expensive | NER approaches |
| **Line-level** | Natural unit for code, fast, interpretable | Can't handle inline code | SCC, our approach |
| Block-level | Matches user mental model | Requires boundary detection first | Linguist, Guesslang |

**Consensus from literature:** Line-level is the sweet spot for code
detection. Block-level for final output, but line-level scoring + block
merging as the pipeline.

### 5.2 Sequence Labeling (BIO Tagging)

The NER-style BIO framework is the natural ML formulation:

- `B-CODE`, `I-CODE`, `B-CONFIG`, `I-CONFIG`, `O` (natural language)
- CRF layer enforces valid transitions (no `I-CODE` without `B-CODE`)
- Features per line: indentation, syntactic char density, keyword count,
  alpha ratio, blank-line distance

**Architecture options:**

| Architecture | Training data | Accuracy | Speed | Boundary quality |
|---|---|---|---|---|
| Feature-engineered CRF | 500-1K docs | ~93-95% | Very fast | Good (models transitions) |
| BiLSTM-CRF | 2-5K docs | ~95-97% | Moderate | Very good |
| Transformer + CRF | 1-5K docs | ~97%+ | Heavy | Best |

The **CRF with hand-crafted features** is the sweet spot for our use
case: directly addresses boundary fragmentation (CRF enforces valid
transitions), needs only 500-1K annotated documents (we have 507+
reviewed), and runs in microseconds per line.

### 5.3 Most Discriminative Features

From the literature and tool analysis, ranked by discriminative power:

1. **Syntactic character density** (`{}()[];=<>|&`) — single strongest
2. **Keyword presence** (`def`, `class`, `import`, `function`, `return`)
3. **Alpha-to-total character ratio** — prose >80%, code 40-70%
4. **Line ending characters** (`;`, `{`, `}`, `)`, `,`)
5. **Indentation depth** — code is indented, prose is flush
6. **Line length distribution** — code clusters at specific widths
7. **Blank line patterns** — code uses blanks differently from paragraphs
8. **Leading symbols** (`$`, `>`, `>>>`, `#`)
9. **Assignment patterns** (`=`, `:=`, `<-`, `=>`)
10. **String literal density** (quoted strings)

### 5.4 Small Model Approaches

| Model | Size | Data needed | Accuracy | Notes |
|---|---|---|---|---|
| FastText char n-gram | <1MB | 10-100K lines | >90% on lang ID | Could train on code-vs-prose |
| Naive Bayes token n-gram | Trivial | 10K lines | 75% (SCC) | Strong baseline |
| Logistic regression | Trivial | 500-1K docs | ~90% | Our heuristic, but learned |
| CRF | ~10KB | 500-1K docs | ~93-95% | Best boundary quality for size |
| CMX-style FFN | <1MB | 5-10K docs | ~93% | Fast, compact |

---

## 6. Failure Modes and Lessons Learned

### 6.1 Boundary Fragmentation

**Root cause:** Breaking at blank lines is correct for CommonMark
indented code blocks but wrong for embedded code. Code has blank lines
between functions, after class definitions, between logical sections.

**Solutions from literature:**
- **Merging heuristic:** After classification, merge same-type blocks
  separated by 1-3 blank lines
- **CRF transition modeling:** CRF learns `CODE → BLANK → CODE` stays
  CODE, while `CODE → BLANK → BLANK → PROSE` transitions
- **Comment bridging:** Treat comment lines within code blocks as code

### 6.2 Comments Within Code Blocks

Comments look like prose (high alpha ratio, natural language). Causes
code blocks to fragment at comment lines.

**Solutions:**
- Feature: "indented consistently with surrounding code?"
- Feature: "starts with comment marker?" (`#`, `//`, `/*`, `--`)
- Context window: Score each line considering 3-5 surrounding lines

### 6.3 Short Code Snippets (1-3 lines)

Insufficient signal for statistical approaches.

**Solutions:**
- Lower confidence threshold but still emit
- Rely on explicit markers (backticks, indentation)
- Use surrounding prose context ("here's the code:", "run this:")

### 6.4 Ambiguous Content

Some content straddles categories (SQL is query or code; YAML is config
or data; pseudocode looks like code but isn't).

**Solution:** Accept multi-label ambiguity with confidence scores rather
than forcing hard boundaries.

### 6.5 Precision/Recall Tradeoff

From the literature:
- **High precision:** Strict markers only (fenced blocks, 4-space indent).
  Misses unfenced code.
- **High recall:** Loose heuristics (any line with `{` or `import`).
  Many false positives.
- **Typical operating point:** 85-95% precision, 70-85% recall for
  unfenced code

Our current 90% detection / 70% boundary recall is consistent with
a heuristic approach that has good precision but fragments boundaries.

---

## 7. Our Empirical Findings (507+ reviews)

### 7.1 FP Category Distribution

Analysis of 35 false positives from 564 reviewed prompts:

| FP Category | Count | % of FPs | Root cause |
|---|---|---|---|
| Aspect ratio lists (`4:3`, `16:9`) | 7 | 20% | Colon syntax triggers code score |
| Structured lists / glossaries | 6 | 17% | Parens/brackets in list items |
| Error messages / build output | 4 | 11% | File paths, line numbers, module refs |
| Dialog / conversation | 3 | 9% | `Name: "text"` format |
| Math / data notation | 3 | 9% | Function-like `p(0,1)`, operators |
| XML heuristic over-trigger | 2 | 6% | Angle brackets in NL instructions |
| Tabular / ASCII tables | 2 | 6% | Pipe/dash table formatting |
| URL / forum / social / academic | 4 | 11% | Low-confidence miscellaneous |
| Fenced non-code | 1 | 3% | Backtick-fenced log output |
| BBCode markup | 1 | 3% | `[tag]` confused with code |
| CSV academic data | 1 | 3% | Delimiter-consistent tabular |

### 7.2 Error Class Distribution

| Error class | Count | % of errors |
|---|---|---|
| Pure FP (no block should exist) | 35 | 64.8% |
| Mistype (right boundaries, wrong type) | 11 | 20.4% |
| Boundary (right type, wrong span) | 3 | 5.6% |
| Fragmentation (1 block split into 2+) | 2 | 3.7% |
| FN (block missed entirely) | 2 | 3.7% |
| Merge (3 blocks merged into 1) | 1 | 1.9% |

### 7.3 Key Empirical Insights

1. **syntax_score at low confidence is the dominant FP source.** 34/37
   FP blocks come from syntax_score. 19 of those have confidence <0.66.
   Threshold bump from 0.650 to 0.670 eliminates 51% of FPs while mean
   TP confidence is 0.715.

2. **Seven FPs (20%) are a single repeated template** (MidJourney aspect
   ratios). One negative pattern eliminates all 7.

3. **Error/build output (4 FPs) shares syntax features with code** but
   has repetitive line-level structure that code doesn't.

4. **The xml_heuristic boundary problem is systematic.** NL instructions
   using angle brackets (`<CLAIM>`, `<MEASURE>`) cause the zone to
   swallow the entire prompt.

5. **Code vs. data is the hardest mistype.** 6/11 mistypes are code →
   data (training tuples, dataset tables, hex colors). These contain
   parens/brackets but aren't executable.

---

## 8. Conclusions

### 8.1 What the literature tells us

1. **Surface features are sufficient for code detection.** Heuristic
   rules outperform deep models at the binary code/prose level (Dolma,
   FineWeb). The signal is in character distributions, not semantics.

2. **Boundaries need transition modeling.** Per-line classification
   alone causes fragmentation. CRF or rule-based transition constraints
   are the standard fix.

3. **Cascade architecture is the proven pattern.** Linguist, enry, and
   Pygments all use cheap-first-expensive-last cascades. Apply this to
   zone detection: fenced blocks → structural parsing → line scoring →
   block merging → selective parse validation.

4. **Context from neighbors matters.** SCC++ gained 13.9% by adding
   surrounding text context. A 3-line window captures most of this
   benefit.

5. **We don't need per-language parsers.** Language-independent
   structural features (Yao et al.) generalize across languages. For
   validation, group languages by syntax family (C-family, Python,
   Markup) — 3 strategies cover 90%+ of cases.

### 8.2 What our data tells us

1. **Most FPs come from non-code structured content** that shares
   surface features with code (lists, dialogs, math notation, error
   output). Negative signals for these specific patterns are
   higher-value than making the positive signals more sophisticated.

2. **Block merging is the highest-ROI improvement.** Detection is
   already 90% accurate. Boundary recall (70%) is the gap, caused by
   fragmentation at blank lines and comments.

3. **We have enough training data for a CRF** (507+ reviewed prompts,
   138 boundary corrections) if we choose to go that route. Feature-
   engineered CRF needs 500-1K documents.

4. **Error output deserves its own zone type.** It's structurally
   distinct from code, high-value for secret detection (credential
   leaks in stack traces), and a common prompt pattern.

### 8.3 Design direction

The research supports a **multi-pass cascade architecture** with:

- **Pass 0:** Bracket/delimiter scanning (structural markers)
- **Pass 1:** Line-level scoring with 3-line context window +
  fragment matching + negative signals
- **Pass 2:** Block assembly with gap bridging + bracket validation
- **Pass 3:** Block-level confirmation with selective parse attempts

This combines the Linguist cascade pattern, the CRF insight about
transition modeling (implemented as rule-based merging in Pass 2),
the SCC++ finding about context importance (3-line window in Pass 1),
and the Pygments multi-voter pattern (language probability as
secondary output).

The architecture is detailed in the companion spec:
`zone_detector_v2_spec.md`.
