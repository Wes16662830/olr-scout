@echo off
rem OLR Scout: check what the OLR results site returns. Copy the text that opens and send it to Claude.
setlocal
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo Run start-windows.bat once first.
  pause
  exit /b 1
)
echo Checking the results site - this takes about 15 seconds...
".venv\Scripts\python.exe" scripts\diagnose_results.py
start "" notepad "%~dp0results-diagnosis.txt"
pause
