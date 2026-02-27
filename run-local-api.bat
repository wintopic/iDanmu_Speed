@echo off
setlocal
cd /d "%~dp0danmu_api-main"

if not exist "package.json" (
  echo Cannot find danmu_api-main\package.json
  exit /b 1
)

if not exist "node_modules" (
  echo [1/2] Installing npm dependencies...
  npm install --no-audit --no-fund
  if errorlevel 1 (
    echo npm install failed
    exit /b 1
  )
)

echo [2/2] Starting local API: http://127.0.0.1:9321
node danmu_api/server.js
