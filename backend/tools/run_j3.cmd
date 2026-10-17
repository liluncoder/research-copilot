@echo off
REM J3 判据复跑入口（Windows）。双击运行，或在 PowerShell 里执行 .\tools\run_j3.cmd
REM 自动挑选解释器：项目 .venv > 本机 WorkBuddy venv > PATH 里的 python
setlocal
cd /d "%~dp0.."

set "PY="
if exist "%~dp0..\.venv\Scripts\python.exe" set "PY=%~dp0..\.venv\Scripts\python.exe"
if not defined PY if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not defined PY set "PY=python"

echo [run_j3] interpreter: %PY%
set PYTHONIOENCODING=utf-8
"%PY%" tools\run_j3.py %*

echo.
echo [run_j3] exit code: %ERRORLEVEL%
if "%~1"=="" pause
