#!/usr/bin/env bash
# Pre-push QA for Package 4.12.3 and regression stack.
#
# Cursor workflow: IMPLEMENT → RUN AUTOMATED QA → FIX → RE-RUN → COMMIT/PUSH
#
# Usage (from repo root):
#   bash scripts/pre_push_qa.sh
#
# Runs consolidated QA including 4.12.3, 4.12.2/4.12, 4.11, 4.10, and autosync.
# Exit 0 only when all required suites pass.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python core/scripts/qa_package4123.py "$@"
