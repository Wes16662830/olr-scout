@echo off
rem OLR Scout: double-click to start. Leave this window open while you use the app.
setlocal
cd /d "%~dp0backend"

rem A finished install leaves .venv\installed.ok (a copy of requirements.txt). If the window
rem was closed half-way, the marker is missing and the install simply runs again. If an update
rem changed requirements.txt, only the packages are brought up to date.
if exist ".venv\installed.ok" (
  "%SystemRoot%\System32\fc.exe" /b requirements.txt ".venv\installed.ok" >nul 2>&1 && goto :screens
  if exist ".venv\Scripts\python.exe" goto :packages
)

echo First run: setting up Python packages. This takes a few minutes - do not close this window.
if exist .venv rmdir /s /q .venv

rem Use Python 3.13, 3.12 or 3.11. Brand-new versions such as 3.15 often lack
rem ready-made packages on Windows and then fail asking for C++ Build Tools.
set "PYCMD="
py -3.13 -c "pass" >nul 2>&1 && set "PYCMD=py -3.13"
if not defined PYCMD py -V:3.13 -c "pass" >nul 2>&1 && set "PYCMD=py -V:3.13"
if not defined PYCMD python3.13 -c "pass" >nul 2>&1 && set "PYCMD=python3.13"
if not defined PYCMD py -3.12 -c "pass" >nul 2>&1 && set "PYCMD=py -3.12"
if not defined PYCMD python3.12 -c "pass" >nul 2>&1 && set "PYCMD=python3.12"
if not defined PYCMD py -3.11 -c "pass" >nul 2>&1 && set "PYCMD=py -3.11"
if not defined PYCMD goto :wrongpython

echo Using: %PYCMD%
%PYCMD% --version
%PYCMD% -m venv .venv
if not exist ".venv\Scripts\python.exe" goto :wrongpython
".venv\Scripts\python.exe" -m pip install --upgrade pip

:packages
echo Installing / updating Python packages...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :pipfail
copy /y requirements.txt ".venv\installed.ok" >nul

:screens
if exist "..\frontend\dist\index.html" goto :run
echo Building the app screens...
pushd ..\frontend
call npm install
if errorlevel 1 goto :npmfail
call npm run build
if errorlevel 1 goto :npmfail
popd

:run
echo.
echo OLR Scout is starting - your browser opens http://localhost:8000 automatically.
echo Close this window to stop it.
echo.
set "OLR_SCOUT_OPEN_BROWSER=1"
rem Use SQLAlchemy without its compiled speed-ups: Windows Smart App Control / Application
rem Control policies can block those files ("DLL load failed ... _processors_cy"). Barely slower.
set "DISABLE_SQLALCHEMY_CEXT_RUNTIME=1"
".venv\Scripts\python.exe" -m uvicorn olr_scout.main:app --host 127.0.0.1 --port 8000
echo.
echo OLR Scout stopped. If you did not stop it yourself, the error is shown above.
pause
exit /b

:wrongpython
echo.
echo ERROR: OLR Scout needs Python 3.13 - 3.12 or 3.11 also work.
echo Newer versions such as 3.15 are too new for some packages on Windows.
echo Install 3.13 next to it: open Command Prompt and type
echo     py install 3.13
echo If that command is not recognised, download Python 3.13 from python.org instead.
echo Then double-click this file again.
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
