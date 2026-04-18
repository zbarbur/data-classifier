import { describe, it, expect } from 'vitest';
import { decodeEncodedStrings } from '../../src/decoder.js';

describe('decodeEncodedStrings', () => {
  it('passes through unprefixed values unchanged', () => {
    expect(decodeEncodedStrings(['hello', 'world'])).toEqual(['hello', 'world']);
  });

  it('decodes a xor: prefixed value with key 0x5A', () => {
    // 'AKIA' XOR 0x5A byte-wise = [0x1B, 0x11, 0x13, 0x1B] → base64 'GxETGw=='
    expect(decodeEncodedStrings(['xor:GxETGw=='])).toEqual(['AKIA']);
  });

  it('decodes a b64: prefixed value (no xor)', () => {
    // base64('hello') = 'aGVsbG8='
    expect(decodeEncodedStrings(['b64:aGVsbG8='])).toEqual(['hello']);
  });

  it('handles a mix of encoded and plain entries', () => {
    expect(decodeEncodedStrings(['plain', 'xor:GxETGw==', 'b64:aGVsbG8='])).toEqual([
      'plain',
      'AKIA',
      'hello',
    ]);
  });

  it('returns an empty array for an empty input', () => {
    expect(decodeEncodedStrings([])).toEqual([]);
  });

  it('throws on malformed base64 in xor: payload (inherited from atob)', () => {
    expect(() => decodeEncodedStrings(['xor:!!!'])).toThrow();
  });

  it('throws on malformed base64 in b64: payload (inherited from atob)', () => {
    expect(() => decodeEncodedStrings(['b64:!!!'])).toThrow();
  });

  it('round-trips an ASCII-only xor: value exactly (pinning the ASCII contract)', () => {
    // Pins that valid-ASCII XOR payloads decode without any U+FFFD substitution.
    const out = decodeEncodedStrings(['xor:GxETGw==']);
    expect(out[0]).toBe('AKIA');
    expect(out[0]).not.toContain('\uFFFD');
  });
});
