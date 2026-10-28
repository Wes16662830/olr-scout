@echo off
rem OLR Scout: double-click to start. Leave this window open while you use the app.
cd /d "%~dp0backend"
if not exist .venv (
  echo First run: setting up Python packages, this takes a few minutes...
  py -3 -m venv .venv || python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
if not exist "..\frontend\dist\index.html" (
  echo Building the app screens...
  pushd ..\frontend
  call npm install
  call npm run build
  popd
)
echo.
echo OLR Scout is running. Open http://localhost:8000 in your browser.
echo Close this window to stop it.
echo.
python -m uvicorn olr_scout.main:app --host 127.0.0.1 --port 8000
pause
