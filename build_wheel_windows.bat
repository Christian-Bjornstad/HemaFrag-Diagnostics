@echo off
REM ============================================================
REM HemaFrag Diagnostics - build the Windows fraggler_kernels wheel
REM
REM Requires: install_rust_windows.bat has been run successfully.
REM Output:   wheels\fraggler_kernels-<ver>-cp<python>-cp<python>-win_amd64.whl
REM ============================================================

setlocal ENABLEDELAYEDEXPANSION

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
cd /d "%REPO_ROOT%"

REM Ensure rust + maturin are on PATH
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
where rustc >nul 2>&1
if errorlevel 1 (
    echo [ERROR] rustc not on PATH. Run install_rust_windows.bat first.
    exit /b 1
)
where maturin >nul 2>&1
if errorlevel 1 (
    if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
        set "PATH=%REPO_ROOT%\.venv\Scripts;%PATH%"
    )
)

if not exist "%REPO_ROOT%\wheels" mkdir "%REPO_ROOT%\wheels"

echo.
echo [wheels] building fraggler_kernels wheel for Python 3.12 + Windows AMD64 ...
echo.

cd /d "%REPO_ROOT%\fraggler-v2\crates\fraggler-kernels-py"
maturin build --release --strip --compatibility pypi
if errorlevel 1 (
    echo [ERROR] maturin build failed.
    exit /b 1
)

echo.
echo [wheels] moving built wheel to %REPO_ROOT%\wheels\
for %%w in (target\wheels\*.whl) do (
    move /y "%%w" "%REPO_ROOT%\wheels\" 1>nul
)
echo [wheels] done.

echo.
echo ============================================================
echo Wheel built. Re-run .\install.bat to install it, or copy the
echo wheel from %REPO_ROOT%\wheels\ into other machines.
echo ============================================================
endlocal
