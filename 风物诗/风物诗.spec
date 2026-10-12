# -*- mode: python ; coding: utf-8 -*-
"""风物诗 —— PyInstaller 打包配置（--onedir）。

为什么是 onedir 而不是 onefile：
  · onefile 每次启动都要把几十 MB 解压到临时目录，冷启动要好几秒；
  · 工具脚本（获取谱子/*.py）本来就要**以文件形式**躺在 exe 旁边被 importlib
    就地加载，onefile 反而把结构搞乱；
  · onedir 便于用户自己替换/修补脚本，也便于做增量更新。

产物：dist/风物诗/风物诗.exe  +  dist/风物诗/_internal/
配套：打包.bat 会把 获取谱子/ 与 parser.py / player.py 复制到 dist/风物诗/，
      让产出的目录**直接可跑**（工具脚本靠 exe 同级的 获取谱子/ 找到）。
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("customtkinter")

hiddenimports = [
    "keyboard",              # 弹琴要的模拟按键（play.py 里在函数内 import）
    "darkdetect",            # customtkinter 的主题探测
    "PIL._tkinter_finder",   # Pillow 在 Tk 下的探测钩子
]
hiddenimports += collect_submodules("darkdetect")

# 瘦身：这些要么用不到，要么体积大又不影响功能
excludes = [
    "pytest", "IPython", "matplotlib", "pandas", "scipy",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    "setuptools", "pip", "PyInstaller",
    "tkinter.test", "test", "unittest", "pydoc", "doctest",
    "numpy.f2py", "numpy.testing", "numpy.distutils",
    "email", "http", "xml", "html", "urllib.request",
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="风物诗",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                     # UPX 压缩会被部分杀软误报，不用
    console=False,                 # ★ 不要黑窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/风物诗.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="风物诗",
)
