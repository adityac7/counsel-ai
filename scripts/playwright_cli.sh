#!/usr/bin/env bash
set -euo pipefail

if ! command -v npx >/dev/null 2>&1; then
  echo "Error: npx is required but not found in PATH." >&2
  exit 1
fi

cmd=(npx --yes --package @playwright/mcp playwright-mcp)
cmd+=("$@")

exec "${cmd[@]}"
