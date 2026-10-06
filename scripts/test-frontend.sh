#!/usr/bin/env bash
# Frontend unit tests (see _implementation.md, phase 37c).
#
# Runs the tests in tests/frontend with node's own test runner and fails unless the card, the panel and
# the rendering module reach 80% line, branch and function coverage. Needs node 22 or later, nothing else.
set -euo pipefail

cd "$(dirname "$0")/.."

exec node --test \
    --experimental-test-coverage \
    --test-coverage-include='custom_components/haanim/ui/**' \
    --test-coverage-lines=80 \
    --test-coverage-branches=80 \
    --test-coverage-functions=80 \
    'tests/frontend/*.test.mjs'
