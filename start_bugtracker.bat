@echo off
rem SPDX-License-Identifier: AGPL-3.0-or-later
rem Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
setlocal EnableExtensions
rem ==========================================================================
rem  Bug Tracker - start in the background and open it in the browser.
rem
rem  Double-click this file, or "Bug Tracker.vbs" for no window at all.
rem  - Uses venv\Scripts\pythonw.exe if there is a venv, else pythonw on PATH
rem  - Installs missing packages on the first run
rem  - Runs Waitress with no console window; output goes to logs\server.log
rem  - If the app is already running, it just opens the page
rem  Stop it with stop_bugtracker.bat.
rem ==========================================================================

rem Port to use. Set HOST=0.0.0.0 to let other computers on the network in.
set "PORT=5000"
set "HOST=127.0.0.1"

set "SILENT="
if /i "%~1"=="/silent" set "SILENT=1"

cd /d "%~dp0"
set "URL=http://127.0.0.1:%PORT%/"

rem -- find Python -----------------------------------------------------------
set "PYW="
set "PY="
if exist "%~dp0venv\Scripts\pythonw.exe" set "PYW=%~dp0venv\Scripts\pythonw.exe"
if not defined PYW if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not defined PYW for %%P in (pythonw.exe) do set "PYW=%%~$PATH:P"
if defined PYW set "PY=%PYW:pythonw.exe=python.exe%"
rem python.org installs without "Add to PATH" still have the py launcher
if not defined PYW for %%P in (pyw.exe) do set "PYW=%%~$PATH:P"
if defined PYW if not defined PY set "PY=%PYW:pyw.exe=py.exe%"
if not defined PYW (
    call :fail "Python was not found. Install Python 3.10 or newer from python.org, then run this again."
    exit /b 1
)

rem -- already running? just open it -----------------------------------------
call :is_up
if not errorlevel 1 goto open

rem -- first run: install packages -------------------------------------------
"%PY%" -c "import flask, flask_sqlalchemy, flask_login, flask_wtf, waitress" >nul 2>&1
if errorlevel 1 (
    if not defined SILENT echo Installing required packages ^(first run only^)...
    "%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt waitress >"%TEMP%\bugtracker_pip.log" 2>&1
    if errorlevel 1 (
        call :fail "Installing packages failed. Details: %TEMP%\bugtracker_pip.log"
        exit /b 1
    )
)

rem -- start the server with no window ---------------------------------------
if not exist "logs" mkdir "logs"
echo.>>"logs\server.log"
echo ===== %DATE% %TIME% starting on %HOST%:%PORT% =====>>"logs\server.log"
start "" /b "%PYW%" -m waitress --host=%HOST% --port=%PORT% app:app >>"logs\server.log" 2>&1

rem -- wait up to 30 seconds for it to answer ---------------------------------
if not defined SILENT echo Starting Bug Tracker...
set /a TRIES=0
:wait
call :is_up
if not errorlevel 1 goto open
set /a TRIES+=1
if %TRIES% geq 30 (
    call :fail "Bug Tracker didn't start within 30 seconds. See logs\server.log in %~dp0"
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait

:open
start "" "%URL%"
exit /b 0

rem -- helpers ---------------------------------------------------------------
:is_up
rem errorlevel 0 when something is accepting connections on the port
powershell -NoProfile -NonInteractive -Command "try { (New-Object Net.Sockets.TcpClient('127.0.0.1', %PORT%)).Close(); exit 0 } catch { exit 1 }" >nul 2>&1
exit /b %errorlevel%

:fail
set "BT_MSG=%~1"
if defined SILENT (
    powershell -NoProfile -NonInteractive -Command "Add-Type -AssemblyName PresentationFramework; [void][System.Windows.MessageBox]::Show($env:BT_MSG, 'Bug Tracker')" >nul 2>&1
    exit /b 1
)
echo.
echo %BT_MSG%
echo.
pause
exit /b 1
