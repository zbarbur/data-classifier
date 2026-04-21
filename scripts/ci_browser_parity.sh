#!/usr/bin/env bash
# Run browser PoC parity checks after Python tests.
# Called by CI after pytest passes. Ensures Python changes
# don't silently break the JS port.
#
# Usage: ./scripts/ci_browser_parity.sh [--strict-validators]
#
# Requires: node >= 18, npm, python3 with data_classifier installed.
# Playwright browsers are installed automatically if missing.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BROWSER_DIR="$REPO_ROOT/data_classifier/clients/browser"

echo "=== Browser PoC parity check ==="

# 1. Regenerate JS assets from current Python source
echo ">> Regenerating JS assets from Python..."
# Prefer .venv/bin/python (local dev) but fall back to system python (CI runner)
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  PYTHON="python"
fi
"$PYTHON" "$REPO_ROOT/scripts/generate_browser_patterns.py" "$@"

# 2. Install npm deps (skip if node_modules exists and is fresh)
echo ">> Installing npm dependencies..."
cd "$BROWSER_DIR"
npm ci --prefer-offline 2>/dev/null || npm install

# 3. Build
echo ">> Building..."
npm run build

# 4. Run unit tests
echo ">> Running unit tests..."
npx vitest run

# 5. Install Playwright browsers if needed
echo ">> Ensuring Playwright browsers..."
npx playwright install chromium --with-deps 2>/dev/null || npx playwright install chromium

# 6. Run differential test
echo ">> Running differential parity test..."
npx playwright test tests/e2e/differential.spec.js

echo "=== Browser PoC parity check PASSED ==="
