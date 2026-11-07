@echo off
setlocal
title Stop local demo

echo ============================================================
echo   Stopping Research Copilot local demo (ports 3010 / 8010)
echo ============================================================
echo.

for %%P in (3010 8010) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr /C:":%%P " ^| findstr LISTENING') do (
    echo   port %%P  ->  killing PID %%a
    taskkill /F /PID %%a >nul 2>nul
  )
)

rem Close the two console windows if they are still sitting at the pause prompt.
taskkill /F /FI "WINDOWTITLE eq backend-8010*" >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq frontend-3010*" >nul 2>nul

echo.
echo Done. Ports 3010 and 8010 are free again.
echo Next time just double-click the launcher.
echo.
timeout /t 4
