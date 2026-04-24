// Scanner-core: orchestrates the regex pass + secret-scanner pass.
// Returns { findings, redactedText, scannedMs }.

import { PATTERNS } from './generated/patterns.js';
import { SECRET_KEY_NAMES } from './generated/secret-key-names.js';
import { STOPWORDS } from './generated/stopwords.js';
import { PLACEHOLDER_VALUES } from './generated/placeholder-values.js';
import { SECRET_SCANNER } from './generated/constants.js';

import { createBackend } from './regex-backend.js';
import { parseKeyValues } from './kv-parsers.js';
import { maskValue, makeFinding } from './finding.js';
import { redact } from './redaction.js';
import {
  shannonEntropy,
  relativeEntropy,
  detectCharset,
  charClassDiversity,
  scoreRelativeEntropy,
} from './entropy.js';
import { initZoneDetector, detectZones, isZoneDetectorReady } from './zone-detector.js';

// Pre-compile word_boundary/suffix regexes for SECRET_KEY_NAMES once at
// module init (one worker scope). Avoids O(pairs * N) regex constructions
// per scan — critical for staying within the 100ms worker kill budget.
const COMPILED_KEY_NAMES = SECRET_KEY_NAMES.map((entry) => {
  let compiledRe = null;
  const escaped = entry.pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  if (entry.match_type === 'word_boundary') {
    compiledRe = new RegExp(`(^|[_\\-\\s.])${escaped}($|[_\\-\\s.])`);
  } else if (entry.match_type === 'suffix') {
    compiledRe = new RegExp(`[_\\-\\s.]${escaped}$`);
  }
  return { ...entry, compiledRe };
});

let backendCache = null;

function getBackend(categoryFilter) {
  const key = categoryFilter.join('|');
  if (backendCache && backendCache.key === key) return backendCache.backend;
  const filtered = PATTERNS.filter((p) => categoryFilter.includes(p.category) && !p.requires_column_hint);
  const backend = createBackend(filtered, STOPWORDS, PLACEHOLDER_VALUES);
  backendCache = { key, backend };
  return backend;
}

export async function initZones(wasmUrl, patternsUrl) {
  return initZoneDetector(wasmUrl, patternsUrl);
}

export function scanText(text, opts = {}) {
  const t0 = performanceNowSafe();
  const verbose = !!opts.verbose;
  const includeRaw = !!opts.dangerouslyIncludeRawValues;
  const categoryFilter = opts.categoryFilter || ['Credential'];
  const redactStrategy = opts.redactStrategy || 'type-label';
  const runSecrets = opts.secrets !== false;
  const runZones = opts.zones !== false;

  // Secret detection (existing JS passes)
  let findings = [];
  let allFindings;
  if (runSecrets) {
    const raw = [];
    raw.push(...regexPass(text, categoryFilter, verbose, includeRaw));
    raw.push(...secretScannerPass(text, verbose, includeRaw));
    raw.push(...opaqueTokenPass(text, verbose, includeRaw));
    findings = dedup(raw);
    if (verbose) allFindings = raw;
  }

  const redactedText = runSecrets ? redact(text, findings, redactStrategy) : text;

  // Zone detection (WASM)
  let zones = null;
  if (runZones && isZoneDetectorReady()) {
    zones = detectZones(text, opts._promptId || '');
  }

  const result = { findings, redactedText, scannedMs: performanceNowSafe() - t0, zones };
  if (verbose && allFindings) result.allFindings = allFindings;
  return result;
}

function regexPass(text, categoryFilter, verbose, includeRaw) {
  const backend = getBackend(categoryFilter);
  const matches = backend.iterate(text);
  const out = [];
  for (const m of matches) {
    const validated = m.validator(m.value);
    if (!validated) continue;
    const p = m.pattern;
    const match = { valueMasked: maskValue(m.value, p.entity_type), start: m.start, end: m.end };
    if (includeRaw) match.valueRaw = m.value;
    out.push(
      makeFinding({
        entityType: p.entity_type,
        category: p.category,
        sensitivity: p.sensitivity,
        confidence: p.confidence,
        engine: 'regex',
        evidence: `Regex: ${p.entity_type} pattern "${p.name}" matched`,
        match,
        detectionType: p.name,
        displayName: p.display_name || p.name,
        details: verbose
          ? {
              pattern: p.name,
              validator: m.validator.isStub ? 'stubbed' : p.validator ? 'passed' : 'none',
            }
          : undefined,
      })
    );
  }
  return out;
}

function secretScannerPass(text, verbose, includeRaw) {
  const pairs = parseKeyValues(text);
  const out = [];
  for (const { key, value, valueStart, valueEnd } of pairs) {
    if (value.length < SECRET_SCANNER.minValueLength) continue;
    if (hasAntiIndicator(key, value)) continue;
    if (PLACEHOLDER_VALUES.has(value.toLowerCase())) continue;
    if (isPlaceholderPattern(value)) continue;
    if (isCompoundNonSecret(key)) continue;
    const { score, tier, subtype } = scoreKeyName(key);
    if (score <= 0) continue;
    const composite = tieredScore(score, tier, value);
    if (composite <= 0) continue;
    const entityType = subtype || 'OPAQUE_SECRET';
    const rel = relativeEntropy(value);
    const charset = detectCharset(value);
    const match = { valueMasked: maskValue(value, entityType), start: valueStart, end: valueEnd };
    if (includeRaw) match.valueRaw = value;
    out.push(
      makeFinding({
        entityType,
        category: 'Credential',
        sensitivity: 'CRITICAL',
        confidence: Math.round(composite * 10000) / 10000,
        engine: 'secret_scanner',
        evidence:
          `secret_scanner: key "${key}" score=${score.toFixed(2)} tier=${tier} ` +
          `charset=${charset} relative_entropy=${rel.toFixed(2)} composite=${composite.toFixed(2)}`,
        match,
        kv: { key, tier },
        details: verbose
          ? {
              pattern: 'secret_scanner',
              validator: 'none',
              entropy: {
                shannon: shannonEntropy(value),
                relative: rel,
                charset,
                score: scoreRelativeEntropy(rel),
              },
              tier,
            }
          : undefined,
      })
    );
  }
  return out;
}

function scoreKeyName(key) {
  const lower = key.toLowerCase();
  let best = { score: 0, tier: '', subtype: 'OPAQUE_SECRET' };
  for (const entry of COMPILED_KEY_NAMES) {
    if (!matchKey(lower, entry)) continue;
    if (entry.score > best.score) {
      best = { score: entry.score, tier: entry.tier, subtype: entry.subtype };
    }
  }
  return best;
}

function matchKey(keyLower, entry) {
  if (entry.compiledRe) return entry.compiledRe.test(keyLower);
  return keyLower.includes(entry.pattern);
}

function tieredScore(keyScore, tier, value) {
  if (tier === 'definitive') {
    if (valueIsObviouslyNotSecret(value)) return 0;
    return keyScore * SECRET_SCANNER.definitiveMultiplier;
  }
  const rel = relativeEntropy(value);
  const div = charClassDiversity(value);
  if (tier === 'strong') {
    if (rel >= SECRET_SCANNER.relativeEntropyStrong || div >= SECRET_SCANNER.diversityThreshold) {
      return keyScore * Math.max(SECRET_SCANNER.strongMinEntropyScore, scoreRelativeEntropy(rel));
    }
    return 0;
  }
  if (rel >= SECRET_SCANNER.relativeEntropyContextual && div >= SECRET_SCANNER.diversityThreshold) {
    return keyScore * scoreRelativeEntropy(rel);
  }
  return 0;
}

// Code expression patterns — values that are code references, not secrets.
// Mirrors Python's code expression and variable reference patterns.
const _CODE_DOT_RE = /^[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)+[;,]?$/;
const _CODE_BRACKET_RE = /^[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)*\[[^\]]+\][;,]?$/;
const _CODE_SEMI_RE = /^[a-zA-Z_]\w*;$/;
const _SHELL_VAR_RE = /^\$[\w{]/;
const _CONSTANT_NAME_RE = /^[A-Z][A-Z0-9]*([_-][A-Z0-9]+)+$/;
const _CODE_PUNCT_RE = /^[\[\](){};<>,./\\|!@#%^&*\-+=~`\s]+$/;
const _FILE_PATH_RE = /^[/~][\w./\-]+$|^[A-Z]:\\[\w\\.\-]+$/;
// Tokens containing both parens and equals/semicolons are code fragments
// (e.g. `OleDbConnection("Provider=Microsoft.Jet.OLEDB.4.0;Data`), not secrets.
const _CODE_CALL_RE = /[({].*[=;]/;

function valueIsObviouslyNotSecret(value) {
  const v = value.toLowerCase().trim();
  if (SECRET_SCANNER.configValues.includes(v)) return true;
  if (_URL_LIKE_RE.test(value)) return true;
  if (_DATE_LIKE_RE.test(value)) return true;
  if (_IP_LIKE_RE.test(value)) return true;
  if (_NUMERIC_ONLY_RE.test(value)) return true;
  if (_CODE_DOT_RE.test(value) || _CODE_BRACKET_RE.test(value) || _CODE_SEMI_RE.test(value) || _CODE_CALL_RE.test(value)) return true;
  if (_SHELL_VAR_RE.test(value)) return true;
  if (_CONSTANT_NAME_RE.test(value)) return true;
  if (_CODE_PUNCT_RE.test(value)) return true;
  if (_FILE_PATH_RE.test(value)) return true;
  if (/^[a-zA-Z]+(-[a-zA-Z]+)*$/.test(value.trim())) return true;
  const stripped = value.trim().replace(/^["']+|["']+$/g, '').trim();
  if (stripped.startsWith('+') || stripped.endsWith('+')) return true;
  // Prose detection for spaced scripts (English, etc.): count ASCII
  // letters — high ratio with spaces means natural language, not a secret.
  if (value.includes(' ')) {
    let alpha = 0;
    for (const c of value) if (/[A-Za-z]/.test(c)) alpha++;
    if (alpha / value.length > SECRET_SCANNER.proseAlphaThreshold) return true;
  }
  // Non-spaced scripts (CJK, etc.): any non-ASCII Unicode letter means
  // this is human-language text, not a credential.  Secrets are ASCII.
  if (/[\u3000-\u9FFF\uAC00-\uD7AF\u0400-\u04FF\u0600-\u06FF]/.test(value)) return true;
  return false;
}

// Compiled from Python's _PLACEHOLDER_PATTERNS via generator
const _PLACEHOLDER_RES = SECRET_SCANNER.placeholderPatterns.map(
  ({ pattern, flags }) => new RegExp(pattern, flags)
);

// Compiled from Python's rejection patterns via generator
const _URL_LIKE_RE = new RegExp(SECRET_SCANNER.urlLikePattern.pattern, SECRET_SCANNER.urlLikePattern.flags);
const _DATE_LIKE_RE = new RegExp(SECRET_SCANNER.dateLikePattern.pattern, SECRET_SCANNER.dateLikePattern.flags);
const _IP_LIKE_RE = new RegExp(SECRET_SCANNER.ipLikePattern.pattern, SECRET_SCANNER.ipLikePattern.flags);
const _NUMERIC_ONLY_RE = new RegExp(SECRET_SCANNER.numericOnlyPattern.pattern, SECRET_SCANNER.numericOnlyPattern.flags);
const _UUID_RE = new RegExp(SECRET_SCANNER.uuidPattern.pattern, SECRET_SCANNER.uuidPattern.flags);

// Port of Python's _is_compound_non_secret (Sprint 13).
// Keys like "token_address" contain a secret-bearing word ("token") but the
// compound name means something non-secret. The allowlist preserves keys
// like "session_id" that ARE sensitive despite ending with a suffix.
const _NON_SECRET_ALLOWLIST = new Set(
  (SECRET_SCANNER.nonSecretAllowlist || []).map((s) => s.toLowerCase())
);

function isCompoundNonSecret(key) {
  const lower = key.toLowerCase().trim();
  if (_NON_SECRET_ALLOWLIST.has(lower)) return false;
  for (const suffix of SECRET_SCANNER.nonSecretSuffixes || []) {
    if (lower.endsWith(suffix)) return true;
  }
  return false;
}

function isPlaceholderPattern(value) {
  for (const re of _PLACEHOLDER_RES) {
    if (re.test(value)) return true;
  }
  return false;
}

// ── Opaque token detection (suspicious high-entropy tokens) ─────────────
// Scans text for standalone tokens that look like opaque secrets: high
// entropy, high char-class diversity, not a UUID/IP/date/URL. Flagged
// as suspicious at lower confidence — same heuristics as Python Path 4.
function opaqueTokenPass(text, verbose, includeRaw) {
  const out = [];
  const minLen = SECRET_SCANNER.minValueLength;
  const entropyThreshold = SECRET_SCANNER.opaqueTokenEntropyThreshold;
  const diversityThreshold = SECRET_SCANNER.opaqueTokenDiversityThreshold;
  const baseConfidence = SECRET_SCANNER.opaqueTokenBaseConfidence;
  const maxConfidence = SECRET_SCANNER.opaqueTokenMaxConfidence;

  const tokenRe = /\S+/g;
  let m;
  while ((m = tokenRe.exec(text)) !== null) {
    const token = m[0];
    const start = m.index;
    const cleaned = token.replace(/^["'`]+|["'`,.;:!?)}\]]+$/g, '');
    if (cleaned.length < minLen) continue;
    if (valueIsObviouslyNotSecret(cleaned)) continue;
    if (_UUID_RE.test(cleaned)) continue;
    if (PLACEHOLDER_VALUES.has(cleaned.toLowerCase())) continue;
    if (isPlaceholderPattern(cleaned)) continue;
    if (hasAntiIndicator('', cleaned)) continue;

    const rel = relativeEntropy(cleaned);
    if (rel < entropyThreshold) continue;
    const div = charClassDiversity(cleaned);
    if (div < diversityThreshold) continue;

    let confidence = baseConfidence;
    if (rel > 0.85) confidence += 0.1;
    if (cleaned.length > 24) confidence += 0.05;
    confidence = Math.min(maxConfidence, confidence);

    const end = start + token.length;
    const match = { valueMasked: maskValue(cleaned, 'OPAQUE_SECRET'), start, end };
    if (includeRaw) match.valueRaw = cleaned;
    out.push(
      makeFinding({
        entityType: 'OPAQUE_SECRET',
        category: 'Credential',
        sensitivity: 'CRITICAL',
        confidence: Math.round(confidence * 10000) / 10000,
        engine: 'secret_scanner',
        evidence:
          `secret_scanner: opaque token — rel_entropy=${rel.toFixed(2)} ` +
          `diversity=${div} len=${cleaned.length}`,
        match,
        details: verbose
          ? {
              pattern: 'opaque_token',
              validator: 'none',
              entropy: { relative: rel, charset: detectCharset(cleaned), diversity: div },
            }
          : undefined,
      })
    );
  }
  return out;
}

function dedup(findings) {
  // Sort by confidence descending — keep the best finding per span.
  const sorted = [...findings].sort((a, b) => b.confidence - a.confidence);
  const kept = [];
  for (const f of sorted) {
    const s = f.match.start;
    const e = f.match.end;
    const overlaps = kept.some((k) => s < k.match.end && e > k.match.start);
    if (!overlaps) kept.push(f);
  }
  // Restore position order for redaction (ascending by start).
  return kept.sort((a, b) => a.match.start - b.match.start);
}

function hasAntiIndicator(key, value) {
  const kl = key.toLowerCase();
  const vl = value.toLowerCase();
  for (const ai of SECRET_SCANNER.antiIndicators) {
    const a = ai.toLowerCase();
    if (kl.includes(a) || vl.includes(a)) return true;
  }
  return false;
}

function performanceNowSafe() {
  if (typeof performance !== 'undefined' && performance.now) return performance.now();
  const [s, ns] = process.hrtime();
  return s * 1000 + ns / 1e6;
}
