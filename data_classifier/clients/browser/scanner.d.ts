/**
 * @data-classifier/browser — client-side secret detection engine.
 *
 * Scans user-submitted text for credentials and returns findings
 * with a redacted version of the input.
 */

// ── Options ──────────────────────────────────────────────────────

/** Strategy for redacting detected secrets in the output text. */
export type RedactStrategy = 'type-label' | 'asterisk' | 'placeholder' | 'none';

/** Behavior when a scan exceeds the timeout budget. */
export type FailMode =
  | 'open'   // resolve with empty findings (safe default)
  | 'closed'; // reject with { code: 'TIMEOUT' }

/** Options passed to `scanner.scan()`. */
export interface ScanOptions {
  /** Worker kill budget in milliseconds. @default 100 */
  timeoutMs?: number;

  /** Behavior on timeout. @default 'open' */
  failMode?: FailMode;

  /** How to redact detected secrets in the output. @default 'type-label' */
  redactStrategy?: RedactStrategy;

  /** Attach a `details` block to each finding with pattern/entropy info. @default false */
  verbose?: boolean;

  /**
   * Populate `match.valueRaw` with the unmasked matched value.
   *
   * **WARNING: Never enable in production.** Raw secret values will be
   * present in the finding objects. Use only for local diagnostics
   * and fixture authoring.
   *
   * @default false
   */
  dangerouslyIncludeRawValues?: boolean;

  /**
   * Which pattern categories to scan for.
   * Currently supports `Credential` only; other categories have unported validators.
   *
   * @default ['Credential']
   */
  categoryFilter?: string[];

  /**
   * Run the secret detection engine (regex + secret_scanner + opaque_token).
   * @default true
   */
  secrets?: boolean;

  /**
   * Run the zone detection engine (code/markup/config identification via WASM).
   * When true, the WASM module is lazy-loaded on first use (~15-25ms init).
   * @default true
   */
  zones?: boolean;
}

/** Options passed to `createScanner()`. */
export interface ScannerOptions {
  /**
   * Number of Web Workers in the pool.
   * @default 2
   */
  poolSize?: number;

  /**
   * Custom worker factory. Override to control worker URL resolution
   * (e.g., in a Chrome extension via `chrome.runtime.getURL`).
   *
   * @default () => new Worker(new URL('./worker.esm.js', import.meta.url), { type: 'module' })
   */
  spawn?: () => Worker;
}

// ── Results ──────────────────────────────────────────────────────

/** Character offset span in the original text. */
export interface Match {
  /** First and last characters visible, middle masked with asterisks. */
  valueMasked: string;

  /** Start offset (inclusive) in the original text. */
  start: number;

  /** End offset (exclusive) in the original text. */
  end: number;

  /**
   * The raw unmasked value. Only present when
   * `dangerouslyIncludeRawValues: true` was passed to `scan()`.
   */
  valueRaw?: string;
}

/** Key-value context for secret-scanner findings. */
export interface KVContext {
  /** The key name that triggered the finding (e.g., `"password"`, `"access_token"`). */
  key: string;

  /** Scoring tier: `"definitive"`, `"strong"`, or `"contextual"`. */
  tier: string;
}

/** Entropy breakdown (present when `verbose: true` and engine is `secret_scanner`). */
export interface EntropyDetails {
  /** Shannon entropy in bits per character. */
  shannon: number;

  /** Shannon / max possible for detected charset. Range 0–1. */
  relative: number;

  /** Detected charset: `"hex"`, `"base64"`, `"alphanumeric"`, or `"full"`. */
  charset: string;

  /** Clamped score: `max(0.5, min(1.0, relative))`. */
  score: number;
}

/** Verbose details block (present when `verbose: true`). */
export interface FindingDetails {
  /** Pattern name (e.g., `"github_token"`) or `"secret_scanner"`. */
  pattern: string;

  /** Validator status: `"passed"`, `"stubbed"`, or `"none"`. */
  validator: string;

  /** Entropy breakdown (secret_scanner findings only). */
  entropy?: EntropyDetails;

  /** Scoring tier (secret_scanner findings only). */
  tier?: string;
}

/** A detected zone block (code, markup, config, etc.). */
export interface ZoneBlock {
  /** Start line (0-indexed, inclusive). */
  start_line: number;

  /** End line (0-indexed, exclusive). */
  end_line: number;

  /** Zone classification. */
  zone_type: 'code' | 'markup' | 'config' | 'query' | 'cli_shell' | 'data' | 'error_output' | 'natural_language';

  /** Detection confidence, 0–1. */
  confidence: number;

  /** Detected programming language (e.g., "python", "javascript"). Empty string if unknown. */
  language_hint: string;

  /** Language detection confidence, 0–1. */
  language_confidence: number;
}

/** Zone detection result. */
export interface ZonesResult {
  /** Total lines in the input text. */
  total_lines: number;

  /** Detected zone blocks. */
  blocks: ZoneBlock[];
}

/** A single detected secret. */
export interface Finding {
  /** Entity type (e.g., `"API_KEY"`, `"OPAQUE_SECRET"`, `"PRIVATE_KEY"`, `"PASSWORD_HASH"`). */
  entity_type: string;

  /** Category (e.g., `"Credential"`). */
  category: string;

  /** Sensitivity level (e.g., `"CRITICAL"`). */
  sensitivity: string;

  /** Detection confidence, 0–1 (4 decimal places). */
  confidence: number;

  /** Which engine produced this finding: `"regex"` or `"secret_scanner"`. */
  engine: string;

  /** Specific detection pattern identifier (e.g., `"aws_access_key"`, `"github_token"`). */
  detection_type?: string;

  /** Human-friendly label (e.g., `"AWS Access Key"`, `"GitHub Token"`). */
  display_name?: string;

  /** Human-readable evidence string with scoring breakdown. */
  evidence: string;

  /** Character offset span in the original text. */
  match: Match;

  /** KV context (secret_scanner findings only). */
  kv?: KVContext;

  /** Verbose details (only when `verbose: true`). */
  details?: FindingDetails;
}

/** Result returned by `scanner.scan()`. */
export interface ScanResult {
  /** Detected secrets, deduplicated by offset (highest confidence wins). */
  findings: Finding[];

  /** Input text with secrets replaced per the chosen `redactStrategy`. */
  redactedText: string;

  /** Wall-clock scan time in milliseconds. */
  scannedMs: number;

  /**
   * All findings from every engine/pass before deduplication.
   * Only present when `verbose: true`. Useful for debugging which
   * engines fired and what was dropped by dedup.
   */
  allFindings?: Finding[];

  /**
   * Zone detection result. Contains detected code/markup/config blocks.
   * `null` when `zones: false` was passed to `scan()`.
   */
  zones: ZonesResult | null;
}

// ── Public API ───────────────────────────────────────────────────

/** Scanner instance returned by `createScanner()`. */
export interface Scanner {
  /**
   * Scan text for secrets.
   *
   * Dispatches to a Web Worker pool, returns findings + redacted text.
   * If the scan exceeds `timeoutMs`, behavior depends on `failMode`:
   * - `'open'` (default): resolves with empty findings
   * - `'closed'`: rejects with `{ code: 'TIMEOUT' }`
   */
  scan(text: string, opts?: ScanOptions): Promise<ScanResult>;

  /**
   * Terminate all workers in the pool.
   *
   * Call this from your MV3 service worker's `chrome.runtime.onSuspend`
   * listener. The next `scan()` call will lazily re-spawn workers.
   */
  onServiceWorkerSuspend(): void;
}

/**
 * Create a scanner instance with a Web Worker pool.
 *
 * @example
 * ```js
 * import { createScanner } from '@data-classifier/browser';
 *
 * const scanner = createScanner();
 * const { findings, redactedText } = await scanner.scan('export API_KEY=ghp_...');
 * ```
 *
 * @example Chrome extension integration
 * ```js
 * const scanner = createScanner({
 *   spawn: () => new Worker(
 *     chrome.runtime.getURL('worker.esm.js'),
 *     { type: 'module' }
 *   ),
 * });
 * ```
 */
export function createScanner(opts?: ScannerOptions): Scanner;
