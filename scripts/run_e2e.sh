#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

export COUNSELAI_TEST_URL="${COUNSELAI_TEST_URL:-http://127.0.0.1:8751}"
export COUNSELAI_HEADED="${COUNSELAI_HEADED:-0}"
export PYTHONPATH="${PYTHONPATH:-src}"

curl -fsS "${COUNSELAI_TEST_URL}/health" >/dev/null

stable_files=(
  "tests/test_e2e.py"
  "tests/test_playwright_flow.py"
  "tests/e2e/test_api.py"
  "tests/e2e/test_dashboard.py"
  "tests/e2e/test_dashboard_overview.py"
  "tests/e2e/test_counsellor_workbench.py"
  "tests/e2e/test_counsellor_review.py"
  "tests/e2e/test_student_dashboard.py"
  "tests/e2e/test_school_dashboard.py"
  "tests/e2e/test_live_session.py"
  "tests/e2e/test_live_session_stubbed.py"
  "tests/e2e/test_session_lifecycle.py"
  "tests/e2e/test_session_end_reliability.py"
  "tests/e2e/test_websocket.py"
)

pytest "${stable_files[@]}"

if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  pytest tests/e2e/test_live_session_provider_smoke.py
else
  echo "Skipping provider smoke: GEMINI_API_KEY is not set."
fi

if [[ "${COUNSELAI_RUN_UAT:-0}" == "1" ]]; then
  pytest -m uat tests/e2e/test_uat.py
fi
