import { describe, test, expect } from 'vitest';
import { isDetectorReady, resetDetector } from '../../src/detector.js';

describe('detector', () => {
  test('isDetectorReady returns false before init', () => {
    resetDetector();
    expect(isDetectorReady()).toBe(false);
  });

  test('resetDetector clears state', () => {
    resetDetector();
    expect(isDetectorReady()).toBe(false);
  });

  test('exports expected functions', async () => {
    const mod = await import('../../src/detector.js');
    expect(typeof mod.initDetector).toBe('function');
    expect(typeof mod.detect).toBe('function');
    expect(typeof mod.resetDetector).toBe('function');
    expect(typeof mod.isDetectorReady).toBe('function');
  });
});
