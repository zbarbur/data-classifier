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

Scan text for secrets. Returns findings + redacted text.

```js
const { findings, redactedText, scannedMs } = await scanner.scan(text);
```

### Parameters

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `timeoutMs` | `number` | `100` | Worker kill budget (ms). If scan exceeds this, behavior depends on `failMode` |
| `failMode` | `'open' \| 'closed'` | `'open'` | `open`: resolve with empty findings on timeout. `closed`: reject with `{ code: 'TIMEOUT' }` |
| `redactStrategy` | `'type-label' \| 'asterisk' \| 'placeholder' \| 'none'` | `'type-label'` | How to redact secrets in the output text |
| `verbose` | `boolean` | `false` | Attach a `details` block to each finding with pattern name, validator status, entropy breakdown |
| `dangerouslyIncludeRawValues` | `boolean` | `false` | Populate `match.valueRaw` with unmasked value. **Never enable in production.** |
| `categoryFilter` | `string[]` | `['Credential']` | Pattern categories to scan. Currently supports `Credential` only |

### Returns: `ScanResult`

```typescript
{
  findings: Finding[];    // detected secrets, deduplicated by offset
  redactedText: string;   // input with secrets replaced per redactStrategy
  scannedMs: number;      // wall-clock scan time in milliseconds
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
  details?: FindingDetails; // verbose info (only when verbose: true)
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

Present when `verbose: true`.

```typescript
{
  pattern: string;        // pattern name or "secret_scanner"
  validator: string;      // "passed", "stubbed", or "none"
  entropy?: {             // secret_scanner only
    shannon: number;      // bits per character
    relative: number;     // 0–1 (shannon / max for charset)
    charset: string;      // "hex", "base64", "alphanumeric", "full"
    score: number;        // clamped: max(0.5, min(1.0, relative))
  };
  tier?: string;          // secret_scanner only
}
```

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

const text = `
export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
db_password = "S3cureP@ss!xyz"
`;

const result = await scanner.scan(text, {
  redactStrategy: 'type-label',
  verbose: true,
});

console.log(result.findings.length);
// → 2

console.log(result.findings[0].entity_type);
// → "API_KEY"

console.log(result.findings[0].detection_type);
// → "github_token"

console.log(result.findings[0].display_name);
// → "GitHub Token"

console.log(result.findings[0].match.valueMasked);
// → "g]************************************a"

console.log(result.findings[0].details.pattern);
// → "github_token"

console.log(result.redactedText);
// → "\nexport GITHUB_TOKEN=[REDACTED:API_KEY]\ndb_password = [REDACTED:OPAQUE_SECRET]\n"

console.log(result.scannedMs);
// → 0.12
```
