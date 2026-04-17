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

let backendCache = null;

function getBackend(categoryFilter) {
  const key = categoryFilter.join('|');
  if (backendCache && backendCache.key === key) return backendCache.backend;
  const filtered = PATTERNS.filter((p) => categoryFilter.includes(p.category) && !p.requires_column_hint);
  const backend = createBackend(filtered, STOPWORDS, PLACEHOLDER_VALUES);
  backendCache = { key, backend };
  return backend;
}

export function scanText(text, opts = {}) {
  const t0 = performanceNowSafe();
  const verbose = !!opts.verbose;
  const includeRaw = !!opts.dangerouslyIncludeRawValues;
  const categoryFilter = opts.categoryFilter || ['Credential'];
  const redactStrategy = opts.redactStrategy || 'type-label';

  const findings = [];
  findings.push(...regexPass(text, categoryFilter, verbose, includeRaw));
  findings.push(...secretScannerPass(text, verbose, includeRaw));

  const redactedText = redact(text, findings, redactStrategy);
  return { findings, redactedText, scannedMs: performanceNowSafe() - t0 };
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
  for (const entry of SECRET_KEY_NAMES) {
    if (!matchKey(lower, entry.pattern, entry.match_type)) continue;
    if (entry.score > best.score) {
      best = { score: entry.score, tier: entry.tier, subtype: entry.subtype };
    }
  }
  return best;
}

function matchKey(keyLower, pattern, matchType) {
  if (matchType === 'word_boundary') {
    const re = new RegExp(`(^|[_\\-\\s.])${escapeRegex(pattern)}($|[_\\-\\s.])`);
    return re.test(keyLower);
  }
  if (matchType === 'suffix') {
    const re = new RegExp(`[_\\-\\s.]${escapeRegex(pattern)}$`);
    return re.test(keyLower);
  }
  return keyLower.includes(pattern);
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
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

function valueIsObviouslyNotSecret(value) {
  const v = value.toLowerCase().trim();
  if (SECRET_SCANNER.configValues.includes(v)) return true;
  if (/^https?:\/\//i.test(value)) return true;
  if (/^\d{4}[-/]\d{2}[-/]\d{2}/.test(value)) return true;
  if (value.includes(' ')) {
    let alpha = 0;
    for (const c of value) if (/[A-Za-z]/.test(c)) alpha++;
    if (alpha / value.length > SECRET_SCANNER.proseAlphaThreshold) return true;
  }
  return false;
}

/**
 * Port of Python's _is_placeholder_value — regex-based placeholder detection.
 * Catches values like "ghp_aaaa...", "xxxxxxxxxxxx", "<your-token>",
 * "YOUR_API_KEY_HERE", "{{VAR}}", "${VAR}", and common documentation examples.
 */
const _PLACEHOLDER_RES = [
  /x{5,}/i,                                                // 5+ consecutive x/X
  /(.)\1{7,}/,                                              // any char repeated 8+
  /<[^>]{1,80}>/,                                           // <angle-bracket>
  /your[_\-\s]?(api|access|auth|secret|token|private|aws|gcp|azure)?[_\-\s]?(key|token|secret|password|credential)/i,
  /put[_\-\s]?your/i,
  /insert[_\-\s]?your/i,
  /replace[_\-\s]?(me|with|this)/i,
  /placeholder/i,
  /redacted/i,
  /\bexample\b/i,
  /^sample[_\-]/i,
  /^dummy[_\-]?/i,
  /\{\{.*\}\}/,                                             // {{VAR}}
  /\$\{[A-Z_]+\}/,                                         // ${VAR}
  /EXAMPLE$/,                                               // AWS doc keys
  /(key|token|secret|password)[_\-\s]here/i,
  /goes[_\-\s]here/i,
  /\bchangeme\b/i,
  /\bfoobar\b/i,
  /\btodo\b/i,
  /\bfixme\b/i,
];

function isPlaceholderPattern(value) {
  for (const re of _PLACEHOLDER_RES) {
    if (re.test(value)) return true;
  }
  return false;
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
