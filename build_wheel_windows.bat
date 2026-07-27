@echo off
REM ============================================================
REM HemaFrag Diagnostics - build the Windows fraggler_kernels wheel
REM
REM Multiple strategies, in order of preference:
REM   1. maturin develop (fastest) - editable install via venv
REM   2. maturin build     (slow)  - wheel artifact
REM
REM Does NOT require MSVC or cargo-build-script-execution succeeds:
REM we surface clear errors if anything goes wrong.
REM ============================================================

setlocal ENABLEDELAYEDEXPANSION

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
cd /d "%REPO_ROOT%"

REM Pick Python: prefer the venv from install.bat (its Python
REM was chosen to match this repo, might be 3.14 or 3.12), then
REM fall back to system 3.14 (work computer), 3.12 (dev machine),
REM then PATH python.
set "PYTHON_EXE="
if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%REPO_ROOT%\.venv\Scripts\python.exe"
) else if exist "C:\Users\molpa\AppData\Local\Programs\Python\Python314\python.exe" (
    set "PYTHON_EXE=C:\Users\molpa\AppData\Local\Programs\Python\Python314\python.exe"
) else if exist "C:\Users\molpa\AppData\Local\Programs\Python\Python312\python.exe" (
    set "PYTHON_EXE=C:\Users\molpa\AppData\Local\Programs\Python\Python312\python.exe"
) else (
    for /f "delims=" %%i in ('where python') do (
        if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
    )
)
if not exist "%PYTHON_EXE%" (
    echo [ERROR] No Python interpreter found. Run .\install.bat first.
    exit /b 1
)
echo [wheels] using python: %PYTHON_EXE%
"%PYTHON_EXE%" --version

REM Make sure maturin is installed in the venv / user site.
"%PYTHON_EXE%" -m maturin --version 1>nul 2>nul
if errorlevel 1 (
    echo [pip] installing maturin ^>= 1.5 ...
    "%PYTHON_EXE%" -m pip install --upgrade "maturin>=1.5,<2.0"
    if errorlevel 1 (
        echo [ERROR] maturin install failed.
        exit /b 1
    )
)

REM Put cargo on PATH (rustup default location).
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
where cargo >nul 2>&1
if errorlevel 1 (
    echo [ERROR] cargo not found. Run .\install_rust_windows.bat.
    exit /b 1
)

REM Default strategy: develop (editable install). Fastest, lowest
REM chance of hitting AppLocker / Defender build-script blocks
REM (because pip-install-editable copies the .pyd straight, no
REM wheel packaging step).
echo.
echo [wheels] strategy 1: maturin develop (editable install)
echo.

set "KERNELS_DIR=%REPO_ROOT%\fraggler-v2\crates\fraggler-kernels-py"
cd /d "%KERNELS_DIR%"

"%PYTHON_EXE%" -m maturin develop --release
if not errorlevel 1 (
    echo.
    echo ============================================================
    echo maturin develop SUCCESS.
    echo fraggler_native is installed editable into:
    echo   %REPO_ROOT%\.venv
    echo ============================================================
    exit /b 0
)

echo.
echo [wheels] develop failed. Trying strategy 2: build a wheel.
echo.

REM Strategy 2: build a wheel artifact (slower, requires running
REM cargo build-script (often blocked by AppLocker)).
if not exist "%REPO_ROOT%\wheels" mkdir "%REPO_ROOT%\wheels"

cd /d "%KERNELS_DIR%"
"%PYTHON_EXE%" -m maturin build --release --compatibility pypi
if errorlevel 1 (
    echo.
    echo [ERROR] maturin build failed too.
    echo.
    echo Common Windows causes:
    echo   1. AppLocker / Software Restriction Policy blocking build-script binaries
    echo      -> check: gpresult /h gp.html
    echo      -> fix: gpedit.msc ^> Security Settings ^> Software Restriction
    echo^      Policies ^> Add a path rule for cargo build-script.
    echo   2. Constrained Language Mode (PowerShell)
    echo      -> check: $ExecutionContext.SessionState.LanguageMode
    echo      -> fix (admin): Set-ItemProperty "HKLM:\SYSTEM\...\PowerShell\EnableConstrainedLanguage" 0
    echo   3. Wrong Python detected (Hermes's own Python overrides AppData Python)
    echo      -> already fixed by this script pinning ^<PYTHON_EXE^>
    echo.
    exit /b 1
)

echo.
echo [wheels] moving wheel to %REPO_ROOT%\wheels\
for %%w in (target\wheels\*.whl) do (
    move /y "%%w" "%REPO_ROOT%\wheels\" 1>nul
)

echo ============================================================
echo maturin build SUCCESS. Wheel in wheels\, run .\install.bat to install.
echo ============================================================
endlocal
