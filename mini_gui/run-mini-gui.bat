@echo off
setlocal
cd /d "%~dp0"

python "%~dp0mini_gui.py"
exit /b %ERRORLEVEL%
