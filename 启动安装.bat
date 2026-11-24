@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "PY_CMD="
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
  if %errorlevel%==0 set "PY_CMD=py -3"
)

if not defined PY_CMD (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    echo "%%P" | findstr /i "\\WindowsApps\\" >nul
    if errorlevel 1 (
      "%%P" -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
      if not errorlevel 1 (
        if not defined PY_CMD set "PY_CMD=%%P"
      )
    )
  )
)

if not defined PY_CMD (
  echo 未检测到可用的 Python 3.10+（已自动跳过微软商店占位符）。
  echo 推荐直接下载免 Python 的 Windows 独立安装包（OwnLine-Setup-*-Windows-x64.zip）：
  echo   https://github.com/AdgaiWalker/VPN-OwnLine/releases/latest
  pause
  exit /b 1
)

"%PY_CMD%" -B ownline.py ui
if errorlevel 1 (
  echo.
  echo 本地安装器未能正常启动，请查看上方提示信息。
  echo 若本机缺少网络或环境依赖，可直接下载免 Python 独立安装包：
  echo   https://github.com/AdgaiWalker/VPN-OwnLine/releases/latest
  pause
  exit /b 1
)
endlocal
