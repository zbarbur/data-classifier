// Shannon entropy + charset-aware relative entropy + char-class diversity.
// Mirrors:
//   data_classifier/engines/heuristic_engine.py :: compute_shannon_entropy,
//                                                  compute_char_class_diversity
//   data_classifier/engines/secret_scanner.py  :: _detect_charset,
//                                                  _compute_relative_entropy,
//                                                  _score_relative_entropy

const LOG2 = Math.log(2);
const log2 = (x) => Math.log(x) / LOG2;

const CHARSET_MAX_ENTROPY = {
  hex: log2(16),
  base64: log2(64),
  alphanumeric: log2(62),
  full: log2(95),
};

const HEX_RE = /^[0-9a-fA-F]+$/;
const BASE64_RE = /^[A-Za-z0-9+/=]+$/;
const ALNUM_RE = /^[A-Za-z0-9]+$/;

export function shannonEntropy(value) {
  if (!value) return 0;
  const counts = new Map();
  for (const ch of value) counts.set(ch, (counts.get(ch) || 0) + 1);
  const n = value.length;
  let h = 0;
  for (const c of counts.values()) {
    const p = c / n;
    h -= p * log2(p);
  }
  return h;
}

// NOTE: Mirrors Python's _detect_charset exactly, including the fact that
// the 'alphanumeric' branch is effectively unreachable — pure alphanumeric
// strings hit the base64 branch first because [A-Za-z0-9] is a subset of
// [A-Za-z0-9+/=]. The 'alphanumeric' charset remains in CHARSET_MAX_ENTROPY
// for symmetry with the Python module.
export function detectCharset(value) {
  if (HEX_RE.test(value)) return 'hex';
  if (BASE64_RE.test(value)) return 'base64';
  if (ALNUM_RE.test(value)) return 'alphanumeric';
  return 'full';
}

export function relativeEntropy(value) {
  if (!value) return 0;
  const h = shannonEntropy(value);
  const charset = detectCharset(value);
  const max = CHARSET_MAX_ENTROPY[charset] || CHARSET_MAX_ENTROPY.full;
  if (max === 0) return 0;
  return Math.min(1.0, h / max);
}

export function charClassDiversity(value) {
  if (!value) return 0;
  let hasLower = false;
  let hasUpper = false;
  let hasDigit = false;
  let hasSymbol = false;
  for (const ch of value) {
    if (ch >= 'a' && ch <= 'z') hasLower = true;
    else if (ch >= 'A' && ch <= 'Z') hasUpper = true;
    else if (ch >= '0' && ch <= '9') hasDigit = true;
    else hasSymbol = true;
  }
  return +hasLower + +hasUpper + +hasDigit + +hasSymbol;
}

export function charClassEvenness(value) {
  if (!value) return 0;
  const counts = [0, 0, 0, 0]; // upper, lower, digit, symbol
  for (const ch of value) {
    if (ch >= 'A' && ch <= 'Z') counts[0]++;
    else if (ch >= 'a' && ch <= 'z') counts[1]++;
    else if (ch >= '0' && ch <= '9') counts[2]++;
    else counts[3]++;
  }
  const n = counts.reduce((a, b) => a + b, 0);
  if (n === 0) return 0;
  const present = counts.filter(c => c > 0).map(c => c / n);
  if (present.length <= 1) return 0;
  const H = -present.reduce((sum, p) => sum + p * Math.log2(p), 0);
  const Hmax = Math.log2(present.length);
  return H / Hmax;
}

export function scoreRelativeEntropy(rel) {
  if (rel < 0.5) return 0;
  return Math.min(1.0, rel);
}
