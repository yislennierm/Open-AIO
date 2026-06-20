@echo off
setlocal
cd /d "%~dp0"
echo Installing Electron runtime...
npm.cmd rebuild electron
if errorlevel 1 (
  echo.
  echo Electron runtime install failed.
  echo Make sure this command is run from a normal terminal with internet access.
  exit /b 1
)
echo.
echo Electron runtime installed. Starting app...
npm.cmd start
