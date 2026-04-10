# Research Summary: Prompt Intent Classification & Data Leakage Detection

**Compiled:** April 2026  
**Scope:** Academic papers and industry research on classifying user intent in LLM prompts, detecting data leakage, and zone-aware prompt analysis (2019–2026)

---

## 1. Instruction-Data Separation (The Foundation)

### "Can LLMs Separate Instructions from Data?" — Willison et al., ICLR 2025

This paper formalizes the core problem our module addresses. The authors define a language model as a mapping `g : A* × A* → M(A*)` with distinct instruction and data arguments, and prove that current LLMs fail to enforce this separation. The paper demonstrates that models treat all input as an undifferentiated token stream — instructions and data are processed identically. This causes models to mistakenly execute instructions embedded in data (prompt injection) or treat data as instructions (unintended behavior). The formal framework establishes instruction-data separation as a measurable property, not just a design aspiration.

**Relevance to our module:** Validates zone segmentation as a real, formally-defined problem. Our module performs this separation externally — analyzing prompts before they reach the LLM to identify what is instruction vs. pasted data.

### "Improving LLM Safety with Instructional Segment Embedding" — Chen et al., ICLR 2025

Proposes an architectural solution: learned segment embeddings that classify each token by its role (system=0, user=1, data=2), inspired by BERT's segment embeddings. Applied during supervised fine-tuning, ISE enables models to distinguish and prioritize instructions based on privilege level. Experiments on Llama-2-13B and Llama-3-8B show effectiveness across five training datasets and four vulnerability types.

**Relevance:** Proves that segment/zone awareness improves LLM safety. Our approach achieves the same awareness externally rather than modifying the LLM architecture.

---

## 2. Prompt Leakage Intent Detection

### "I've Decided to Leak": Probing Internals Behind Prompt Leakage Intents — Dong et al., EMNLP 2025

**Key finding:** A simple linear probe can predict prompt leakage risks from pre-generation hidden states — without generating any tokens — achieving 90%+ AUROC across all tested models (including GPT-4o, Llama, Qwen). The authors define "prompt leakage intent" as a latent binary variable and develop a hybrid labeling pipeline to identify broader leakage behaviors beyond verbatim leaks. The probes generalize to new system prompts and attacks not seen during training.

**Relevance:** Demonstrates that intent to leak can be detected before generation occurs. This is the closest existing work to our intent classification approach — but it operates on model internals (hidden states), while our module operates on the prompt text externally. Both validate that intent is a detectable, classifiable signal.

### PromptKeeper: Safeguarding System Prompts for LLMs — EMNLP Findings 2025

Proposes a framework for detecting prompt leakage by comparing model responses against a zero-leakage baseline using likelihood ratio tests. Identifies side-channel attacks where denial-of-service responses themselves leak information about the system prompt. Evaluated on 79 real system prompts from deployed GPT services.

**Relevance:** Addresses the output side of prompt leakage (detecting leaked content in responses). Complementary to our input-side approach (detecting sensitive data in prompts before they reach the LLM).

---

## 3. Intent-Based Defense Paradigms

### IntentGuard: Mitigating Indirect Prompt Injection via Instruction-Following Intent Analysis — OpenReview 2025 (submitted to top venue)

The decisive insight: the critical factor in prompt injection is not the presence of malicious text, but whether the LLM intends to follow instructions from untrusted data. IntentGuard uses an instruction-following intent analyzer (IIA) that identifies which parts of an input prompt the model recognizes as actionable instructions, then flags overlaps with untrusted data segments. Uses three "thinking intervention" strategies with reasoning-enabled LLMs: start-of-thinking prefilling, end-of-thinking refinement, and adversarial in-context demonstration. Reduces attack success rates from 100% to 8.5% on Mind2Web scenarios.

**Relevance:** Directly validates our zone segmentation + intent classification approach. IntentGuard operates inside the LLM's reasoning process; our module operates externally on the prompt text. Both use intent analysis to distinguish safe from dangerous prompts.

### Intent-Based Defense Paradigm (IBD) — Referenced in Ferrag et al., ScienceDirect 2025

Proposes that LLMs can identify harmful intents in compositional jailbreak attacks, significantly reducing attack success rate by over 74%. Uses the CIAQA dataset (2.7K questions from 900 successful jailbreaks) to demonstrate that LLMs fail to properly discern underlying harmful intent and to prioritize tasks effectively — but that explicit intent analysis can overcome this.

**Relevance:** Validates intent classification as a security-relevant capability with measurable effectiveness. The 74% reduction in attack success through intent analysis is a concrete benchmark for the value of our intent classification pipeline.

### Defending against Indirect Prompt Injection by Instruction Detection — Wen et al., EMNLP Findings 2025

Proposes InstructDetector: uses hidden state features and gradient features fused together to detect whether text within a prompt is an instruction or data. Trains on paired examples of legitimate content vs. injection attempts. Evaluated on the BIPIA benchmark.

**Relevance:** Another approach to instruction-data separation that operates on model internals. Validates the same fundamental problem our zone segmenter addresses, but our approach works without access to model internals.

---

## 4. Prompt Attack Detection Methods

### Prompt Attack Detection with LLM-as-a-Judge and Mixture-of-Models — Le et al., arXiv March 2026

Proposes structured chain-of-thought reasoning for prompt attack detection. The judge is required to explicitly deconstruct user intent, verify safety signals, assess potential harm, and perform self-reflection before committing to a verdict. This structured CoT approach outperforms binary classification ("Yes/No") prompting for grey-area inputs. The paper also proposes a Mixture-of-Models voting ensemble combining multiple LLM judges for improved robustness.

**Key architectures compared:**
- Lightweight encoder classifiers (DeBERTa-based) — fast but lack reasoning for nuanced attacks
- Prompt Guard 2 (Meta, 2025) — transformer encoder for sequence classification
- ProtectAI model (2024) — embeddings + XGBoost
- LLM-as-a-Judge with structured CoT — highest accuracy but slowest

**Relevance:** Directly maps to our intent classification tier strategy. We use the same cascade: fast encoder-based classifiers first (GLiNER2, NLI), structured CoT reasoning (SLM) for ambiguous cases. The paper validates this tiered approach.

### PromptArmor: Simple yet Effective Prompt Injection Defenses — Shi et al., arXiv July 2025

Evaluates using a generalist LLM as a guardrail to analyze intent before downstream processing. Tests GPT-3.5-Turbo, GPT-4o, GPT-4.1, and o4-mini as guardrail LLMs. Finds that lightweight defenses are often bypassed by adaptive attacks, while LLM-based intent analysis provides stronger protection.

**Relevance:** Validates the LLM-as-intent-analyzer approach (our Tier 6) but highlights cost and latency concerns — which is why our architecture uses it as a last resort after cheaper methods.

### Lessons from Defending Gemini Against Indirect Prompt Injections — Google DeepMind, May 2025

Google's internal report on defending Gemini against prompt injection. Key insight: the main challenge is maintaining user intent when malicious instructions are embedded within retrieved data. Evaluates four in-context defenses and finds that placement of defensive instructions matters more than their content. Warning-based defenses placed before untrusted data outperform post-hoc defenses.

**Relevance:** Validates that distinguishing trusted instructions from untrusted data (our zone segmentation) is a recognized, unsolved problem even at Google's scale.

---

## 5. Zero-Shot Classification Methods

### "Benchmarking Zero-shot Text Classification: Datasets, Evaluation and Entailment Approach" — Yin et al., EMNLP 2019

The foundational paper for NLI-based zero-shot classification. Frames text classification as a Natural Language Inference (entailment) problem: "Does this text entail the hypothesis [label description]?" Enables classification against arbitrary labels without training data. BART-MNLI (~400M parameters) is the standard implementation.

**Relevance:** Foundation for our NLI intent verification tier (Tier 4). Any natural-language intent label works immediately — no training data needed for new intents.

### GLiNER2: Schema-Driven Multi-Task Learning for Structured Information Extraction — Zaratiana et al., EMNLP 2025

A unified 205M parameter model performing NER, text classification, and structured data extraction through a schema-driven interface. Maintains CPU efficiency while enabling multi-task composition in a single forward pass. Competitive with LLM-based alternatives at a fraction of the cost.

**Relevance:** The unified model we use for content NER + intent classification + zone extraction. The paper demonstrates that a single small model can serve all three tasks our prompt module needs.

### Soft Contextualized Encoder for User Defined Text Classification — Maheshwari & Raina, arXiv January 2026

Proposes a dual-encoder architecture (RoBERTa + jina-embedding-v3, ~680M combined) that outperforms or matches LLMs on zero-shot text classification across unseen domains. Demonstrates that encoder-based approaches remain competitive with much larger models for classification tasks.

**Relevance:** Validates our architectural choice of using encoder-based models (GLiNER2, NLI) rather than full LLMs for intent classification — smaller models can match LLM accuracy at lower cost.

---

## 6. Enterprise Data Leakage Landscape

### LayerX Enterprise AI and SaaS Data Security Report 2025

Updated 2025 data (original report cited 18%; updated figures are higher): 77% of employees paste data into GenAI tools. 82% of that activity happens through personal accounts. GenAI accounts for 32% of all corporate-to-personal data exfiltration, making it the #1 vector. On average, employees make 46 pastes per day. Small volumes still carry big risks — three sensitive entries per day into ChatGPT compound exposure.

**Relevance:** Quantifies the scale of the problem. The shift from 18% (2024 initial report) to 77% (2025 updated report) shows the problem is accelerating. Our module addresses the highest-volume exfiltration channel.

### Context-Based Access Control (CBAC) — Lasso Security, August 2024

Introduces CBAC for RAG security: dynamic access decisions based on user identity, behavior, and data type. Unlike RBAC (role-based) or ABAC (attribute-based), CBAC evaluates the context of each request at the moment the agent asks, based on who's asking, why, and what context they're operating in. Demonstrated with finance team members blocked from R&D data even when using the same GenAI tool.

**Relevance:** Our risk cross-correlation engine implements a similar concept: access/risk decisions based on content × intent × zone context, not just content patterns. CBAC validates the approach for internal RAG systems; we extend it to monitoring prompts sent to external LLMs.

### CSA (Cloud Security Alliance): How to Build AI Prompt Guardrails — December 2025

Industry guidance establishing that prompt guardrails are not just content filters — they form a multilayered security architecture. DLP is the starting point, but AI-focused DLP requires context-aware, adaptive approaches because GenAI prompts are inherently conversational. Classification metadata (sensitivity labels) should be the primary enforcement signal, not just content inspection.

**Relevance:** Validates our multi-layer approach (content + intent + zones) over content-only DLP. The CSA explicitly states that "without classification and labeling, guardrails are blind."

---

## 7. Research Gaps Our Module Addresses

| Gap | Current State | Our Approach |
|-----|--------------|-------------|
| **Zone segmentation** from outside the model | ISE modifies the LLM (ICLR 2025). IntentGuard uses reasoning-enabled LLMs. InstructDetector uses model internals. | External heuristic + GLiNER2 extraction — no model access needed |
| **Intent classification for data leakage** (not security attacks) | All existing work focuses on malicious intent (jailbreaks, injection). None classifies benign user intents (document_rewrite, code_debug) for data risk. | 10-category taxonomy of data-handling intents with risk mapping |
| **Content × intent × zones convergence** | DLP does content-only. Guardrails do intent-only (is this an attack?). No system combines all three. | Risk cross-correlation engine with zone-weighted sensitivity |
| **Tiered intent classification** | Binary (LLM-as-Judge: safe/unsafe) or single-model approaches. | 6-tier cascade: keywords → GLiNER2 → embeddings → NLI → SLM → LLM |
| **Consumer-extensible intent taxonomy** | Fixed attack categories in security tools. | Zero-shot labels — consumers add custom intents without retraining |

---

## 8. Complete Reference List

### Peer-Reviewed Conference Papers

| # | Paper | Venue | Year | Key Contribution |
|---|-------|-------|------|-----------------|
| 1 | "Can LLMs Separate Instructions from Data?" | ICLR | 2025 | Formal framework for instruction-data separation |
| 2 | "Instructional Segment Embedding" | ICLR | 2025 | Token-level role classification (system/user/data) |
| 3 | "Instruction-Following in LLMs" (linear probe study) | ICLR | 2025 | Hidden state separability for instruction-following |
| 4 | "I've Decided to Leak" — Probing Prompt Leakage Intents | EMNLP | 2025 | Linear probes predict leakage intent at 90%+ AUROC |
| 5 | PromptKeeper: Safeguarding System Prompts | EMNLP Findings | 2025 | Likelihood-ratio detection of prompt leakage |
| 6 | Defending against IPI by Instruction Detection | EMNLP Findings | 2025 | Hidden state + gradient features for instruction detection |
| 7 | GLiNER2: Schema-Driven Multi-Task Learning | EMNLP Demos | 2025 | Unified NER + classification + extraction, 205M, CPU |
| 8 | GLiNER: Generalist Model for NER | NAACL | 2024 | Zero-shot NER via bidirectional transformer encoder |
| 9 | "Benchmarking Zero-shot Text Classification" | EMNLP | 2019 | NLI-based zero-shot classification foundation |
| 10 | The Dangers of IPI on LLM Web Agents | EMNLP Demos | 2025 | GCG-optimized triggers for web agent attacks |
| 11 | PLeak: Prompt Leaking Attacks | ACM CCS | 2024 | Automated prompt extraction via adversarial optimization |
| 12 | "Exploring Vulnerability of Content Moderation via Intent Manipulation" | EMNLP Findings | 2025 | Intent manipulation bypasses content moderation |
| 13 | Defense Against Prompt Injection by Leveraging Attack Techniques | ACL | 2025 | Defense methods designed from attack technique analysis |
| 14 | Prompt Injection Attacks: Comprehensive Review | MDPI Information | 2026 | 128-study synthesis, PALADIN defense-in-depth strategy |
| 15 | StruQ: Defending with Structured Queries | USENIX Security | 2025 | Fine-tuning to separate instructions from injected content |
| 16 | Instruction Hierarchy | OpenAI / arXiv | 2024 | Training methodology for instruction privilege levels |
| 17 | Leaky Thoughts: Large Reasoning Models Are Not Private | EMNLP | 2025 | Reasoning traces increase privacy leakage in LRMs |

### Preprints and Technical Reports

| # | Paper | Source | Year | Key Contribution |
|---|-------|--------|------|-----------------|
| 18 | IntentGuard: Instruction-Following Intent Analysis | OpenReview | 2025 | Intent analyzer identifies actionable instructions in prompts |
| 19 | Prompt Attack Detection with LLM-as-a-Judge | arXiv | 2026 | Structured CoT reasoning for prompt attack detection |
| 20 | PromptArmor: Simple yet Effective Defenses | arXiv | 2025 | LLM-based intent analysis as guardrail |
| 21 | Lessons from Defending Gemini Against IPI | Google DeepMind | 2025 | Layered defense strategies, adaptive attack evaluation |
| 22 | Defense Against IPI via Tool Result Parsing | arXiv | 2025 | ParseData + CheckTool for sanitizing tool results |
| 23 | Log-To-Leak: Prompt Injection via MCP | OpenReview | 2025 | Tool invocation attacks through Model Context Protocol |
| 24 | Automating Prompt Leakage Attacks Using Agentic Approach | arXiv | 2025 | Agent-based collaborative prompt leakage probing |
| 25 | RTBAS: Defending LLM Agents Against Prompt Injection and Privacy Leakage | arXiv | 2025 | Runtime defense for LLM agents |
| 26 | Soft Contextualized Encoder for User Defined Text Classification | arXiv | 2026 | Dual-encoder outperforms LLMs on zero-shot classification |
| 27 | The Million-Label NER: Breaking Scale Barriers with GLiNER bi-encoder | arXiv | 2026 | Scaling GLiNER to million+ labels |

### Industry Reports and Frameworks

| # | Source | Year | Key Contribution |
|---|--------|------|-----------------|
| 28 | OWASP LLM Top 10 2025 — LLM02: Sensitive Information Disclosure | 2025 | Framework for LLM data leakage risks |
| 29 | OWASP LLM Top 10 2025 — LLM07: System Prompt Leakage | 2025 | Prompt extraction threat classification |
| 30 | LayerX Enterprise AI and SaaS Data Security Report | 2025 | 77% of employees paste data into GenAI; #1 exfiltration vector |
| 31 | Lasso Security CBAC for RAG Security | 2024 | Context-Based Access Control for GenAI |
| 32 | CSA: How to Build AI Prompt Guardrails | 2025 | Multi-layered prompt security architecture guidance |
| 33 | Prompt Hacking in LLMs 2024-2025 Literature Review | 2025 | Comprehensive synthesis of prompt attack/defense research |

---

## 9. Pre-Trained Models for Structural Detection (Verified April 2026)

Research into pre-trained encoder models suitable for our structural content classifier, boundary detector, and secret scanner.

### ModernBERT — Warner et al., arXiv December 2024

**Paper:** "Smarter, Better, Faster, Longer: A Modern Bidirectional Encoder for Fast, Memory Efficient, and Long Context Finetuning and Inference"

Modernized BERT architecture: 149M (base) / 395M (large) parameters, 8192 token context, trained on 2T tokens. Uses RoPE, GeGLU, FlashAttention, alternating global/local attention (every 3rd layer global, others 128-token sliding window), unpadding. Apache 2.0 license.

**Verified benchmarks:** SOTA on GLUE, outperforms DeBERTaV3 at 1/5 memory and 2-3x speed. Code understanding: 56.4 (base) vs RoBERTa 44.3 on StackOverflow-QA. Code retrieval: 73.6 (base), 83.9 (large) vs BERT-large 60.8. Few-shot (SetFit): 92.7% accuracy with 8 samples per class on IMDB.

**Relevance:** Top candidate for Phase 3 pre-trained model evaluation. Strong code understanding without code-specific training. Compatible with GliNER and Sentence-Transformers.

### ModernBERT vs DeBERTaV3 — Antoun et al., IJCNLP 2026

**Paper:** "ModernBERT or DeBERTaV3? Examining Architecture and Data Influence on Transformer Encoder Models Performance"

Finds that data quality matters more than architecture differences between ModernBERT and DeBERTaV3. A DeBERTaV3 trained on higher-quality filtered data can approach ModernBERT performance. Implication: our training data quality will matter more than encoder choice.

### StarEncoder / StarPii — BigCode Project, 2023

**Model card:** `bigcode/starencoder`, `bigcode/starpii` on HuggingFace

StarEncoder: ~125M parameter encoder trained on 86 programming languages from The Stack (~400B tokens). MLM + NSP objectives. 1024 token context. OpenRAIL-M license.

StarPii: StarEncoder fine-tuned for PII/secret NER in code. 6 classes: Names, Emails, Keys, Passwords, IP addresses, Usernames. Trained on 20,961 annotated secrets across 31 languages. Key finding: high false positive rate for Keys and Passwords required retaining only entities with trigger words ("key", "auth", "pwd") in surrounding context. Post-processing: ignore secrets <4 chars, keys <9 chars, gibberish detection on values.

**Relevance:** Directly validates our Structured Secret Scanner's key-name scoring approach. StarPii's false positive mitigation strategy (context trigger words + length thresholds + gibberish detection) mirrors our design.

### Mamba — Gu & Dao, COLM 2024

**Paper:** "Mamba: Linear-Time Sequence Modeling with Selective State Spaces"

Introduces selective state space models with input-dependent state transitions. O(n) complexity vs Transformer's O(n²). Hardware-aware parallel algorithm. At 3B scale, outperforms Transformers of same size and matches Transformers at 2x size.

**Relevance:** SSMs are theoretically ideal for boundary detection (state transitions = content type changes). The selective mechanism means the model decides what to remember based on current input.

### Mamba-2 / SSD — Dao & Gu, arXiv May 2024

**Paper:** "Transformers are SSMs: Generalized Models and Efficient Algorithms Through Structured State Space Duality"

Proves SSMs and attention are mathematical duals. The SSD layer has a ~30-line minimal PyTorch implementation. Enables parallel training via matrix operations.

### Mamba-3 — Lahoti et al., OpenReview October 2025 (published March 2026)

**Paper:** "Mamba-3: Improved Sequence Modeling using State Space Principles Through Structured State Space Duality"

Three improvements: (1) more expressive recurrence from SSM discretization, (2) complex-valued state updates for richer state tracking, (3) MIMO formulation for improved performance without increased decode latency. At 1.5B scale, 1.8 point accuracy improvement over Gated DeltaNet. Comparable perplexity to Mamba-2 with half the state size.

**Relevance:** Complex-valued states could represent both "content type" and "transition confidence" simultaneously — directly useful for boundary detection.

### CodeSSM Interpretability — arXiv February 2026

**Paper:** "Towards Understanding What State Space Models Learn About Code"

First interpretability study of SSMs for code understanding. Shows CodeSSM (BiGS encoder-only architecture) outperforms comparable Transformer baselines (RoCoder) on retrieval and classification with superior compute efficiency. Introduces SSM-Interpret for frequency-domain analysis of learned kernels.

**Critical finding:** SSM representations degrade between pre-training and fine-tuning. This suggests distillation from a frozen CodeSSM may work better than direct fine-tuning for our structural classification task.

### Complete Pre-Trained Model Reference List

| # | Model / Paper | Venue | Year | Key Contribution |
|---|--------------|-------|------|-----------------|
| 34 | ModernBERT (base + large) | arXiv | 2024 | SOTA encoder, 8192 ctx, 2T tokens, Apache 2.0 |
| 35 | ModernBERT vs DeBERTaV3 | IJCNLP | 2026 | Data quality > architecture for encoder comparison |
| 36 | StarEncoder | BigCode | 2023 | Code encoder, 86 languages, ~125M params |
| 37 | StarPii | BigCode | 2023 | PII/secret NER in code, 6 classes, 20K+ annotated secrets |
| 38 | Mamba | COLM | 2024 | Selective SSM, O(n), input-dependent state transitions |
| 39 | Mamba-2 / SSD | arXiv | 2024 | SSM-attention duality, parallel training |
| 40 | Mamba-3 | OpenReview | 2025/2026 | Complex-valued states, MIMO, half state size |
| 41 | CodeSSM interpretability | arXiv | 2026 | SSMs for code; representation degradation during fine-tuning |
| 42 | CodeBERT | EMNLP | 2020 | Code+prose encoder, attention for boundaries |
| 43 | UniXcoder | ACL | 2022 | AST-aware code encoder |
| 44 | CodeT5-small | EMNLP | 2021 | Identifier-aware encoder-decoder, 60M |
| 45 | BioClinical ModernBERT | arXiv | 2025 | Domain-specific ModernBERT; validates domain adaptation approach |
