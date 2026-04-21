import { test, expect } from '@playwright/test';

// Pathological input designed to be slow under backtracking regex.
// Worker kill budget should terminate and fail-open.
test('worker terminate on pathological input under fail-open', async ({ page }) => {
  await page.goto('/tester/');
  const pathological = 'a'.repeat(50_000) + '!';
  await page.fill('#input', pathological);
  await page.click('#scan-btn');

  await page.waitForSelector('#results', { state: 'visible', timeout: 10_000 });
  const scanTime = await page.locator('#scan-time').textContent();
  expect(scanTime).toContain('ms');
});
