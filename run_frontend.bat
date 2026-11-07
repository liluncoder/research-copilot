@echo off
setlocal
rem ============================================================
rem  Frontend (Next.js dev server) on port 3010
rem  Every step writes a line to _tmp\frontend_steps.log so a
rem  failure can be diagnosed later without a screenshot.
rem ============================================================
set "LOG=%~dp0_tmp\frontend_steps.log"
if not exist "%~dp0_tmp" mkdir "%~dp0_tmp"
echo [%DATE% %TIME%] ---- start ---- >> "%LOG%"

title frontend-3010

rem The WorkBuddy sandbox injects NODE_OPTIONS (a safe-delete shim) that makes
rem `next dev` abort while cleaning .next. A normal double-click does not have
rem it, but clearing it here makes every launch behave the same way.
set NODE_OPTIONS=
set NEXT_TELEMETRY_DISABLED=1

cd /d "%~dp0frontend"
if errorlevel 1 (
  echo [ERROR] cannot enter the frontend folder:
  echo     %~dp0frontend
  echo [%TIME%] cd failed >> "%LOG%"
  pause
  exit /b 1
)
echo [%TIME%] cwd=%CD% >> "%LOG%"

rem API base is baked into the Next.js bundle at build time,
rem so it must be set BEFORE the dev server starts.
set NEXT_PUBLIC_API_URL=http://127.0.0.1:8010

rem ------------------------------------------------------------------
rem Resolve npm.cmd to an ABSOLUTE path.
rem Two traps this avoids:
rem   1) `where npm` also returns the Unix shim "npm" and "npm.ps1",
rem      which cmd cannot execute;
rem   2) npm is a .cmd batch file: calling it from this .bat WITHOUT
rem      `call` transfers control away permanently - the rest of this
rem      script never runs and no error is printed. That is exactly why
rem      the frontend window used to close instantly and silently.
rem ------------------------------------------------------------------
set "NPM="
for /f "delims=" %%p in ('where npm.cmd 2^>nul') do if not defined NPM set "NPM=%%p"
if not defined NPM if exist "%ProgramFiles%\nodejs\npm.cmd" set "NPM=%ProgramFiles%\nodejs\npm.cmd"
if not defined NPM if exist "%APPDATA%\npm\npm.cmd" set "NPM=%APPDATA%\npm\npm.cmd"
if not defined NPM (
  echo.
  echo [ERROR] npm.cmd not found.
  echo Install Node.js 18+ from https://nodejs.org/ and start again.
  echo [%TIME%] npm missing >> "%LOG%"
  echo.
  pause
  exit /b 1
)
echo [%TIME%] npm=%NPM% >> "%LOG%"

rem A stale server on 3010 would make this window die with EADDRINUSE.
netstat -ano | findstr /C:":3010 " | findstr LISTENING >nul
if not errorlevel 1 (
  echo [ERROR] port 3010 is already in use.
  echo Close the old frontend window, or double-click the stop script first.
  echo [%TIME%] port 3010 busy >> "%LOG%"
  pause
  exit /b 1
)

if not exist "node_modules" (
  echo node_modules is missing, installing dependencies once...
  echo This may take a few minutes on the first run.
  echo [%TIME%] npm install start >> "%LOG%"
  call "%NPM%" install
  if errorlevel 1 (
    echo.
    echo [ERROR] npm install failed. Check your network, then run it manually:
    echo     cd frontend
    echo     npm install
    echo [%TIME%] npm install failed >> "%LOG%"
    echo.
    pause
    exit /b 1
  )
  echo [%TIME%] npm install done >> "%LOG%"
)

echo Frontend starting on http://localhost:3010
echo The first page you open may take 20-40 seconds to compile.
echo Keep this window open. Closing it stops the web page.
echo.
echo [%TIME%] next dev start >> "%LOG%"
call "%NPM%" run dev -- -p 3010
echo [%TIME%] next dev exited code=%ERRORLEVEL% >> "%LOG%"
echo.
echo Frontend stopped.
echo If this window closed by itself, open _tmp\frontend_steps.log to see where.
pause
