@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY_CMD="
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
  if %errorlevel%==0 set "PY_CMD=py -3"
)

if not defined PY_CMD (
  where python >nul 2>&1
  if %errorlevel%==0 (
    python -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
    if %errorlevel%==0 set "PY_CMD=python"
  )
)

if not defined PY_CMD (
  echo Python 3.10+ not found. Please install Python 3.10 or newer and double-click again.
  pause
  exit /b 1
)

%PY_CMD% -B ownline.py ui
if errorlevel 1 (
  echo Local launcher exited with an error. Check the messages above.
  pause
  exit /b 1
)
endlocal
