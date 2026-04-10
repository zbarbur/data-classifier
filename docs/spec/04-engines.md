# Classification Library — Engines & Capabilities

This document describes each engine (model, service, or algorithm) available in the classification library. Engines are the building blocks — pipelines (doc 05) compose them into task-specific flows.

Each engine is described once here. Pipeline docs reference engines by name without repeating capability details.

---

## Engine Overview

| Engine | Type | Size | Latency | What It Does |
|--------|------|------|---------|-------------|
| **Structural Content Classifier** | ML-trained / heuristic | <200KB model | <1ms | Identifies code, config, query, log, CLI, markup vs. natural language |
| **Boundary Detector** | ML-trained / heuristic | reuses structural classifier | <2ms | Finds content-type transitions in mixed text via sliding window |
| **Structured Secret Scanner** | Algorithm (parsers + scoring) | — | <5ms | Parses JSON/YAML/env/code, extracts key-value pairs, scores via key-name + Shannon entropy |
| Regex Patterns | Algorithm | — | <1ms | Pattern matching with format validation (Luhn, checksum) for PII + known-format secrets |
| Column Name Semantics | Algorithm | — | <1ms | Fuzzy matching against 400+ sensitive field name variants |
| Heuristic Statistics | Algorithm | — | <1ms | Statistical analysis: entropy, cardinality, length distribution |
| Financial Density Scorer | Algorithm | — | <1ms | Detects clusters of currency amounts + percentages + financial terms |
| Customer Dictionaries | Algorithm | — | <1ms | Hash-set lookup against consumer-provided value lists |
| Cloud DLP | Cloud API | — | 50-200ms | Google Cloud DLP inspect_content with 150+ InfoTypes |
| PII Base (NER) | Local model | ~500M | 10-30ms | PII-specialized named entity recognition — 81% F1 |
| GLiNER2 (intent/zones) | Local model | 205M | 10-30ms | Text classification + structured extraction for intent & zones |
| EmbeddingGemma | Local model | 308M | 5-20ms | Semantic similarity via dense vector embeddings |
| NLI / BART-MNLI | Local model | 400M | 10-30ms | Natural language inference (entailment-based classification) |
| SLM / Gemma | Local model | 3-4B | 50-200ms | Chain-of-thought reasoning with structured prompts |
| LLM API | Cloud API | — | 200-2000ms | Full reasoning via Gemini Flash / Claude Haiku / GPT-4o-mini |

**Dual model strategy:** PII Base and GLiNER2 are both loaded by default in Standard+ profiles. PII Base handles content NER (highest accuracy for entity detection). GLiNER2 handles intent classification and zone extraction (multi-task capability). Combined ~700MB. All local models load lazily (first invocation) and are managed by the shared Model Registry.

---

## Structural Content Classifier

**Type:** ML-trained model (XGBoost/LightGBM) exported as decision rules, with heuristic fallback

Classifies text blocks into 7 categories: `source_code`, `configuration`, `query`, `log_output`, `cli_command`, `markup`, `natural_language`. Language-agnostic — doesn't identify Python vs Java, identifies code vs not-code.

**How it works:** Extracts 40 engineered features from the text (character distribution, line-level patterns, keyword density, structural signals, parse success, word-level metrics). Feeds features to a trained gradient-boosted tree model. The model is exported as pure Python decision rules (<200KB) — no ML runtime dependency in production.

**Key features that drive classification:**
- Syntactic density (special chars / total chars) — code: 0.08-0.25, prose: 0.02-0.05
- Semicolon line-end ratio — C-family: 0.7+, prose: ~0
- Code keyword line-start ratio (import, def, class, function, etc.) — strongest universal signal
- Structural brace patterns (at line boundaries vs inline)
- Function-call density (identifier before parenthesis)
- Parse success (JSON, XML, env format)
- CamelCase and snake_case word density

**Why ML not hand-tuned rules:** 40 features × 7 classes with complex interactions (e.g., "high braces AND high semicolons" = C-family, "high braces BUT no semicolons" = Go). ML finds optimal decision boundaries from training data. Hand-tuning weights across this space is impractical.

**Training:** Offline ML pipeline trains on GitHub code corpus (20+ languages), config files, SQL datasets, LogHub logs, CLI examples, and prose corpora. Synthetic mixed-content prompts provide boundary-labeled data. See doc 09 for full pipeline spec.

**Pipeline scope:** All modes. First engine to run — its output informs the Structured Secret Scanner and Boundary Detector.

---

## Boundary Detector

**Type:** ML-trained via sliding window, with heuristic fallback

Identifies where content type transitions occur within mixed text. A prompt containing "Fix this error:\n\nimport boto3..." has a boundary between line 1 (natural language) and line 3 (source code).

**How it works:** Runs the Structural Content Classifier on overlapping 5-line windows. When the classification changes between adjacent windows, that's a boundary. Produces boundary positions with confidence scores.

**Heuristic fallback:** Before ML model is trained, detects boundaries via code fences (triple backticks), explicit delimiters (---), empty lines with structural shifts, and typographic conventions (colon + newline).

**Pipeline scope:** All modes, but primarily valuable for unstructured and prompt modes where mixed content is common.

---

## Structured Secret Scanner

**Type:** Deterministic algorithm — parsers + key-name dictionary + Shannon entropy scoring

Detects secrets embedded in structured content by exploiting key-value structure. A high-entropy string in a JSON value keyed as `api_key` is almost certainly a credential — even without a known-format regex match.

**How it works in 4 steps:**

1. **Parse** — Attempt to parse text into a known structure (JSON, YAML, XML, env, SQL, CLI arguments, HTTP headers, code string literals)
2. **Extract** — Pull out all key-value pairs. For code: extract `variable_name = "string_literal"` patterns across any language
3. **Score** — For each pair, compute: key-name score (curated dictionary of secret-indicating names, 0.0-0.95) × value score (Shannon entropy + character-class analysis + length + known format matching) × structure-type boost
4. **Filter** — Apply anti-indicators ("example", "test", "placeholder", known example values like AKIAIOSFODNN7EXAMPLE) to reduce false positives

**What this catches that regex misses:**
- `"api_key": "8f14e45f..."` — no known prefix, but key name + high entropy = secret
- `DB_PASSWORD=kJ#9xMp$2wLq!` — no standard format, but key name = definitive
- `IDENTIFIED BY 'Pr0dP@ss!'` — SQL grammar position = credential
- `docker login -p SuperSecret` — CLI argument position = credential

**Pipeline scope:** All modes. Runs on content identified as structured by the Structural Classifier.

---

## Regex Patterns

**Type:** Deterministic algorithm, no model. Google RE2 engine (C++ backend, linear-time guarantee).

Pattern matching against 50+ curated regular expressions with format validation. Uses RE2 set matching — all patterns matched in a single pass over the text, not 50 separate scans.

**Implementation: Two-Phase RE2**

Phase 1 (screening): All 50+ patterns compiled into a single RE2 Set. One pass over the input identifies WHICH patterns matched. C++ execution, releases GIL, linear-time guaranteed.

Phase 2 (extraction): Only matched patterns (typically 1-3, not 50) run individually to extract positions and values. Secondary validators (Luhn checksum, format checks) applied per match.

```python
# Architecture (see full implementation in classification-library-spec.md)
class RegexEngine:
    def __init__(self, patterns):
        self.pattern_set = re2.Set()       # compiled set for screening
        self.compiled = {}                  # individual patterns for extraction
        self.validators = {}               # secondary validation functions
    
    def scan(self, text) -> list[Match]:
        hit_indices = self.pattern_set.Match(text)  # ONE pass, C++
        # extract positions only for matched patterns
        # run validators (Luhn, format checks)
        return matches
```

**Why RE2 over Python `re`:**
- **Security:** Linear-time guarantee — no catastrophic backtracking. Python `re` uses backtracking, vulnerable to ReDoS (Regular Expression Denial of Service). Critical for prompt gateways accepting arbitrary user input.
- **Performance:** Set matching scans text once for all 50+ patterns (C++, ~0.3ms for 10KB). Python `re` scans 50 times (~2ms, Python overhead per call).
- **Concurrency:** RE2 matching runs in C++, releases Python GIL. Enables true multi-threaded parallelism.
- **Dependency:** `pip install google-re2` (~5MB). No external system libraries needed.

**Capabilities:**
- Detects formatted PII: SSN (XXX-XX-XXXX), credit card numbers (with Luhn), phone numbers, email addresses
- Detects credentials: AWS access keys (AKIA prefix + length), JWT tokens (three base64 segments), private keys (PEM headers), connection strings
- Detects formatted identifiers: IP addresses, MAC addresses, IBANs, passport numbers
- Returns character-level spans (start, end) for redaction

**Secondary validators (post-match):**

| Pattern | Validator | Purpose |
|---------|-----------|---------|
| Credit card | Luhn checksum | Reject numbers that match format but fail checksum |
| US SSN | No all-zeros groups | Reject 000-XX-XXXX, XXX-00-XXXX, XXX-XX-0000 |
| IPv4 | Octet range check | Reject 999.999.999.999 |
| AWS key | Length + charset | Exactly 20 chars, uppercase alphanumeric after AKIA |

**Shipped:** 50+ patterns covering PII, PHI, PCI, and credential categories.

**Consumer extensible:** Yes — consumers inject additional regex patterns at initialization. Custom patterns are compiled into the RE2 set alongside built-in patterns.

**Future option (if regex becomes throughput bottleneck):** Intel Hyperscan compiles all patterns into a SIMD-accelerated DFA, matching in ~0.05ms. Only needed at >10K requests/second. Requires `libhyperscan` system library.

---

## Column Name Semantics

**Type:** Deterministic algorithm, no model

Fuzzy matching of database column names against a curated taxonomy of 400+ sensitive field name variants. Uses normalized string comparison: lowercased, stripped of underscores/hyphens/spaces, common abbreviation expansion (dob → date_of_birth, ssn → social_security_number).

**Capabilities:**
- Classifies columns by name alone, without examining data
- Handles common abbreviations and naming conventions across languages and frameworks
- Supports multi-token matching: "customer_social_security_num" → SSN
- Returns the matched taxonomy category with confidence based on match quality

**Limitations:**
- Only works for structured data with meaningful column names
- Fails on generic names ("field1", "col_a", "value")
- Cannot detect renamed or obfuscated columns

**Shipped:** 400+ variants across PII, PHI, PCI categories (10+ variants per sensitive type).

**Consumer extensible:** Yes — consumers add custom column name mappings.

**Pipeline scope:** Structured pipeline only.

---

## Heuristic Statistics

**Type:** Deterministic algorithm, no model

Statistical analysis of column sample values to infer data type characteristics. Examines cardinality, value length distribution, character class ratios, entropy, and pattern consistency.

**Capabilities:**
- High-cardinality short strings → likely identifiers (SSN, account number)
- Low-cardinality strings → likely categorical (gender, department, status)
- Consistent length + mixed alphanumeric → likely formatted ID
- High entropy → likely passwords, hashes, or encrypted data
- Date-like distributions → likely date fields

**Limitations:**
- Requires sample values (at least 10-20 for meaningful statistics)
- Statistical signals are suggestive, not definitive — best used to boost or lower confidence from other engines

**Pipeline scope:** Structured pipeline only (requires columnar statistics).

---

## Customer Dictionaries

**Type:** Deterministic algorithm, no model

Hash-set lookup against consumer-provided value lists. Supports exact match, case-insensitive match, and prefix match modes.

**Capabilities:**
- Organization-specific sensitive terms (project codenames, drug names, disease codes)
- Known entity lists (employee names, customer IDs, vendor codes)
- Industry-specific vocabularies (ICD codes, drug names, financial instruments)

**Limitations:**
- Only detects exact values in the dictionary — no fuzzy matching
- Dictionary quality and completeness determines effectiveness
- Dictionary content is itself sensitive — never stored by the library

**Consumer extensible:** This engine exists entirely for consumer customization. The library ships no dictionaries — consumers load them from their own secure storage.

**Pipeline scope:** All pipelines (structured, unstructured, prompt).

---

## Cloud DLP

**Type:** Cloud API (Google Cloud DLP)

Google Cloud DLP's inspect_content API with 150+ built-in InfoTypes. Context-aware detection that uses surrounding text to improve accuracy.

**Capabilities:**
- 150+ built-in InfoTypes covering global PII, PHI, financial data
- Context-aware: uses surrounding text to distinguish SSN from product code
- Likelihood scoring (VERY_UNLIKELY to VERY_LIKELY)
- Locale-aware: country-specific ID formats
- Supports custom InfoTypes via consumer configuration

**Limitations:**
- Requires API call — adds 50-200ms latency
- API cost per call (though minimal per-text)
- Requires GCP credentials and network access
- Not available in air-gapped environments

**Consumer extensible:** Yes — custom InfoTypes via DLP API configuration.

**Pipeline scope:** All pipelines. In the prompt pipeline, DLP is focused on pasted_content and data_block zones to reduce API cost and noise.

---

## GLiNER2

**Type:** Local transformer model, 205M parameters

A unified multi-task framework (EMNLP 2025) that performs named entity recognition, text classification, and hierarchical structured data extraction within a single model through a schema-driven interface. CPU-optimized, pip-installable (`pip install gliner2`).

**Capabilities — three tasks in one model:**

**NER (Named Entity Recognition):**
- Zero-shot entity detection against arbitrary natural-language labels
- Returns character-level spans with confidence scores
- 60+ shipped labels covering PII, PHI, PCI, credentials
- Consumer-extensible: add custom entity types ("internal project name", "vendor code") without retraining
- Fine-tunable on customer-specific labeled data

**Text Classification:**
- Zero-shot classification against arbitrary natural-language category descriptions
- Returns category label with confidence score
- Used by the prompt pipeline for intent classification

**Structured Extraction:**
- Extract typed fields from text via a JSON schema definition
- Returns structured data matching the schema
- Used by the prompt pipeline for zone segmentation

**Multi-task composition:** All three tasks can execute in a single forward pass when provided together, sharing contextual understanding across tasks.

**Model variants:**

| Model | Size | Strength |
|-------|------|----------|
| GLiNER2 (default) | 205M | Unified NER + classification + extraction |
| `knowledgator/gliner-pii-base-v1.0` | ~500M | Higher PII-specific accuracy (81% F1) |
| `knowledgator/gliner-pii-edge-v1.0` | Smaller | Resource-constrained environments |

**Pipeline scope:** All pipelines. NER for content detection (all pipelines), classification for intent (prompt pipeline), extraction for zones (prompt pipeline).

**Reference:** Zaratiana et al., "GLiNER2: Schema-Driven Multi-Task Learning for Structured Information Extraction," EMNLP 2025.

---

## EmbeddingGemma

**Type:** Local embedding model, 308M parameters

Google's embedding model that maps text to dense vector representations where semantic similarity corresponds to geometric proximity. Supports 100+ languages and Matryoshka dimension selection (256/512/768 dimensions) for speed-accuracy tradeoffs.

**Capabilities:**
- Semantic similarity matching: "remuneration" close to "salary" in embedding space
- Topic sensitivity detection: embed text against pre-computed reference taxonomy
- Intent similarity: embed prompt instruction against intent reference vectors
- Configurable dimensions via Matryoshka representations

**How it works in classification:**
- **Content:** Text or column name embedded and compared via cosine similarity against a pre-computed taxonomy of 80+ sensitive categories. Catches semantic sensitivity that regex and keyword matching miss.
- **Intent:** Prompt instruction zone embedded and compared against pre-computed intent reference vectors (5-10 example phrasings per intent). Catches semantic intent that keywords miss: "polish this for the board" → high similarity to document_rewrite.

**Limitations:**
- Semantic similarity is fuzzy — "salary" near "money" near "payment" creates false positive chains
- Requires threshold tuning per deployment
- Pre-computed reference vectors need maintenance as categories evolve

**Shipped:** 80+ pre-computed taxonomy categories, 10 intent reference vector sets.

**Pipeline scope:** All pipelines. Content sensitivity (all), intent similarity (prompt pipeline).

**Reference:** Google, EmbeddingGemma (2025). Apache 2.0.

---

## NLI / BART-MNLI

**Type:** Local NLI model, ~400M parameters

Natural Language Inference model that evaluates whether a premise entails, contradicts, or is neutral to a hypothesis. Used for zero-shot classification by framing intent labels as hypotheses: "Does this prompt entail: the user wants to perform document editing?"

**Capabilities:**
- Zero-shot text classification against arbitrary natural-language labels
- Architecturally distinct from GLiNER2 (entailment vs. span-matching) — provides ensemble robustness
- No training data needed for new labels
- Cross-verification when GLiNER2 intent confidence is below threshold

**How it works:**
For each candidate intent label, construct hypothesis: "The user wants to perform {intent_description}." Score entailment probability. Highest-scoring label is the classified intent.

**Limitations:**
- Slower than GLiNER2 for classification (~10-30ms vs ~10-20ms)
- Less effective for entity detection (not its purpose)
- Hypothesis template design affects accuracy

**Pipeline scope:** Prompt pipeline only (intent cross-verification).

**Reference:** Yin et al., "Benchmarking Zero-shot Text Classification: Datasets, Evaluation and Entailment Approach," EMNLP 2019. Model: `facebook/bart-large-mnli`.

---

## SLM / Gemma

**Type:** Local small language model, 3-4B parameters (quantized to ~2GB)

Google Gemma 3 4B-IT or Gemma 4 E4B MoE for reasoning tasks that require contextual understanding beyond pattern matching or embedding similarity. Runs quantized (4-bit GGUF) on CPU.

**Capabilities:**
- Chain-of-thought reasoning about ambiguous content
- Structured prompt → structured JSON output
- Context-aware classification using surrounding information
- Explanation generation for auditability

**How it works in each context:**
- **Content:** Reasons about whether ambiguous text contains sensitive data, considering context
- **Intent:** Structured reasoning: "What is the user asking the LLM to do? What kind of content did they paste?"
- **Zones:** Reasons about structural boundaries when heuristics and GLiNER2 disagree

**Model strategy:**
- Default: Gemma 3 4B-IT (beats Gemma 2 27B on benchmarks)
- Advanced: Gemma 4 E4B MoE (higher accuracy, similar resource footprint)
- Budget: Gemma 3 1B-IT (smaller, less accurate)
- All Apache 2.0 licensed. Model interfaces abstracted for swappability.

**Limitations:**
- Slowest local engine (50-200ms)
- Highest memory footprint (~2GB quantized)
- Output parsing required (may produce malformed JSON)

**Pipeline scope:** All pipelines (content reasoning, intent reasoning, zone reasoning).

**Fine-tuning:** Supports LoRA/QLoRA fine-tuning on customer-specific data. Fine-tuned SLM is the primary accuracy improvement lever — a customer-tuned 4B model often outperforms a general-purpose LLM on that customer's data.

---

## LLM API

**Type:** Cloud API (Gemini Flash / Claude Haiku / GPT-4o-mini)

Full LLM reasoning as a last resort when all local engines fail to classify. Only fires when budget permits and nothing has been found by cheaper engines.

**Capabilities:**
- Highest accuracy on genuinely novel or ambiguous content
- Can reason about complex, multi-signal scenarios
- Supports arbitrary prompt engineering per consumer

**Limitations:**
- Slowest engine (200-2000ms)
- API cost per call
- Requires network access
- Privacy concern: data leaves the organization's perimeter

**Pipeline scope:** All pipelines (fallback only). In practice, <5% of inputs reach this tier.

---

## Engine Comparison Matrix

| Engine | Content Detection | Secret Detection | Intent Classification | Zone / Boundary | Structured Data | Unstructured Text | Needs API | Needs GPU |
|--------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **Structural Classifier** | — | enables targeted scanning | — | ✅ boundary detection | ✅ | ✅ | — | — |
| **Structured Secret Scanner** | — | ✅ key-name + entropy | — | — | ✅ | ✅ | — | — |
| Regex | ✅ PII formats | ✅ known-format secrets | — | — | ✅ | ✅ | — | — |
| Column Name | ✅ | — | — | — | ✅ | — | — | — |
| Heuristics | ✅ | — | — | — | ✅ | — | — | — |
| Financial Density | ✅ topic | — | — | — | ✅ | ✅ | — | — |
| Dictionaries | ✅ | ✅ consumer patterns | — | — | ✅ | ✅ | — | — |
| Cloud DLP | ✅ | ✅ | — | — | ✅ | ✅ | ✅ | — |
| PII Base NER | ✅ entities | — | — | — | partial | ✅ | — | — |
| GLiNER2 | — | — | ✅ classify | ✅ extract | — | ✅ | — | — |
| EmbeddingGemma | ✅ topic sensitivity | — | ✅ similarity | — | ✅ | ✅ | — | — |
| NLI / BART-MNLI | — | — | ✅ entailment | — | — | ✅ | — | — |
| SLM / Gemma | ✅ reasoning | ✅ "real vs example?" | ✅ reasoning | ✅ reasoning | ✅ | ✅ | — | optional |
| LLM API | ✅ reasoning | ✅ reasoning | ✅ reasoning | ✅ reasoning | ✅ | ✅ | ✅ | — |
