@echo off
rem OLR Scout: download the latest version from GitHub and install it over this folder.
rem Keeps your .env, your data (backend\data), installed packages and recorded pages.
setlocal
cd /d "%~dp0"
echo Close the OLR Scout window first if it is running.
pause

echo Downloading the latest OLR Scout...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $zip=Join-Path $env:TEMP 'olr-scout-update.zip'; $dir=Join-Path $env:TEMP 'olr-scout-update'; Invoke-WebRequest -UseBasicParsing 'https://github.com/Wes16662830/olr-scout/archive/refs/heads/main.zip' -OutFile $zip; if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }; Expand-Archive -Path $zip -DestinationPath $dir -Force"
if errorlevel 1 goto :fail

echo Installing it...
robocopy "%TEMP%\olr-scout-update\olr-scout-main" "%CD%" /E /XD .venv data node_modules dist recorded /XF .env update-windows.bat /NFL /NDL /NJH /NJS /NP
if %ERRORLEVEL% GEQ 8 goto :fail

rem Rebuild the app screens on next start, and add any new Python packages now.
if exist "frontend\dist" rmdir /s /q "frontend\dist"
if exist "backend\.venv\Scripts\python.exe" "backend\.venv\Scripts\python.exe" -m pip install -q -r backend\requirements.txt

echo.
echo Updated. Double-click start-windows.bat to run the new version
echo (the first start rebuilds the app screens - give it a minute or two).
pause
exit /b

:fail
echo.
echo ERROR: the update failed - see the messages above. Nothing important was changed;
echo your .env and data are untouched. Check the internet connection and try again.
pause
exit /b 1
