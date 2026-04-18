import { describe, it, expect } from 'vitest';
import { scanText } from '../../src/scanner-core.js';

describe('scanText — regex pass', () => {
  it('detects a GitHub PAT in env-file text and returns a redacted output', () => {
    const text = 'please set export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa thanks';
    const { findings, redactedText, scannedMs } = scanText(text, {});
    expect(findings.length).toBeGreaterThan(0);
    const f = findings.find((x) => x.category === 'Credential');
    expect(f).toBeDefined();
    expect(redactedText.includes('ghp_aaaaaaaaaa')).toBe(false);
    expect(scannedMs).toBeGreaterThanOrEqual(0);
  });
});

describe('scanText — secret-scanner pass', () => {
  it('fires on a KV pair whose key is "api_key" and value has high entropy', () => {
    const text = 'api_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCY9aBc4dZz8qRtY2"';
    const { findings } = scanText(text, {});
    const f = findings.find((x) => x.engine === 'secret_scanner');
    expect(f).toBeDefined();
    expect(['API_KEY', 'OPAQUE_SECRET', 'PRIVATE_KEY']).toContain(f.entity_type);
  });

  it('does not fire on a placeholder value', () => {
    const text = 'api_key = "changeme"';
    const { findings } = scanText(text, {});
    expect(findings.find((x) => x.engine === 'secret_scanner')).toBeUndefined();
  });
});

describe('scanText — verbose mode', () => {
  it('attaches details only when verbose=true', () => {
    const text = 'export TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
    const plain = scanText(text, { verbose: false }).findings[0];
    const verbose = scanText(text, { verbose: true }).findings[0];
    expect(plain.details).toBeUndefined();
    expect(verbose.details).toBeDefined();
    expect(typeof verbose.details.pattern).toBe('string');
  });
});

describe('scanText — raw values', () => {
  it('omits valueRaw by default', () => {
    const text = 'export TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
    const f = scanText(text, {}).findings[0];
    expect(f.match.valueRaw).toBeUndefined();
  });

  it('includes valueRaw when dangerouslyIncludeRawValues=true', () => {
    const text = 'export TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
    const f = scanText(text, { dangerouslyIncludeRawValues: true }).findings[0];
    expect(f.match.valueRaw).toBeTypeOf('string');
    expect(f.match.valueRaw.startsWith('ghp_')).toBe(true);
  });
});
