#!/usr/bin/env bash
# verify.sh: paras's gate. The tests run end to end (the integration tests need a Hindawi checkout: PARAS_TEST_HINDAWI,
# or this script fetches one into ./.verify). Nothing is released unless this passes.
set -uo pipefail
cd "$(dirname "$0")/.."
if [ -z "${PARAS_TEST_HINDAWI:-}" ]; then
  [ -d .verify/hindawi2026.10 ] || git clone -q --depth 1 https://github.com/hindawiai/hindawi2026.10 .verify/hindawi2026.10 || exit 1
  export PARAS_TEST_HINDAWI="$PWD/.verify/hindawi2026.10"
fi
PYTHONPATH="$PWD/src" python3 -m pytest -q tests
