@echo off
setlocal
title Research Copilot - local demo launcher
set "ROOT=%~dp0"

echo ============================================================
echo   Research Copilot  local demo
echo     backend  http://127.0.0.1:8010
echo     frontend http://localhost:3010
echo ============================================================
echo.

rem ---- curl must exist (it ships with Windows 10 1803+) ----
curl --version >nul 2>nul
if errorlevel 1 (
  echo [ERROR] curl.exe not found. Windows 10 1803+ ships it by default.
  echo Upgrade Windows or install curl from https://curl.se/windows/
  pause
  exit /b 1
)

rem ---- backend: reuse if already healthy, else start it ----
set "BE=000"
for /f "delims=" %%c in ('curl -s --noproxy "*" -o nul -w "%%{http_code}" -m 4 http://127.0.0.1:8010/health') do set "BE=%%c"
if "%BE%"=="200" (
  echo Backend already running on 8010, reusing it.
) else (
  echo Starting backend window...
  start "backend-8010" "%ROOT%run_backend.bat"
)

rem ---- frontend: reuse if already serving, else start it ----
set "FE=000"
for /f "delims=" %%c in ('curl -s --noproxy "*" -o nul -w "%%{http_code}" -m 4 http://127.0.0.1:3010/') do set "FE=%%c"
if "%FE%"=="200" (
  echo Frontend already running on 3010, reusing it.
) else (
  echo Starting frontend window...
  start "frontend-3010" "%ROOT%run_frontend.bat"
)
echo.

rem ---- wait for backend health: HTTP 200, max 120s ----
echo Waiting for backend /health to return 200 ...
set /a n=0
:wait_backend
set /a n+=1
set "CODE=000"
for /f "delims=" %%c in ('curl -s --noproxy "*" -o nul -w "%%{http_code}" -m 4 http://127.0.0.1:8010/health') do set "CODE=%%c"
if "%CODE%"=="200" goto backend_ok
if %n% geq 60 goto backend_fail
timeout /t 2 /nobreak >nul
goto wait_backend

:backend_fail
echo.
echo [WARN] Backend did not return 200 within 120s.
echo Look at the "backend-8010" window for the real error.
echo Most common cause: Python dependencies not installed yet. Run once:
echo     cd backend
echo     python -m pip install -r requirements-demo.txt
echo.
pause
exit /b 1

:backend_ok
echo Backend is up ^(HTTP 200^).

rem ---- wait for frontend: HTTP 200, max about 120s ----
echo Waiting for frontend to compile ^(first run can take 40s or more^) ...
set /a n=0
:wait_frontend
set /a n+=1
set "CODE=000"
for /f "delims=" %%c in ('curl -s --noproxy "*" -o nul -w "%%{http_code}" -m 8 http://127.0.0.1:3010/') do set "CODE=%%c"
if "%CODE%"=="200" goto frontend_ok
if %n% geq 30 goto frontend_slow
timeout /t 4 /nobreak >nul
goto wait_frontend

:frontend_slow
echo.
echo [WARN] Frontend is still not answering HTTP 200 after about 2 minutes.
echo Check the "frontend-3010" window. If it closed, the npm log there says why.
echo Opening the browser anyway - press F5 inside the page.
goto open

:frontend_ok
echo Frontend is up ^(HTTP 200^).

:open
start "" http://localhost:3010
echo.
echo Tips:
echo   - Wait until the top-bar badge turns green before you start recording.
echo   - "service not connected" => press F5 once, and check the backend window is still open.
echo   - Ports: script route = 3010 / 8010 ; docker route = 3000 / 8000. Do not mix them.
echo   - To stop: close the two black windows (backend-8010 / frontend-3010).
echo.
pause
