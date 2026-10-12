@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"
title Shipu WebUI - jianpu image to machine score

echo ====================================================================
echo   Shipu WebUI - frontend UI / backend processing
echo ====================================================================
echo.

set "PYPIL="
set "PYANY="

if defined SHIPU_PY (
  set "PYANY=%SHIPU_PY%"
  "!PYANY!" -c "import sys" >nul 2>&1 || set "PYANY="
)

for /f "delims=" %%L in ('where python.exe 2^>nul') do (
  if not defined PYANY (
    "%%L" -c "import sys" >nul 2>&1 && set "PYANY=%%L"
  )
  if not defined PYPIL (
    "%%L" -c "import PIL" >nul 2>&1 && set "PYPIL=%%L"
  )
)
for /f "delims=" %%L in ('where python3.exe 2^>nul') do (
  if not defined PYANY (
    "%%L" -c "import sys" >nul 2>&1 && set "PYANY=%%L"
  )
  if not defined PYPIL (
    "%%L" -c "import PIL" >nul 2>&1 && set "PYPIL=%%L"
  )
)
if not defined PYANY if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" (
  set "PYANY=%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
  "!PYANY!" -c "import sys" >nul 2>&1 || set "PYANY="
)
if not defined PYPIL if defined PYANY (
  "!PYANY!" -c "import PIL" >nul 2>&1 && set "PYPIL=!PYANY!"
)

rem Prefer an interpreter that has PIL: scale-normalize runs inside this server.
set "PYEXE=!PYANY!"
if defined PYPIL set "PYEXE=!PYPIL!"

if not defined PYEXE (
  echo   [ERROR] No usable Python found.
  echo   Install Python 3.10+ , or set SHIPU_PY to the interpreter path.
  echo.
  pause
  exit /b 1
)

echo   Python    : !PYEXE!
"!PYEXE!" -c "import importlib.util as u,sys;print('   Version   : '+sys.version.split()[0]);print('   PIL       : '+('yes' if u.find_spec('PIL') else 'no  -> scale-normalize disabled'))"
echo.
echo   A browser tab will open at http://127.0.0.1:8760/
echo   Close this window (or press Ctrl+C) to stop the server.
echo.

"!PYEXE!" "%~dp0server.py"

echo.
echo   Server stopped.
pause
exit /b 0
