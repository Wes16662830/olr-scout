@echo off
rem OLR Scout: checks what is installed. Double-click, then send a screenshot of the window.
setlocal
cd /d "%~dp0"
echo ============ OLR Scout setup check ============
echo Folder: %CD%
echo.

echo [Python]
py -3 --version 2>nul || python --version 2>nul || echo    NOT FOUND - install Python 3.12 and tick "Add python.exe to PATH"
echo.
echo [Node.js]
node --version 2>nul || echo    NOT FOUND - install Node.js LTS from nodejs.org
call npm --version 2>nul || echo    npm NOT FOUND
echo.
echo [Git - optional]
git --version 2>nul || echo    not installed (fine if you downloaded the ZIP)
echo.

echo [Settings file .env]
if exist ".env" (
  findstr /b /c:"OLR_SCOUT_PASSWORD=change-me" ".env" >nul && echo    PROBLEM: password is still change-me || echo    ok - .env found
  findstr /b /r /c:"OLR_SCOUT_PASSWORD=.." ".env" >nul || echo    PROBLEM: OLR_SCOUT_PASSWORD is empty
) else (
  if exist ".env.txt" (echo    PROBLEM: the file is called .env.txt - rename it to .env) else (echo    PROBLEM: no .env file - copy .env.example to .env)
)
echo.

echo [Python packages]
if exist "backend\.venv\installed.ok" (
  "backend\.venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, apscheduler, httpx, bs4, lxml, openpyxl; print('   ok - all packages installed')" 2>nul || echo    PROBLEM: packages incomplete - delete backend\.venv and run start-windows.bat again
) else (
  if exist "backend\.venv" (echo    PROBLEM: install did not finish - run start-windows.bat again and keep it open) else (echo    not installed yet - run start-windows.bat)
)
echo.

echo [App screens]
if exist "frontend\dist\index.html" (echo    ok - built) else (echo    not built yet - start-windows.bat builds them)
echo.

echo [Is OLR Scout running?]
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul && echo    yes - open http://localhost:8000 || echo    no - double-click start-windows.bat
echo.

echo [Data]
if exist "backend\data\olr_scout.db" (echo    ok - database exists) else (echo    no database yet - created on first start)
if exist "backend\tests\fixtures\recorded" (echo    recorded pages found - upload this folder to GitHub) else (echo    no recorded pages yet - Stage 1 step 6)
echo.
echo ===============================================
pause
