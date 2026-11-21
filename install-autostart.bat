@echo off
rem Launch Hotkey automatically at Windows sign-in.
setlocal
cd /d "%~dp0"
python "%~dp0Hotkey.pyw" --install-autostart --verbose
echo.
pause
