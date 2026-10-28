@echo off
rem OLR Scout: double-click to start. Leave this window open while you use the app.
setlocal
cd /d "%~dp0backend"

rem A finished install leaves .venv\installed.ok. If the window was closed half-way,
rem the marker is missing and the install simply runs again.
if not exist ".venv\installed.ok" (
  echo First run: setting up Python packages. This takes a few minutes - do not close this window.
  if exist .venv rmdir /s /q .venv
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" goto :nopython
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :pipfail
  echo ok> ".venv\installed.ok"
)

if not exist "..\frontend\dist\index.html" (
  echo Building the app screens...
  pushd ..\frontend
  call npm install
  if errorlevel 1 goto :npmfail
  call npm run build
  if errorlevel 1 goto :npmfail
  popd
)

echo.
echo OLR Scout is running. Open http://localhost:8000 in your browser.
echo Close this window to stop it.
echo.
".venv\Scripts\python.exe" -m uvicorn olr_scout.main:app --host 127.0.0.1 --port 8000
echo.
echo OLR Scout stopped. If you did not stop it yourself, the error is shown above.
pause
exit /b

:nopython
echo.
echo ERROR: Python was not found. Install Python 3.12 from python.org and tick
echo "Add python.exe to PATH" on the first installer screen, then restart the PC.
pause
exit /b 1

:pipfail
echo.
echo ERROR: installing Python packages failed - see the messages above.
echo Check the internet connection and run this file again.
pause
exit /b 1

:npmfail
popd
echo.
echo ERROR: building the app screens failed - see the messages above.
echo Is Node.js installed? Run this file again after installing it.
pause
exit /b 1
