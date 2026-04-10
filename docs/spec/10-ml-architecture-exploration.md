# ML Architecture Exploration: Structural Detection & Feature Discovery

**Version:** 2.0 (updated April 2026 — added verified pre-trained model benchmarks, Mamba-3, CodeSSM interpretability findings, production deployment survey)
**Date:** April 2026  
**Status:** Design exploration — for team discussion  
**Context:** Classification library structural content classifier, boundary detector, and secret scanner

---

## 1. What We're Solving

Three detection problems within the classification library:

**Problem 1: Structural Content Classification.** Given a block of text, identify whether it's source code, configuration, SQL query, log output, CLI command, markup, or natural language. Language-agnostic — we don't need to distinguish Python from Java, just code from not-code.

**Problem 2: Boundary Detection.** Given a prompt containing mixed content (e.g., "Fix this error:\n\nimport boto3..."), find the transition points where content type changes. This is a sequence labeling problem — at each position, is the content type the same as the previous position or has it changed?

**Problem 3: Secret Detection in Structured Content.** Given text identified as code or configuration, parse the structure, extract key-value pairs, and score each pair for secret likelihood using key-name analysis and Shannon entropy. This problem is deterministic (no ML needed) but benefits from the structural classifier's output to know WHEN to parse.

Problems 1 and 2 are classification tasks suitable for ML. Problem 3 is deterministic but consumes the output of Problems 1 and 2.

---

## 2. Constraints

| Constraint | Value | Rationale |
|-----------|-------|-----------|
| Inference latency | <10ms total for all three engines | Fast engine tier — runs on every request |
| Model size | <5MB combined | Embedded in classification library |
| Runtime dependencies | Prefer zero; accept onnxruntime (~30MB) if justified | Library consumers shouldn't need PyTorch |
| Training hardware | CPU only (no GPU requirement) | Accessible to all contributors |
| Interpretability | Must be able to explain why a classification was made | Security teams need explainable decisions |

---

## 3. The Baseline: Engineered Features + Tree Models

### 3.1 Feature Engineering (40 Features)

We identified 40 numerical features computable from raw text in <1ms:

**Character distribution (12 features):** Density of syntactic characters (`{}[]();=<>|&`), braces, parentheses, angle brackets, semicolons, quotes, equals, colons, commas, hashes, slashes, dots — each as ratio to total characters.

**Line-level patterns (4 features):** Ratio of lines ending with semicolons, lines ending with `{`, lines starting with `}`, lines ending with `:`.

**Keyword density (4 features):** Ratio of lines starting with code keywords (import, def, class, function, etc.), SQL keywords (SELECT, INSERT, etc.), CLI commands (curl, docker, kubectl, etc.), log patterns (timestamps, log levels).

**Structural signals (8 features):** Function-call density (`identifier(` ratio), indentation consistency, average indent depth, line length variance, average line length, empty line ratio, assignment pattern ratio, key-value pattern ratio.

**Parse success (3 features):** Binary indicators for JSON parseable, XML parseable, env-file format.

**Word-level (5 features):** Alpha ratio, digit ratio, uppercase ratio, camelCase density, snake_case density.

**String literal (4 features):** String literal density per line, string content ratio, average string length, mean Shannon entropy of string contents.

### 3.2 Why Individual Character Signals Are Insufficient

Individual characters are ambiguous between code and prose:

| Character | Code Usage | Prose Usage | Conclusion |
|-----------|-----------|-------------|-----------|
| `;` | Statement terminator (C-family, CSS) | Clause separator ("revenue rose; margins fell") | Ambiguous alone. Reliable as LINE-ENDING ratio. |
| `{ }` | Block delimiters, object literals | Academic refs "{see Table 3}", template vars | Ambiguous alone. Reliable at LINE BOUNDARIES. |
| `( )` | Function calls, grouping | Parenthetical asides "(founded in 2015)" | Ambiguous alone. Reliable as `identifier(` pattern. |
| `:` | Python blocks, YAML keys, ternary | Greetings, labels, time "3:45 PM", URLs | Highly ambiguous. Useful only as COMPOUND signal. |
| `< >` | HTML tags, generics | Comparisons | Reliable as MATCHED PAIRS with content. |
| `=` | Assignment | Equations, very rare in prose | Moderate signal. Better as `identifier = value` pattern. |

The signal is in the **combination and distribution** across lines, not individual characters. This is inherently a multi-feature classification problem — which is why hand-tuning weights across 40 features and 7 classes is impractical and ML is the right approach.

### 3.3 Tree Model Training

**Approach:** Train multiple gradient-boosted tree candidates (XGBoost, LightGBM, CatBoost, Random Forest) with Optuna hyperparameter search. Select winner by weighted F1 on 5-fold cross-validation. Export winner as pure Python decision rules.

**Why trees for tabular features:** Strong empirical evidence (Grinsztajn et al., "Why do tree-based models still outperform deep learning on tabular data?", NeurIPS 2022) that tree-based methods beat neural networks on tabular data with engineered features. Trees handle feature interactions naturally (e.g., "high braces AND high semicolons" → C-family code). Interpretable via feature importance. Microsecond inference.

**ML framework:** scikit-learn + Optuna + candidate model libraries (xgboost, lightgbm, catboost). No PyTorch, no TensorFlow for this phase.

**Export:** Trained model converted to pure Python if/else decision rules. <200KB file, no ML runtime dependency, <0.1ms inference. This is the production deployment format.

**Estimated accuracy:** >0.90 weighted F1 across 7 classes (target). Natural language false positive rate <2%.

### 3.4 Limitations of Engineered Features

The 40 features are our best guesses. They have known gaps:

- **Python is hard to detect:** Low syntactic density, no braces, no semicolons. Relies heavily on keyword density + indentation consistency. Edge cases with Python-like pseudocode may be missed.
- **Features may be redundant:** `semicolon_density` and `semicolon_line_end_ratio` are correlated. The tree model handles this (learns to ignore redundant features) but we may be wasting feature slots.
- **Unknown unknowns:** There may be character patterns that strongly predict content type that we simply haven't thought of. Example: the ratio of closing-paren-followed-by-semicolon-followed-by-newline (`);⏎`) is a strong C-family signal we didn't include.
- **Boundary detection is approximate:** Sliding window over a block classifier misses boundaries that require understanding the sequential transition between content types.

These limitations motivate the neural feature discovery phase.

---

## 4. Neural Feature Discovery: Three Architectural Families

Each neural architecture has a different **inductive bias** — it's predisposed to discover different kinds of patterns. Using all three gives us the most comprehensive feature discovery.

### 4.1 CNN — Discovers Local Character Patterns

**Inductive bias:** Convolutional filters are local pattern detectors. Each filter slides across the text and activates when it matches a specific character sequence. After training, each filter has specialized to detect a particular pattern.

**What CNNs discover that we might miss:**

The CNN finds optimal character-level patterns at multiple scales. After training, we inspect what each filter maximally activates on:

```
Example discoveries:

Filter 8-char[7]: "statement_transition_rhythm"
  Top activations: ");⏎    i", ");⏎    r", ");⏎    c"
  Pattern: closing-paren + semicolon + newline + indentation
  Meaning: C-family statement transitions
  Already captured? Partially (semicolon_line_end_ratio) but not the compound pattern
  → NEW FEATURE: statement_transition_density = count(r'\);\s*\n\s+') / lines

Filter 3-char[22]: "comparison_operators"
  Top activations: "== ", "!= ", ">= ", "<= "
  Pattern: comparison operators with trailing space
  Meaning: Code conditionals (not assignment, not URLs)
  Already captured? No — equals_density counts ALL = signs
  → NEW FEATURE: comparison_operator_density = count(r'[!=<>]=\s') / chars

Filter 15-char[3]: "json_secret_key_indent"
  Top activations: '        "api_ke', '        "secret', '        "passwo'
  Pattern: indented JSON keys with secret-indicating names
  Meaning: Configuration with embedded credentials
  Already captured? No — this combines structural classifier signal with secret scanner signal
  → NEW FEATURE: indented_secret_key_density (cross-engine signal)
```

**Architecture:**

```python
class CharCNN(nn.Module):
    def __init__(self, embed_dim, conv_specs, activation, pooling, 
                 hidden_dim, dropout, num_classes=7):
        super().__init__()
        self.embed = nn.Embedding(256, embed_dim)  # byte-level
        self.convs = nn.ModuleList([
            nn.Conv1d(embed_dim, n_filters, kernel_size=k, padding=k//2)
            for k, n_filters in conv_specs
        ])
        # ... classifier on concatenated pooled features
```

**Architecture hyperparameters to search (via Optuna):**

| Parameter | Search Space | What It Controls |
|-----------|-------------|-----------------|
| `embed_dim` | [16, 32, 48, 64] | Information capacity per byte |
| `n_filter_groups` | 2-5 | How many pattern scales |
| `kernel_size` per group | 2-30 | Pattern length each group detects |
| `n_filters` per group | [16, 32, 48, 64, 96, 128] | How many patterns at each scale |
| `activation` | [relu, gelu, silu] | Non-linearity shape |
| `pooling` | [max, avg, max_and_avg] | Presence vs density vs both |
| `hidden_dim` | [64, 128, 256] | Classifier capacity |
| `dropout` | 0.1-0.5 | Regularization strength |

**Model size:** ~200K-1M parameters. ~1-4MB. 2-5ms inference on CPU.

**Inspectability:** HIGH. Each filter is a direct pattern detector. Feed training data through, collect max-activating snippets, cluster by pattern, name in human terms. Directly convertible to regex-based engineered features.

**Limitations:**
- Global max pooling loses positional information. The CNN knows `def` exists but not WHERE in the text.
- Can't track state (brace nesting, indentation changes over time).
- Can't discover relationships between distant text regions.

### 4.2 RNN — Discovers Sequential State Transitions

**Inductive bias:** Recurrent networks process text sequentially, maintaining a hidden state that accumulates evidence. At each position, the state reflects everything seen so far. The state naturally tracks things like nesting depth, indentation level, and content type transitions.

**What RNNs discover that CNNs can't:**

```
Example discoveries:

Hidden state delta spike at line 5:
  Line 4: "Fix this error:"
  Line 5: "import boto3"
  Meaning: The RNN detected a style transition (prose → code)
  Already captured? Not as an engineered feature
  → NEW FEATURE: style_shift_magnitude (measure statistical change between adjacent windows)

Hidden state dimension 42 tracks brace nesting:
  Probe analysis shows dim 42 increases at each '{', decreases at each '}'
  Meaning: The RNN learned to count nesting depth
  Already captured? No — we have brace_density but not brace_nesting_depth
  → NEW FEATURE: max_brace_nesting_depth, avg_brace_nesting_depth

Hidden state shifts after ':' at line end:
  The RNN expects indentation increase after colon
  If indentation doesn't increase → prose (colon was punctuation)
  If indentation increases → Python code (colon was block start)
  Already captured? Partially (colon_line_end_ratio + indent_consistency separately) 
  → NEW FEATURE: colon_indent_transition_count (compound sequential signal)
```

**Architecture:**

```python
class BidirectionalGRU(nn.Module):
    def __init__(self, embed_dim, hidden_dim, num_layers, dropout, num_classes=7):
        super().__init__()
        self.embed = nn.Embedding(256, embed_dim)
        self.rnn = nn.GRU(
            embed_dim, hidden_dim,
            bidirectional=True,     # sees future context too
            num_layers=num_layers,
            dropout=dropout,
            batch_first=True,
        )
        # Per-position classifier (boundary detection)
        self.position_head = nn.Linear(hidden_dim * 2, num_classes)
        # Global classifier (block classification)
        self.global_head = nn.Linear(hidden_dim * 2, num_classes)
```

**Architecture hyperparameters to search:**

| Parameter | Search Space | What It Controls |
|-----------|-------------|-----------------|
| `embed_dim` | [16, 32, 48, 64] | Information capacity per byte |
| `hidden_dim` | [32, 64, 128, 256] | State capacity (what the RNN can remember) |
| `num_layers` | 1-3 | Abstraction depth |
| `cell_type` | [GRU, LSTM] | GRU: simpler, fewer params. LSTM: explicit forget gate |
| `bidirectional` | [True, False] | True for classification, False for streaming |
| `dropout` | 0.1-0.5 | Regularization |

**Model size:** ~200K-2M parameters. ~1-8MB. 5-15ms inference on CPU.

**Inspectability:** MEDIUM. Hidden states aren't directly interpretable like CNN filters. But two inspection techniques work:

1. **State delta analysis:** Track how the hidden state changes at each character. Large deltas = the RNN detected something. Correlate delta positions with text to understand what triggered the change.

2. **Linear probing:** Train a simple linear classifier on the hidden states at each position to predict content type. If the probe achieves high accuracy, the RNN IS tracking content type in its state. The probe weights reveal which hidden dimensions carry this information.

**Limitations:**
- Slower inference than CNN (sequential processing, even with bidirectional).
- Hidden states are harder to convert to discrete engineered features.
- Vanishing gradients can limit very-long-range dependencies (partially mitigated by LSTM/GRU gating, fully solved by attention).

**Key strength for boundary detection:** The RNN naturally outputs a per-position classification. Boundaries emerge as transitions in the output sequence. This is more principled than the sliding-window approach used with the CNN/tree classifier.

### 4.3 Attention — Discovers Cross-Region Relationships

**Inductive bias:** Self-attention computes pairwise relationships between ALL positions. At every position, the model asks "which other positions in this text are relevant to understanding THIS position?" The attention weights are a relationship map.

**What attention discovers that CNN and RNN can't:**

```
Example discoveries (from attention weight inspection):

Line-level attention on mixed prompt:
  Line 5 ("aws_access_key_id='AKIA...'") attends to:
    → Line 4 ("client = boto3.client('s3',") — credential relates to API call
    → Line 6 ("aws_secret_access_key='wJal...'") — credentials cluster together
    → Line 0 ("Fix this error:") — credential knows it's being submitted for help
    → Line 2 ("import boto3") — credential relates to the SDK being used

Feature discoveries:
  → instruction_precedes_secret: boolean (instruction line before code with credentials)
  → credential_proximity: when one secret found, check adjacent lines for more
  → sensitive_import_present: imports of boto3, stripe, psycopg2 predict credentials
```

These are **relational features** — they describe how parts of the text relate to each other, not what any individual part looks like. CNN discovers patterns. RNN discovers transitions. Attention discovers relationships.

**Architecture: Chunked Attention (recommended for our use case)**

Operating on raw bytes at full sequence length is expensive (2000 × 2000 = 4M attention entries). Instead, chunk the text into lines, encode each line with a small CNN, then attend between line-level representations:

```python
class CNNAttentionClassifier(nn.Module):
    """CNN for local patterns + Attention for cross-region relationships.
    
    Step 1: CNN encodes each chunk/line into a fixed-size vector
    Step 2: Transformer attends between chunk vectors
    Step 3: Both per-chunk (boundary) and global (classification) output
    """
    
    def __init__(self, embed_dim, cnn_filters, num_heads, num_layers,
                 num_classes=7, chunk_size=80):
        super().__init__()
        self.chunk_size = chunk_size
        self.embed = nn.Embedding(256, embed_dim)
        
        # Local: CNN encodes each chunk
        self.local_cnn = nn.Sequential(
            nn.Conv1d(embed_dim, cnn_filters, kernel_size=5, padding=2),
            nn.GELU(),
            nn.Conv1d(cnn_filters, cnn_filters, kernel_size=5, padding=2),
            nn.GELU(),
            nn.AdaptiveMaxPool1d(1),
        )
        
        # Global: Transformer attends between chunks
        self.pos_embed = nn.Embedding(200, cnn_filters)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=cnn_filters, nhead=num_heads,
            dim_feedforward=cnn_filters * 2,
            dropout=0.1, activation='gelu', batch_first=True,
        )
        self.cross_attention = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        
        # Dual output
        self.per_chunk_head = nn.Linear(cnn_filters, num_classes)
        self.global_head = nn.Linear(cnn_filters, num_classes)
```

**Architecture hyperparameters to search:**

| Parameter | Search Space | What It Controls |
|-----------|-------------|-----------------|
| `embed_dim` | [32, 48, 64] | Byte embedding dimension |
| `cnn_filters` | [32, 48, 64, 96] | Local pattern capacity |
| `cnn_kernel_sizes` | combinations of [3,5,7,9] | Local pattern scales |
| `num_heads` | [2, 4, 8] | Number of independent attention patterns |
| `num_layers` | [1, 2, 3] | Depth of cross-region reasoning |
| `chunk_size` | [40, 60, 80, 120] | Granularity (chars per chunk, roughly one line) |
| `dropout` | 0.1-0.4 | Regularization |

**Model size:** ~300K-2M parameters. ~1-8MB. 5-10ms inference on CPU.

**Inspectability:** HIGH at the chunk/line level. Attention weights between lines are directly interpretable: "when classifying line 5, the model looked at lines 2, 4, and 6 with weights 0.3, 0.25, 0.2." This reveals cross-line relationships that are convertible to relational features.

**Limitations:**
- More complex to implement than CNN or RNN alone.
- Attention is O(n²) in sequence length — mitigated by chunking, but still more expensive than CNN.
- Harder to export as decision rules (attention is fundamentally a matrix operation).

### 4.4 SSM (State Space Models) — Deep Dive

*This section is intentionally comprehensive to preserve knowledge across session boundaries.*

#### 4.4.1 The Fundamental Problem

You have a sequence of inputs — characters or lines of text in a prompt. You need to process them and produce a classification. The question is: how do you compress "everything I've seen so far" into a representation useful for deciding "what comes next"?

Three approaches exist:

**Transformers** let every position look at every other position. For 1000 tokens, that's 1,000,000 pairwise comparisons. Powerful but expensive — O(n²) in compute and O(n) in memory for KV cache.

**RNNs** maintain a hidden state updated at each step. Process token 1 → update state → process token 2 → update state. By token 1000, the state has been updated 1000 times. Each update is cheap but information from early tokens gets diluted — the "forgetting" problem. O(n) total but lossy.

**SSMs** come from control theory, not from NLP. They process sequences through a mathematically principled linear dynamical system that has a unique property: the same computation can be performed either as a sequential recurrence (like an RNN, for inference) or as a global convolution (like a CNN, for training). This dual nature gives the best of both worlds.

#### 4.4.2 The Mathematics (From First Principles)

A continuous-time state space model is defined by:

```
State evolution:    h'(t) = A · h(t) + B · x(t)     (differential equation)
Output:             y(t)  = C · h(t) + D · x(t)
```

Where:
- `x(t)` is the input signal at time t
- `h(t)` is the hidden state (a vector of dimension N, the "state size")
- `y(t)` is the output
- `A` is the state transition matrix (N×N) — controls how state evolves
- `B` is the input projection matrix (N×1) — controls how input enters the state
- `C` is the output projection matrix (1×N) — controls how state maps to output
- `D` is the direct feedthrough (skip connection)

This is a linear ordinary differential equation (ODE). It has a closed-form solution:

```
h(t) = exp(A·t) · h(0) + ∫₀ᵗ exp(A·(t-τ)) · B · x(τ) dτ
```

To use this on discrete sequences (tokens), we **discretize** — convert from continuous time to discrete steps using a step size Δ:

```
Discretized (using zero-order hold):
  Ā = exp(A · Δ)
  B̄ = (A)⁻¹ · (Ā - I) · B
  
  h[k+1] = Ā · h[k] + B̄ · x[k]      ← recurrence (sequential)
  y[k]   = C · h[k] + D · x[k]
```

This looks like an RNN. But here's the key property: because A is structured (typically diagonal), the entire sequence output can also be computed as:

```
K = (CB̄, CĀB̄, CĀ²B̄, ..., CĀⁿB̄)    ← this is a convolution kernel
y = K * x                                ← convolution (parallel)
```

**During training:** compute the convolution kernel K once, then convolve with the input. This is parallel and fast (GPU-friendly matrix operations).

**During inference:** use the recurrence h[k+1] = Ā·h[k] + B̄·x[k]. Process one token at a time, maintaining state. O(1) per step, constant memory.

This is the "dual" nature: same math, two computation paths, choose based on whether you need training speed or inference efficiency.

#### 4.4.3 S4: The First Practical SSM (Gu et al., 2021)

The original structured state space model (S4) made this practical by:

1. **HiPPO initialization** — initializing A using a specific mathematical formulation (High-order Polynomial Projection Operators) that's optimized for remembering history. Instead of random initialization, A starts with a structure that's provably good at compressing long sequences.

2. **Diagonal structure** — constraining A to be diagonal (or diagonal plus low-rank), which makes exp(A·Δ) trivially computable (just exponentiate each diagonal element). This reduces the state update from O(N²) to O(N).

3. **Efficient convolution** — computing the kernel K via FFT, making the full-sequence computation O(n log n) rather than O(n·N).

S4 achieved breakthrough results on the Long Range Arena benchmark — tasks requiring understanding of 1K-16K token sequences where Transformers struggled.

**Limitation:** The state transition matrices A, B, C were **fixed** (input-independent). The same update rule applied to every token regardless of content. If A says "retain 80% of state," it retains 80% whether the input is a crucial `import` keyword or meaningless whitespace.

#### 4.4.4 Mamba (Gu & Dao, December 2023) — The Selective SSM

**The insight:** Make the SSM parameters **functions of the input**:

```
Before (S4):    h[k+1] = Ā · h[k] + B̄ · x[k]           ← Ā, B̄ are constant
After (Mamba):  h[k+1] = Ā(x[k]) · h[k] + B̄(x[k]) · x[k]  ← Ā, B̄ depend on input
```

Specifically, Mamba makes B, C, and Δ (the discretization step size) functions of the input via learned linear projections:

```python
# Simplified Mamba block (conceptual)
def mamba_block(x):
    # x: (batch, length, d_model)
    
    # Project input to SSM parameters
    B = linear_B(x)        # (batch, length, state_dim) — input-dependent
    C = linear_C(x)        # (batch, length, state_dim) — input-dependent
    delta = softplus(linear_delta(x))  # (batch, length, d_inner) — input-dependent step size
    
    # A is learned but NOT input-dependent (diagonal, initialized via HiPPO)
    A = param_A  # (d_inner, state_dim) — diagonal
    
    # Discretize A using input-dependent delta
    A_bar = exp(A * delta)       # input-dependent because delta is
    B_bar = delta * B            # simplified discretization
    
    # Sequential scan (inference) or parallel scan (training)
    h = zeros(batch, d_inner, state_dim)
    outputs = []
    for k in range(length):
        h = A_bar[k] * h + B_bar[k] * x_projected[k]  # selective state update
        y = (h * C[k]).sum(dim=-1)                       # output projection
        outputs.append(y)
    
    return stack(outputs)
```

**What "selective" means concretely:** The model controls two things via the input:

1. **What to forget** (via Δ and A): A large delta means "take a big step" — the state decays more, forgetting old information. A small delta means "take a small step" — preserve the existing state. When the model sees a transition signal (empty line followed by code keywords), it can increase delta to rapidly update its belief.

2. **What to remember** (via B): B controls how strongly the current input is injected into the state. When the model sees a highly informative token (like `import` or `SELECT`), B can be large — injecting strong evidence. When the token is uninformative (whitespace, generic punctuation), B can be small.

**The cost of selectivity:** Input-dependent parameters break the convolution property (the kernel K now changes at every step, so you can't precompute it). Mamba solves this with a hardware-aware parallel scan algorithm:

- The sequence is chunked into tiles
- Each tile is loaded from HBM (slow GPU memory) into SRAM (fast on-chip memory)
- The scan is computed within SRAM without materializing the full N-dimensional intermediate states in HBM
- This is a memory-IO optimization, not an algorithmic one — the math is the same as sequential scan, but the memory access pattern is optimized for GPU architecture

**Results:** At 3B parameters, Mamba matches Transformers of 2x its size on language modeling. 5x higher inference throughput. Linear scaling to million-length sequences.

**Published at COLM 2024.** Paper: arxiv.org/abs/2312.00752. Code: github.com/state-spaces/mamba.

#### 4.4.5 Mamba-2 / SSD (Dao & Gu, May 2024) — The Duality

**The theoretical result:** Selective SSMs and softmax attention are **mathematical duals**. The SSD (Structured State Space Duality) framework proves that:

1. Any selective SSM can be expressed as a specific structured attention pattern
2. Any structured attention pattern can be expressed as a selective SSM
3. The two representations are computationally equivalent — they produce the same output

This isn't an approximation. It's an exact mathematical equivalence under certain structural constraints.

**Why this matters:** It means SSMs aren't "cheaper but worse attention." They're a different computational path to the same result. The choice between SSM and attention becomes a hardware efficiency question, not an accuracy question.

**The practical improvement:** The SSD algorithm computes the selective SSM using matrix multiplications (which GPUs are optimized for) rather than sequential scans. This makes Mamba-2 significantly faster to train than Mamba-1. A minimal implementation is ~30 lines of PyTorch.

**Architecture changes:** Mamba-2 produces the A, B, C parameters in parallel with the input X (instead of sequentially), making it more amenable to tensor parallelism for scaling.

**Paper:** arxiv.org/abs/2405.21060.

#### 4.4.6 Mamba-3 (Lahoti et al., March 2026) — Three Improvements

**Improvement 1: Better discretization.**

The continuous-to-discrete conversion loses information. Mamba-3 uses a more expressive discretization formula that better preserves the continuous-time dynamics. The result is better model quality — less information lost in the conversion.

**Improvement 2: Complex-valued states.**

Previous Mambas used real-valued states (regular floating-point numbers). Mamba-3 uses **complex numbers** (a + bi) for the state update matrices.

Why complex numbers matter — they naturally encode two quantities in one:

```
Complex number z = a + bi
  Magnitude |z| = sqrt(a² + b²)  — "how much"
  Phase arg(z) = atan2(b, a)     — "what kind" or "where in cycle"
```

For our boundary detection, the dual encoding could represent:

- **Magnitude:** confidence in current content type classification ("I'm 0.9 sure this is code")
- **Phase:** position within a content block ("I'm deep inside a code block" vs "I'm near the edge")

Or equivalently:
- **Real part:** content type belief (positive = code, negative = prose)
- **Imaginary part:** transition momentum (large = approaching a boundary, small = stable region)

The mathematical property: complex exponentials naturally model **oscillatory dynamics** — things that cycle between states. Code/prose alternation in mixed prompts is exactly this kind of oscillatory pattern. Real-valued states can model it but need more dimensions; complex states represent it natively.

**Result:** Mamba-3 achieves comparable perplexity to Mamba-2 with **half the state size**. The complex representation is fundamentally more efficient for encoding rich state information.

**Improvement 3: MIMO (Multi-Input Multi-Output).**

Standard Mamba processes each "channel" (dimension of the hidden state) through the SSM independently. MIMO lets multiple input dimensions jointly influence the state update:

```
Standard (SISO):  h_i[k+1] = A_i · h_i[k] + B_i · x_i[k]    ← each dimension independent
MIMO:             h[k+1]   = A · h[k] + B · x[k]              ← cross-dimension interaction
```

For our use case: if one input dimension encodes "semicolon density" and another encodes "brace density," MIMO lets the SSM jointly process both — recognizing "high semicolons + high braces = C-family code" in a single state update, without needing a separate mixing layer.

**Results at scale:** At 1.5B parameters, Mamba-3 improves average downstream accuracy by 1.8 points over the best alternative (Gated DeltaNet). The MIMO variant adds an additional 1.2 points. Total gain: 1.8 points — significant at this benchmark maturity.

**Paper:** OpenReview (NeurIPS submission). arxiv.org/abs/2603.15569. Code integrated into github.com/state-spaces/mamba.

#### 4.4.7 CodeSSM — SSMs for Code Understanding

**CodeSSM (Verma et al., EMNLP 2025):** The first encoder-only SSM designed specifically for code understanding. Uses the BiGS (Bidirectional Gated SSM) architecture — running the SSM forward and backward over the sequence, then combining the two directions.

**Key results:** Outperforms comparable Transformer baselines (RoCoder, a BERT-variant with RoPE) on Stack Overflow question-answer retrieval and code classification, while being more compute-efficient and sample-efficient.

**Interpretability study (February 2026, arXiv):** "Towards Understanding What State Space Models Learn About Code" provides the first detailed analysis:

- SSMs capture syntactic code structure (AST relationships, nesting) in their hidden states
- The model learns different features at different layers (shallow = local syntax, deep = long-range structure)
- **Critical finding: SSM representations degrade during fine-tuning.** The pre-trained features that capture code structure get partially overwritten during task-specific fine-tuning. This doesn't happen (or happens less) with Transformers.

**Implication for our project:** If we use CodeSSM, we should use **probing + distillation** rather than direct fine-tuning:
1. Freeze the pre-trained CodeSSM
2. Probe each layer to find which layers best capture code/prose distinction
3. Extract features from those layers
4. Train a small classifier (or tree model) on the extracted features

This preserves the pre-trained representations while adapting to our task.

#### 4.4.8 How SSMs Apply to Our Three Problems

**Problem 1: Structural content classification (code vs prose vs config).**

An SSM scans the text and accumulates evidence. After processing the full sequence, the final hidden state encodes "what kind of content was this?" A linear classifier on the final state produces the classification.

This is similar to how our XGBoost tree works (accumulate features, classify), but the SSM discovers its own features from raw text rather than using our 40 engineered features. The question is whether the SSM discovers features we missed.

**Advantage over tree model:** Can discover sequential patterns (e.g., "import statement followed by function definition" is stronger evidence of code than either alone).

**Disadvantage:** Less interpretable. Tree model can say "code_keyword_ratio was 0.45, which is above the 0.31 threshold, so → source_code." SSM can only say "the final state had high activation in dimensions 3, 7, 15, which correlate with source_code."

**Problem 2: Boundary detection (where does content type change).**

This is where SSMs have the strongest theoretical advantage. A boundary IS a state transition — the text was prose, now it's code. SSMs model state evolution over sequences. The magnitude of state change at each position is the boundary signal:

```python
def detect_boundaries_ssm(text_lines, ssm_model):
    states = []
    h = initial_state()
    
    for line in text_lines:
        tokens = tokenize(line)
        for token in tokens:
            h = ssm_step(h, token)  # selective state update
        states.append(h.clone())
    
    # Boundary = large state change between adjacent lines
    boundaries = []
    for i in range(1, len(states)):
        delta = torch.norm(states[i] - states[i-1])
        if delta > threshold:
            boundaries.append(i)
    
    return boundaries
```

**Advantage over sliding window:** The SSM sees the full sequence history at each position. The sliding window approach runs the tree classifier on 5-line windows independently — it can't use information from line 1 when classifying line 50. The SSM's state carries that information forward.

**Advantage over attention:** O(n) instead of O(n²). For a 200-line prompt, attention computes 40,000 pairwise comparisons. SSM computes 200 state updates.

**Problem 3: Secret detection (key-name + entropy analysis).**

SSMs are NOT needed here. Our structured secret scanner is deterministic: parse the structure, extract key-value pairs, score via dictionary + entropy. This is a pattern-matching problem, not a sequence-modeling problem. No neural architecture improves on "if key_name contains 'password' and value has high entropy, flag it."

SSMs could theoretically learn to detect secrets without explicit key-name dictionaries — discovering from training data that tokens after "password=" tend to be secrets. But this is slower, less interpretable, and harder to maintain than our curated dictionary approach.

#### 4.4.9 Concrete Architecture for Boundary Detection with SSM

If Phase 2 shows sequential models outperform attention for boundary detection, here's the deployment architecture:

```python
# Tiny Mamba for boundary detection
# Target: <2MB model, 2-5ms inference on CPU

config = MambaConfig(
    d_model=64,           # small — we're not doing language modeling
    state_dim=32,         # how much history to retain
    expand_factor=2,      # inner dimension = 128
    conv_kernel=4,        # local convolution
    num_layers=4,         # 4 Mamba blocks
    bidirectional=True,   # forward + backward scan
    complex_valued=True,  # Mamba-3 complex states (if beneficial)
    vocab_size=256,       # byte-level input (no tokenizer needed)
)

# Input: raw bytes of the text (no tokenization, no feature engineering)
# Output: per-position classification (code/config/query/log/cli/markup/prose)
# Boundary: positions where classification changes

# Model size: ~200K-500K parameters (~1-2MB)
# Inference: 2-5ms for a 2000-byte prompt on CPU via ONNX
```

**Why byte-level input:** Eliminates tokenizer dependency and tokenizer-induced artifacts. The SSM sees raw characters — exactly the same signal our engineered features compute over. It can discover character-level patterns (like our CNN) while maintaining sequential state (like our RNN).

**Why bidirectional:** Classification isn't autoregressive. We can look at the full text. Bidirectional SSM runs forward and backward, then combines the two states at each position. This means the model knows what comes AFTER a boundary, not just what came before — which helps resolve ambiguous transitions.

#### 4.4.10 When SSMs Definitively Win (and When They Don't)

**SSMs WIN for:**

1. **Streaming analysis** — processing prompts character-by-character as the user types. SSMs' sequential inference is O(1) per step with constant memory. Maintain state, update on each keystroke, emit boundary alerts in real-time. Transformers can't do this efficiently (need to recompute attention over the full sequence at each step).

2. **Very long documents** — >10K tokens. O(n) vs O(n²) becomes decisive. A 50K-token code file takes seconds with attention, milliseconds with an SSM.

3. **Boundary detection as a first-class output** — if we need per-position classifications (not just per-block), the SSM's natural output is per-position. The sliding window approach is an approximation; the SSM computes it directly.

**SSMs DON'T WIN for:**

1. **Short sequences** — most prompts are <1000 tokens. At this length, attention is fast enough and tooling is mature.

2. **Block classification** — classifying a single block as code/prose/config. The tree model on 40 features is <0.1ms and highly interpretable. No neural architecture justifies 2-5ms for marginal accuracy improvement on this task.

3. **Feature discovery** — CNN filters are more inspectable and exportable than SSM states. If the goal is "discover features, export to tree model," CNN+Attention is better.

4. **Secret detection** — deterministic parsing + scoring outperforms any ML approach for structured secrets. SSMs add latency without improving accuracy.

#### 4.4.11 SSM Research References

| Paper | Venue | Year | Key Contribution |
|-------|-------|------|-----------------|
| S4: Efficiently Modeling Long Sequences with Structured State Spaces (Gu et al.) | ICLR | 2022 | First practical SSM with HiPPO initialization |
| Mamba: Linear-Time Sequence Modeling with Selective State Spaces (Gu & Dao) | COLM | 2024 | Selective (input-dependent) SSM, hardware-aware scan |
| Mamba-2: Transformers are SSMs via Structured State Space Duality (Dao & Gu) | arXiv | 2024 | SSM-attention mathematical duality, SSD algorithm |
| Mamba-3: Improved Sequence Modeling using State Space Principles (Lahoti et al.) | OpenReview | 2025/2026 | Complex-valued states, MIMO, better discretization |
| CodeSSM: SSMs for code understanding (Verma et al.) | EMNLP | 2025 | First encoder-only SSM for code, outperforms RoCoder |
| Towards Understanding What SSMs Learn About Code (interpretability) | arXiv | 2026 | SSM-Interpret, representation degradation during fine-tuning |
| Mamba-360: Survey of SSMs as Transformer alternatives | Engineering Applications of AI | 2025 | Comprehensive SSM survey across domains |
| PerfMamba: Performance Analysis and Pruning (Al Asif et al.) | arXiv | 2025 | SSM component profiling, 1.14x speedup via pruning |

### 4.5 Comparison Matrix

| Capability | CNN | RNN | Attention | SSM | Tree (baseline) |
|-----------|:---:|:---:|:---------:|:---:|:---------------:|
| **Classification accuracy** | Good | Good | Best (with pre-training) | Good (expected) | Good (with features) |
| **Boundary detection** | Sliding window (approx.) | Per-position (natural) | Per-chunk (natural) | Per-position (principled — state transitions) | Sliding window (approx.) |
| **Local pattern discovery** | ✅ Best — filters are patterns | Partial — hidden in state | Partial — in attention | Partial — in state | ❌ Uses given features |
| **Sequential state discovery** | ❌ No state | ✅ Good — hidden state | Partial — positional encoding | ✅ Best — mathematically principled state | ❌ No sequence |
| **Relationship discovery** | ❌ No cross-position | Partial — accumulation | ✅ Best — attention weights | ❌ Compressed state only | ❌ No relationships |
| **Inspectability** | High (filter activation) | Medium (probing, deltas) | High (attention weights) | Medium (state transitions, probing) | High (feature importance) |
| **Feature export to tree** | Easy (pattern → regex) | Hard (state → function) | Medium (relationship → boolean) | Hard (state → function) | N/A |
| **Inference speed (CPU)** | 2-5ms | 5-15ms | 5-10ms (chunked) | 3-8ms | <0.1ms |
| **Sequence length scaling** | O(1) per position | O(n) total | O(n²) total | O(n) total | N/A |
| **Long sequence (>10K)** | ✅ (but no cross-position) | ⚠️ (gradient issues) | ❌ (quadratic cost) | ✅ (linear, designed for this) | N/A |
| **Model size** | 1-4MB | 1-8MB | 1-8MB | 1-8MB | <200KB |
| **Training complexity** | Low | Medium | Medium-High | Medium-High | Low |
| **Maturity / tooling** | Very mature | Mature | Very mature | New — limited tooling | Very mature |

---

## 5. Pre-Trained Models

*Section updated April 2026 with web research verification. All claims below are confirmed via published papers, HuggingFace model cards, or official documentation.*

### 5.1 Available Models (Verified April 2026)

| Model | Year | Params | Architecture | License | HuggingFace ID | Best For |
|-------|------|--------|-------------|---------|----------------|----------|
| **ModernBERT-base** | 2024 | 149M | Encoder (RoPE, GeGLU, FlashAttention, alternating global/local attention, 8192 ctx) | Apache 2.0 | `answerdotai/ModernBERT-base` | **Top candidate.** SOTA encoder. Outperforms DeBERTaV3 on GLUE at 1/5 memory. Scores 56.4 on code understanding (vs RoBERTa 44.3). 2-3x faster than DeBERTaV3. |
| **ModernBERT-large** | 2024 | 395M | Encoder (same arch, 28 layers) | Apache 2.0 | `answerdotai/ModernBERT-large` | Distillation teacher. 83.9 on code retrieval (vs BERT-large 60.8). |
| **StarEncoder** | 2023 | ~125M | Encoder (BERT-style, MLM+NSP on code, 1024 ctx) | OpenRAIL-M | `bigcode/starencoder` | Code-specific. Trained on 86 languages from The Stack (~400B tokens). Proven for PII detection via StarPii. |
| **StarPii** | 2023 | ~125M | StarEncoder + token classification head | OpenRAIL-M | `bigcode/starpii` | PII/secret NER in code. 6 classes: Names, Emails, Keys, Passwords, IPs, Usernames. Trained on 20,961 annotated secrets across 31 languages. |
| **CodeSSM** | 2025 | TBD | Encoder-only SSM (BiGS architecture) | TBD | Not on HuggingFace | SSM for code understanding. Outperforms RoCoder (Transformer) on retrieval and classification. Interpretability study published Feb 2026. |
| **CodeBERT** | 2020 | 125M | Encoder (RoBERTa on code+prose pairs) | MIT | `microsoft/codebert-base` | Code-prose relationship understanding. Attention analysis for boundaries. |
| **UniXcoder** | 2022 | 125M | Encoder (code + AST + comments) | MIT | `microsoft/unixcoder-base` | AST-aware — understands structural ambiguity (`{` in Java ≠ `{` in JSON). |
| **CodeT5-small** | 2021 | 60M | Encoder-decoder (identifier-aware) | BSD-3 | `Salesforce/codet5-small` | Smallest code model. Identifier-aware training relevant for variable/key names. |
| **ByT5-small** | 2021 | 300M | Encoder-decoder (byte-level, no tokenizer) | Apache 2.0 | `google/byt5-small` | Byte-level — sees raw characters like our CNN. Good for character pattern comparison. |
| **StarCoder2-3B** | 2024 | 3B | Decoder (code generation, 600+ languages) | OpenRAIL-M | `bigcode/starcoder2-3b` | Distillation teacher only — too large for direct use. Trained on 3.3T code tokens. |

All models with listed HuggingFace IDs are freely downloadable. All licenses permit commercial use (OpenRAIL-M has ethical use restrictions that don't affect security/classification products).

### 5.2 Why ModernBERT Is the Top Candidate

*Verified via HuggingFace blog post (Dec 2024), benchmark results, and independent evaluations.*

ModernBERT (December 2024, Answer.AI + LightOn) is a modernized BERT trained on 2 trillion tokens:

- **8192 token context** — handles full prompts without truncation (CodeBERT: 512, StarEncoder: 1024)
- **Rotary positional embeddings (RoPE)** — better position understanding than absolute embeddings
- **GeGLU activation** — smoother than GELU, better gradient flow
- **Alternating attention** — every 3rd layer uses global attention, others use 128-token sliding window
- **FlashAttention + unpadding** — 2-3x faster than DeBERTaV3, 5x less memory
- **Trained on 2T tokens** — 20x more data than CodeBERT's training set

**Verified benchmarks:**

| Task | ModernBERT-base | ModernBERT-large | Best Competitor |
|------|:-:|:-:|:-:|
| GLUE (NLU) | SOTA | SOTA | DeBERTaV3 (uses 5x memory) |
| Code understanding (StackOverflow-QA) | 56.4 | 59.5 | GTE-en-MLM-base: 44.9, RoBERTa: 44.3 |
| Code retrieval | 73.6 | 83.9 | BERT-large: 60.8 |
| Few-shot classification (SetFit, 8 samples) | 92.7% (IMDB) | — | Near all-data baseline (25K samples) |

**Caveat from research (IJCNLP 2026):** A comparative study found that data quality matters more than architecture — a DeBERTaV3 trained on higher-quality data can match ModernBERT. This suggests our training data quality will matter more than model choice.

ModernBERT is already being used for prompt classification (LLM routing) — essentially our intent classification task. Compatible with GliNER for zero-shot NER and Sentence-Transformers for retrieval.

### 5.3 StarEncoder for Code-Specific Tasks

*Verified via HuggingFace model card and BigCode documentation.*

StarEncoder (BigCode) is the most relevant code-specific encoder:

- Trained on 86 programming languages from The Stack (~400B tokens over 100K steps, batch size 4096, max length 1024)
- **StarPii** — the PII detection fine-tune — is directly relevant to our secret detection problem:
  - 6 entity classes: Names, Emails, **Keys**, **Passwords**, IP addresses, Usernames
  - Training dataset: 20,961 annotated secrets across 31 programming languages
  - Used pseudo-labeling: ensemble of DeBERTa-v3-large + stanford-deidentifier-base for initial labels
  - **Key finding on false positives:** High FP rate for Keys and Passwords. They retained only entities with **trigger words like "key", "auth", "pwd" in surrounding context** — this is exactly our key-name scoring approach
  - Post-processing included: ignore secrets <4 chars, ignore keys <9 chars, gibberish detection on key values, IP address validation
- Licensed under OpenRAIL-M (permits commercial use with ethical restrictions)

**Relevance to our project:** StarPii validates three of our design decisions: (1) key-name context matters more than the value alone for secret detection, (2) false positive reduction requires anti-indicators, (3) post-processing heuristics (length thresholds, gibberish detection) are necessary even with ML models. Our Structured Secret Scanner implements the same principles deterministically.

### 5.4 Distillation Strategy

All pre-trained models are too large for a "fast engine." The deployment path:

```
Step 1: Fine-tune pre-trained model (teacher) on our 7-class task
        → High accuracy, large model (60-395M params)

Step 2: Train tiny model (student) to match teacher's predictions
        → Student learns teacher's understanding in <1M parameters
        → Student can be CNN, RNN, CNN+Attention, or SSM architecture

Step 3: Deploy student (~2MB, 2-5ms inference)
        → Carries distilled knowledge from the pre-trained teacher
```

The student learns from "soft labels" (probability distributions) rather than hard labels. A teacher output of [0.7, 0.15, 0.1, 0.03, 0.02, 0.0, 0.0] transfers more information than the hard label [1, 0, 0, 0, 0, 0, 0] — it tells the student "this is mostly source_code but has some configuration-like properties."

**When to use distillation vs. training from scratch:**

| Scenario | Approach | Rationale |
|----------|---------|-----------|
| Plenty of labeled data (>100K samples) | Train from scratch | Enough data for small models to learn directly |
| Limited labeled data (<10K samples) | Distill from pre-trained | Teacher's pre-trained knowledge compensates for scarcity |
| Need to exceed tree model significantly | Distill from ModernBERT/StarEncoder | Pre-trained understanding hard to learn from scratch |
| Only need modest improvement | Train from scratch | Simpler pipeline, no large model download |

---

## 6. Feature Harvesting Pipeline

Regardless of which neural architecture we use, the goal is the same: **discover features that improve the tree model.** The neural model is a research tool. The tree model is the production system.

### 6.1 CNN Feature Harvesting

```
Train CNN → Inspect filters → Cluster activating snippets → Name patterns
→ Check correlation with existing 40 features → If novel: implement as regex feature
→ Add to tree model → Measure improvement
```

**Output:** regex-expressible features. Example: `comparison_operator_density()`, `statement_transition_density()`.

### 6.2 RNN Feature Harvesting

```
Train RNN → Track hidden state deltas → Find positions where state changes sharply
→ Correlate with text content at those positions → Identify what triggers transitions
→ Implement as stateful counting features

Also: Train linear probes on hidden states → Identify which hidden dimensions
track which properties (nesting depth, indentation level, content type)
→ Implement those tracked properties as explicit features
```

**Output:** stateful features. Example: `max_brace_nesting_depth()`, `colon_indent_transition_count()`, `style_shift_magnitude()`.

### 6.3 Attention Feature Harvesting

```
Train CNN+Attention → Extract line-level attention weights
→ For each line, see which other lines it attends to most strongly
→ Identify recurring attention patterns across training examples
→ Convert to relational features
```

**Output:** relational features. Example: `instruction_precedes_secret()`, `credential_line_clustering()`, `sensitive_import_present()`.

### 6.4 Validation

Every harvested feature goes through the same validation:

```python
def validate_feature(new_feature_fn, X_original, y, training_texts):
    # Extract new feature for all training texts
    new_col = [new_feature_fn(text) for text in training_texts]
    X_expanded = np.column_stack([X_original, new_col])
    
    # Compare tree model accuracy with and without new feature
    original_f1 = cross_val_f1(X_original, y)
    expanded_f1 = cross_val_f1(X_expanded, y)
    
    improvement = expanded_f1 - original_f1
    if improvement > 0.001:
        print(f"KEEP: +{improvement:.4f} F1")
    else:
        print(f"DISCARD: no meaningful improvement")
```

Only features that measurably improve F1 (even by 0.001) are kept.

---

## 7. Deployment Options

### 7.1 Decision Rules (Recommended Default)

Tree model exported as pure Python if/else. No dependencies. <0.1ms inference. <200KB.

```python
# Auto-generated from trained XGBoost model
def classify_structural(features: dict) -> tuple[str, float]:
    scores = [0.0] * 7
    # Tree 0
    if features["code_kw_ratio"] > 0.315:
        if features["semi_line_end"] > 0.42:
            scores[0] += 0.234  # source_code
        ...
    # Softmax → class + confidence
```

**Best when:** Tree model accuracy is sufficient. Zero-dependency deployment is required.

### 7.2 ONNX Runtime

Neural model exported to ONNX format. ~30MB runtime dependency (onnxruntime). 2-5ms inference. ~1-4MB model.

```python
import onnxruntime as ort
session = ort.InferenceSession("structural_classifier.onnx")
result = session.run(None, {"input": byte_tensor})
```

**Best when:** Neural model significantly outperforms tree model (>2% F1). Consumer accepts onnxruntime dependency.

### 7.3 Hybrid: Tree + Neural Features

Tree model with expanded feature set (40 original + N discovered features). No neural runtime dependency. <0.1ms inference. Best of both worlds.

**Best when:** Neural feature discovery yields a few high-value features expressible as simple functions. Most common outcome.

### 7.4 Decision Framework

```
After Phase 2 exploration:

Tree model with 40 features achieves X% F1
Tree model with 40 + CNN features achieves Y% F1
Tree model with 40 + CNN + RNN + Attention features achieves Z% F1
Best neural model (standalone) achieves W% F1

IF Z ≈ W (within 1%):
  → Deploy tree with expanded features (hybrid approach)
  → No neural runtime dependency
  → Discovery was successful — features captured the signal

IF W >> Z (>2% gap):
  → Neural model captures signals that can't be reduced to engineered features
  → Deploy via ONNX Runtime
  → Accept onnxruntime dependency

IF Y ≈ X (CNN features didn't help):
  → The 40 engineered features already capture the important signals
  → Stay with original tree model
  → Move on to other optimization opportunities
```

---

## 8. Architecture Search Methodology

### 8.1 N-gram Baseline (Always Run First)

Before any neural model, establish the simplest possible baseline:

```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(2, 6), max_features=5000)
X_ngram = vectorizer.fit_transform(training_texts)
lr = LogisticRegression(max_iter=1000)
```

If character n-grams + logistic regression matches or beats the tree model, we don't need neural networks at all — the features are already implicit in the data and simpler methods suffice. The n-gram model's weights are also directly inspectable:

```python
# Which n-grams predict which class?
for class_idx, class_name in enumerate(classes):
    top = sorted(zip(feature_names, lr.coef_[class_idx]), key=lambda x: -x[1])[:10]
    print(f"{class_name}: {[t[0] for t in top]}")
```

### 8.2 Neural Architecture Search (Optuna)

Search across all four families simultaneously:

```python
def objective(trial):
    arch = trial.suggest_categorical("architecture", 
        ["cnn", "rnn", "cnn_attention", "ssm_mamba", "distilled_modernbert"])
    
    if arch == "cnn":
        model = build_cnn(trial)
    elif arch == "rnn":
        model = build_rnn(trial)
    elif arch == "cnn_attention":
        model = build_cnn_attention(trial)
    elif arch == "ssm_mamba":
        model = build_mamba(trial)
    elif arch == "distilled_modernbert":
        model = build_distilled_student(trial, teacher="modernbert")
    
    train(model, train_data, epochs=10)  # quick training for search
    accuracy = evaluate(model, val_data)
    
    # Track model size (prefer smaller at similar accuracy)
    trial.set_user_attr("n_params", count_params(model))
    trial.set_user_attr("inference_ms", measure_inference(model))
    
    return accuracy

study = optuna.create_study(direction="maximize")
study.optimize(objective, n_trials=250)
```

This searches across architectures AND hyperparameters within each architecture. Optuna's TPE sampler learns which architecture family is most promising and allocates more trials to it.

### 8.3 Search Budget

| Phase | Trials | Time (CPU) | What It Finds |
|-------|--------|-----------|--------------|
| N-gram baseline | 1 | Minutes | Lower bound on character-pattern separability |
| CNN search | 50 | ~1 hour | Best local pattern architecture |
| RNN search | 50 | ~2 hours | Best sequential architecture |
| CNN+Attention search | 50 | ~2 hours | Best relational architecture |
| SSM/Mamba search | 50 | ~2 hours | Best state-space architecture |
| Cross-architecture | 50 | ~2 hours | Best overall architecture |
| **Total** | **~250** | **~9 hours** | Best architecture + hyperparameters |

All on CPU. No GPU required.

### 8.4 Pre-Trained Model Evaluation (Separate Track)

Pre-trained models are evaluated separately because they require different methodology (fine-tuning, not training from scratch):

```
Step 1: Layer probing (1 day)
  Fine-tune: ModernBERT-base, StarEncoder, CodeBERT, CodeT5-small
  For each: probe each layer with linear classifier
  → At which layer does the model reach our tree model's accuracy?

Step 2: Feature extraction comparison (1 day)
  Extract [CLS] embeddings from each frozen model
  Train XGBoost on 768-dim features
  → Which model's representations best separate our 7 classes?
  → How much gap vs. our 40 engineered features?

Step 3: Fine-tune best candidate (1 day)
  Full fine-tuning on our 7-class task
  → This is the ceiling — best possible accuracy from pre-trained knowledge

Step 4: Distillation to tiny student (1-2 days)
  Teacher: best fine-tuned pre-trained model
  Student: best architecture from Phase 2 Optuna search
  → Compare distilled student vs. trained-from-scratch student
```

---

## 9. Practical Implementation Plan

### Phase 1: Tree Model (Week 1) — Ship This

```
Day 1-2: Data collection (GitHub code, LogHub, Wikipedia prose)
Day 3:   Synthetic mixed-content generation (50K samples)
Day 4:   Feature extraction (40 features) + multi-model benchmark
Day 5:   Export winner as decision rules
Day 6-7: Integration testing + deployment
```

**Deliverable:** Structural classifier engine with >0.90 F1, <0.1ms inference, zero dependencies.

### Phase 2: Neural Feature Discovery (Week 2-3) — Optimize

```
Day 1:   N-gram baseline (set expectations)
Day 2-3: CNN architecture search + training (local pattern discovery)
Day 4:   RNN architecture search + training (sequential state discovery)
Day 5-6: CNN+Attention architecture search + training (relational discovery)
Day 7:   SSM/Mamba search (if RNN shows sequential models are promising)
Day 8:   Filter/state/attention inspection → feature candidates
Day 9:   Convert discoveries to engineered features
Day 10:  Retrain tree model with expanded features → measure improvement
```

**Deliverable:** Expanded tree model (40+N features) OR ONNX neural model. Feature discovery report.

### Phase 3: Pre-Trained Model Exploration (Week 4) — Leverage Existing Knowledge

```
Day 1:   Layer probing on ModernBERT-base and StarEncoder
         → At which layer does each model reach our tree model's accuracy?
Day 2:   Feature extraction comparison (frozen embeddings → XGBoost)
         → How much gap between pre-trained representations and our 40 features?
Day 3:   Fine-tune best candidate on our 7-class task
         → Accuracy ceiling from pre-trained knowledge
Day 4:   Attention analysis on fine-tuned model
         → Which heads specialize in code-prose boundaries?
Day 5:   Distillation to tiny student (if fine-tuned model significantly beats Phase 2)
         → Compare distilled student vs. trained-from-scratch
```

**Deliverable:** Assessment of whether pre-trained models add value. If yes, distilled student model. If no, confirmation that Phase 2 results are sufficient.

### Phase 4: SSM Deep Dive (Optional, Week 5) — Only If Justified

Only pursue if Phase 2 shows sequential models (RNN) outperform attention for boundary detection:

```
Day 1-2: Implement Mamba-based boundary detector
Day 3:   Compare with RNN and CNN+Attention boundary detectors
Day 4:   State transition analysis for feature discovery
Day 5:   Decision: SSM boundary detector vs. existing solution
```

**Deliverable:** SSM-based boundary detector if it outperforms alternatives. Otherwise, skip.

### Phase 5: Continuous Improvement (Ongoing)

```
Collect runtime events with features → accumulate labeled examples via consumer feedback
Monthly retrain: tree model on expanded dataset
Quarterly: re-run neural feature discovery on accumulated data
Annual: re-evaluate architecture choices, check for new pre-trained code models
```

---

## 10. Recommendations

### Primary Recommendation: Ship Tree Model, Explore Neural Discovery, Evaluate Pre-Trained

**Ship immediately (Phase 1):** The tree model on 40 engineered features is production-ready. It handles the common cases well, has zero dependencies, and provides the foundation for everything else.

**Explore on a parallel track (Phase 2):** Run the neural architecture search across all four families (CNN, RNN, Attention, SSM). The cost is ~2 weeks and the potential upside is significant — discovering features we haven't thought of.

**Evaluate pre-trained models (Phase 3):** ModernBERT-base and StarEncoder are the top candidates. The layer probing experiment (1 day) definitively answers whether pre-trained representations add value over our engineered features. If yes, distillation compresses that value into a deployable-size model.

**Don't pre-commit to an architecture.** Let the data decide. The Optuna search across all families plus the pre-trained model evaluation gives us a complete picture.

### Architecture Predictions (Informed Guesses)

Based on the properties of our problem:

1. **ModernBERT-base fine-tuned will set the accuracy ceiling.** 149M parameters trained on 2T tokens with 8192 context — it will likely be the most accurate model we test. The question is whether we can match that accuracy with something smaller.

2. **CNN+Attention hybrid will be the best small architecture** for combined classification + boundary detection. Local CNN filters catch character patterns. Cross-line attention catches relationships. Both are needed.

3. **SSM/Mamba may be best for boundary detection specifically** because boundary = state transition, which is exactly what SSMs model. But only if Phase 2's RNN experiments show sequential models outperform attention for this task.

4. **CNN will yield the most actionable feature discoveries** because its filters are the most directly inspectable and convertible to engineered features.

5. **The expanded tree model (40 + discovered features) will likely match or approach pre-trained model accuracy** for block classification. For boundary detection, neural models may retain an edge.

6. **StarEncoder's PII detection proof-of-concept validates** using code encoders for our secret detection problem. Worth exploring even if ModernBERT wins on structural classification.

### Deployment Prediction

Most likely outcome: **tree model with expanded features for block classification** (zero dependencies, <0.1ms) + **ONNX-deployed CNN+Attention for boundary detection** (onnxruntime dependency, 5-10ms). This gives the best accuracy where it matters most (boundaries are harder than blocks) while keeping the block classifier maximally lightweight.

### What We Don't Know Yet

- Whether the 40 engineered features already capture most of the signal (Phase 2 answers this)
- Which neural architecture family performs best on our specific data distribution
- Whether pre-trained code models add value beyond training from scratch
- Whether relational features (from attention) are convertible to discrete engineered features or require keeping the neural model
- Whether the boundary detection problem is better served by the RNN's per-position output or the attention model's per-chunk output

All of these are empirical questions. The plan is designed to answer them systematically.

---

## 11. Dependencies Summary

### Phase 1 (Tree Model — Production)

```
# Runtime (classification library)
None — decision rules are pure Python

# Training (ml_pipeline/)
scikit-learn
xgboost
lightgbm
catboost
optuna
pandas
numpy
datasets (HuggingFace — for data collection)
```

### Phase 2 (Neural Feature Discovery — Research)

```
# Training only (ml_pipeline/, not runtime)
torch>=2.0
onnx
onnxruntime  (for export validation)
mamba-ssm    (for SSM experiments, optional)
```

### Phase 2 Deployment (if neural model wins)

```
# Runtime (classification library — only if ONNX path chosen)
onnxruntime>=1.16  (~30MB, C++ inference, no PyTorch)
```

### Phase 3 (Pre-Trained Model Exploration)

```
# Training only
transformers (HuggingFace — for ModernBERT, StarEncoder, CodeBERT, CodeT5)
```

---

## 12. Decisions Log

| ID | Decision | Status |
|----|----------|--------|
| D23 | Multi-model benchmark for tree classifier (XGBoost, LightGBM, CatBoost, RF) via Optuna | **Decided** |
| D24 | Sliding window boundary detection (reuses block classifier) | **Decided** — may be superseded by RNN/SSM/attention in Phase 2 |
| D25 | Deterministic secret scanner (parsers + key-name + entropy) | **Decided** — no ML needed |
| D26 | Ship heuristics first, ML second | **Decided** |
| D27 | Neural feature discovery uses all four families (CNN, RNN, Attention, SSM) | **Proposed** — pending Phase 2 |
| D28 | CNN+Attention hybrid as primary architecture candidate | **Proposed** — pending benchmark |
| D29 | ModernBERT-base as primary pre-trained candidate; StarEncoder as code-specific backup | **Proposed** — pending Phase 3 probing |
| D30 | Pre-trained model exploration as Phase 3 (ModernBERT too promising to skip) | **Proposed** — pending probing results |
| D31 | ONNX Runtime for neural model deployment if needed | **Proposed** — only if neural model significantly beats expanded tree |
| D32 | SSM exploration conditional on Phase 2 RNN results | **Proposed** — only if sequential models outperform attention for boundaries |
