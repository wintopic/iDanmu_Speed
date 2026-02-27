@echo off
setlocal
cd /d "%~dp0"

echo [1/3] Install PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
  echo Failed to install PyInstaller
  exit /b 1
)

echo [2/3] Build EXE...
python -m PyInstaller --noconfirm --clean --windowed --onefile --name iDanmu_Speed_Mini --paths .. --add-data "..\\danmu_api-main;danmu_api-main" mini_gui.py
if errorlevel 1 (
  echo Build failed
  exit /b 1
)

echo [3/3] Done
echo EXE: dist\iDanmu_Speed_Mini.exe
echo Note: pure-local API mode needs Node.js + npm (for danmu_api-main).
exit /b 0
