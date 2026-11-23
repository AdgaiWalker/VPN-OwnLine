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

if not exist ".venv\Scripts\python.exe" (
  %PY_CMD% -m venv .venv
  if errorlevel 1 (
    echo Failed to create local virtual environment .venv.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -c "import paramiko, bcrypt" >nul 2>&1
if errorlevel 1 (
  echo First launch: installing locked local dependencies from requirements.lock...
  ".venv\Scripts\python.exe" -m pip install --no-input --disable-pip-version-check --timeout 10 --retries 1 --require-hashes -r requirements.lock --index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
  if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install --no-input --disable-pip-version-check --timeout 10 --retries 1 --require-hashes -r requirements.lock --index-url https://pypi.org/simple
  )
  if errorlevel 1 (
    echo Dependency installation failed. Check network or Python environment.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -B -m server.local_setup
endlocal
