#!/usr/bin/env bash
# cross_runtime_parity.sh
#
# Validates that the Rust native detector and the WASM detector produce
# identical output on the same inputs.
#
# Native path:  cargo test --no-default-features --test secret_integration
# WASM path:    Node.js + wasm_parity_test.mjs (loads pkg/ WASM binary)
#
# Exit 0 = both runtimes pass.  Exit 1 = at least one failure.

set -euo pipefail
cd "$(dirname "$0")/.."

BOLD='\033[1m'
GREEN='\033[0;32m'
RED='\033[0;31m'
RESET='\033[0m'

pass() { echo -e "${GREEN}${BOLD}  $*${RESET}"; }
fail() { echo -e "${RED}${BOLD}  $*${RESET}"; }

echo ""
echo -e "${BOLD}=== Cross-runtime parity test ===${RESET}"
echo ""

# ---------------------------------------------------------------------------
# 1. Rust native — integration tests
# ---------------------------------------------------------------------------

echo -e "${BOLD}>> [1/3] Rust native: cargo test --test secret_integration${RESET}"
echo ""

export PATH="$HOME/.cargo/bin:$PATH"

NATIVE_OUTPUT=$(
  cargo test \
    --no-default-features \
    --test secret_integration \
    --manifest-path data_classifier_core/Cargo.toml \
    2>&1
)

if echo "$NATIVE_OUTPUT" | grep -q "^test result: ok"; then
  NATIVE_COUNT=$(echo "$NATIVE_OUTPUT" | grep "^test result: ok" | grep -oE '[0-9]+ passed' | head -1)
  pass "Rust native: $NATIVE_COUNT"
else
  fail "Rust native: FAILED"
  echo "$NATIVE_OUTPUT"
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. WASM binary — build if pkg/ is missing or stale
# ---------------------------------------------------------------------------

echo ""
echo -e "${BOLD}>> [2/3] WASM: check / build${RESET}"

WASM_BIN="data_classifier_core/pkg/data_classifier_core_bg.wasm"
CARGO_TOML="data_classifier_core/Cargo.toml"

if [ ! -f "$WASM_BIN" ]; then
  echo "     pkg/ not found — building WASM (wasm-pack --target web --release)..."
  (cd data_classifier_core && wasm-pack build --target web --release 2>&1 | tail -5)
elif [ "$CARGO_TOML" -nt "$WASM_BIN" ]; then
  echo "     Cargo.toml newer than WASM binary — rebuilding..."
  (cd data_classifier_core && wasm-pack build --target web --release 2>&1 | tail -5)
else
  echo "     pkg/ is up-to-date, skipping rebuild"
fi

# ---------------------------------------------------------------------------
# 3. Node.js WASM parity test
# ---------------------------------------------------------------------------

echo ""
echo -e "${BOLD}>> [3/3] WASM parity: node scripts/wasm_parity_test.mjs${RESET}"
echo ""

node scripts/wasm_parity_test.mjs

# ---------------------------------------------------------------------------
# 4. Optional: labeled-eval regression sweep (Sprint 18)
# ---------------------------------------------------------------------------
#
# Pass `--labeled` to also run the WildChat labeled-eval regression
# tests.  Skipped by default because the labeled set (~48 MB) is
# DVC-tracked and may not be hydrated on every dev box.

LABELED_FLAG=""
for arg in "$@"; do
  if [ "$arg" = "--labeled" ]; then LABELED_FLAG="1"; fi
done

if [ -n "$LABELED_FLAG" ]; then
  echo ""
  echo -e "${BOLD}>> [4/4] Labeled-eval regression sweep${RESET}"
  echo ""

  if [ ! -f "data/wildchat_labeled_eval/labeled_set.jsonl" ]; then
    echo "     labeled_set.jsonl not found — pulling via dvc..."
    dvc pull data/wildchat_labeled_eval.dvc || {
      fail "dvc pull failed.  Run: dvc pull data/wildchat_labeled_eval.dvc"
      exit 1
    }
  fi

  if [ -x ".venv/bin/python" ]; then
    .venv/bin/python -m pytest tests/test_wildchat_labeled_regression.py -v
  else
    python -m pytest tests/test_wildchat_labeled_regression.py -v
  fi
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo ""
pass "=== Cross-runtime parity PASSED ==="
echo ""
