import { describe, it, expect } from 'vitest';
import {
  shannonEntropy,
  detectCharset,
  relativeEntropy,
  charClassDiversity,
  scoreRelativeEntropy,
} from '../../src/entropy.js';

describe('shannonEntropy', () => {
  it('returns 0 for an empty string', () => {
    expect(shannonEntropy('')).toBe(0);
  });

  it('returns 0 for a constant string', () => {
    expect(shannonEntropy('aaaa')).toBe(0);
  });

  it('returns 1 bit per char for a balanced 2-symbol string', () => {
    expect(shannonEntropy('abab')).toBeCloseTo(1.0, 4);
  });

  it('returns log2(4) for a balanced 4-symbol string', () => {
    expect(shannonEntropy('abcd')).toBeCloseTo(2.0, 4);
  });
});

describe('detectCharset', () => {
  it('detects hex', () => {
    expect(detectCharset('deadbeef1234')).toBe('hex');
  });

  it('detects base64', () => {
    expect(detectCharset('SGVsbG8gV29ybGQ=')).toBe('base64');
  });

  it('detects alphanumeric (mixed-case, no symbols)', () => {
    expect(detectCharset('AbcDef123')).toBe('alphanumeric');
  });

  it('falls back to full for strings with symbols or spaces', () => {
    expect(detectCharset('hello world!')).toBe('full');
  });
});

describe('relativeEntropy', () => {
  it('returns 0 for an empty string', () => {
    expect(relativeEntropy('')).toBe(0);
  });

  it('returns > 0.6 for a high-entropy full-charset string', () => {
    const v = '9sK!2f#Aq@Lp$7tZ&rM*uX(jN)bH+cY^';
    expect(relativeEntropy(v)).toBeGreaterThan(0.6);
    expect(relativeEntropy(v)).toBeLessThanOrEqual(1.0);
  });
});

describe('charClassDiversity', () => {
  it('counts lowercase + uppercase + digit + symbol classes', () => {
    expect(charClassDiversity('Abc123!')).toBe(4);
  });

  it('counts only present classes', () => {
    expect(charClassDiversity('abc')).toBe(1);
    expect(charClassDiversity('abc123')).toBe(2);
    expect(charClassDiversity('Abc123')).toBe(3);
  });
});

describe('scoreRelativeEntropy', () => {
  it('returns 0 below the 0.5 floor', () => {
    expect(scoreRelativeEntropy(0.4)).toBe(0);
  });

  it('scales linearly above the floor, capped at 1.0', () => {
    expect(scoreRelativeEntropy(0.5)).toBeCloseTo(0.5, 4);
    expect(scoreRelativeEntropy(0.75)).toBeCloseTo(0.75, 4);
    expect(scoreRelativeEntropy(1.0)).toBe(1.0);
    expect(scoreRelativeEntropy(1.5)).toBe(1.0);
  });
});
