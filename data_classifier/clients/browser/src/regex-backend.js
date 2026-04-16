// Stage-1 regex backend: JS RegExp iteration over all patterns.
// Stage 2 (re2-wasm) reimplements this module against the same interface.

import { resolveValidator } from './validators.js';

export function createBackend(patterns, stopwordsSet, placeholderSet) {
  const compiled = patterns.map((p) => ({
    pattern: p,
    re: safeCompile(p.regex),
    validator: resolveValidator(p.validator, {
      notPlaceholderCredential: makeNotPlaceholder(placeholderSet),
    }),
  }));

  function iterate(text) {
    const out = [];
    for (const { pattern, re, validator } of compiled) {
      if (!re) continue;
      for (const m of text.matchAll(re)) {
        const value = m[0];
        if (valueIsStopword(value, pattern, stopwordsSet)) continue;
        if (matchesAllowlist(value, pattern)) continue;
        out.push({
          pattern,
          value,
          start: m.index,
          end: m.index + value.length,
          validator,
        });
      }
    }
    return out;
  }

  return { iterate };
}

function safeCompile(regex) {
  try {
    return new RegExp(regex, 'g');
  } catch {
    return null;
  }
}

function valueIsStopword(value, pattern, globalStopwords) {
  const lower = value.toLowerCase().trim();
  for (const s of pattern.stopwords || []) {
    if (s.toLowerCase() === lower) return true;
  }
  return globalStopwords.has(lower);
}

function matchesAllowlist(value, pattern) {
  for (const allow of pattern.allowlist_patterns || []) {
    try {
      if (new RegExp(allow).test(value)) return true;
    } catch {
      // invalid allowlist regex — ignore
    }
  }
  return false;
}

function makeNotPlaceholder(placeholderSet) {
  return function notPlaceholderCredential(value) {
    return !placeholderSet.has(value.trim().toLowerCase());
  };
}
