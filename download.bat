@echo off
setlocal

if "%~1"=="" (
  echo 鐢ㄦ硶:
  echo   download.bat --input tasks.jsonl --base-url http://127.0.0.1:9321 --token 87654321
  echo.
  echo 鍙厛鎵ц:
  echo   download.bat --help
  exit /b 1
)

python "%~dp0danmu_batch_downloader.py" %*
exit /b %ERRORLEVEL%

