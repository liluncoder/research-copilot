@echo off
setlocal
rem ============================================================
rem  Backend (FastAPI / uvicorn) on port 8010
rem  Every step writes a line to _tmp\backend_steps.log.
rem ============================================================
set "LOG=%~dp0_tmp\backend_steps.log"
if not exist "%~dp0_tmp" mkdir "%~dp0_tmp"
echo [%DATE% %TIME%] ---- start ---- >> "%LOG%"

title backend-8010
set PYTHONIOENCODING=utf-8

rem numpy index: chunks.jsonl + vectors.npy are prebuilt in the repo.
rem Without this the app opens an empty Chroma collection => zero hits
rem => every question is refused.
set STORE_BACKEND=numpy

cd /d "%~dp0backend"
if errorlevel 1 (
  echo [ERROR] cannot enter the backend folder:
  echo     %~dp0backend
  echo [%TIME%] cd failed >> "%LOG%"
  pause
  exit /b 1
)
echo [%TIME%] cwd=%CD% >> "%LOG%"

rem An old backend still holding 8010 would make uvicorn exit immediately.
netstat -ano | findstr /C:":8010 " | findstr LISTENING >nul
if not errorlevel 1 (
  echo [ERROR] port 8010 is already in use.
  echo Close the old backend window, or run the stop script first.
  echo [%TIME%] port 8010 busy >> "%LOG%"
  pause
  exit /b 1
)

rem ------------------------------------------------------------------
rem Auto-detect the interpreter. PY must always end up as a REAL PATH,
rem never as the "py -3" launcher, otherwise the quotes below break:
rem     "%PY%" -m uvicorn   ->   "py -3" -m uvicorn   (fails)
rem So every candidate is resolved through sys.executable.
rem ------------------------------------------------------------------
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
if not defined PY if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not defined PY for /f "delims=" %%p in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%p"
if not defined PY for /f "delims=" %%p in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%p"
if not defined PY (
  echo.
  echo [ERROR] Python 3 not found.
  echo Install Python 3.11+ from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup.
  echo [%TIME%] python missing >> "%LOG%"
  echo.
  pause
  exit /b 1
)
echo [%TIME%] interpreter=%PY% >> "%LOG%"

echo Using interpreter: %PY%
"%PY%" -c "import uvicorn, fastapi" >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERROR] Backend dependencies are missing for this interpreter.
  echo Run this once, then start again:
  echo     cd backend
  echo     "%PY%" -m pip install -r requirements-demo.txt
  echo [%TIME%] deps missing >> "%LOG%"
  echo.
  pause
  exit /b 1
)
echo [%TIME%] deps ok >> "%LOG%"

echo Backend starting on http://127.0.0.1:8010
echo Keep this window open while you use the demo. Ctrl+C to stop.
echo.
echo [%TIME%] uvicorn start >> "%LOG%"
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8010
echo [%TIME%] uvicorn exited code=%ERRORLEVEL% >> "%LOG%"
echo.
echo Backend stopped.
echo If this window closed by itself, open _tmp\backend_steps.log to see where.
pause
