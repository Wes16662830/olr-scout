@echo off
rem OLR Scout: download the latest version from GitHub and install it over this folder.
rem Keeps your .env, your data (backend\data), installed packages and recorded pages.
rem Uses only tools built into Windows 10/11 (curl, tar, robocopy), called by full path.
setlocal
cd /d "%~dp0"
set "SYS=%SystemRoot%\System32"
set "WORK=%TEMP%\olr-scout-update"
set "ZIP=%TEMP%\olr-scout-update.zip"

echo Close the OLR Scout window first if it is running.
pause

echo Downloading the latest OLR Scout...
if exist "%ZIP%" del /q "%ZIP%"
"%SYS%\curl.exe" -L --fail --silent --show-error -o "%ZIP%" "https://github.com/Wes16662830/olr-scout/archive/refs/heads/main.zip"
if errorlevel 1 goto :fail

echo Unpacking...
if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%WORK%"
"%SYS%\tar.exe" -xf "%ZIP%" -C "%WORK%"
if errorlevel 1 goto :fail
if not exist "%WORK%\olr-scout-main\start-windows.bat" goto :fail

echo Installing it...
"%SYS%\robocopy.exe" "%WORK%\olr-scout-main" "%CD%" /E /XD .venv data node_modules dist recorded /XF .env update-windows.bat /NFL /NDL /NJH /NJS /NP
if %ERRORLEVEL% GEQ 8 goto :fail

rem Rebuild the app screens on next start, and add any new Python packages now.
if exist "frontend\dist" rmdir /s /q "frontend\dist"
if exist "backend\.venv\Scripts\python.exe" "backend\.venv\Scripts\python.exe" -m pip install -q -r backend\requirements.txt

echo.
echo Updated. Double-click start-windows.bat to run the new version
echo (the first start rebuilds the app screens - give it a minute or two).

rem Replace this updater last. The whole block is read before it runs, so
rem overwriting the file underneath is safe.
(
  copy /y "%WORK%\olr-scout-main\update-windows.bat" "%~f0" >nul
  pause
  exit /b 0
)

:fail
echo.
echo ERROR: the update failed - see the messages above. Your .env and data are untouched.
echo Check the internet connection and try again, or update by hand with the ZIP from GitHub.
pause
exit /b 1
