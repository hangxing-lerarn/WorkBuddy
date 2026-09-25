@echo off
setlocal EnableExtensions
chcp 936 >nul 2>nul
title MIDI 批量转换 - 原神机器谱

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo ============================================================
echo    MIDI 批量转「原神风物之诗琴」机器谱
echo ============================================================
echo    待转换的 MIDI 放入 ： change_base\no
echo    生成的谱子　　　　 ： scores\ 下与 MIDI 同名的 txt
echo    转换完成的 MIDI 　 ： 自动移入 change_base\yes
echo ============================================================
echo.

rem ---------- 找一个可用的 python（本工具纯标准库，无需第三方依赖） ----------
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

"%PY_EXE%" "%ROOT%获取谱子\midi_to_score.py" %*
set "RC=%ERRORLEVEL%"

echo.
echo ============================================================
if "%RC%"=="0" (
    echo    全部转换完成
) else (
    echo    转换结束，有文件失败，它们仍留在 change_base\no
)
echo ============================================================
pause
exit /b %RC%

rem ---------- 子程序 ----------
:TryPython
rem 入参 %1 = 解释器命令；只要是 python3 就采用
if defined PY_EXE exit /b 0
%~1 -c "import sys; raise SystemExit(0 if sys.version_info[0] == 3 else 1)" >nul 2>&1
if not errorlevel 1 set "PY_EXE=%~1"
exit /b 0
