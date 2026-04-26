# API Reference

## `createScanner(opts?)`

Create a scanner instance with a Web Worker pool.

```js
import { createScanner } from '@data-classifier/browser';
const scanner = createScanner();
```

### Parameters

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `poolSize` | `number` | `2` | Number of Web Workers in the pool |
| `spawn` | `() => Worker` | (built-in) | Custom worker factory — override for Chrome extension integration |

### Returns

A `Scanner` object with `.scan()` and `.onServiceWorkerSuspend()`.

### Chrome extension example

```js
const scanner = createScanner({
  spawn: () => new Worker(
    chrome.runtime.getURL('worker.esm.js'),
    { type: 'module' }
  ),
});
```

---

## `scanner.scan(text, opts?)`

Scan text for secrets and code zones. Returns findings, zone blocks, and redacted text.

```js
const { findings, zones, redactedText, scannedMs } = await scanner.scan(text);
```

### Parameters

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `secrets` | `boolean` | `true` | Run secret detection (Rust/WASM: regex + secret_scanner + opaque_token passes, 24 validators) |
| `zones` | `boolean` | `true` | Run zone detection (Rust/WASM: code/markup/config classification). First call lazy-loads the WASM module (~15-25ms init) |
| `timeoutMs` | `number` | `5000` (zones) / `100` (secrets-only) | Worker kill budget (ms). Higher default when zones enabled to allow WASM init |
| `failMode` | `'open' \| 'closed'` | `'open'` | `open`: resolve with empty findings on timeout. `closed`: reject with `{ code: 'TIMEOUT' }` |
| `redactStrategy` | `'type-label' \| 'asterisk' \| 'placeholder' \| 'none'` | `'type-label'` | How to redact secrets in the output text |
| `verbose` | `boolean` | `false` | Include `allFindings` (pre-dedup) in the result. The WASM engine does not produce per-finding `details` blocks |
| `dangerouslyIncludeRawValues` | `boolean` | `false` | Populate `match.valueRaw` with unmasked value. **Never enable in production.** |
| `categoryFilter` | `string[]` | `['Credential']` | Pattern categories to scan. Currently supports `Credential` only |

### Selective scanning

```js
// Both engines (default)
const result = await scanner.scan(text);

// Secrets only — WASM never loads
const result = await scanner.scan(text, { secrets: true, zones: false });

// Zones only — secret detection pass skipped
const result = await scanner.scan(text, { secrets: false, zones: true });
```

### Returns: `ScanResult`

```typescript
{
  findings: Finding[];          // detected secrets, deduplicated by offset
  zones: ZonesResult | null;    // zone blocks, or null when zones: false / WASM not loaded
  redactedText: string;         // input with secrets replaced per redactStrategy
  scannedMs: number;            // wall-clock scan time in milliseconds
}
```

---

## `scanner.onServiceWorkerSuspend()`

Terminate all workers in the pool. Call from MV3 `chrome.runtime.onSuspend`.
The next `.scan()` call lazily re-spawns workers.

```js
chrome.runtime.onSuspend.addListener(() => {
  scanner.onServiceWorkerSuspend();
});
```

---

## Types

### `Finding`

A single detected secret.

```typescript
{
  entity_type: string;    // "API_KEY", "OPAQUE_SECRET", "PRIVATE_KEY", "PASSWORD_HASH"
  category: string;       // "Credential"
  sensitivity: string;    // "CRITICAL"
  confidence: number;     // 0–1, 4 decimal places
  engine: string;         // "regex" or "secret_scanner"
  detection_type?: string; // pattern identifier (e.g., "aws_access_key", "github_token")
  display_name?: string;  // human-friendly label (e.g., "AWS Access Key", "GitHub Token")
  evidence: string;       // human-readable scoring breakdown
  match: Match;           // offset span in original text
  kv?: KVContext;         // key-value context (secret_scanner only)
}
```

### Entity types

| Entity type | Description | Engine |
|-------------|-------------|--------|
| `API_KEY` | API keys, access tokens, PATs (GitHub, Stripe, OpenAI, etc.) | Both |
| `OPAQUE_SECRET` | Passwords, generic secrets, bot tokens | secret_scanner |
| `PRIVATE_KEY` | PEM-encoded private keys | regex |
| `PASSWORD_HASH` | bcrypt, argon2, scrypt, sha-crypt hashes | regex |

### `Match`

Character offset span in the original text.

```typescript
{
  valueMasked: string;    // "s]******[7" — first/last char visible, middle masked
  start: number;          // start offset (inclusive)
  end: number;            // end offset (exclusive)
  valueRaw?: string;      // unmasked value (only with dangerouslyIncludeRawValues)
}
```

`text.slice(match.start, match.end)` reproduces the original matched text.

### `KVContext`

Present on secret_scanner findings only.

```typescript
{
  key: string;    // key name that triggered scoring (e.g., "password", "access_token")
  tier: string;   // "definitive", "strong", or "contextual"
}
```

### Tiers

| Tier | Confidence range | Gate on value | Example keys |
|------|-----------------|---------------|-------------|
| `definitive` | 0.85–0.95 | Not obviously non-secret | `password`, `secret_key`, `client_secret` |
| `strong` | 0.50–0.85 | Entropy >= 0.5 OR diversity >= 3 | `token`, `auth`, `bot_token` |
| `contextual` | 0.35–0.65 | Entropy >= 0.7 AND diversity >= 3 | `key`, `hash`, `salt` |

### `FindingDetails`

> **Removed.** The Rust/WASM engine does not produce per-finding `details` blocks.
> The `Finding` type no longer has a `details` field. Use `verbose: true` to obtain
> `allFindings` (pre-dedup list) in the `ScanResult` for diagnostic purposes.

### `ZonesResult`

Zone detection result. `null` when `zones: false` or WASM failed to load.

```typescript
{
  total_lines: number;     // total lines in input text
  blocks: ZoneBlock[];     // detected zone blocks (may be empty for pure prose)
}
```

### `ZoneBlock`

A single detected zone.

```typescript
{
  start_line: number;          // 0-indexed, inclusive
  end_line: number;            // 0-indexed, exclusive
  zone_type: string;           // "code", "config", "markup", "query", "cli_shell", "data", "error_output", "natural_language"
  confidence: number;          // 0–1
  language_hint: string;       // detected language (e.g., "python", "json") or "" if unknown
  language_confidence: number; // 0–1
}
```

### Zone types

| Zone type | Description | Detection method |
|-----------|-------------|-----------------|
| `code` | Programming source code | Structural (fences), syntax scoring |
| `config` | Configuration (JSON, YAML, ENV) | Structural (fences), format detection |
| `markup` | HTML, XML, SVG | Structural (fences), format detection |
| `query` | SQL, GraphQL | Structural (fences with `sql`/`graphql` tag) |
| `cli_shell` | Shell commands | Structural (fences with `bash`/`sh`/`shell` tag) |
| `data` | Structured data (CSV, logs) | Format detection |
| `error_output` | Stack traces, error logs | Negative filter (reclassified from code) |
| `natural_language` | Prose inside fenced blocks | Interior classification |

See [zone-detection.md](zone-detection.md) for the full 10-step pipeline and detection logic.

---

## Redaction strategies

| Strategy | Output | Example |
|----------|--------|---------|
| `type-label` (default) | `[REDACTED:<TYPE>]` | `[REDACTED:API_KEY]` |
| `asterisk` | `*` repeated to match original length | `**********` |
| `placeholder` | Fixed Unicode token | `«secret»` |
| `none` | Original text unchanged | (passthrough) |

---

## Error handling

### Timeout

When a scan exceeds `timeoutMs`:

- **`failMode: 'open'`** (default): resolves normally with `{ findings: [], redactedText: <original>, scannedMs: <timeoutMs> }`
- **`failMode: 'closed'`**: rejects with `{ code: 'TIMEOUT' }`

### Worker errors

If the scanner engine throws internally, the worker catches the error
and surfaces it as a rejection: `{ message: "..." }`. The pool
terminates the failed worker and lazily respawns on the next scan.

---

## Full example

```js
import { createScanner } from '@data-classifier/browser';

const scanner = createScanner({ poolSize: 2 });

const text = `Fix this Python script:

\`\`\`python
import os
API_KEY = os.environ.get("OPENAI_KEY", "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234")

def call_api(prompt):
    return requests.post("https://api.openai.com/v1/chat", headers={"Authorization": f"Bearer {API_KEY}"})
\`\`\`

It should handle rate limiting.`;

const result = await scanner.scan(text, { verbose: true });

// Secret detection
console.log(result.findings.length);       // → 1
console.log(result.findings[0].entity_type); // → "API_KEY"
console.log(result.findings[0].display_name); // → "OpenAI API Key"

// Zone detection
console.log(result.zones.blocks.length);    // → 1
console.log(result.zones.blocks[0].zone_type); // → "code"
console.log(result.zones.blocks[0].language_hint); // → "python"
console.log(result.zones.blocks[0].start_line);  // → 2
console.log(result.zones.blocks[0].end_line);    // → 9

// Redacted output
console.log(result.redactedText);
// → "Fix this Python script:\n\n```python\nimport os\nAPI_KEY = os.environ.get(\"OPENAI_KEY\", \"[REDACTED:API_KEY]\")..."

console.log(result.scannedMs); // → 1.2
```

### Secrets-only (skip WASM loading)

```js
const { findings, redactedText } = await scanner.scan(text, { zones: false });
// zones field is null, WASM never loaded
```

### Zones-only (skip secret scanning)

```js
const { zones } = await scanner.scan(text, { secrets: false });
// findings is [], no redaction applied
```
