@echo off
setlocal EnableExtensions
chcp 936 >nul 2>nul
title 自动弹琴 - 原神风物之诗琴

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "RELAUNCHED="
if /i "%~1"=="--elevated" set "RELAUNCHED=1"
set "SKIP_ELEVATE="
if /i "%~1"=="--no-elevate" set "SKIP_ELEVATE=1"

echo ============================================================
echo    原神「风物之诗琴」自动弹琴
echo ============================================================
echo.

rem ---------- 1. 权限检查：原神以管理员运行，发按键必须同级权限 ----------
if defined SKIP_ELEVATE goto :ADMIN_UNKNOWN
fltmc >nul 2>&1
if not errorlevel 1 goto :ADMIN_OK
if defined RELAUNCHED goto :ADMIN_UNKNOWN

echo [权限] 当前不是管理员身份，正在申请提权...
echo        原因：原神以管理员权限运行，普通权限发出的按键会被 Windows
echo        静默丢弃，表现为「脚本日志正常、游戏毫无反应」。
echo        马上会弹出 UAC 窗口，请点「是」。
echo.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%ROOT%' -ArgumentList '--elevated' -Verb RunAs"
if errorlevel 1 (
    echo [错误] 提权失败或被取消。
    echo        请右键本文件，选择「以管理员身份运行」。
    echo.
    pause
)
exit /b 0

:ADMIN_OK
echo [权限] 管理员身份：OK
echo.
goto :FIND_PY

:ADMIN_UNKNOWN
echo [权限] 未确认管理员身份，继续执行。
echo        若游戏对按键毫无反应，请改用「以管理员身份运行」。
echo.
goto :FIND_PY

rem ---------- 2. 找一个可用的 python ----------
:FIND_PY
set "PY_EXE="
call :TryPython python
if not defined PY_EXE call :TryPython py
if not defined PY_EXE call :TryPython "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
if not defined PY_EXE (
    echo [错误] 没有找到可用的 python 解释器。
    echo        请先安装 Python 3，再重新运行本脚本。
    echo.
    pause
    exit /b 1
)
echo [解释器] %PY_EXE%
echo.

rem ---------- 3. 检查 keyboard 依赖 ----------
"%PY_EXE%" -c "import keyboard" >nul 2>&1
if errorlevel 1 (
    echo [错误] 缺少依赖库 keyboard，无法模拟按键。
    echo.
    echo   请把下面这条命令复制到命令行里执行，然后重新运行本脚本：
    echo       "%PY_EXE%" -m pip install -r "%ROOT%requirements.txt"
    echo.
    pause
    exit /b 1
)
echo [依赖] keyboard：OK
echo.

rem ---------- 4. 启动 ----------
echo 操作提示：
echo   1. 在下面选曲目、起始行、倍速，然后按回车。
echo   2. 切回原神窗口，打开琴的演奏界面。
echo   3. 在游戏窗口中按 F8 开始，会有 2 秒缓冲。
echo   4. 演奏中按空格暂停；暂停时按 F8 继续，按 P 返回选曲。
echo.
"%PY_EXE%" "%ROOT%main.py"
echo.
echo 程序已退出。
pause
exit /b 0

rem ---------- 子程序 ----------
:TryPython
rem 入参 %1 = 解释器命令；python3 且能 import keyboard 才采用
if defined PY_EXE exit /b 0
%~1 -c "import sys, keyboard; raise SystemExit(0 if sys.version_info[0] == 3 else 1)" >nul 2>&1
if not errorlevel 1 set "PY_EXE=%~1"
exit /b 0
