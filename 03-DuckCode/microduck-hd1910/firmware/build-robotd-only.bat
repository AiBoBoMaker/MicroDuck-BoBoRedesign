@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "WSL_ROOT="
for /f "delims=" %%I in ('wsl wslpath -a "%CD%"') do set "WSL_ROOT=%%I"
if not defined WSL_ROOT (
  echo No WSL.
  exit /b 1
)
wsl -e bash -lc "source /root/.cargo/env 2>/dev/null || true; cd '%WSL_ROOT%' && export PYTHONIOENCODING=utf-8 PYTHONUTF8=1 && python3 build-robotd-only.py %*"
exit /b %ERRORLEVEL%
