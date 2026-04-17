import { test, expect } from '@playwright/test';

test('tester page detects a GitHub PAT', async ({ page }) => {
  await page.goto('/tester/');
  await page.fill(
    '#input',
    'please set export GITHUB_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa done',
  );
  await page.click('#scan-btn');

  await page.waitForSelector('#findings-out:not(:empty)', { timeout: 10_000 });
  const findings = await page.locator('#findings-out').textContent();
  expect(findings).toMatch(/"category":\s*"Credential"/);

  const redacted = await page.locator('#redacted-out').textContent();
  expect(redacted).not.toContain('ghp_aaaaaaaaaaaaaaaa');
});
