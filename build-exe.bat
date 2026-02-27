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
python -m PyInstaller --noconfirm --clean --windowed --onedir --name iDanmu danmu_gui.py
if errorlevel 1 (
  echo Build failed
  exit /b 1
)

echo [3/3] Done
echo EXE: dist\iDanmu\iDanmu.exe
echo Note: Node.js is NOT required at runtime.
exit /b 0
