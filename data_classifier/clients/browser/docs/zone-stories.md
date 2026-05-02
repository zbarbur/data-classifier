# Zone Detection Stories

Annotated examples showing how the zone detector classifies structured content in real user prompts. The tester page includes all stories; the ones documented below demonstrate each detection method and zone type.

To see the actual prompts, use the tester page (`npm run serve`, then open `http://localhost:4173/tester/` and select "Zones (real)" or "Zones (showcase)" from the category selector). Prompts are XOR-encoded and decoded client-side.

## Showcase Stories (Synthetic)

Clean, short examples (10-30 lines) demonstrating each zone type. These are the best way to understand what each zone type looks like.

---

### Fenced Python code block

**ID:** `zone_showcase_python_fenced`

- **Zone type:** `code`
- **Language:** `python`
- **Method:** `structural_fence`
- **Confidence:** 0.95
- **Lines:** 2-11

> A `` ```python `` fenced block containing a sort function. The structural detector identifies the fence markers and maps the `python` tag to `code` zone type. Highest confidence (0.95) because the fences are explicit delimiters.

---

### JSON config (fenced)

**ID:** `zone_showcase_json_config`

- **Zone type:** `config`
- **Language:** `json`
- **Method:** `structural_fence`
- **Confidence:** 0.95
- **Lines:** 2-18

> A `` ```json `` fenced block containing a webpack configuration. The structural detector maps the `json` tag to `config` zone type via `lang_tag_map`. Note: unfenced JSON objects require valid JSON parsing and may not be detected if they contain JavaScript-specific syntax (regex literals, trailing commas).

---

### HTML with embedded script and style

**ID:** `zone_showcase_html_markup`

- **Zone types:** `code` (CSS), `markup` (HTML), `code` (JavaScript)
- **Method:** `structural_delimiter`
- **Confidence:** 0.90
- **3 blocks detected**

> An HTML page with `<style>` and `<script>` sections. The structural detector identifies three zones: CSS within `<style>` tags (code), the HTML body (markup), and JavaScript within `<script>` tags (code). Delimiter-pair detection fires for `<script>` and `<style>` specifically.

---

### SQL query in fenced block

**ID:** `zone_showcase_sql_query`

- **Zone type:** `query`
- **Language:** `sql`
- **Method:** `structural_fence`
- **Confidence:** 0.95
- **Lines:** 2-12

> A `` ```sql `` fenced block with a SELECT/JOIN query. The `sql` tag maps to `query` zone type. This is one of the specialized zone types that distinguishes database queries from general code.

---

### Bash commands in fenced block

**ID:** `zone_showcase_bash_cli`

- **Zone type:** `cli_shell`
- **Language:** `bash`
- **Method:** `structural_fence`
- **Confidence:** 0.95
- **Lines:** 2-9

> Docker + kubectl deployment commands in a `` ```bash `` fence. Maps to `cli_shell` zone type. Shell commands are distinguished from code because they represent a different security context (command injection vs code injection).

---

### Python stack trace

**ID:** `zone_showcase_error_output`

- **Zone type:** `error_output`
- **Language:** `python`
- **Method:** `negative_filter`
- **Confidence:** 0.95
- **Lines:** 2-12

> A Python traceback. The syntax scorer initially classifies this as code (it has file paths, line numbers, function names). The negative filter step then reclassifies it as `error_output` based on the `Traceback (most recent call last):` pattern and `File "..." line N` structure.

---

### Unfenced Python code in prose

**ID:** `zone_showcase_unfenced_code`

- **Zone type:** `code`
- **Language:** `python`
- **Method:** `syntax_scoring`
- **Confidence:** 0.95
- **Lines:** 1-18

> Python functions embedded directly in prose without ``` fences. This is the hardest case — the syntax scorer must distinguish code from surrounding text using keyword density, indentation patterns, bracket balance, and operator frequency. The 3-pass scoring pipeline (raw features → context smoothing → comment bridging) handles the transition between prose and code.

---

### Pure prose (no zones)

**ID:** `zone_showcase_pure_prose`

- **Zone types:** none
- **0 blocks detected**

> A question about software architecture with no code, config, or markup. The pre-screen step detects no code indicators and returns immediately with empty blocks. This is the fast path — 97% of pure prose prompts are rejected in <0.1ms.

---

## Real-World Stories (WildChat Corpus)

13 curated prompts from the 647-record human-reviewed WildChat corpus. These are actual user prompts submitted to ChatGPT, showing the detector working on messy, multilingual, real-world input.

### Categories

| Category | Count | What it demonstrates |
|----------|-------|---------------------|
| Fenced (tagged) | 2 | Code blocks with language tags (Mermaid diagrams, structured JSON) |
| Fenced (untagged) | 1 | Chinese-language prompt with unfenced code in a ``` block |
| Unfenced code | 3 | Django models, Firebase/Java, C# — code without fences |
| Config/multi-block | 3 | Express.js apps, HTML+CSS+JS, JSON APIs — multiple zone types per prompt |
| Markup | 2 | XML extraction, HTML modification with Farsi text |
| Pure prose | 2 | AI prompt generation, OS theory question — no zones |

### Highlighted Stories

---

#### Django models (unfenced code)

**ID:** `zone_unfenced_code_000e1ecd` | 16 lines | 1 code block

> English prompt: "In django, I have the following models:" followed by unfenced Python class definitions. The syntax scorer identifies `class`, `models.Model`, `name=`, and indentation as code signals. A clean example of unfenced code detection in a short prompt.

---

#### Firebase Java code (unfenced)

**ID:** `zone_unfenced_code_003f0541` | 24 lines | 1 code block

> Java/Firebase code pasted directly into the prompt without fences. Contains `CollectionReference`, method calls, and `.get()` chains. The syntax scorer handles Java's verbose style (long identifiers, dot access chains) correctly.

---

#### Express.js full-stack app (multi-block)

**ID:** `zone_config_0062813a` | 350 lines | 3 blocks (code + markup + code)

> Russian-language prompt with a complete Express.js application. Three distinct zones detected: server-side JavaScript, HTML templates, and client-side JavaScript. Demonstrates multi-block detection in a long, real-world prompt.

---

#### HTML modification with Farsi (markup + code)

**ID:** `zone_markup_027fa905` | 205 lines | 6 blocks

> Request to modify an HTML page, written partly in Farsi. Contains `<!DOCTYPE html>`, CSS styles, JavaScript event handlers, and HTML structure. The detector correctly identifies 6 separate zones: markup sections, CSS code, and JavaScript code. Demonstrates handling of RTL scripts mixed with code.

---

#### Pure prose — AI prompt generation

**ID:** `zone_pure_prose_00e27fe1` | 35 lines | 0 blocks

> A meta-prompt asking an AI to generate images. No code, no markup, no config. Pre-screen rejects it immediately. Demonstrates the false-positive avoidance — even though the prompt mentions technical concepts, no zones are emitted.

---

## Story File Format

Stories are stored as JSONL (one JSON object per line) with XOR-encoded prompts:

```json
{
  "id": "zone_showcase_python_fenced",
  "title": "Fenced Python code block",
  "prompt_xor": "xor:base64-encoded-xor-text...",
  "annotation": "Tagged fenced block — high confidence structural detection.",
  "expected_zones": [
    {
      "zone_type": "code",
      "start_line": 2,
      "end_line": 11
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `id` | Unique story identifier |
| `title` | Human-readable title shown in tester dropdown |
| `prompt_xor` | XOR-encoded prompt text (key `0x5a`, base64, prefixed `xor:`) |
| `annotation` | Contextual note shown in tester page |
| `expected_zones` | Ground truth zone blocks (from Rust detector output) |

The `expected_zones` are generated by running each prompt through the Rust native detector, not hand-annotated. This guarantees the ground truth matches the WASM detector output (100% parity).

## File Locations

| File | Content | Used by |
|------|---------|---------|
| `tester/corpus/zone-showcase.jsonl` | 8 synthetic showcase examples | Tester dropdown, documentation |
| `tester/corpus/zone-real.jsonl` | 13 curated real WildChat prompts | Tester dropdown |
| `tests/e2e/zone-stories.jsonl` | 20 real WildChat prompts (test suite) | Playwright e2e tests |
