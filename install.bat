@echo off
REM ============================================================
REM HemaFrag Diagnostics — first-time install (Windows / cmd.exe)
REM
REM Behaviour:
REM   - Prefers C:\Users\molpa\AppData\Local\Programs\Python\Python314\python.exe
REM     (the 3.14.6 work-computer interpreter -- the migration target).
REM   - Falls back to Python312\python.exe (this dev machine) and
REM     finally to whatever `where python` resolves on PATH.
REM   - Creates .venv at the repo root.
REM   - pip install --upgrade pip wheel setuptools in the venv.
REM   - pip install -r requirements.txt in the venv.
REM   - If wheels\fraggler_kernels*.whl exists, installs it (Rust engine).
REM   - start.bat is pre-committed in the repo.
REM
REM Re-runnable: deletes .venv and rebuilds if one already exists.
REM ============================================================

setlocal ENABLEDELAYEDEXPANSION

REM Where are we?
set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
echo [install] repo root:  %REPO_ROOT%
echo [install] python exe:
set "PYTHON_EXE="
REM Prefer Python 3.14.6 (work computer's interpreter -- the 3.14
REM migration target). Falls back to 3.12 (this dev machine) and then
REM to whatever `where python` finds on PATH.
if exist "C:\Users\molpa\AppData\Local\Programs\Python\Python314\python.exe" (
    set "PYTHON_EXE=C:\Users\molpa\AppData\Local\Programs\Python\Python314\python.exe"
    echo [install]   - using 3.14 path: %PYTHON_EXE%
) else if exist "C:\Users\molpa\AppData\Local\Programs\Python\Python312\python.exe" (
    set "PYTHON_EXE=C:\Users\molpa\AppData\Local\Programs\Python\Python312\python.exe"
    echo [install]   - using 3.12 path: %PYTHON_EXE%
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] python.exe not found. Install Python 3.11+ from https://www.python.org/downloads/
        exit /b 1
    )
    for /f "delims=" %%i in ('where python') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
    )
    echo [install]   - using system python: %PYTHON_EXE%
)
if not exist "%PYTHON_EXE%" (
    echo [ERROR] python.exe chosen does not exist: %PYTHON_EXE%
    exit /b 1
)

REM Check Python version >= 3.11
echo [install] python version check:
"%PYTHON_EXE%" --version
"%PYTHON_EXE%" -c "import sys; sys.exit(0 if (sys.version_info[0], sys.version_info[1]) >= (3, 11) else 1)"
if errorlevel 1 (
    echo [ERROR] Python 3.11+ required.
    exit /b 1
)

REM Create .venv if missing
if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
    echo [install] .venv already exists, will reuse.
) else (
    echo [install] creating .venv...
    "%PYTHON_EXE%" -m venv "%REPO_ROOT%\.venv"
    if errorlevel 1 (
        echo [ERROR] venv creation failed.
        exit /b 1
    )
)

set "VENV_PY=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] venv python missing: %VENV_PY%
    exit /b 1
)

echo [install] venv python: %VENV_PY%
"%VENV_PY%" --version

REM Upgrade pip + install wheel + setuptools + requirements
echo.
echo [pip] upgrading pip, wheel, setuptools...
"%VENV_PY%" -m pip install --upgrade pip wheel setuptools
if errorlevel 1 (
    echo [ERROR] pip self-upgrade failed.
    exit /b 1
)

echo [pip] installing requirements.txt ...
if not exist "%REPO_ROOT%\requirements.txt" (
    echo [ERROR] requirements.txt missing in %REPO_ROOT%
    exit /b 1
)
"%VENV_PY%" -m pip install -r "%REPO_ROOT%\requirements.txt"
if errorlevel 1 (
    echo [ERROR] requirements.txt install failed.
    exit /b 1
)

REM Optional Rust engine wheel
echo.
echo [inprocess] checking for fraggler_kernels wheel...
set "WHEEL_INSTALLED=0"
for %%w in ("%REPO_ROOT%\wheels\fraggler_kernels-*.whl") do (
    echo [inprocess] installing %%w
    "%VENV_PY%" -m pip install --force-reinstall --no-deps "%%w"
    if errorlevel 1 (
        echo [WARN] wheel install failed: %%w
    ) else (
        set "WHEEL_INSTALLED=1"
    )
)
if "%WHEEL_INSTALLED%"=="1" (
    echo [inprocess] Rust engine wheel is INSTALLED.
) else (
    echo [inprocess] no wheel found  -  Python fallback will be used.
    echo [inprocess]     to enable Rust: drop a .whl file into wheels\, or run build_wheel_windows.bat.
)

REM start.bat is committed alongside install.bat - no need to generate.
if exist "%REPO_ROOT%\start.bat" (
    echo [install] start.bat already exists.
) else (
    echo [WARN] start.bat missing  -  re-run git pull or restore from commit history.
)

REM Final verification
echo.
echo [install] verifying venv ...
"%VENV_PY%" -c "import sys, PyQt6, pandas, plotly, openpyxl; print('  - sys', sys.version.split()[0]); print('  - PyQt6 OK'); print('  - pandas OK'); print('  - plotly OK'); print('  - openpyxl OK')" 1>nul 2>err.log
if errorlevel 1 (
    echo [WARN] one or more imports failed. See err.log:
    type err.log
    del err.log
    exit /b 1
)
del err.log 2>nul
echo [install] all key deps import cleanly.

echo.
echo ============================================================
echo HemaFrag Diagnostics installed.
echo.
echo Next: run the GUI with start.bat (or double-click it).
echo ============================================================
endlocal
