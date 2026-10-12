"""配置读写：%LOCALAPPDATA%\\风物诗\\settings.json

只存「这台机器上的偏好」，不存任何曲谱数据。缺字段就补默认值（深合并），
所以以后加新配置项不会因为旧配置文件而炸。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from . import paths

DEFAULTS: dict[str, Any] = {
    "appearance": {
        "mode": "dark",            # dark / light / system
        "accent": "紫",
        "font_scale": 1.0,          # 0.8 ~ 1.5
        "bg_kind": "preset",        # preset / image / solid
        "bg_preset": "深空紫",
        "bg_image": "",
        "bg_solid": "#0E0E16",
        "bg_dim": 0.30,             # 背景压暗 0~0.8（面板可读性）
        "bg_blur": 4,               # 背景高斯模糊半径
        "animations": True,         # 切页淡入等过渡动效
        "win_opacity": 1.0,         # 窗口整体不透明度（0.85~1.0）
    },
    "paths": {
        "scripts": "",             # 自定义 获取谱子 目录
        "data_dir": "",            # 自定义数据目录（空=文档\风物诗）
    },
    "behaviour": {
        "default_head": "1=C 4/4 91",
        "remember_head": True,
        "last_head": "",
        "sync_back": False,        # 「同步回仓库」开关（默认关，每次仍要点确认）
        "keep_preview": True,      # 转换后先给看产物、再点保存
        "auto_open_out": True,     # 完成后自动打开产物目录
    },
    "window": {
        "w": 1020, "h": 680, "x": None, "y": None, "maximized": False,
    },
    "play": {
        "start_delay": 2.0,        # F8 之后的缓冲秒数
        "speed": 1.0,
    },
}


def _merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


# 最近一次落盘的结果，供界面/自检查询（失败时非 None）
LAST_ERROR: str | None = None


def load() -> dict:
    try:
        raw = json.loads(Path(paths.SETTINGS_PATH).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return _merge(DEFAULTS, raw)
    except FileNotFoundError:
        pass
    except Exception:
        # 配置文件坏了也不能让应用起不来：退回默认，并把坏文件另存一份备份。
        # 注意：备份走 paths.write_text（不能 os.replace / os.remove，
        # 受限环境下改名与删除会被拒），且**不删除**原文件。
        try:
            p = Path(paths.SETTINGS_PATH)
            if p.exists():
                paths.write_text(p.with_name(p.name + ".bak"),
                                 p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    return copy.deepcopy(DEFAULTS)


def save(data: dict) -> str:
    """落盘，返回实际使用的写盘模式（atomic / direct）。

    ★ 失败**不再静默**：异常直接往上抛，并由 LAST_ERROR 留痕。
      之前这里写了 `except Exception: pass`，导致「配置写不进去」被瞒了整轮。
    """
    global LAST_ERROR
    text = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        mode = paths.write_text(paths.SETTINGS_PATH, text)
        LAST_ERROR = None
        return mode
    except Exception as e:
        LAST_ERROR = f"{type(e).__name__}: {e}"
        raise


def update(**sections: Any) -> dict:
    """局部更新并落盘，返回新配置。用法：update(appearance={"font_scale": 1.2})"""
    data = load()
    for k, v in sections.items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k] = _merge(data[k], v)
        else:
            data[k] = v
    save(data)
    return data


def update_quiet(**sections: Any) -> tuple[dict, str | None]:
    """update() 的「不炸界面」版本：返回 (配置, 错误信息或 None)。"""
    try:
        return update(**sections), None
    except Exception as e:
        data = load()
        for k, v in sections.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k] = _merge(data[k], v)
            else:
                data[k] = v
        return data, f"{type(e).__name__}: {e}"
