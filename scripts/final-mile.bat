@echo off
setlocal enabledelayedexpansion

echo === Final Mile Checks (Windows) ===

echo.
echo [1/5] Lint and Type Check (Node)
npm run lint && npm run type-check
if errorlevel 1 (
  echo ERROR: Lint or type-check failed.
  exit /b 1
)

echo.
echo [2/5] Node Dependency Audit
npm audit --production
if errorlevel 1 (
  echo WARNING: npm audit reported issues. Review before release.
)

echo.
echo [3/5] Secrets Scan (gitleaks) if available
where gitleaks >nul 2>&1
if %errorlevel%==0 (
  gitleaks detect --no-git -v
  if errorlevel 1 (
    echo WARNING: gitleaks found potential secrets. Review required.
  )
) else (
  echo Skipping: gitleaks not found.
)

echo.
echo [4/5] Python Security (bandit/safety) if available
where bandit >nul 2>&1
if %errorlevel%==0 (
  bandit -r api
) else (
  echo Skipping: bandit not found.
)

where safety >nul 2>&1
if %errorlevel%==0 (
  safety check -r api\requirements.txt
) else (
  echo Skipping: safety not found.
)

echo.
echo [5/5] Performance Test (k6) if available and stack running
where k6 >nul 2>&1
if %errorlevel%==0 (
  if exist tests\perf\k6_health_check.js (
    set BASE_URL=http://localhost:8080
    k6 run tests\perf\k6_health_check.js
  ) else (
    echo Skipping: tests\perf\k6_health_check.js not found.
  )
) else (
  echo Skipping: k6 not found.
)

echo.
echo Done. Review results and complete FINAL_MILE_CHECKLIST.md.
endlocal

