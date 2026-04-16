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
    assertOffsets(text, out.filter((p) => p.key === 'api_key'));
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
