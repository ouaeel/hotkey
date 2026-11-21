@echo off
rem Start Hotkey in the background (no console window).
setlocal
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0Hotkey.pyw" %*
    exit /b 0
)
start "" python "%~dp0Hotkey.pyw" %*
