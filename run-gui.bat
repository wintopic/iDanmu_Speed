@echo off
setlocal
cd /d "%~dp0"

python "%~dp0danmu_gui.py"
exit /b %ERRORLEVEL%
