#!/usr/bin/env bash
set -euo pipefail

echo "=== Final Mile Checks (Unix) ==="

echo
echo "[1/5] Lint and Type Check (Node)"
npm run lint
npm run type-check

echo
echo "[2/5] Node Dependency Audit"
if ! npm audit --production; then
  echo "WARNING: npm audit reported issues. Review before release." >&2
fi

echo
echo "[3/5] Secrets Scan (gitleaks) if available"
if command -v gitleaks >/dev/null 2>&1; then
  if ! gitleaks detect --no-git -v; then
    echo "WARNING: gitleaks found potential secrets. Review required." >&2
  fi
else
  echo "Skipping: gitleaks not found."
fi

echo
echo "[4/5] Python Security (bandit/safety) if available"
if command -v bandit >/dev/null 2>&1; then
  bandit -r api || true
else
  echo "Skipping: bandit not found."
fi
if command -v safety >/dev/null 2>&1; then
  safety check -r api/requirements.txt || true
else
  echo "Skipping: safety not found."
fi

echo
echo "[5/5] Performance Test (k6) if available and stack running"
if command -v k6 >/dev/null 2>&1; then
  if [ -f tests/perf/k6_health_check.js ]; then
    BASE_URL=${BASE_URL:-http://localhost:8080} k6 run tests/perf/k6_health_check.js || true
  else
    echo "Skipping: tests/perf/k6_health_check.js not found."
  fi
else
  echo "Skipping: k6 not found."
fi

echo
echo "Done. Review results and complete FINAL_MILE_CHECKLIST.md."

