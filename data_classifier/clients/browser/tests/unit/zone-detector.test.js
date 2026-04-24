import { describe, it, expect } from 'vitest';

// We test the module's export shape and option-gating logic.
// Full WASM integration is tested in e2e (Playwright).

describe('zone-detector exports', () => {
  it('exports the expected functions', async () => {
    const mod = await import('../../src/zone-detector.js');
    expect(typeof mod.initZoneDetector).toBe('function');
    expect(typeof mod.detectZones).toBe('function');
    expect(typeof mod.resetZoneDetector).toBe('function');
    expect(typeof mod.isZoneDetectorReady).toBe('function');
  });

  it('isZoneDetectorReady returns false before init', async () => {
    const mod = await import('../../src/zone-detector.js');
    mod.resetZoneDetector();
    expect(mod.isZoneDetectorReady()).toBe(false);
  });

  it('detectZones returns null when not initialized', async () => {
    const mod = await import('../../src/zone-detector.js');
    mod.resetZoneDetector();
    const result = mod.detectZones('hello world', 'test-1');
    expect(result).toBeNull();
  });
});

describe('scanText zones option', () => {
  it('zones is null when zones option is false', async () => {
    const { scanText } = await import('../../src/scanner-core.js');
    const result = scanText('hello world', { zones: false });
    expect(result.zones).toBeNull();
  });

  it('zones is null when detector not initialized (default)', async () => {
    const { scanText } = await import('../../src/scanner-core.js');
    const result = scanText('hello world');
    expect(result.zones).toBeNull();
  });

  it('findings is empty array when secrets is false', async () => {
    const { scanText } = await import('../../src/scanner-core.js');
    const result = scanText('export API_KEY=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', { secrets: false });
    expect(result.findings).toEqual([]);
  });

  it('result always has zones key', async () => {
    const { scanText } = await import('../../src/scanner-core.js');
    const result = scanText('hello', {});
    expect('zones' in result).toBe(true);
  });
});
