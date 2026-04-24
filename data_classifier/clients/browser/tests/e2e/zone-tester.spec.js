import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const STORIES_PATH = resolve(__dirname, 'zone-stories.jsonl');
const XOR_KEY = 0x5a;

function decodeXor(encoded) {
  if (encoded.startsWith('xor:')) encoded = encoded.slice(4);
  const raw = Buffer.from(encoded, 'base64');
  const decoded = Buffer.alloc(raw.length);
  for (let i = 0; i < raw.length; i++) decoded[i] = raw[i] ^ XOR_KEY;
  return decoded.toString('utf-8');
}

const stories = readFileSync(STORIES_PATH, 'utf-8')
  .split('\n')
  .filter(Boolean)
  .map((l) => JSON.parse(l));

test.describe('zone detection stories', () => {
  test.setTimeout(60_000);

  for (const story of stories) {
    test(`${story.category}: ${story.id}`, async ({ page }) => {
      await page.goto('/tester/');

      const text = decodeXor(story.text_xor);

      const result = await page.evaluate(async (text) => {
        const { createScanner } = await import('../dist/scanner.esm.js');
        const scanner = createScanner();
        return scanner.scan(text, { secrets: false, zones: true });
      }, text);

      expect(result.zones).not.toBeNull();

      const actualBlocks = result.zones.blocks;
      const expectedBlocks = story.expected_zones;
      const tolerance = story.tolerance_lines || 2;

      // Verify block count matches (with some flexibility for edge cases)
      if (expectedBlocks.length === 0) {
        expect(actualBlocks.length).toBe(0);
        return;
      }

      // Each expected block should have a matching actual block
      for (const expected of expectedBlocks) {
        const match = actualBlocks.find(
          (b) =>
            b.zone_type === expected.zone_type &&
            Math.abs(b.start_line - expected.start_line) <= tolerance &&
            Math.abs(b.end_line - expected.end_line) <= tolerance,
        );
        expect(match, `Expected ${expected.zone_type} block near lines ${expected.start_line}-${expected.end_line}`).toBeTruthy();
      }
    });
  }
});
