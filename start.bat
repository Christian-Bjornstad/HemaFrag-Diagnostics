@echo off
REM start.bat - launch HemaFrag Diagnostics GUI
REM   - Activates the venv created by install.bat
REM   - Runs qt_app.py with UTF-8 stdout/stderr
REM   - Captures output to start.log (overwrite, not append - latest run only)
REM   - Always flushes the log to disk before anything else
REM   - Exit code mirrors what qt_app.py crashed with

setlocal

REM Repo root is the directory containing this start.bat
set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

cd /d "%REPO_ROOT%"

set "VENV_PY=%REPO_ROOT%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [start.bat] .venv not found at %REPO_ROOT%\.venv
    echo [start.bat] Run .\install.bat first to create the venv.
    exit /b 2
)

REM Truncate the log first so we never read a stale traceback from a prior run.
echo --- HemaFrag Diagnostics start.bat --- > "%REPO_ROOT%\start.log"
echo run bat: %~f0                    >> "%REPO_ROOT%\start.log"
echo run stamp: %DATE% %TIME%          >> "%REPO_ROOT%\start.log"
echo venv python: %VENV_PY%             >> "%REPO_ROOT%\start.log"
echo qt_app: %REPO_ROOT%\qt_app.py      >> "%REPO_ROOT%\start.log"
echo ----------------------------------   >> "%REPO_ROOT%\start.log"
echo.                                    >> "%REPO_ROOT%\start.log"

REM Run qt_app.py, capture both stdout and stderr, with -u for unbuffered output.
"%VENV_PY%" -u -X utf8 "%REPO_ROOT%\qt_app.py" %* 1>>"%REPO_ROOT%\start.log" 2>&1
set "EC=%ERRORLEVEL%"

echo.                                                 >> "%REPO_ROOT%\start.log"
echo ----------------------------------              >> "%REPO_ROOT%\start.log"
echo exit code: %EC%                                  >> "%REPO_ROOT%\start.log"

if not "%EC%"=="0" (
    echo.
    echo [start.bat] qt_app.py exited with code %EC% — see start.log
)

exit /b %EC%
