@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 936 >nul 2>nul
title 风物诗 - 打包

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo ==================================================
echo    风物诗 . 打包
echo ==================================================
echo.

set "PY_EXE="
call :TryPython python
if not defined PY_EXE call :TryPython py
if not defined PY_EXE call :TryPython "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
if not defined PY_EXE goto :NO_PY

echo [解释器] %PY_EXE%
echo.
"%PY_EXE%" "%ROOT%tools\build.py" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" goto :OK
echo [失败] 退出码 %RC%
goto :DONE

:OK
echo [完成] 产物在  %ROOT%dist\风物诗\
echo        双击运行  %ROOT%dist\风物诗\风物诗.exe
echo        打安装包请加参数 --inno

:DONE
echo.
pause
exit /b %RC%

:NO_PY
echo [错误] 没找到装了 PyInstaller 的 python。
echo.
echo        装法：
echo          python -m pip install -r "%ROOT%requirements.txt"
echo          python -m pip install pyinstaller
echo.
pause
exit /b 1

:TryPython
rem 入参 %1 = 解释器命令；要能 import PyInstaller 才采用
if defined PY_EXE exit /b 0
%~1 -c "import PyInstaller" >nul 2>&1
if not errorlevel 1 set "PY_EXE=%~1"
exit /b 0
