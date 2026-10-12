"""路径契约：数据目录 / 缓存目录 / 工具脚本位置。

设计前提（已与用户逐项确认）：

  · 曲谱与 MIDI 队列放「文档\\风物诗\\」—— 便携、用户可见、方便往里丢文件
  · 字模、识谱中间产物、背景缓存、配置放 %LOCALAPPDATA%\\风物诗\\
  · 仓库里原有的 简谱/ scores/ change_base/ **一律不动**；
    首次运行只「复制一份」给应用用，绝不移动、绝不删除、绝不覆盖

工具脚本（jianpu_to_score.py / midi_to_score.py / 识谱.py …）仍然住在仓库的
`获取谱子/` 下，应用通过 importlib 就地加载它们 —— 它们自己相对 __file__ 定位的
数据（字模.json 等）因此依然正确。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "风物诗"
APP_VERSION = "0.1.0"
EXE_NAME = "风物诗"

# --------------------------------------------------------------------------
# 应用自身位置
# --------------------------------------------------------------------------


def app_dir() -> Path:
    """打包后 = exe 所在目录；开发期 = 风物诗/ 目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = app_dir()


# --------------------------------------------------------------------------
# 数据目录（文档\风物诗\）
# --------------------------------------------------------------------------


def _documents() -> Path:
    """向 Windows 要「文档」的真实位置（可能被 OneDrive 重定向到别处）。"""
    try:
        buf = ctypes.create_unicode_buffer(260)
        # CSIDL_PERSONAL = 5，SHGFP_TYPE_CURRENT = 0
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:
            p = Path(buf.value)
            if p.is_dir():
                return p
    except Exception:
        pass
    return Path(os.path.expanduser("~")) / "Documents"


def _local_appdata() -> Path:
    p = os.environ.get("LOCALAPPDATA")
    return Path(p) if p else Path(os.path.expanduser("~")) / "AppData" / "Local"


DATA_DIR = _documents() / APP_NAME
SCORES_DIR = DATA_DIR / "scores"            # 机器谱（弹琴读这里）
JIANPU_DIR = DATA_DIR / "简谱"               # 简谱文本
BASE_DIR = DATA_DIR / "change_base"
NO_DIR = BASE_DIR / "no"                    # 待转 MIDI
YES_DIR = BASE_DIR / "yes"                  # 已转 MIDI
OUT_DIR = DATA_DIR / "产物"                  # 识谱/转换的预览产物

def _cache_override() -> Path | None:
    """允许把缓存/配置目录挪到别处（环境变量 FENGWUSHI_CACHE_DIR）。

    用途：多份配置并存、把配置放到便携目录、或排查写盘权限问题时换个目录试。
    """
    p = os.environ.get("FENGWUSHI_CACHE_DIR", "").strip()
    return Path(p) if p else None


_cache_env = _cache_override()
CACHE_DIR = _cache_env if _cache_env else (_local_appdata() / APP_NAME)
WORK_DIR = CACHE_DIR / "work"               # 临时首行改写副本、识谱中间件
PREVIEW_DIR = CACHE_DIR / "preview"         # 转换产物预览（保存前）
BG_DIR = CACHE_DIR / "backgrounds"          # 预设背景图
LOG_DIR = CACHE_DIR / "logs"
SETTINGS_PATH = CACHE_DIR / "settings.json"
SEED_MARK = CACHE_DIR / ".seeded"

ALL_DIRS = (
    DATA_DIR, SCORES_DIR, JIANPU_DIR, NO_DIR, YES_DIR, OUT_DIR,
    CACHE_DIR, WORK_DIR, PREVIEW_DIR, BG_DIR, LOG_DIR,
)


# 用户可在设置里改数据目录；为空则用默认。放在 settings 里，避免这里反向导入。
def data_dirs() -> dict:
    """返回当前生效的数据目录集合（settings 里若覆盖过就用覆盖值）。"""
    override = os.environ.get("FENGWUSHI_DATA_DIR", "").strip()
    if not override:
        try:
            from .settings import load as _load
            override = str(_load().get("paths", {}).get("data_dir", "") or "").strip()
        except Exception:
            override = ""
    if not override:
        return {
            "data": DATA_DIR, "scores": SCORES_DIR, "jianpu": JIANPU_DIR,
            "base": BASE_DIR, "no": NO_DIR, "yes": YES_DIR, "out": OUT_DIR,
        }
    root = Path(override)
    return {
        "data": root, "scores": root / "scores", "jianpu": root / "简谱",
        "base": root / "change_base", "no": root / "change_base" / "no",
        "yes": root / "change_base" / "yes", "out": root / "产物",
    }


# --------------------------------------------------------------------------
# 写盘：优先「写 .tmp + os.replace」原子替换，受限环境自动降级为直接覆盖
# --------------------------------------------------------------------------
#
# 实测（Windows / 本机）：某些受限环境会**只拦两件事** ——
#   · os.replace(tmp, dst) 改名覆盖 → PermissionError [WinError 5]
#   · os.remove / os.unlink 删除   → OSError [safe-delete]
# 而「新建文件」「open(p,'w') 覆盖已存在文件」都是允许的。
#
# 所以这里不假设 os.replace 可用：能用就用（崩溃安全），不能用就降级为
# 直接覆盖写，并把降级结果记在模块级变量里，避免每次都留一个 .tmp 残骸。

_WRITE_MODE: str | None = None          # None=未知 / "atomic" / "direct"


def write_mode() -> str:
    return _WRITE_MODE or "unknown"


def write_text(path, text: str) -> str:
    """写文本文件。返回实际走通的模式："atomic" 或 "direct"。

    失败会**向上抛**（不再静默吞掉）——静默失败会让调用方以为已经生效。
    """
    global _WRITE_MODE
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # 已知不支持改名覆盖：直接覆盖写
    if _WRITE_MODE == "direct":
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return "direct"

    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    except OSError:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        _WRITE_MODE = "direct"
        return "direct"

    try:
        os.replace(tmp, path)
    except OSError:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        _WRITE_MODE = "direct"
        try:
            os.remove(tmp)                      # 正常环境能删掉；沙箱里删不掉也不致命
        except OSError:
            pass
        return "direct"

    _WRITE_MODE = "atomic"
    return "atomic"


def ensure_dirs() -> None:
    for d in ALL_DIRS:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    for d in data_dirs().values():
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


# --------------------------------------------------------------------------
# 工具脚本位置
# --------------------------------------------------------------------------


_SCRIPTS_CACHE: Path | None | bool = False       # False = 还没找过


def scripts_dir() -> Path | None:
    """`获取谱子/` 目录。找不到返回 None（应用会给出明确提示，不静默失败）。"""
    global _SCRIPTS_CACHE
    if _SCRIPTS_CACHE is not False:
        return _SCRIPTS_CACHE  # type: ignore[return-value]

    cands: list[Path] = []
    env = os.environ.get("FENGWUSHI_SCRIPTS", "").strip()
    if env:
        cands.append(Path(env))
    try:
        from .settings import load as _load
        p = str(_load().get("paths", {}).get("scripts", "") or "").strip()
        if p:
            cands.append(Path(p))
    except Exception:
        pass
    # 打包后：依赖与 获取谱子/ 平级；开发期：风物诗/ 的上一级就是仓库根
    cands += [APP_DIR / "获取谱子", APP_DIR.parent / "获取谱子"]

    found: Path | None = None
    for c in cands:
        try:
            if (c / "jianpu_to_score.py").is_file():
                found = c
                break
        except Exception:
            continue
    _SCRIPTS_CACHE = found
    return found


def script(name: str) -> Path | None:
    d = scripts_dir()
    if d is None:
        return None
    p = d / name
    return p if p.is_file() else None


def ocr_dir() -> Path | None:
    d = scripts_dir()
    if d is None:
        return None
    p = d / "简谱识谱"
    return p if p.is_dir() else None


def ocr_script() -> Path | None:
    d = ocr_dir()
    return (d / "识谱.py") if d and (d / "识谱.py").is_file() else None


def repo_dir() -> Path | None:
    d = scripts_dir()
    return d.parent if d else None


# --------------------------------------------------------------------------
# 首次运行：把仓库现成数据复制一份给应用（只复制，绝不移动/删除/覆盖）
# --------------------------------------------------------------------------


def seed_data() -> list[str]:
    """返回本次新复制进来的条目名（首次运行才有内容）。"""
    if SEED_MARK.exists():
        return []
    repo = repo_dir()
    if repo is None:
        return []
    pairs = (("scores", SCORES_DIR), ("简谱", JIANPU_DIR), ("change_base", BASE_DIR))
    copied: list[str] = []
    for name, dst in pairs:
        src = repo / name
        if not src.is_dir():
            continue
        try:
            dst.mkdir(parents=True, exist_ok=True)
        except Exception:
            continue
        for item in sorted(src.iterdir()):
            target = dst / item.name
            if target.exists():
                continue
            try:
                if item.is_dir():
                    shutil.copytree(item, target)
                else:
                    shutil.copy2(item, target)
                copied.append(f"{name}/{item.name}")
            except Exception:
                continue
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        SEED_MARK.write_text(
            f"seeded from {repo}\n{len(copied)} items\n", encoding="utf-8")
    except Exception:
        pass
    return copied


def describe() -> str:
    """一行摘要，给设置页显示。"""
    d = data_dirs()
    s = scripts_dir()
    return (f"数据目录：{d['data']}\n"
            f"缓存目录：{CACHE_DIR}\n"
            f"工具脚本：{s if s else '未找到（请在设置里指定 获取谱子 目录）'}")
