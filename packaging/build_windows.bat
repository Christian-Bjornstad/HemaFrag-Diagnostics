@echo off
setlocal
cd /d "%~dp0\.."

REM Build on Windows 10/11 x64 with Python 3.12-3.14 and Rust/MSVC installed.
python -c "import sys; assert (3,12) <= sys.version_info[:2] < (3,15) and sys.maxsize > 2**32, 'Use 64-bit Python 3.12-3.14'"
if errorlevel 1 exit /b 1

if not exist ".venv-build\Scripts\python.exe" (
    python -m venv .venv-build
    if errorlevel 1 exit /b 1
)
set "BUILD_PYTHON=.venv-build\Scripts\python.exe"
"%BUILD_PYTHON%" -m pip install -r requirements.txt -r packaging\build-requirements.txt
if errorlevel 1 exit /b 1
"%BUILD_PYTHON%" -m pip install --force-reinstall --no-deps wheels\fraggler_kernels-0.1.3-cp310-abi3-win_amd64.whl
if errorlevel 1 exit /b 1
"%BUILD_PYTHON%" -c "import fraggler_native; assert fraggler_native.is_available(); assert fraggler_native.version == '0.1.3'"
if errorlevel 1 exit /b 1
"%BUILD_PYTHON%" build_qt.py
if errorlevel 1 exit /b 1

echo Build complete: dist\releases\HemaFrag_Windows.zip
exit /b 0
