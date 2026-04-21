import { describe, it, expect } from 'vitest';
import { createBackend } from '../../src/regex-backend.js';

const SAMPLE_PATTERNS = [
  {
    name: 'github_pat_like',
    regex: 'ghp_[A-Za-z0-9]{20,}',
    entity_type: 'API_KEY',
    category: 'Credential',
    sensitivity: 'CRITICAL',
    confidence: 0.95,
    validator: '',
    description: 'Test github-style PAT',
    context_words_boost: [],
    context_words_suppress: [],
    stopwords: [],
    allowlist_patterns: [],
    requires_column_hint: false,
    column_hint_keywords: [],
  },
  {
    name: 'password_gate',
    regex: '[A-Za-z0-9!@#$%^&*]{8,}',
    entity_type: 'PASSWORD',
    category: 'Credential',
    sensitivity: 'CRITICAL',
    confidence: 0.5,
    validator: 'random_password',
    description: 'Needs a validator',
    context_words_boost: [],
    context_words_suppress: [],
    stopwords: [],
    allowlist_patterns: [],
    requires_column_hint: false,
    column_hint_keywords: [],
  },
];

describe('createBackend', () => {
  it('iterates patterns and yields matches with start/end offsets', () => {
    const backend = createBackend(SAMPLE_PATTERNS, new Set(), new Set());
    const text = 'token=ghp_aaaaaaaaaaaaaaaaaaaaBBBB remaining prose';
    const matches = backend.iterate(text);
    const pat = matches.find((m) => m.pattern.name === 'github_pat_like');
    expect(pat).toBeDefined();
    expect(pat.value.startsWith('ghp_')).toBe(true);
    expect(pat.start).toBeGreaterThan(0);
    expect(pat.end).toBe(pat.start + pat.value.length);
    expect(text.slice(pat.start, pat.end)).toBe(pat.value);
  });

  it('skips stopwords (case-insensitive)', () => {
    const stop = new Set(['ghp_placeholder_dont_match_me_12345']);
    const backend = createBackend(SAMPLE_PATTERNS, stop, new Set());
    const matches = backend.iterate('token=ghp_placeholder_dont_match_me_12345 rest');
    expect(matches.find((m) => m.pattern.name === 'github_pat_like')).toBeUndefined();
  });

  it('resolves the validator by name', () => {
    const backend = createBackend(SAMPLE_PATTERNS, new Set(), new Set());
    const matches = backend.iterate('pw=Abc123!xyz done');
    const pwMatch = matches.find((m) => m.pattern.name === 'password_gate');
    expect(pwMatch).toBeDefined();
    expect(pwMatch.validator(pwMatch.value)).toBe(true);
  });
});
