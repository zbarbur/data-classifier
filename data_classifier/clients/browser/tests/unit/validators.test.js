import { describe, it, expect } from 'vitest';
import {
  awsSecretNotHex,
  randomPassword,
  makeNotPlaceholderCredential,
  resolveValidator,
} from '../../src/validators.js';

describe('awsSecretNotHex', () => {
  it('rejects pure-hex strings (git SHAs)', () => {
    expect(awsSecretNotHex('a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0')).toBe(false);
  });

  it('accepts base64-shaped values with mixed case', () => {
    expect(awsSecretNotHex('wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY')).toBe(true);
  });

  it('rejects values that are only uppercase or only lowercase', () => {
    expect(awsSecretNotHex('ALLUPPERCASENOLOWER12345')).toBe(false);
    expect(awsSecretNotHex('alllowercasenoupper12345')).toBe(false);
  });
});

describe('randomPassword', () => {
  it('accepts a 3-class value with symbol', () => {
    expect(randomPassword('Abc123!x')).toBe(true);
  });

  it('rejects values without a symbol', () => {
    expect(randomPassword('Hello123')).toBe(false);
  });

  it('accepts the minimum length (4) when all other gates pass', () => {
    expect(randomPassword('Ab1!')).toBe(true);
  });

  it('rejects length-only failure isolated from other gates (length 3 with 3 classes)', () => {
    // 'Ab!' has lower + upper + symbol (3 classes), but length 3 < 4.
    // The ONLY reason for rejection here is length.
    expect(randomPassword('Ab!')).toBe(false);
  });

  it('accepts the maximum length (64) when all other gates pass', () => {
    // 62 lowercase 'a' + '1' + '!' = length 64 exactly, 3 classes, has symbol.
    const v = 'a'.repeat(62) + '1!';
    expect(v.length).toBe(64);
    expect(randomPassword(v)).toBe(true);
  });

  it('rejects length above maximum (65)', () => {
    // 63 lowercase 'a' + '1' + '!' = length 65, exceeds the 64 cap.
    const v = 'a'.repeat(63) + '1!';
    expect(v.length).toBe(65);
    expect(randomPassword(v)).toBe(false);
  });

  it('rejects 2-class values even with symbols', () => {
    expect(randomPassword('hello!!!')).toBe(false);
  });
});

describe('makeNotPlaceholderCredential', () => {
  it('rejects values in the placeholder set (case-insensitive)', () => {
    const validator = makeNotPlaceholderCredential(new Set(['changeme', 'password123']));
    expect(validator('changeme')).toBe(false);
    expect(validator('CHANGEME')).toBe(false);
    expect(validator('password123')).toBe(false);
  });

  it('accepts values not in the placeholder set', () => {
    const validator = makeNotPlaceholderCredential(new Set(['changeme']));
    expect(validator('ghp_abc123xyz')).toBe(true);
  });

  it('trims whitespace before comparing', () => {
    const validator = makeNotPlaceholderCredential(new Set(['changeme']));
    expect(validator('  changeme  ')).toBe(false);
  });
});

describe('resolveValidator', () => {
  it('returns a function for a known validator name', () => {
    expect(typeof resolveValidator('aws_secret_not_hex')).toBe('function');
    expect(typeof resolveValidator('random_password')).toBe('function');
  });

  it('returns a stub (always true) for an unported validator name', () => {
    const r = resolveValidator('luhn');
    expect(typeof r).toBe('function');
    expect(r('anything')).toBe(true);
    expect(r.isStub).toBe(true);
  });

  it('returns an un-branded passthrough for empty/null validator names (pattern declares no validator)', () => {
    const empty = resolveValidator('');
    const nully = resolveValidator(null);
    expect(empty('x')).toBe(true);
    expect(nully('x')).toBe(true);
    // Intentionally NOT branded isStub: scanner-core distinguishes
    // "no validator configured" (report 'none') from "validator configured
    // but not ported" (report 'stubbed'). Branding the passthrough would
    // collapse that distinction.
    expect(empty.isStub).toBeUndefined();
    expect(nully.isStub).toBeUndefined();
  });
});
