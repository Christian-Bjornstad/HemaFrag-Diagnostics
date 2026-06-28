@echo off
REM ============================================================
REM HemaFrag Diagnostics - one-time Rust toolchain setup (Windows)
REM
REM Installs: rustup (stable Rust) + Visual Studio Build Tools (C++)
REM Builds:   nothing - this only installs prerequisites.
REM
REM After this completes successfully, run build_wheel_windows.bat.
REM ============================================================

setlocal ENABLEDELAYEDEXPANSION

REM 1) rustup
where rustup >nul 2>&1
if not errorlevel 1 (
    echo [rust] rustup already installed.
    rustup --version
) else (
    echo [rust] installing rustup via winget...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo [WARN] winget not found. Falling back to https://rustup.rs download.
    ) else (
        winget install --id Rustlang.Rustup --silent --accept-package-agreements --accept-source-agreements
        if errorlevel 1 (
            echo [WARN] winget install failed  -  falling back to direct download.
        )
    )
    where rustup >nul 2>&1
    if errorlevel 1 (
        echo [rust] direct download from https://win.rustup.rs/x86_64 ...
        bitsadmin /transfer rustupInstall https://win.rustup.rs/x86_64 "%TEMP%\rustup-init.exe" >nul
        "%TEMP%\rustup-init.exe" -y --default-toolchain stable-msvc --profile minimal --no-modify-path
        if errorlevel 1 (
            echo [ERROR] rustup install failed.
            exit /b 1
        )
    )
)

REM 2) Make sure stable-msvc toolchain is installed and default
where rustc >nul 2>&1
if errorlevel 1 (
    set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
)
rustup show active-toolchain 1>nul 2>nul
if errorlevel 1 (
    rustup toolchain install stable-msvc
    rustup default stable-msvc
)

REM 3) Visual Studio Build Tools (for MSVC linker)
where cl >nul 2>&1
if errorlevel 1 (
    echo [msvc] checking for VS Build Tools...
    if exist "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vs_installer.exe" (
        echo [msvc] VS Installer found but no cl.exe visible. Add the MSVC tool directory to PATH.
        echo [msvc] try:  C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\<version>\bin\Hostx64\x64
    ) else (
        echo [msvc] installing VS Build Tools 2022 ...
        winget install --id Microsoft.VisualStudio.2022.BuildTools --silent --accept-source-agreements --override "/quiet /norestart /noprocessrelaunch /add Microsoft.VisualStudio.Workload.VCTools /add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 /add Microsoft.VisualStudio.Component.Windows10SDK.20348"
    )
)

REM 4) Install maturin for wheel building
echo.
echo [pip] installing maturin ...
where "%REPO_ROOT%\.venv\Scripts\python.exe" >nul 2>nul
if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
    "%REPO_ROOT%\.venv\Scripts\python.exe" -m pip install --upgrade maturin
) else (
    python -m pip install --upgrade maturin --user
)

echo.
echo ============================================================
echo Rust toolchain setup complete.
echo.
echo Next step:   run   .\build_wheel_windows.bat
echo ============================================================
endlocal
