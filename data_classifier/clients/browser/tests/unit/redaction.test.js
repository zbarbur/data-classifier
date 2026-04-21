import { describe, it, expect } from 'vitest';
import { redact } from '../../src/redaction.js';

describe('redact', () => {
  const text = 'Hello API_KEY=ghp_abc123 and AUTH=xyz';
  const findings = [
    {
      entity_type: 'API_KEY',
      match: { valueMasked: 'gh***23', start: 14, end: 24 },
    },
    {
      entity_type: 'OPAQUE_SECRET',
      match: { valueMasked: 'x**z', start: 34, end: 37 },
      kv: { key: 'AUTH', tier: 'definitive' },
    },
  ];

  it('type-label (default) replaces each span with [REDACTED:<TYPE>]', () => {
    expect(redact(text, findings, 'type-label')).toBe(
      'Hello API_KEY=[REDACTED:API_KEY] and AUTH=[REDACTED:OPAQUE_SECRET]'
    );
  });

  it('asterisk preserves length', () => {
    const redacted = redact(text, findings, 'asterisk');
    expect(redacted.length).toBe(text.length);
    expect(redacted).toBe('Hello API_KEY=********** and AUTH=***');
  });

  it('placeholder uses a fixed token', () => {
    expect(redact(text, findings, 'placeholder')).toBe(
      'Hello API_KEY=«secret» and AUTH=«secret»'
    );
  });

  it('none returns the text unchanged', () => {
    expect(redact(text, findings, 'none')).toBe(text);
  });

  it('handles multiple non-overlapping findings via right-to-left replacement', () => {
    const t = '0123456789';
    const fs = [
      { entity_type: 'A', match: { start: 0, end: 4 } },
      { entity_type: 'B', match: { start: 6, end: 9 } },
    ];
    expect(redact(t, fs, 'type-label')).toBe('[REDACTED:A]45[REDACTED:B]9');
  });

  it('throws on unknown strategy', () => {
    expect(() => redact(text, findings, 'unknown')).toThrow();
  });

  it('skips overlapping findings when processed right-to-left', () => {
    const t = 'aaaXXXbbb';
    const fs = [
      { entity_type: 'FIRST', match: { start: 3, end: 6 } },
      { entity_type: 'SECOND', match: { start: 4, end: 7 } },
    ];
    // Sorted descending by start: SECOND (start=4) first, FIRST (start=3) second.
    // SECOND replaces [4..7); leftBound becomes 4. FIRST ends at 6 > 4 → skip.
    expect(redact(t, fs, 'type-label')).toBe('aaaX[REDACTED:SECOND]bb');
  });
});
