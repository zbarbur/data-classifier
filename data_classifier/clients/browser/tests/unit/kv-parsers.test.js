import { describe, it, expect } from 'vitest';
import { parseKeyValues } from '../../src/kv-parsers.js';

function assertOffsets(text, pairs) {
  for (const p of pairs) {
    expect(text.slice(p.valueStart, p.valueEnd)).toBe(p.value);
  }
}

describe('parseKeyValues — JSON', () => {
  it('extracts flat string KV pairs', () => {
    const text = '{"api_key": "ghp_abc123", "port": 8080}';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([
      ['api_key', 'ghp_abc123'],
      ['port', '8080'],
    ]);
    // Covers both the quoted-string path ('api_key') and the number path ('port')
    assertOffsets(text, out);
  });

  it('flattens nested dicts with dotted keys', () => {
    const text = '{"db": {"password": "s3cret"}}';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['db.password', 's3cret']]);
    assertOffsets(text, out);
  });

  it('returns empty on non-object JSON', () => {
    expect(parseKeyValues('[1,2,3]')).toEqual([]);
    expect(parseKeyValues('"hello"')).toEqual([]);
  });

  it('handles JSON values with escaped quotes (offsets point to the raw escaped span)', () => {
    const text = '{"token": "abc\\"def"}';
    const out = parseKeyValues(text);
    expect(out.length).toBe(1);
    expect(out[0].key).toBe('token');
    expect(out[0].value).toBe('abc"def');
    // Offsets bracket the raw escaped form (abc\"def) so redaction replaces
    // the whole on-wire span, not the decoded one.
    const raw = text.slice(out[0].valueStart, out[0].valueEnd);
    expect(raw).toBe('abc\\"def');
  });

  it('handles JSON values with backslashes (Windows paths, etc.)', () => {
    const text = '{"path": "C:\\\\Users\\\\secret"}';
    const out = parseKeyValues(text);
    expect(out.length).toBe(1);
    expect(out[0].key).toBe('path');
    expect(out[0].value).toBe('C:\\Users\\secret');
    const raw = text.slice(out[0].valueStart, out[0].valueEnd);
    expect(raw).toBe('C:\\\\Users\\\\secret');
  });
});

describe('parseKeyValues — env format', () => {
  it('parses bare KEY=VALUE', () => {
    const text = 'API_KEY=ghp_abc123';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['API_KEY', 'ghp_abc123']]);
    assertOffsets(text, out);
  });

  it('parses export KEY=VALUE', () => {
    const text = 'export AUTH_TOKEN=xyz789';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['AUTH_TOKEN', 'xyz789']]);
    assertOffsets(text, out);
  });

  it('parses quoted values and strips quotes', () => {
    const text = 'PASS="my secret"';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['PASS', 'my secret']]);
    assertOffsets(text, out);
  });

  it('parses multiple lines', () => {
    const text = 'KEY_A=aaa\nKEY_B=bbb';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([
      ['KEY_A', 'aaa'],
      ['KEY_B', 'bbb'],
    ]);
    assertOffsets(text, out);
  });
});

describe('parseKeyValues — code literals', () => {
  it('parses identifier = "value"', () => {
    const text = 'password = "hunter2"';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['password', 'hunter2']]);
    assertOffsets(text, out);
  });

  it("parses identifier = 'value'", () => {
    const text = "api_key = 'abc-def'";
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['api_key', 'abc-def']]);
    assertOffsets(text, out);
  });

  it('parses identifier := "value"', () => {
    const text = 'pw := "golang-style"';
    const out = parseKeyValues(text);
    expect(out.map((p) => [p.key, p.value])).toEqual([['pw', 'golang-style']]);
    assertOffsets(text, out);
  });
});

describe('parseKeyValues — empty / whitespace', () => {
  it('returns empty on empty input', () => {
    expect(parseKeyValues('')).toEqual([]);
    expect(parseKeyValues('   \n  ')).toEqual([]);
  });

  it('returns empty on prose with no KV structure', () => {
    expect(parseKeyValues('just some prose with no structure')).toEqual([]);
  });
});
