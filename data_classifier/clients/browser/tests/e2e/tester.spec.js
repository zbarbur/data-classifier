import { test, expect } from '@playwright/test';

test('tester page detects a GitHub PAT', async ({ page }) => {
  await page.goto('/tester/');
  await page.fill(
    '#input',
    'please set export GITHUB_TOKEN=ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789 done',
  );
  await page.click('#scan-btn');

  await page.waitForSelector('#findings-summary .finding-card', { timeout: 10_000 });
  const findingType = await page.locator('.finding-card .finding-type').first().textContent();
  expect(findingType).toBeTruthy();

  const redacted = await page.locator('#redacted-out').textContent();
  expect(redacted).not.toContain('ghp_aBcDeFgHiJk');

  // Verify original text highlights the secret
  const highlight = await page.locator('#original-out .secret-highlight').first().textContent();
  expect(highlight).toContain('ghp_');
});
