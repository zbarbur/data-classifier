# Structural Detection & Secret Scanning — Design Spec

**Version:** 1.0  
**Date:** April 2026  
**Status:** Design

---

## Overview

This document specifies three new engines for the classification library and the offline ML training pipeline that produces their models.

**New runtime engines (within classification library):**
1. **Structural Content Classifier** — identifies code, config, query, log, CLI, markup vs. natural language
2. **Boundary Detector** — finds transition points where content type changes within a prompt
3. **Structured Secret Scanner** — parses structured content, extracts key-value pairs, scores secrets via key-name + entropy analysis

**Offline tool (separate from runtime):**
4. **ML Training Pipeline** — collects labeled data, trains classifiers, exports decision rules consumed by runtime engines

The engines run in the classification library's Fast tier (<10ms combined). The training pipeline runs offline, periodically, and produces compact artifacts (<200KB) that engines import.

```
┌─ RUNTIME ────────────────────────────────────┐    ┌─ OFFLINE ─────────────────────┐
│                                               │    │                               │
│  Classification Library                       │    │  ML Training Pipeline          │
│  ├── Structural Classifier Engine  ◄──────────│────│── trained_structural.rules     │
│  ├── Boundary Detector Engine      ◄──────────│────│── trained_boundary.rules       │
│  ├── Structured Secret Scanner     ◄──────────│────│── key_name_weights.json        │
│  ├── Regex Engine                             │    │                               │
│  ├── PII NER Engine                           │    │  Inputs:                       │
│  ├── EmbeddingGemma Engine                    │    │  ├── GitHub code corpus         │
│  └── ...                                      │    │  ├── Config file corpus         │
│       │                                       │    │  ├── Event store (runtime data) │
│       │ emits classification events            │    │  └── Labeled edge cases         │
│       ▼                                       │    │                               │
│  Event Store (consumer-owned) ────────────────│───►│  Periodic retrain              │
│                                               │    │                               │
└───────────────────────────────────────────────┘    └───────────────────────────────┘
```

---

## Part 1: Structural Content Classifier

### Problem

Detecting code, configuration, queries, logs, and CLI commands within prompt text. This is not about identifying the programming language — it's about identifying that content is **machine-readable** (not natural language) so that appropriate scanning strategies can be applied.

### Why Character Signals Alone Aren't Enough

Individual characters are ambiguous:

| Character | Code Meaning | Prose Meaning |
|-----------|-------------|---------------|
| `;` | Statement terminator (C-family, CSS, SQL) | Clause separator ("Revenue rose; margins fell") |
| `{ }` | Block delimiters, object literals | Rare — academic references "{see Table 3}" |
| `( )` | Function calls, grouping | Parenthetical asides "(founded in 2015)" |
| `:` | Python blocks, YAML keys, ternary | Greetings, labels, time ("Dear team:", "3:45 PM") |
| `< >` | HTML tags, generics, templates | Comparisons, less common in prose |
| `=` | Assignment | Rare in prose (equations) |
| `#` | Comments (Python, Shell, YAML) | Section numbers, hashtags |

**No single character reliably distinguishes code from prose.** The signal is in the combination and distribution across lines. This is inherently a classification problem — which is why an ML model learning the optimal feature weights outperforms hand-tuned heuristics.

### Features (40 engineered features)

**Character distribution features (12):**

| Feature | What It Measures |
|---------|-----------------|
| `syntactic_density` | Ratio of `{}[]();=<>\|&!@#$^*/\\~` to total chars |
| `brace_density` | `{ }` per character |
| `paren_density` | `( )` per character |
| `angle_density` | `< >` per character |
| `semicolon_density` | `;` per character |
| `quote_density` | `"`, `'`, backtick per character |
| `equals_density` | `=` per character |
| `colon_density` | `:` per character |
| `comma_density` | `,` per character |
| `hash_density` | `#` per character |
| `slash_density` | `/` `\\` per character |
| `dot_density` | `.` per character |

**Line-level pattern features (4):**

| Feature | What It Measures |
|---------|-----------------|
| `semicolon_line_end_ratio` | Lines ending with `;` / total lines |
| `brace_line_end_ratio` | Lines ending with `{` / total lines |
| `brace_line_start_ratio` | Lines starting with `}` / total lines |
| `colon_line_end_ratio` | Lines ending with `:` / total lines |

**Keyword features (4):**

| Feature | What It Measures |
|---------|-----------------|
| `code_keyword_ratio` | Lines starting with `import`, `def`, `class`, `function`, `func`, `var`, `let`, `const`, `public`, `private`, `return`, `if`, `else`, `for`, `while`, `try`, `catch`, `struct`, `interface`, `enum`, `package`, `module`, `use`, `using`, `include` / total lines |
| `sql_keyword_ratio` | Lines starting with `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER`, `DROP`, `GRANT`, `FROM`, `WHERE`, `JOIN` / total lines |
| `cli_command_ratio` | Lines starting with `curl`, `docker`, `kubectl`, `ssh`, `git`, `npm`, `pip`, `brew`, `apt`, `wget`, `chmod`, `export` / total lines |
| `log_pattern_ratio` | Lines matching timestamp prefix or `[ERROR]`, `[WARN]`, `[INFO]`, `[DEBUG]` / total lines |

**Structural features (8):**

| Feature | What It Measures |
|---------|-----------------|
| `func_call_ratio` | `identifier(` patterns / total `(` occurrences |
| `indent_consistency` | Standard deviation of leading spaces (low = consistent = code) |
| `avg_indent_depth` | Average leading spaces per line |
| `line_length_variance` | Standard deviation of line lengths |
| `avg_line_length` | Mean line length |
| `empty_line_ratio` | Double-newlines / total newlines |
| `assignment_ratio` | `identifier = value` patterns per line |
| `key_value_ratio` | `key: value` or `key=value` patterns per line |

**Parse success features (3):**

| Feature | What It Measures |
|---------|-----------------|
| `json_parseable` | 1 if `json.loads()` succeeds, 0 otherwise |
| `xml_parseable` | 1 if XML parser succeeds, 0 otherwise |
| `env_parseable` | 1 if 80%+ of lines match `KEY=VALUE`, 0 otherwise |

**Word-level features (5):**

| Feature | What It Measures |
|---------|-----------------|
| `alpha_ratio` | Letters / total characters |
| `digit_ratio` | Digits / total characters |
| `upper_ratio` | Uppercase / total characters |
| `camelcase_density` | camelCase words / total words |
| `underscore_word_density` | snake_case words / total words |

**String literal features (4):**

| Feature | What It Measures |
|---------|-----------------|
| `string_literal_density` | Quoted strings per line |
| `string_content_ratio` | Characters inside quotes / total characters |
| `avg_string_length` | Mean length of quoted strings |
| `string_entropy_mean` | Mean Shannon entropy of string literal contents |

**Total: 40 features. All computable in <1ms.**

### Model

**Architecture:** Gradient-boosted decision tree — winner selected from benchmarking multiple candidates.

**Why trees, not neural nets:** Features are already engineered. There's strong empirical evidence (Grinsztajn et al., "Why do tree-based models still outperform deep learning on tabular data?", NeurIPS 2022) that tree-based methods beat neural networks on tabular data with fewer than ~1000 features. Trees handle feature interactions naturally (e.g., "high brace density AND high semicolon line-end ratio" → C-family code). They're interpretable via feature importance. Inference is microseconds. No GPU needed.

**Model selection via benchmarking:** We don't hardcode XGBoost. We train four candidates and pick the winner on held-out data:

| Candidate | Strengths | Typical Performance |
|-----------|-----------|-------------------|
| XGBoost | Mature, well-documented, exact greedy splitting | Strong baseline for most tabular tasks |
| LightGBM | Faster training (histogram-based), handles categoricals natively | Often matches or beats XGBoost, faster |
| CatBoost | Best overfitting detection, handles categoricals well | Slightly slower inference, larger model files |
| Random Forest | Simple, no HP sensitivity, hard to overfit | Slightly less accurate than boosted methods |

All four train in under a minute on CPU for our dataset size (~200K samples, 40 features). The training pipeline runs all four with Optuna hyperparameter search (50 trials each, Bayesian optimization), evaluates on 5-fold cross-validation, and selects the highest weighted F1. The winner gets exported.

**ML framework stack:**

```
scikit-learn     — Pipeline, cross-validation, metrics, preprocessing
xgboost          — Candidate model 1
lightgbm         — Candidate model 2
catboost          — Candidate model 3 (Random Forest via scikit-learn)
optuna           — Bayesian hyperparameter optimization
pandas / numpy   — Data loading, feature arrays
```

No PyTorch, no TensorFlow — we're training tree models on 40 features, not neural networks on raw data. scikit-learn's `Pipeline`, `StratifiedKFold`, `cross_val_score`, and `classification_report` provide everything we need.

Experiment tracking via structured JSON logs (model name, params, metrics, feature importance). MLflow can be added later if regular retraining cycles justify the infrastructure.

**Classes (7):**

| Class | Description | Key Distinguishing Features |
|-------|-------------|---------------------------|
| `source_code` | Programming language source | keyword_ratio, func_call_ratio, indent_consistency |
| `configuration` | Config files (env, YAML, TOML, INI) | key_value_ratio, env_parseable, assignment_ratio |
| `query` | SQL, GraphQL, Cypher | sql_keyword_ratio |
| `log_output` | Application logs, stack traces | log_pattern_ratio, line structure consistency |
| `cli_command` | Shell commands, scripts | cli_command_ratio, flag patterns |
| `markup` | HTML, XML, JSX, templates | angle_density, xml_parseable |
| `natural_language` | Prose, instructions, questions | high alpha_ratio, low syntactic_density |

**Output:** Class label + confidence score. Confidence enables fallback: if confidence < 0.6, treat as natural language (conservative default).

**Model size:** <200KB as exported tree ensemble. Can be converted to pure decision rules (Python if/else) for zero-dependency deployment.

**Beyond tree models:** Doc 10 (`10-ml-architecture-exploration.md`) explores neural alternatives: CNN for local pattern discovery, RNN for sequential state tracking, Attention for cross-region relationships, and SSM/Mamba for efficient boundary detection. The exploration includes pre-trained model evaluation (ModernBERT, StarEncoder), distillation strategies, and a phased architecture search. Tree models ship first (Phase 1); neural alternatives are Phase 2-4 research.

### Language Coverage

The model is explicitly **language-agnostic** for code detection. It doesn't identify Python vs. Java — it identifies code vs. not-code. The features that distinguish code from prose work across all language families:

| Language Family | Primary Signals |
|----------------|----------------|
| C-family (Java, C, C++, C#, Go, Rust, Swift, Kotlin) | semicolon_line_end, brace structure, keyword_ratio |
| Python | keyword_ratio, indent_consistency, colon_line_end |
| JavaScript/TypeScript | keyword_ratio, brace structure, func_call_ratio |
| Ruby, Perl | keyword_ratio, syntactic_density |
| Functional (Haskell, Elixir, Clojure) | keyword_ratio, paren_density (Clojure), indent_consistency |
| Shell/Bash | cli_command_ratio, assignment_ratio |
| SQL | sql_keyword_ratio (very distinctive vocabulary) |
| CSS | semicolon_line_end, brace structure, colon_density |
| YAML/TOML/INI | key_value_ratio, indent_consistency, colon_density |

Python is the hardest language to detect by character signals (low syntactic density, no braces, no semicolons). The model relies on keyword density + indentation consistency — which are Python's distinctive structural properties.

---

## Part 2: Boundary Detector

### Problem

A prompt typically contains multiple content types. The boundary detector identifies transition points where content type changes:

```
"Fix this error in my Python code:\n\nimport boto3\nclient = boto3.client..."
                                    ↑
                              BOUNDARY: natural_language → source_code
```

### Approach: Sliding Window Classification

Run the structural classifier on overlapping windows. When the classification changes between adjacent windows, that's a boundary.

```python
def detect_boundaries(text: str, window_lines: int = 5) -> list[Boundary]:
    lines = text.split('\n')
    boundaries = []
    prev_class = None
    prev_confidence = 0.0
    
    for i in range(len(lines)):
        # 5-line window centered on line i
        window = lines[max(0, i - 2) : min(len(lines), i + 3)]
        window_text = '\n'.join(window)
        
        features = extract_features(window_text)
        classification, confidence = structural_model.predict(features)
        
        if prev_class and classification != prev_class:
            # Boundary detected — record the transition
            boundary_confidence = min(prev_confidence, confidence)
            boundaries.append(Boundary(
                line=i,
                from_type=prev_class,
                to_type=classification,
                confidence=boundary_confidence
            ))
        
        prev_class = classification
        prev_confidence = confidence
    
    return boundaries
```

**Cost:** For a 100-line prompt: 100 windows × 40 features × tree prediction = ~1-2ms total.

### Boundary-Specific Features

In addition to the block-level features, the boundary detector uses **contrast features** between adjacent windows:

| Feature | What It Measures |
|---------|-----------------|
| `syntactic_density_delta` | Change in syntactic density between windows |
| `alpha_ratio_delta` | Change in letter ratio (prose→code = decrease) |
| `avg_line_length_delta` | Change in average line length |
| `indent_depth_delta` | Change in indentation level |
| `keyword_ratio_delta` | Change in code keyword density |

Sharp deltas indicate boundaries. A gradual drift indicates mixed content.

### Fallback: Heuristic Boundaries

Before the ML model is trained, or when the model's confidence is low, fall back to heuristic boundary detection:

- **Code fence markers:** Triple backticks with optional language tag
- **Explicit labels:** Lines ending with ":" followed by structurally different content
- **Empty line + structural shift:** Blank line where the content type changes
- **Delimiter lines:** `---`, `===`, `***` used as section separators

These heuristics are the **Stage 1 implementation** before ML is available.

---

## Part 3: Structured Secret Scanner

### Problem

Detect secrets embedded in structured content by exploiting the key-value structure. A high-entropy string in a JSON value position keyed as `api_key` is almost certainly a credential. The same string in free prose is ambiguous.

### Approach: Parse → Extract → Score

```
Input text (from Structural Classifier: "configuration" or "source_code")
    │
    ▼
Step 1: Parse into known structure
    JSON, YAML, XML, env, SQL, CLI, HTTP headers
    │
    ▼
Step 2: Extract key-value pairs
    (key_name, value_string) tuples
    For code: extract (variable_name, string_literal) tuples
    │
    ▼
Step 3: Score each pair
    Key-name score × Value entropy score × Structure-type boost
    │
    ▼
Step 4: Output findings with confidence
```

### Structure Parsers

Each parsable format has a dedicated extractor:

| Format | Parser | Key-Value Extraction |
|--------|--------|---------------------|
| JSON | `json.loads()` | Recursive key-value from all nested objects |
| YAML | `yaml.safe_load()` | Recursive key-value from all nested mappings |
| XML | `xml.etree.ElementTree` | Element names → attribute values, text content |
| env / INI | Line-by-line `KEY=VALUE` | Direct extraction |
| SQL | Regex for `IDENTIFIED BY`, `PASSWORD =`, `CREATE USER` | Positional extraction |
| CLI | Argument parsing for `curl -H`, `docker -p`, `ssh -i` | Flag-value extraction |
| HTTP headers | `Header-Name: value` per line | Direct extraction |
| Source code (any language) | Regex: `identifier = "string"` patterns | Variable name + string literal |

### Key-Name Scoring

Curated dictionary with weighted tiers. No ML needed — the vocabulary of secret-carrying key names is well-known and finite:

```python
SECRET_KEY_SCORES = {
    # Definitive (0.90-0.95)
    0.95: {"password", "passwd", "pwd", "secret_key", "private_key",
           "secret_access_key", "client_secret", "signing_key",
           "encryption_key", "master_key"},
    0.90: {"api_key", "apikey", "access_key", "auth_token",
           "access_token", "refresh_token", "bearer_token",
           "api_secret", "app_secret", "webhook_secret"},
    
    # Strong (0.70-0.85)
    0.85: {"token", "credential", "authorization"},
    0.80: {"secret", "private", "signing"},
    0.70: {"connection_string", "database_url", "redis_url",
           "mongodb_uri", "dsn", "jdbc", "sqlalchemy"},
    
    # Moderate (0.40-0.60)
    0.50: {"key", "cert", "certificate", "ssh"},
    0.40: {"auth", "session", "cookie"},
    
    # Infrastructure (not secrets, but sensitive)
    0.30: {"host", "hostname", "endpoint", "server", "ip"},
    0.20: {"url", "uri", "port", "database", "db_name"},
}

ANTI_INDICATORS = {
    -0.30: {"example", "sample", "test", "dummy", "placeholder",
            "fake", "mock", "demo", "default", "template"},
    -0.50: {"EXAMPLE", "CHANGEME", "YOUR_KEY_HERE", "xxx",
            "TODO", "REPLACE", "FIXME", "INSERT"},
}
```

Matching is fuzzy: `DB_PASSWORD` matches "password", `stripe_secret_key` matches "secret_key". Case-insensitive. Underscores/hyphens normalized.

### Value Entropy Scoring

Shannon entropy measures randomness. Combined with length and character-class analysis:

```python
def score_value(value: str) -> float:
    if len(value) < 8:
        return 0.1  # too short for a meaningful secret
    
    # Known format match (highest confidence, overrides entropy)
    if matches_known_format(value):  # AKIA, JWT, PEM, connection string
        return 0.95
    
    # Exclude known non-secret high-entropy patterns
    if is_uuid_v4(value):       return 0.05
    if is_md5_hex(value):       return 0.15
    if is_sha256_hex(value):    return 0.15
    if is_base64_image(value):  return 0.0
    if is_semver(value):        return 0.0
    
    entropy = shannon_entropy(value)
    char_classes = count_char_classes(value)  # lowercase, uppercase, digits, special
    length = len(value)
    
    # Entropy + length thresholds
    if entropy > 4.5 and length > 16:   return 0.85
    if entropy > 4.0 and length > 24:   return 0.70
    if entropy > 3.5 and length > 32:   return 0.55
    
    # Password-like: mixed character classes, moderate length
    if char_classes >= 3 and length >= 8 and length <= 64:
        return 0.60
    
    return 0.10
```

### Combined Scoring

The combination weights below are initial hand-tuned values. They are optimized offline via ML training (see "Secret Scoring Parameter Optimization" in Part 4). The runtime code stays deterministic — only the parameter values are updated.

```python
def combined_secret_score(key: str, value: str, structure_type: str) -> float:
    key_score = score_key_name(key)
    value_score = score_value(value)
    
    # Check anti-indicators in key AND surrounding context
    anti_score = check_anti_indicators(key, value)
    
    # Structure type boost
    structure_boost = {
        "env": 0.10,        # everything in .env is configuration
        "docker_compose": 0.10,
        "kubernetes": 0.10,
        "terraform": 0.10,
        "json_config": 0.05,
        "yaml_config": 0.05,
        "source_code": 0.0,
        "http_headers": 0.05,
    }.get(structure_type, 0.0)
    
    # Combination logic:
    # If key strongly indicates secret → value entropy is confirmation
    # If key is generic → rely primarily on value analysis
    # If anti-indicators present → reduce confidence
    
    if key_score >= 0.7:
        # Key says "this is a secret" — value entropy confirms
        combined = key_score * 0.6 + value_score * 0.3 + structure_boost
    elif key_score >= 0.3:
        # Key is suggestive — need stronger value signal
        combined = key_score * 0.3 + value_score * 0.6 + structure_boost
    else:
        # Generic key — almost entirely value-driven
        combined = key_score * 0.1 + value_score * 0.8 + structure_boost
    
    # Apply anti-indicators
    combined += anti_score  # negative values reduce score
    
    return max(0.0, min(1.0, combined))
```

### What This Catches That Regex Misses

| Scenario | Regex | Structured Scanner |
|----------|:-----:|:-----------------:|
| `"api_key": "8f14e45f..."` (no known prefix) | ❌ | ✅ key name + entropy |
| `DB_PASSWORD=kJ#9xMp$2wLq!` (no standard format) | ❌ | ✅ key name + password complexity |
| `IDENTIFIED BY 'Pr0dP@ss!'` (SQL) | ❌ | ✅ SQL grammar position |
| `docker login -p SuperSecret` (CLI) | ❌ | ✅ CLI argument position |
| `{"x": "8f14e45f..."}` (obfuscated key) | ❌ | ⚠️ entropy only (moderate confidence) |
| `AKIAIOSFODNN7EXAMPLE` (known prefix) | ✅ | ✅ (regex catches first) |
| High-entropy string in free prose | ⚠️ false positive risk | ❌ not parsable — falls to context regex |

---

## Part 4: ML Training Pipeline

### Purpose

An offline tool that trains the structural classifier and boundary detector models, and calibrates secret scoring weights. Runs periodically, produces compact artifacts consumed by runtime engines.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  ML TRAINING PIPELINE                                           │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ Data Sources  │  │ Feature      │  │ Model Training        │  │
│  │              │  │ Engineering  │  │                       │  │
│  │ GitHub code   │  │              │  │ XGBoost / LightGBM   │  │
│  │ Config corpus │──►│ 40 features  │──►│ Cross-validation     │  │
│  │ LogHub logs   │  │ per block    │  │ Hyperparameter search │  │
│  │ SQL datasets  │  │              │  │                       │  │
│  │ Prose corpora │  │ Line-level   │  │ Boundary model        │  │
│  │ Event store   │  │ features for │  │ (sliding window)      │  │
│  │ Edge cases    │  │ boundaries   │  │                       │  │
│  └──────────────┘  └──────────────┘  └───────────┬───────────┘  │
│                                                   │              │
│                                      ┌────────────▼────────────┐ │
│                                      │ Export                  │ │
│                                      │                         │ │
│                                      │ ► Decision rules (.py)  │ │
│                                      │ ► Feature weights (.json)│ │
│                                      │ ► Evaluation report     │ │
│                                      └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Data Collection Strategy

**Phase 1: Public datasets (before deployment)**

| Category | Source | Volume | Notes |
|----------|--------|--------|-------|
| Source code | The Stack v2, CodeSearchNet | 1M+ samples | Sample 20+ languages proportionally |
| Configuration | GitHub `.env`, `docker-compose.yml`, `*.yaml`, `*.toml`, terraform files | 100K+ | Filter for config-specific repos |
| SQL | WikiSQL, Spider, Stack Overflow [sql] tag | 50K+ | Include DDL, DML, DCL |
| Logs | LogHub benchmark, Elastic sample datasets | 50K+ | Multiple log formats |
| CLI | Stack Overflow [bash] [docker] [kubernetes] tags, shell history datasets | 50K+ | curl, docker, kubectl, git heavy |
| Markup | Common Crawl HTML, GitHub JSX/template files | 100K+ | Sample diverse markup types |
| Natural language | Wikipedia, news (CC-News), email (Enron), Reddit comments | 500K+ | Diverse registers: formal, casual, technical |

**Phase 2: Synthetic mixed-content (before deployment)**

Generate prompts containing multiple content types with labeled boundaries:

```python
MIXED_TEMPLATES = [
    # Instruction + code
    ("{instruction}\n\n{code}", ["natural_language", "source_code"]),
    ("{instruction}\n```\n{code}\n```", ["natural_language", "source_code"]),
    ("{instruction}\n\n{code}\n\n{followup_question}", ["natural_language", "source_code", "natural_language"]),
    
    # Instruction + config
    ("Here's my config:\n\n{config}", ["natural_language", "configuration"]),
    ("{instruction}\n{env_file}", ["natural_language", "configuration"]),
    
    # Instruction + log output
    ("I'm getting this error:\n\n{log}", ["natural_language", "log_output"]),
    ("{instruction}\n{stack_trace}\n{question}", ["natural_language", "log_output", "natural_language"]),
    
    # Instruction + SQL
    ("Optimize this query:\n\n{sql}", ["natural_language", "query"]),
    
    # Instruction + data (JSON/CSV in prompt)
    ("Analyze this data:\n\n{json_data}", ["natural_language", "configuration"]),
    
    # Mixed code + config
    ("{code}\n\n# Config:\n{config}", ["source_code", "configuration"]),
    
    # Ambiguous (hardest cases)
    ("{prose_with_inline_code}", ["natural_language"]),  # code mentioned but not pasted
    ("{instruction_flowing_into_content}", ["mixed"]),   # no clear boundary
]
```

Generate 50K-100K mixed examples with boundary labels.

**Phase 3: Runtime event collection (after deployment)**

The classification library emits events for every analysis. These events include the raw features and the classification result. Over time, this builds a dataset of real-world prompts with their classifications.

Consumer feedback (correct/incorrect labels) creates ground-truth labels for retraining:

```python
# Event emitted during runtime
StructuralClassificationEvent(
    request_id="...",
    text_hash="...",            # privacy: hash not raw text
    features=extracted_features, # all 40 features
    predicted_class="source_code",
    predicted_confidence=0.87,
    # Consumer adds feedback later:
    feedback_correct=True,       # or False with corrected label
)
```

### Training Process

```python
# train_structural_model.py

import xgboost as xgb
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.metrics import classification_report

def train():
    # 1. Load and combine datasets
    data = load_public_datasets()           # Phase 1
    data += load_synthetic_mixed()          # Phase 2
    data += load_runtime_events_with_feedback()  # Phase 3 (if available)
    
    # 2. Extract features
    X = [extract_features(sample.text) for sample in data]
    y = [sample.label for sample in data]
    
    # 3. Train with cross-validation
    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        objective='multi:softprob',
        eval_metric='mlogloss',
    )
    
    cv = StratifiedKFold(n_splits=5, shuffle=True)
    scores = cross_val_score(model, X, y, cv=cv, scoring='f1_weighted')
    print(f"CV F1: {scores.mean():.3f} ± {scores.std():.3f}")
    
    model.fit(X, y)
    
    # 4. Evaluate
    print(classification_report(y_test, model.predict(X_test)))
    
    # 5. Feature importance (interpretability)
    importance = model.feature_importances_
    for name, score in sorted(zip(feature_names, importance), key=lambda x: -x[1]):
        print(f"  {name}: {score:.4f}")
    
    # 6. Export to decision rules
    export_to_decision_rules(model, "structural_classifier_rules.py")
    
    # 7. Export model for runtime (if runtime has XGBoost)
    model.save_model("structural_classifier.xgb")
    
    return model
```

### Secret Scoring Parameter Optimization

The secret scanner runs deterministically at runtime — but its parameters (dictionary weights, entropy thresholds, combination weights, structure boosts, anti-indicator adjustments) are optimized offline via ML.

**Why ML-optimize a deterministic engine?** The hand-tuned parameters (password=0.95, entropy threshold=4.5, key_score×0.6 + value_score×0.3) are educated guesses. ML learns the actual optimal values from labeled data — especially for borderline cases, feature interactions, and novel key-name patterns the dictionary misses.

**Training data:** StarPii's annotated dataset (20,961 secrets across 31 languages) provides ground truth. We extract our features from their labeled examples:

```python
SECRET_FEATURES = [
    # Key-name features (from Part 3 key-name dictionary)
    "dictionary_score",          # score from SECRET_KEY_SCORES lookup
    "key_length",                # shorter names more likely to be abbreviations
    "key_contains_common_prefix", # api_, db_, aws_, stripe_
    "key_is_all_caps",           # ENVIRONMENT_VARIABLE style
    "key_naming_style",          # camelCase=0, snake_case=1, SCREAMING=2
    
    # Value features
    "shannon_entropy",           # randomness measure
    "value_length",              # longer values more likely to be real secrets
    "char_distribution_type",    # base64=0, hex=1, alphanumeric=2, mixed=3
    "has_special_chars",         # ! @ # $ % etc.
    "starts_with_known_prefix",  # AKIA, ghp_, sk-, xox-
    "digit_ratio",               # proportion of digits
    
    # Context features
    "structure_type",            # json=0, yaml=1, env=2, code=3, sql=4, cli=5
    "nesting_depth",             # deeper nesting = more likely config
    "file_extension_signal",     # .env=high, .yaml=medium, .py=low
    
    # Anti-indicator features
    "anti_indicator_score",      # from ANTI_INDICATORS lookup
    "value_is_url",              # URLs are rarely secrets
    "value_is_numeric_only",     # pure numbers are rarely secrets
]
```

**Optimization process:**

```python
def optimize_secret_scoring(labeled_data):
    """
    Train XGBoost on secret detection features, then extract
    optimized parameters for the deterministic scorer.
    """
    # Step 1: Extract features from labeled data
    X = extract_secret_features(labeled_data)  # ~18 features per sample
    y = labeled_data["is_secret"]               # binary labels
    
    # Step 2: Train XGBoost to find optimal decision boundaries
    model = xgb.XGBClassifier(
        n_estimators=100, max_depth=4, eval_metric="aucpr"
    )
    model.fit(X, y, eval_set=[(X_val, y_val)])
    
    # Step 3: Extract feature importances
    importances = model.feature_importances_
    # → Tells us which features matter most (dictionary_score? entropy? both?)
    
    # Step 4: Extract optimal thresholds via decision tree analysis
    # Walk the tree to find the actual split points the model learned:
    #   "entropy > 4.2 (not 4.5 as we hand-tuned)"
    #   "key_length > 6 AND entropy > 3.8 → secret"
    thresholds = extract_split_thresholds(model)
    
    # Step 5: Optimize combination weights
    # Use Optuna to find the best weights for the deterministic formula:
    def objective(trial):
        key_weight_high = trial.suggest_float("key_weight_high", 0.3, 0.9)
        value_weight_high = trial.suggest_float("value_weight_high", 0.1, 0.6)
        entropy_threshold = trial.suggest_float("entropy_threshold", 3.5, 5.5)
        min_length = trial.suggest_int("min_length", 8, 24)
        # ... more parameters
        
        scores = deterministic_scorer(X, key_weight_high, value_weight_high,
                                       entropy_threshold, min_length)
        return f1_score(y, scores > 0.5)
    
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=200)
    
    # Step 6: Export optimized parameters
    return {
        "dictionary_scores": optimized_key_scores,     # updated weights
        "entropy_threshold": study.best_params["entropy_threshold"],
        "min_value_length": study.best_params["min_length"],
        "combination_weights": {
            "key_weight_high_confidence": study.best_params["key_weight_high"],
            "value_weight_high_confidence": study.best_params["value_weight_high"],
            # ...
        },
        "structure_boosts": optimized_structure_boosts,
        "feature_importances": importances,             # for debugging
    }
```

**What gets exported:** A JSON file of optimized parameters that the deterministic scorer loads at startup. The runtime code doesn't change — only the numbers inside it do.

```
training/output/secret_scoring_params.json:
{
  "dictionary_scores": {"password": 0.93, "api_key": 0.88, ...},
  "entropy_threshold": 4.2,
  "min_value_length": 12,
  "combination_weights": {"key_high": 0.55, "value_high": 0.35, ...},
  "structure_boosts": {"env": 0.12, "docker_compose": 0.08, ...},
  "anti_indicator_weights": {"example": -0.28, "test": -0.32, ...},
  "trained_on": "starpii_20961_secrets",
  "f1_score": 0.91,
  "optimized_at": "2026-04-15T10:30:00Z"
}
```

**Key insight:** The ML doesn't replace the deterministic engine. It TUNES it. The runtime is still: parse → extract → look up key-name → compute entropy → apply weights → combine → score. But the weights, thresholds, and boosts are learned from data instead of guessed by humans.

### Export to Decision Rules

A trained XGBoost model with 200 trees of depth 6 can be converted to pure Python if/else logic. This eliminates runtime ML dependencies:

```python
def export_to_decision_rules(model, output_path: str):
    """Convert trained model to pure Python decision rules.
    
    The output is a .py file with a single function:
    
        def classify_structural(features: dict) -> tuple[str, float]:
            # ... 500-2000 lines of if/else
            return (class_label, confidence)
    
    No imports needed. No ML runtime. Just Python.
    """
    trees = model.get_booster().get_dump(dump_format='json')
    # Convert each tree to nested if/else
    # Combine via weighted voting (softmax of tree outputs)
    # Write to .py file
```

**Model size as decision rules:** ~50-200KB of Python source code. Loads in microseconds. Runs in microseconds.

**Alternative: keep as XGBoost model** (~200KB .xgb file) if the runtime has XGBoost installed. Inference is slightly faster than decision rules due to optimized C++ internals.

### Evaluation Metrics

**Block classification:**

| Metric | Target | Meaning |
|--------|--------|---------|
| **Precision (per class)** | >0.90 | When we say "code," it's actually code |
| **Recall (per class)** | >0.85 | We find most actual code blocks |
| **F1 (weighted)** | >0.90 | Balanced accuracy across all classes |
| **Natural language FPR** | <0.02 | English prose almost never classified as code |

**Boundary detection:**

| Metric | Target | Meaning |
|--------|--------|---------|
| **Boundary recall** | >0.80 | We find most true boundaries |
| **Boundary precision** | >0.85 | Detected boundaries are real transitions |
| **Boundary accuracy (±2 lines)** | >0.90 | Boundary within 2 lines of true position |

**Secret detection (structural scanner):**

| Metric | Target | Meaning |
|--------|--------|---------|
| **Secret recall (structured)** | >0.85 | Catch most secrets in parsable content |
| **Secret precision** | >0.80 | Flagged secrets are actual secrets |
| **Example rejection rate** | >0.70 | Known example values correctly identified as non-secrets |

### Retraining Schedule

| Trigger | Frequency | What Retrains |
|---------|-----------|---------------|
| Initial deployment | Once | All models from public + synthetic data |
| New language support | As needed | Structural classifier (add training data for new language) |
| Consumer feedback accumulation | Monthly (if feedback available) | All models with runtime data added |
| False positive spike | Ad hoc | Investigate, add edge cases, retrain |
| New secret format discovered | Ad hoc | Add to regex patterns AND key-name dictionary |

### Pipeline Implementation

```
ml_pipeline/
├── __init__.py
├── data/
│   ├── collectors/
│   │   ├── github_collector.py       # Fetch code, config, SQL from GitHub
│   │   ├── loghub_collector.py       # Fetch log datasets
│   │   ├── prose_collector.py        # Fetch Wikipedia, news, email
│   │   └── event_collector.py        # Fetch runtime events with feedback
│   ├── generators/
│   │   ├── mixed_content_gen.py      # Generate synthetic mixed prompts
│   │   └── edge_case_gen.py          # Generate adversarial examples
│   └── loaders/
│       └── dataset.py                # Unified dataset loading
│
├── features/
│   ├── block_features.py             # 40 features for block classification
│   ├── line_features.py              # Per-line features for boundary detection
│   └── feature_extractor.py          # Unified extraction interface
│
├── training/
│   ├── structural_trainer.py         # Train block classifier
│   ├── boundary_trainer.py           # Train boundary detector
│   ├── secret_scorer_optimizer.py    # ML-optimize secret scoring parameters
│   ├── hyperparameter_search.py      # Bayesian optimization for HP tuning
│   └── cross_validation.py           # K-fold CV with stratification
│
├── evaluation/
│   ├── block_evaluator.py            # Per-class precision/recall/F1
│   ├── boundary_evaluator.py         # Boundary accuracy within N lines
│   ├── secret_evaluator.py           # Secret detection recall/precision
│   └── report_generator.py           # HTML/markdown evaluation report
│
├── export/
│   ├── decision_rules_exporter.py    # XGBoost → Python if/else
│   ├── model_exporter.py             # Save .xgb model file
│   └── weights_exporter.py           # Export key-name weights as JSON
│
├── configs/
│   ├── training_config.yaml          # Hyperparameters, data paths, thresholds
│   └── feature_config.yaml           # Feature definitions and parameters
│
└── scripts/
    ├── train_all.py                  # Full pipeline: collect → train → evaluate → export
    ├── retrain_with_feedback.py      # Incremental retrain with runtime data
    └── evaluate_model.py             # Evaluate existing model on new data
```

---

## Part 5: Integration with Classification Library

### Where the New Engines Sit

```
UPDATED ENGINE STACK:

Pass 1: Structural Analysis (<5ms)
  1. Structural Content Classifier (NEW)  ← ML-trained, identifies code/config/query/log/CLI/markup
  2. Boundary Detector (NEW)              ← ML-trained, finds content type transitions
  
Pass 2: Pattern Detection (<5ms)  
  3. Format-Based Secret Regex            ← existing: AKIA, JWT, PEM, connection strings
  4. Structured Secret Scanner (NEW)      ← parse structure, extract key-value, score key+entropy
  5. Context-Window Secret Regex          ← existing: "password = X" in unstructured text
  6. PII Pattern Regex                    ← existing: SSN, CC, phone, email
  7. Financial Density Scorer             ← density of currency + percentages + financial terms
  8. SQL Schema Analyzer                  ← extract column names, check sensitivity
  9. Consumer Dictionary Matching         ← existing: consumer-provided patterns

Pass 3: ML-Based Detection (<30ms)
  10. PII Base NER (~500M)                ← existing: person names, medical conditions
  11. EmbeddingGemma Topic Sensitivity    ← existing: M&A, competitive intel, HR topics
  12. GLiNER2 Intent + Zones (prompt mode)← existing: intent classification, zone extraction

Pass 4: Optional Heavy Engines
  13. NLI Cross-Verification              ← existing: prompt mode intent verification
  14. SLM Reasoning                       ← existing: ambiguous cases
  15. LLM Fallback                        ← existing: last resort
```

### Runtime Data Flow

```
Input text
    │
    ▼
Structural Classifier → { type: "configuration", confidence: 0.92 }
    │
    ├─► type == "configuration" or "source_code" or "query" or "cli_command"
    │       │
    │       ▼
    │   Structured Secret Scanner
    │       Parse structure → extract key-value pairs → score key+entropy
    │       Output: [SecretFinding(key="DB_PASSWORD", score=0.94), ...]
    │
    ├─► Boundary Detector (if text has mixed content)
    │       Sliding window classification → boundary positions
    │       Output: [Boundary(line=5, from=natural_language, to=source_code), ...]
    │
    └─► All engines (regex, NER, embeddings) run on full text regardless
            Structural analysis ADDS findings, doesn't replace other engines
```

### Build Stages

| Stage | What Ships | Depends On |
|-------|-----------|-----------|
| S1 | Hand-tuned structural classifier (heuristic rules) | None |
| S2 | Structured secret scanner (parsers + key-name dict + entropy) | S1 |
| S3 | Boundary detector (heuristic: code fences, delimiters) | S1 |
| S4 | ML training pipeline (data collection + training scripts) | S1-S3 |
| S5 | ML-trained structural classifier (replace heuristics with trained model) | S4 |
| S6 | ML-trained boundary detector (replace heuristics with trained model) | S4, S5 |
| S7 | Runtime feedback loop (event collection → retraining) | S4-S6, event system |

**S1-S3 ship first with zero ML dependencies.** Hand-tuned heuristics and deterministic parsers. Immediately useful.

**S4-S7 add ML accuracy.** The training pipeline produces models that replace the heuristics. Continuous improvement via runtime feedback.

---

## Decisions

### D23: Structural Content Classifier as ML Model
**Decision:** Train a gradient-boosted tree (XGBoost/LightGBM) on 40 engineered features to classify code/config/query/log/CLI/markup/natural_language. Export as decision rules for zero-dependency deployment.
**Rationale:** Hand-tuning weights for 40 features across 7 classes is error-prone. ML finds optimal decision boundaries. Tree models handle feature interactions (e.g., "high braces AND high semicolons" → C-family) that linear weights miss. Decision rule export means no ML runtime in production.

### D24: Boundary Detection via Sliding Window
**Decision:** Detect content-type boundaries by running the structural classifier on overlapping N-line windows. Boundary = classification change between adjacent windows.
**Rationale:** Simpler than training a separate sequence model. Reuses the structural classifier. Window-based approach naturally smooths single-line noise.

### D25: Structured Secret Scanner as Deterministic Engine with ML-Optimized Parameters
**Decision:** Secret detection runtime is always deterministic: parse → extract key-value → score via dictionary + entropy + anti-indicators. No ML model at inference time. Scoring parameters (dictionary weights, entropy thresholds, combination weights, structure boosts) are optimized offline via ML training on labeled secret datasets (StarPii: 20,961 secrets, 31 languages). ML output = optimized parameter values baked into the deterministic code.
**Rationale:** Runtime stays interpretable, fast (<5ms), zero-dependency. ML finds optimal decision boundaries for borderline cases, feature interactions, and novel key-name patterns. Same pattern as D26: ship hand-tuned first, ML-optimize later.

### D26: Start with Heuristics, Replace with ML
**Decision:** Ship S1-S3 with hand-tuned heuristics. Train ML replacements in S4-S6. Keep heuristics as fallback.
**Rationale:** Delivers value immediately. ML accuracy comes later without blocking the initial release. Heuristics serve as fallback if ML models haven't been trained or if the consumer prefers deterministic behavior.

---

## Part 6: How to Build the ML Pipeline (Practical Guide)

### Prerequisites

```
Python 3.11+
pip install xgboost scikit-learn pandas numpy datasets huggingface_hub
```

No GPU needed. Training runs on CPU in minutes (small tabular dataset).

### Step 1: Collect Training Data (1-2 days)

```python
# scripts/collect_training_data.py

from datasets import load_dataset

def collect():
    samples = []
    
    # Source code — use The Stack or CodeSearchNet
    code = load_dataset("bigcode/the-stack-dedup", split="train", streaming=True)
    for i, item in enumerate(code):
        if i >= 50000: break  # 50K code samples
        # Sample proportionally across languages
        samples.append({"text": item["content"][:2000], "label": "source_code"})
    
    # Configuration — GitHub search for config files
    # Use GitHub API: search for files named .env, docker-compose.yml, *.yaml, *.toml
    # Alternatively: use repos known to have config files
    
    # SQL — use Spider or WikiSQL
    sql = load_dataset("spider", split="train")
    for item in sql:
        samples.append({"text": item["query"], "label": "query"})
    
    # Logs — use LogHub
    # Download from https://github.com/logpai/loghub
    
    # Natural language — use Wikipedia + news
    wiki = load_dataset("wikipedia", "20220301.en", split="train", streaming=True)
    for i, item in enumerate(wiki):
        if i >= 50000: break
        # Take random paragraphs, not full articles
        paragraphs = item["text"].split("\n\n")
        for p in paragraphs[:3]:
            if len(p) > 100:
                samples.append({"text": p[:2000], "label": "natural_language"})
    
    return samples
```

**Target: ~200K labeled samples across 7 classes.** This is a small dataset by ML standards — training takes minutes, not hours.

### Step 2: Generate Mixed-Content Samples (1 day)

```python
# scripts/generate_mixed_content.py

import random

def generate_mixed_samples(code_samples, config_samples, prose_samples):
    mixed = []
    
    templates = [
        # Instruction + code (most common prompt pattern)
        lambda p, c: (f"{p}\n\n{c}", [
            ("natural_language", 0, len(p)),
            ("source_code", len(p)+2, len(p)+2+len(c))
        ]),
        
        # Instruction + code fence
        lambda p, c: (f"{p}\n\n```\n{c}\n```", [
            ("natural_language", 0, len(p)),
            ("source_code", len(p)+5, len(p)+5+len(c))
        ]),
        
        # Instruction + config
        lambda p, c: (f"Here's my config:\n\n{c}", [
            ("natural_language", 0, 18),
            ("configuration", 20, 20+len(c))
        ]),
        
        # Instruction + log output
        lambda p, c: (f"I'm getting this error:\n\n{c}", [
            ("natural_language", 0, 23),
            ("log_output", 25, 25+len(c))
        ]),
    ]
    
    for _ in range(50000):  # 50K mixed samples
        prose = random.choice(prose_samples)["text"][:200]
        code = random.choice(code_samples)["text"][:500]
        template = random.choice(templates)
        text, boundaries = template(prose, code)
        mixed.append({"text": text, "boundaries": boundaries})
    
    return mixed
```

### Step 3: Feature Extraction (hours, automated)

```python
# features/block_features.py

import re
import math
from collections import Counter
import json

def shannon_entropy(text: str) -> float:
    if not text: return 0.0
    freq = Counter(text)
    length = len(text)
    return -sum((c/length) * math.log2(c/length) for c in freq.values())

def extract_features(text: str) -> dict:
    lines = [l for l in text.split('\n') if l.strip()]
    n = max(len(lines), 1)
    chars = max(len(text), 1)
    
    features = {}
    
    # Character distribution (12 features)
    for name, charset in [
        ("syntactic", '{}[]();=<>|&!@#$^*/\\~'),
        ("brace", '{}'), ("paren", '()'), ("angle", '<>'),
    ]:
        features[f"{name}_density"] = sum(1 for c in text if c in charset) / chars
    
    features["semicolon_density"] = text.count(';') / chars
    features["quote_density"] = sum(1 for c in text if c in '"\'`') / chars
    features["equals_density"] = text.count('=') / chars
    features["colon_density"] = text.count(':') / chars
    features["comma_density"] = text.count(',') / chars
    features["hash_density"] = text.count('#') / chars
    features["slash_density"] = sum(1 for c in text if c in '/\\') / chars
    features["dot_density"] = text.count('.') / chars
    
    # Line patterns (4 features)
    features["semi_line_end"] = sum(1 for l in lines if l.strip().endswith(';')) / n
    features["brace_line_end"] = sum(1 for l in lines if l.strip().endswith('{')) / n
    features["brace_line_start"] = sum(1 for l in lines if l.strip().startswith('}')) / n
    features["colon_line_end"] = sum(1 for l in lines if l.strip().endswith(':')) / n
    
    # Keyword features (4 features)
    CODE_KW = r'^\s*(import|from|def|class|function|func|var|let|const|public|private|return|if|else|for|while|try|catch|struct|interface|enum|package|module|use|using|include)\b'
    SQL_KW = r'^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|GRANT|FROM|WHERE|JOIN)\b'
    CLI_KW = r'^\s*(curl|docker|kubectl|ssh|git|npm|pip|brew|apt|wget|chmod|export)\b'
    LOG_KW = r'^\d{4}[-/]\d{2}[-/]\d{2}|\[?(ERROR|WARN|INFO|DEBUG|TRACE)\]?'
    
    features["code_kw_ratio"] = sum(1 for l in lines if re.match(CODE_KW, l)) / n
    features["sql_kw_ratio"] = sum(1 for l in lines if re.match(SQL_KW, l, re.I)) / n
    features["cli_kw_ratio"] = sum(1 for l in lines if re.match(CLI_KW, l)) / n
    features["log_kw_ratio"] = sum(1 for l in lines if re.match(LOG_KW, l)) / n
    
    # Structural (8 features)
    all_parens = text.count('(')
    func_calls = len(re.findall(r'\w+\s*\(', text))
    features["func_call_ratio"] = func_calls / max(all_parens, 1)
    
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    features["indent_consistency"] = 1.0 - min(1.0, (
        sum(1 for i in indents if i % 2 != 0 and i % 4 != 0) / max(len(indents), 1)))
    features["avg_indent"] = sum(indents) / max(len(indents), 1)
    
    lengths = [len(l) for l in lines]
    features["line_len_var"] = (sum((l - sum(lengths)/n)**2 for l in lengths) / n)**0.5 if n > 1 else 0
    features["avg_line_len"] = sum(lengths) / n
    features["empty_line_ratio"] = text.count('\n\n') / max(text.count('\n'), 1)
    features["assignment_ratio"] = len(re.findall(r'\w+\s*=\s*\S', text)) / n
    features["kv_ratio"] = len(re.findall(r'^\s*[\w.-]+\s*[:=]\s*\S', text, re.M)) / n
    
    # Parse success (3 features)
    features["json_ok"] = 1.0 if _try_json(text) else 0.0
    features["xml_ok"] = 1.0 if _try_xml(text) else 0.0
    features["env_ok"] = 1.0 if _try_env(lines) else 0.0
    
    # Word-level (5 features)
    words = re.findall(r'\b\w+\b', text)
    nw = max(len(words), 1)
    features["alpha_ratio"] = sum(1 for c in text if c.isalpha()) / chars
    features["digit_ratio"] = sum(1 for c in text if c.isdigit()) / chars
    features["upper_ratio"] = sum(1 for c in text if c.isupper()) / chars
    features["camel_density"] = sum(1 for w in words if re.match(r'[a-z]+[A-Z]', w)) / nw
    features["snake_density"] = sum(1 for w in words if '_' in w and w != '_') / nw
    
    # String literal features (4 features)
    strings = re.findall(r'["\'][^"\']{1,200}["\']', text)
    features["string_density"] = len(strings) / n
    features["string_content_ratio"] = sum(len(s) for s in strings) / chars if strings else 0
    features["avg_string_len"] = sum(len(s) for s in strings) / max(len(strings), 1)
    features["string_entropy_mean"] = (
        sum(shannon_entropy(s[1:-1]) for s in strings) / len(strings) if strings else 0)
    
    return features  # 40 features total

def _try_json(text):
    try: json.loads(text.strip()); return True
    except: return False

def _try_xml(text):
    try:
        import xml.etree.ElementTree as ET
        ET.fromstring(text.strip()); return True
    except: return False

def _try_env(lines):
    matches = sum(1 for l in lines if re.match(r'^[A-Z][A-Z0-9_]+=', l.strip()))
    return matches / max(len(lines), 1) > 0.6
```

### Step 4: Train the Model (minutes)

```python
# training/structural_trainer.py

import xgboost as xgb
import lightgbm as lgb
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.metrics import classification_report
import optuna
import numpy as np
import json

CLASSES = ["source_code", "configuration", "query", "log_output",
           "cli_command", "markup", "natural_language"]

# Candidate models with Optuna search spaces
CANDIDATES = {
    "xgboost": {
        "model_fn": lambda p: xgb.XGBClassifier(
            objective="multi:softprob", num_class=len(CLASSES),
            tree_method="hist", n_jobs=-1, **p),
        "space": {
            "n_estimators": ("int", 50, 300),
            "max_depth": ("int", 3, 8),
            "learning_rate": ("float_log", 0.01, 0.3),
            "subsample": ("float", 0.6, 1.0),
            "colsample_bytree": ("float", 0.6, 1.0),
            "min_child_weight": ("int", 1, 10),
        },
    },
    "lightgbm": {
        "model_fn": lambda p: lgb.LGBMClassifier(
            objective="multiclass", num_class=len(CLASSES),
            n_jobs=-1, verbose=-1, **p),
        "space": {
            "n_estimators": ("int", 50, 300),
            "max_depth": ("int", 3, 8),
            "learning_rate": ("float_log", 0.01, 0.3),
            "subsample": ("float", 0.6, 1.0),
            "colsample_bytree": ("float", 0.6, 1.0),
            "num_leaves": ("int", 15, 63),
        },
    },
    "random_forest": {
        "model_fn": lambda p: RandomForestClassifier(n_jobs=-1, **p),
        "space": {
            "n_estimators": ("int", 100, 500),
            "max_depth": ("int", 4, 12),
            "min_samples_leaf": ("int", 2, 20),
        },
    },
}

def sample_params(trial, space):
    params = {}
    for name, spec in space.items():
        if spec[0] == "int":
            params[name] = trial.suggest_int(name, spec[1], spec[2])
        elif spec[0] == "float":
            params[name] = trial.suggest_float(name, spec[1], spec[2])
        elif spec[0] == "float_log":
            params[name] = trial.suggest_float(name, spec[1], spec[2], log=True)
    return params

def find_best_model(X, y, n_trials=50):
    """Train all candidates with Optuna HP search, return winner."""
    
    label_map = {c: i for i, c in enumerate(CLASSES)}
    y_enc = np.array([label_map[label] for label in y])
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    
    results = {}
    
    for name, config in CANDIDATES.items():
        print(f"\n{'='*50}")
        print(f"Training {name} ({n_trials} Optuna trials)")
        print(f"{'='*50}")
        
        def objective(trial):
            params = sample_params(trial, config["space"])
            model = config["model_fn"](params)
            scores = cross_val_score(model, X, y_enc, cv=cv,
                                    scoring="f1_weighted", n_jobs=-1)
            return scores.mean()
        
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
        
        # Retrain winner on full data
        best_model = config["model_fn"](study.best_params)
        best_model.fit(X, y_enc)
        
        results[name] = {
            "f1": study.best_value,
            "params": study.best_params,
            "model": best_model,
        }
        print(f"  Best F1 (weighted): {study.best_value:.4f}")
    
    # Pick winner
    winner = max(results, key=lambda k: results[k]["f1"])
    model = results[winner]["model"]
    
    print(f"\n{'='*50}")
    print(f"WINNER: {winner} (F1: {results[winner]['f1']:.4f})")
    print(f"{'='*50}")
    
    # Detailed evaluation of winner
    y_pred = model.predict(X)
    print(classification_report(y_enc, y_pred, target_names=CLASSES))
    
    # Feature importance (if available)
    if hasattr(model, 'feature_importances_'):
        importance = sorted(zip(feature_names, model.feature_importances_),
                           key=lambda x: -x[1])
        print("\nTop 10 features:")
        for fname, score in importance[:10]:
            print(f"  {fname}: {score:.4f}")
    
    # Log experiment
    log_experiment(winner, results, output_dir="models/")
    
    return winner, model, results

def log_experiment(winner, results, output_dir):
    """Structured JSON experiment log — no MLflow needed."""
    from datetime import datetime
    experiment = {
        "timestamp": datetime.now().isoformat(),
        "winner": winner,
        "candidates": {
            name: {"f1_weighted": r["f1"], "params": r["params"]}
            for name, r in results.items()
        },
    }
    with open(f"{output_dir}/experiment_log.json", "w") as f:
        json.dump(experiment, f, indent=2)
```

def train_boundary_model(X_windows, y_boundaries):
    """Train boundary detection as binary classification on window features."""
    model = xgb.XGBClassifier(
        n_estimators=100, max_depth=4, learning_rate=0.1,
        objective="binary:logistic", eval_metric="logloss",
    )
    model.fit(X_windows, y_boundaries)
    return model
```

### Step 5: Export to Decision Rules (minutes)

```python
# export/decision_rules_exporter.py

def export_to_rules(model, classes, feature_names, output_path):
    """Convert XGBoost model to pure Python function.
    
    Output: a .py file with no imports, containing:
    
        CLASSES = ["source_code", "configuration", ...]
        
        def classify_structural(features: dict) -> tuple[str, float]:
            scores = [0.0] * 7
            # Tree 0
            if features["code_kw_ratio"] > 0.315:
                if features["semi_line_end"] > 0.42:
                    scores[0] += 0.234  # source_code
                else: ...
            # Tree 1 ...
            # Softmax
            max_idx = scores.index(max(scores))
            confidence = exp(scores[max_idx]) / sum(exp(s) for s in scores)
            return CLASSES[max_idx], confidence
    """
    booster = model.get_booster()
    trees = booster.get_dump(dump_format="json")
    
    lines = []
    lines.append("# Auto-generated structural classifier")
    lines.append("# Do not edit — regenerate via train_all.py")
    lines.append(f"# Trained on {model.n_features_in_} features, {len(trees)} trees")
    lines.append(f"CLASSES = {classes}")
    lines.append("")
    lines.append("from math import exp")
    lines.append("")
    lines.append("def classify_structural(features: dict) -> tuple[str, float]:")
    lines.append(f"    scores = [0.0] * {len(classes)}")
    
    for i, tree_json in enumerate(trees):
        tree = json.loads(tree_json)
        tree_lines = _tree_to_python(tree, feature_names, indent=4)
        lines.append(f"    # Tree {i}")
        lines.extend(tree_lines)
    
    lines.append("    # Softmax")
    lines.append("    max_s = max(scores)")
    lines.append("    exp_scores = [exp(s - max_s) for s in scores]")
    lines.append("    total = sum(exp_scores)")
    lines.append("    probs = [e / total for e in exp_scores]")
    lines.append("    max_idx = probs.index(max(probs))")
    lines.append("    return CLASSES[max_idx], probs[max_idx]")
    
    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    
    print(f"Exported {len(trees)} trees to {output_path} ({len(lines)} lines)")
```

### Step 6: Validate Before Deployment

```python
# scripts/validate_exported_model.py

def validate(original_model, exported_rules_path, test_X, test_y):
    """Ensure exported rules match original model predictions."""
    
    import importlib.util
    spec = importlib.util.spec_from_file_location("rules", exported_rules_path)
    rules = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rules)
    
    mismatches = 0
    for i in range(len(test_X)):
        features = dict(zip(feature_names, test_X[i]))
        
        # Original model prediction
        orig_class = classes[original_model.predict([test_X[i]])[0]]
        
        # Exported rules prediction
        rules_class, rules_conf = rules.classify_structural(features)
        
        if orig_class != rules_class:
            mismatches += 1
    
    match_rate = 1 - mismatches / len(test_X)
    print(f"Export fidelity: {match_rate:.4%} ({mismatches} mismatches / {len(test_X)} samples)")
    assert match_rate > 0.999, f"Export fidelity too low: {match_rate}"
```

### Full Pipeline Script

```bash
# Run the complete pipeline
python ml_pipeline/scripts/train_all.py

# What it does:
# 1. Loads/downloads training data from configured sources
# 2. Generates synthetic mixed-content samples
# 3. Extracts 40 features from all samples
# 4. Trains XGBoost structural classifier (5-fold CV)
# 5. Trains boundary detector
# 6. Prints evaluation metrics (per-class F1, confusion matrix)
# 7. Exports to decision rules (.py)
# 8. Validates export fidelity
# 9. Copies rules to classification_library/patterns/structural_rules.py

# Output:
#   models/structural_classifier.xgb      (XGBoost model, ~200KB)
#   models/boundary_detector.xgb          (XGBoost model, ~100KB)
#   rules/structural_rules.py             (Python decision rules, ~100KB)
#   reports/evaluation_report.md           (Metrics, confusion matrix, feature importance)
```

### Timeline

| Step | Effort | Output |
|------|--------|--------|
| Data collection scripts | 1-2 days | Collectors for GitHub, LogHub, Wikipedia |
| Mixed-content generator | 1 day | 50K synthetic labeled prompts |
| Feature extraction | Already specced (40 features) | `extract_features()` function |
| Model training | Hours (automated) | Trained XGBoost + evaluation report |
| Decision rules export | Hours (automated) | Pure Python classifier |
| Integration + testing | 1-2 days | Structural classifier engine in library |
| **Total** | **~1 week** | Working ML-trained structural classifier |

---

## Part 7: Phase 2 — Neural Feature Discovery (PyTorch)

### Purpose

The 40 engineered features in Part 1 are our best guesses at what distinguishes code from prose. They work. But there may be character patterns we haven't thought of that the data could reveal. A character-level CNN trained on the same data discovers its own features directly from raw text. We inspect what it learned, convert discoveries to engineered features, and feed them back into the tree model.

**The CNN is a feature discovery tool, not the production model.** The tree model stays in production (fast, small, exportable as decision rules). But it gains features informed by neural network discoveries.

### When to Run This

After the tree model is deployed (Part 6) and baseline accuracy is measured. This is an optimization step — not blocking for initial release. Run it when:
- The tree model has known blind spots (specific content types it misclassifies)
- We want to squeeze more accuracy without adding expensive ML models
- We're curious what patterns exist in the data that we haven't considered

### Character-Level CNN Architecture

A small model (~200K parameters, ~1MB) that learns directly from raw text bytes:

```python
import torch
import torch.nn as nn

class CharCNN(nn.Module):
    """Character-level CNN for structural content classification.
    
    Learns convolutional filters at multiple scales that detect
    character patterns predictive of content type. After training,
    filters can be inspected to discover new engineered features.
    
    ~200K parameters. ~1MB model file. ~2-5ms inference on CPU.
    """
    
    def __init__(self, num_classes=7, max_len=2000):
        super().__init__()
        # Map raw bytes (0-255) to learned 32-dimensional embeddings
        self.embed = nn.Embedding(256, 32)
        
        # Filters at different scales capture different pattern types:
        # 3-char: operators (==, !=), short keywords (def, var, let)
        self.conv3 = nn.Conv1d(32, 64, kernel_size=3, padding=1)
        # 5-char: medium keywords (class, const, yield), delimiters
        self.conv5 = nn.Conv1d(32, 64, kernel_size=5, padding=2)
        # 8-char: long keywords (function, import__), compound patterns
        self.conv8 = nn.Conv1d(32, 64, kernel_size=8, padding=3)
        # 15-char: line-level patterns, statement rhythms, indentation
        self.conv15 = nn.Conv1d(32, 32, kernel_size=15, padding=7)
        
        # Global max pooling → one activation per filter → concat → classify
        self.classifier = nn.Sequential(
            nn.Linear(224, 128),   # 64+64+64+32 = 224 CNN features
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, num_classes),
        )
    
    def forward(self, x):
        # x: (batch, max_len) tensor of byte values 0-255
        x = self.embed(x).transpose(1, 2)  # (batch, 32, max_len)
        
        # Each conv layer detects its patterns, global max pool keeps strongest
        c3 = torch.max(torch.relu(self.conv3(x)), dim=2).values    # (batch, 64)
        c5 = torch.max(torch.relu(self.conv5(x)), dim=2).values    # (batch, 64)
        c8 = torch.max(torch.relu(self.conv8(x)), dim=2).values    # (batch, 64)
        c15 = torch.max(torch.relu(self.conv15(x)), dim=2).values  # (batch, 32)
        
        features = torch.cat([c3, c5, c8, c15], dim=1)  # (batch, 224)
        return self.classifier(features)
    
    def extract_features(self, x):
        """Return the 224-dim feature vector without classification."""
        x = self.embed(x).transpose(1, 2)
        c3 = torch.max(torch.relu(self.conv3(x)), dim=2).values
        c5 = torch.max(torch.relu(self.conv5(x)), dim=2).values
        c8 = torch.max(torch.relu(self.conv8(x)), dim=2).values
        c15 = torch.max(torch.relu(self.conv15(x)), dim=2).values
        return torch.cat([c3, c5, c8, c15], dim=1)
```

### Training the CNN

```python
def train_cnn(training_data, epochs=20, batch_size=64, lr=1e-3):
    model = CharCNN(num_classes=7, max_len=2000)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.CrossEntropyLoss()
    
    for epoch in range(epochs):
        for batch_texts, batch_labels in dataloader(training_data, batch_size):
            # Convert text to byte tensors
            x = texts_to_byte_tensors(batch_texts, max_len=2000)
            
            logits = model(x)
            loss = criterion(logits, batch_labels)
            
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        
        # Evaluate
        accuracy = evaluate(model, val_data)
        print(f"Epoch {epoch}: accuracy={accuracy:.4f}")
    
    return model

def texts_to_byte_tensors(texts, max_len=2000):
    """Convert list of strings to (batch, max_len) byte tensor."""
    batch = torch.zeros(len(texts), max_len, dtype=torch.long)
    for i, text in enumerate(texts):
        bytes_val = text.encode('utf-8', errors='replace')[:max_len]
        batch[i, :len(bytes_val)] = torch.tensor(list(bytes_val))
    return batch
```

### Filter Inspection: What Did the CNN Learn?

The key step — look inside the trained filters and find patterns:

```python
def inspect_filter(model, training_texts, conv_layer, filter_idx, kernel_size):
    """Find which text snippets maximally activate a specific filter."""
    
    model.eval()
    top_activations = []
    
    with torch.no_grad():
        for text in training_texts:
            x = texts_to_byte_tensors([text], max_len=2000)
            embedded = model.embed(x).transpose(1, 2)  # (1, 32, max_len)
            
            # Run just this conv layer
            activations = torch.relu(conv_layer(embedded)).squeeze(0)  # (out_channels, seq_len)
            filter_acts = activations[filter_idx]  # (seq_len,)
            
            # Find position of maximum activation
            max_pos = filter_acts.argmax().item()
            max_score = filter_acts[max_pos].item()
            
            # Extract the text snippet that triggered this activation
            snippet = text[max_pos : max_pos + kernel_size]
            context = text[max(0, max_pos - 15) : max_pos + kernel_size + 15]
            
            top_activations.append((max_score, snippet, context))
    
    # Sort by activation strength, return top examples
    top_activations.sort(key=lambda x: -x[0])
    return top_activations[:20]

def inspect_all_filters(model, training_texts):
    """Inspect every filter across all conv layers."""
    
    discoveries = []
    
    for conv_name, conv_layer, kernel_size in [
        ("3-char", model.conv3, 3),
        ("5-char", model.conv5, 5),
        ("8-char", model.conv8, 8),
        ("15-char", model.conv15, 15),
    ]:
        for i in range(conv_layer.out_channels):
            top = inspect_filter(model, training_texts, conv_layer, i, kernel_size)
            
            # Cluster the top snippets to identify the common pattern
            pattern = cluster_snippets(top)
            
            discoveries.append({
                "filter": f"{conv_name}[{i}]",
                "kernel_size": kernel_size,
                "pattern_name": pattern["name"],
                "regex_approx": pattern["regex"],
                "top_snippets": [t[1] for t in top[:5]],
                "top_contexts": [t[2] for t in top[:5]],
                "max_activation": top[0][0],
                "class_specificity": measure_class_specificity(model, conv_layer, i, training_texts),
            })
    
    return discoveries
```

### Example Discoveries

After running inspection, you'd get output like:

```
=== FILTER DISCOVERIES ===

NOVEL (not captured by existing features):

  Filter 8-char[7]: "statement_transition_rhythm"
    Pattern: );\\n followed by indentation
    Regex:   r'\);\s*\n\s+'
    Snippets: [");\\n    i", ");\\n    r", ");\\n    c"]
    Class: source_code (C-family)
    Correlation with existing features: 0.31
    → NEW FEATURE CANDIDATE

  Filter 3-char[22]: "comparison_operators"
    Pattern: == != >= <= with trailing space
    Regex:   r'[!=<>]=\s'
    Snippets: ["== ", "!= ", ">= "]
    Class: source_code (all languages)
    Correlation with existing features: 0.28
    → NEW FEATURE CANDIDATE

  Filter 15-char[3]: "json_secret_key_indent"
    Pattern: indented JSON key with secret-indicating name
    Regex:   r'\s+"(?:api_key|secret|password|token)"'
    Snippets: ['        "api_ke', '        "secret', '        "passwo']
    Class: configuration
    Correlation with existing features: 0.42
    → NEW FEATURE CANDIDATE

  Filter 15-char[11]: "python_log_delimiter"
    Pattern: log message delimiter " - LEVEL - ["
    Regex:   r' - (?:INFO|ERROR|WARNING|DEBUG) - \['
    Snippets: [" - INFO - [mai", " - ERROR - [pa", "] - WARNING - "]
    Class: log_output
    Correlation with existing features: 0.55
    → MARGINAL — partially captured by log_pattern_ratio

REDUNDANT (already captured):

  Filter 5-char[12]: "python_def"
    Pattern: "def " at line start with space
    Snippets: ["def _", "def p", "def c"]
    Correlation with existing features: 0.92
    → SKIP — captured by code_keyword_ratio

  Filter 3-char[0]: "semicolon_newline"
    Pattern: ";\n" at line end
    Snippets: [";\n ", ";\n\t", ";\n}"]
    Correlation with existing features: 0.95
    → SKIP — captured by semicolon_line_end_ratio
```

### Converting Discoveries to Engineered Features

```python
def convert_discovery_to_feature(discovery):
    """Generate a feature function from a CNN filter discovery."""
    
    regex = discovery["regex_approx"]
    name = discovery["pattern_name"]
    
    # Generate the feature function
    code = f'''
def {name}_density(text: str) -> float:
    """Discovered by CNN filter {discovery["filter"]}.
    Pattern: {regex}
    Top snippets: {discovery["top_snippets"][:3]}
    """
    matches = len(re.findall(r'{regex}', text))
    return matches / max(len(text), 1)
'''
    return name, code
```

### Validation: Does the Discovery Actually Help?

```python
def validate_new_features(X_original, y, new_feature_fns, training_texts):
    """Add discovered features to tree model, measure improvement."""
    
    # Extract new features for all training texts
    new_features = np.zeros((len(training_texts), len(new_feature_fns)))
    for i, text in enumerate(training_texts):
        for j, fn in enumerate(new_feature_fns):
            new_features[i, j] = fn(text)
    
    # Concatenate with original features
    X_expanded = np.hstack([X_original, new_features])
    
    # Train tree model with expanded features
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    
    # Original model
    original_scores = cross_val_score(
        xgb.XGBClassifier(n_estimators=200, max_depth=6),
        X_original, y, cv=cv, scoring="f1_weighted"
    )
    
    # Expanded model
    expanded_scores = cross_val_score(
        xgb.XGBClassifier(n_estimators=200, max_depth=6),
        X_expanded, y, cv=cv, scoring="f1_weighted"
    )
    
    improvement = expanded_scores.mean() - original_scores.mean()
    
    print(f"Original:  F1 = {original_scores.mean():.4f} ± {original_scores.std():.4f}")
    print(f"Expanded:  F1 = {expanded_scores.mean():.4f} ± {expanded_scores.std():.4f}")
    print(f"Improvement: {improvement:+.4f}")
    
    if improvement > 0.001:
        print("→ KEEP new features")
    else:
        print("→ DISCARD — no meaningful improvement")
    
    return improvement, expanded_scores
```

### Alternative: Hybrid Model (Engineered + Learned Features)

Instead of extracting individual features, concatenate the CNN's entire 224-dim representation with the 40 engineered features:

```python
class HybridClassifier(nn.Module):
    """Combines engineered features with CNN-learned features.
    
    Useful when CNN discovers many subtle patterns that are hard
    to express as individual regex features but collectively improve accuracy.
    """
    
    def __init__(self, num_engineered=40, num_classes=7):
        super().__init__()
        self.char_cnn = CharCNN(num_classes=num_classes)
        
        # Replace CNN's classifier with one that also takes engineered features
        self.classifier = nn.Sequential(
            nn.Linear(224 + num_engineered, 128),  # CNN features + engineered
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, num_classes),
        )
    
    def forward(self, raw_bytes, engineered_features):
        cnn_features = self.char_cnn.extract_features(raw_bytes)  # (batch, 224)
        combined = torch.cat([cnn_features, engineered_features], dim=1)  # (batch, 264)
        return self.classifier(combined)
```

**Deployment options if the hybrid model wins:**

| Option | How | Dependency | Inference | When |
|--------|-----|-----------|-----------|------|
| **Distill to tree** | Extract CNN features as new engineered features → retrain tree | None | <0.1ms | CNN finds a few high-value features |
| **ONNX Runtime** | Export hybrid model to ONNX → deploy with onnxruntime | onnxruntime (~30MB) | 2-5ms | CNN finds many subtle features that can't be individually extracted |
| **Keep tree only** | Use tree model, skip CNN entirely | None | <0.1ms | CNN doesn't meaningfully improve accuracy |

```python
# ONNX export for deployment
import torch.onnx

def export_hybrid_to_onnx(model, output_path):
    sample_bytes = torch.zeros(1, 2000, dtype=torch.long)
    sample_features = torch.zeros(1, 40)
    
    torch.onnx.export(
        model, (sample_bytes, sample_features),
        output_path,
        input_names=["raw_bytes", "engineered_features"],
        output_names=["class_logits"],
        dynamic_axes={"raw_bytes": {0: "batch"}, "engineered_features": {0: "batch"}},
    )

# Deploy with ONNX Runtime (no PyTorch needed)
import onnxruntime as ort

session = ort.InferenceSession("hybrid_classifier.onnx")
result = session.run(None, {
    "raw_bytes": byte_array,
    "engineered_features": feature_array,
})
```

### Dependencies for Phase 2

```
# Added to ml_pipeline only — NOT runtime
torch>=2.0         # CNN training and inspection
torchvision         # (optional, for data utilities)
onnx                # Model export
onnxruntime         # Validate ONNX export

# Runtime (only if deploying ONNX model)
onnxruntime>=1.16   # ~30MB, C++ inference, no Python ML stack
```

PyTorch is a **training-time dependency only.** It lives in the `ml_pipeline/` directory and is never imported by the classification library runtime. If the ONNX deployment path is chosen, only `onnxruntime` (~30MB) is added to runtime.

### Phase 2 Timeline

| Step | Effort | Output |
|------|--------|--------|
| Implement CharCNN + training loop | 1 day | Trained CNN |
| Filter inspection tooling | 1 day | Discovery report |
| Review discoveries, implement as features | 1-2 days | N new engineered features |
| Validate with expanded tree model | Hours | Accuracy comparison report |
| (Optional) Hybrid model + ONNX export | 1 day | ONNX model if hybrid wins |
| **Total** | **~1 week** | Expanded feature set OR hybrid model |

### Decision Framework

```
After Phase 2 inspection:

IF CNN discovers 1-5 high-value features 
   AND they can be expressed as simple regex/counting functions:
   → Add as engineered features #41-45
   → Retrain tree model
   → Keep decision rules deployment (no new dependencies)

IF CNN discovers many subtle patterns
   AND hybrid model accuracy is significantly better (>2% F1):
   → Deploy hybrid model via ONNX Runtime
   → Accept 2-5ms latency (still within Fast engine budget)
   → Accept onnxruntime dependency (~30MB)

IF CNN doesn't meaningfully improve over tree model:
   → Stay with tree model
   → The 40 engineered features already capture the important signals
   → Move on to other optimization opportunities
```
