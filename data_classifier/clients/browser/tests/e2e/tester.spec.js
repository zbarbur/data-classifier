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

  // Verify the unified output shows the secret as a redacted pill
  const redactedPill = page.locator('#unified-out .secret-redacted').first();
  await expect(redactedPill).toBeVisible();
  const pillText = await redactedPill.textContent();
  expect(pillText).toContain('GitHub Token');
});
