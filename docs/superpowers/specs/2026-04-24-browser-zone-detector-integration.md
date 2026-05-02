# Browser Library Zone Detector Integration

## Goal

Add zone detection (code/markup/config/query/cli/data/error_output identification) to the `@data-classifier/browser` library via the Rust/WASM `data_classifier_core` crate. The browser library ships a unified `scan()` API that returns both secret findings and zone blocks in a single call, with per-call configuration.

## Architecture

Two detection engines run side by side inside the existing worker pool:

- **Secret scanner** -- existing JS implementation (122 regex + 283 key-name patterns + entropy gating). Unchanged.
- **Zone detector** -- Rust/WASM (`data_classifier_core`), lazy-loaded on first use.

The WASM module and `zone_patterns.json` ship as static assets in the extension bundle. No network fetch -- everything is local.

### Future-proofing

The architecture anticipates the secret scanner migrating into the same Rust/WASM crate (post-Sprint 15). To keep this path clear:

- The zone detector wrapper (`zone-detector.js`) is a thin loader, not a deep integration. It can be replaced by a unified WASM API later without touching `scanner-core.js` significantly.
- Result types (`zones`, `findings`) remain separate at the API surface. A future unified detector can populate both from a single WASM call.
- No JS-side coupling between secret findings and zone blocks -- the mutual benefit logic (e.g., secrets-in-code-zones get higher confidence) will live in Rust when both detectors share the crate.

## API

```javascript
const scanner = createScanner({ workers: 2 });

// Default: both engines run
const result = await scanner.scan(text);

// Selective: per-call options
const result = await scanner.scan(text, { secrets: true, zones: false });
const result = await scanner.scan(text, { secrets: false, zones: true });
```

### Result shape

```javascript
{
  findings: [                          // secret detections (existing shape)
    { type: 'GITHUB_PAT', value: '...', start: 42, end: 82 }
  ],
  zones: {                             // zone detections (new)
    total_lines: 47,
    blocks: [
      {
        start_line: 5,
        end_line: 25,
        zone_type: 'code',             // code|markup|config|query|cli_shell|data|error_output|natural_language
        confidence: 0.92,
        language_hint: 'python',
        language_confidence: 0.85
      }
    ]
  }
}
```

When `zones: false`, `result.zones` is `null` and the WASM module never loads.
When `secrets: false`, `result.findings` is `[]` and the JS secret scanner is skipped.

Both options default to `true`.

## WASM Loading Strategy

Lazy-load on first `scan()` call that needs zones:

1. Worker starts (existing pool init).
2. First scan with `zones: true` -- worker fetches WASM binary + `zone_patterns.json` from extension bundle.
3. Calls `init_detector(patternsJson)` -- compiles ~100 regex patterns. Takes ~15-25ms, happens once per worker lifetime.
4. Subsequent scans reuse the compiled detector -- ~0.5ms per prompt.
5. On MV3 service worker suspend (`scanner.onServiceWorkerSuspend()`), WASM state is discarded. Next scan re-initializes.

The WASM binary is ~1.6MB uncompressed (~500KB gzipped). It is loaded from `chrome.runtime.getURL()` in extension context, or from a relative path in standalone usage.

## Files to Create/Modify

### New files

| File | Purpose |
|------|---------|
| `src/zone-detector.js` | WASM loader: lazy fetch, init_detector, detect wrapper. Exports `initZoneDetector()`, `detectZones(text, promptId)` |
| `assets/data_classifier_core_bg.wasm` | WASM binary (copied from `data_classifier_core/pkg/`) |
| `assets/zone_patterns.json` | Patterns config (copied from `v2/patterns/`) |
| `tests/unit/zone-detector.test.js` | Unit tests: WASM lifecycle, options handling, error fallback |
| `tests/e2e/zone-stories.jsonl` | ~25 real WildChat zone detection stories with ground truth |
| `tester/corpus/zone-showcase.jsonl` | ~8-10 clean synthetic showcase examples |

### Modified files

| File | Change |
|------|--------|
| `src/scanner.js` | Accept `{ secrets, zones }` options in `scan()`, pass to worker |
| `src/scanner-core.js` | Add zone detection pass: call `detectZones()` when zones enabled, merge into result |
| `src/worker.js` | Import zone-detector, lazy-init on first zone-enabled scan |
| `tests/e2e/tester.spec.js` | Add zone detection story tests alongside existing secret stories |
| `tests/e2e/bench.spec.js` | Add three benchmark modes (secrets-only, zones-only, combined) with P50/P95/P99 latency reporting |
| `package.json` | Add WASM + patterns to build copy step |
| `esbuild.config.js` (or equivalent) | Copy WASM + patterns assets to dist |

## Test Plan

### Story-based tests (Playwright e2e)

**Real corpus stories** (~25 prompts from the 647-record WildChat labeled corpus):

| Category | Count | What it tests |
|----------|-------|---------------|
| Fenced code (tagged) | 4 | ```python, ```json, ```bash, ```sql |
| Fenced code (untagged) | 2 | Interior classification (code vs prose) |
| Unfenced code in prose | 4 | Syntax scoring, context smoothing, comment bridge |
| Config files | 3 | JSON, YAML, ENV detection |
| Markup | 2 | XML, HTML with script/style |
| Error output | 2 | Stack traces, log output |
| Pure prose (no zones) | 3 | Must return empty blocks |
| Edge cases | 5 | Math/LaTeX (not code), Chinese text with tags, `console.log` scoring, short blocks, mixed secrets+code |

Each story has:
- `prompt_id`: original WildChat ID for traceability
- `text`: full prompt text
- `expected_zones`: list of `{ zone_type, start_line, end_line }` (approximate boundaries, tolerance +/-2 lines)
- `description`: human-readable explanation of what this tests

**Synthetic showcase stories** (~8-10):

Clean, short examples that demonstrate each zone type clearly. Used for documentation and the HTML tester page. Each is 10-30 lines, self-contained, with a clear expected outcome.

### Performance benchmarks (Playwright e2e)

Three benchmark modes, each running the full 647-prompt corpus through the worker pool:

| Mode | What runs | What it measures |
|------|-----------|-----------------|
| Secrets only | `{ zones: false }` | Baseline JS-only throughput |
| Zones only | `{ secrets: false }` | WASM zone detection throughput |
| Combined | `{ secrets: true, zones: true }` | Real-world combined throughput |

For each mode, report:
- **Throughput**: prompts/sec
- **Latency distribution**: P50, P95, P99 (per-prompt, in ms)
- **WASM init time**: first-call latency (includes lazy load + pattern compilation)

### Unit tests (Vitest)

- WASM loading: successful init, re-init after suspend, init with bad patterns
- Options: `zones: false` never touches WASM, `secrets: false` skips findings
- Result shape: zones field structure matches spec
- Graceful degradation: if WASM fails to load, scan still returns secrets (zones = null, warning logged)

## What's NOT in scope

- Porting secret scanner to Rust/WASM (follow-up, post-Sprint 15 rebase)
- Cross-detector logic (secrets-in-code-zones boosting) -- future, when both detectors share the Rust crate
- Chrome extension manifest / content scripts / UI -- separate integration task
- Bundle size optimization (`wasm-opt -Oz`, tree-shaking) -- follow-up
- `zone_patterns.json` consolidation (single source of truth across Python/Rust/browser) -- follow-up
