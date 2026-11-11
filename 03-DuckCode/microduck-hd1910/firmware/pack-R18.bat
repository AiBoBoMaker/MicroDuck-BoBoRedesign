@echo off
setlocal
cd /d "%~dp0"
if /I "%~1"=="--no-build" goto pack

where cargo-zigbuild >nul 2>&1
if errorlevel 1 goto nobuild
where zig >nul 2>&1
if errorlevel 1 goto nobuild
cargo zigbuild --locked --release --config profile.release.package.robotd.codegen-units=1 -p robotd --target aarch64-unknown-linux-gnu.2.31
if errorlevel 1 exit /b 1
goto pack

:nobuild
if exist "target\aarch64-unknown-linux-gnu\release\robotd" goto pack
echo 未找到 cargo-zigbuild / zig，也没有已编好的 robotd
echo 继续只打包安装文件。鸭子上可以执行安装，但没有 robotd 时服务不会开机自启。

:pack
where py >nul 2>&1
if not errorlevel 1 (
  py -3 pack_r18.py
  exit /b %ERRORLEVEL%
)
where python >nul 2>&1
if not errorlevel 1 (
  python pack_r18.py
  exit /b %ERRORLEVEL%
)
where python3 >nul 2>&1
if not errorlevel 1 (
  python3 pack_r18.py
  exit /b %ERRORLEVEL%
)
echo 未找到 Python 3。
exit /b 1
