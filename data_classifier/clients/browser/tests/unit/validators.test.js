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

  it('rejects values below minimum length', () => {
    expect(randomPassword('Ab1!')).toBe(true);
    expect(randomPassword('Ab1')).toBe(false);
  });

  it('rejects values above maximum length', () => {
    expect(randomPassword('A'.repeat(65) + '1!')).toBe(false);
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

  it('returns a passthrough for unknown/empty names', () => {
    expect(resolveValidator('')('x')).toBe(true);
    expect(resolveValidator(null)('x')).toBe(true);
  });
});
