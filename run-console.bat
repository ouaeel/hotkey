@echo off
rem Start Hotkey inside a console so you can watch the log.
setlocal
cd /d "%~dp0"
python "%~dp0Hotkey.pyw" --verbose %*
pause
