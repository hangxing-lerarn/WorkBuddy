# -*- coding: utf-8 -*-
"""自检报告：一次性把「运行环境到底对不对」摊开写成文本。

两个用途：
  1. 打包后验证 —— `风物诗.exe --selftest 报告.txt`，确认冻结环境里路径都找得到；
  2. 出问题时取证 —— 设置页可一键导出，用户把报告发过来就能定位。

刻意只做只读检查 + 一次配置落盘试写，不碰任何曲谱文件。
"""
from __future__ import annotations

import os
import platform
import sys
import time
from pathlib import Path

from . import paths

# 应用要用到的工具脚本（相对 获取谱子/）
TOOL_SCRIPTS = [
    "jianpu_to_score.py", "midi_to_score.py", "retime.py", "add_hold.py",
    "verify_original.py", "字母谱转谱.py", "字母谱对账.py",
]
OCR_SCRIPTS = ["识谱.py", "imgio.py", "audit.py", "字模.json"]
DEPS = [
    ("customtkinter", "界面框架"),
    ("PIL", "图片处理"),
    ("numpy", "背景生成/数值"),
    ("keyboard", "模拟按键（弹琴要）"),
    ("darkdetect", "主题探测"),
    ("tkinter", "Windows 自带"),
]


def _line(title: str = "") -> str:
    return ("\n" + "=" * 68 + ("\n" + title if title else "") + "\n" + "=" * 68
            if title else "")


def collect() -> str:
    out: list[str] = []
    add = out.append

    add("风物诗 自检报告")
    add("生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    add("版本：%s" % paths.APP_VERSION)

    add(_line("一、运行环境"))
    add("Python：%s" % sys.version.replace("\n", " "))
    add("平台：%s %s" % (platform.system(), platform.release()))
    add("架构：%s" % platform.machine())
    add("打包运行(frozen)：%s" % bool(getattr(sys, "frozen", False)))
    add("sys.executable：%s" % sys.executable)
    add("应用目录(APP_DIR)：%s" % paths.APP_DIR)
    add("工作目录(cwd)：%s" % os.getcwd())

    add(_line("二、依赖"))
    for mod, why in DEPS:
        try:
            m = __import__(mod)
            v = getattr(m, "__version__", "") or getattr(m, "TkVersion", "")
            add("  ✓ %-14s %-22s %s" % (mod, str(v)[:22], why))
        except Exception as e:
            add("  ✗ %-14s %-22s %s   （%s）" % (mod, "缺失", why, e))

    add(_line("三、目录"))
    add("数据目录(文档\\风物诗)：%s" % paths.DATA_DIR)
    add("缓存目录(LOCALAPPDATA)：%s" % paths.CACHE_DIR)
    dd = paths.data_dirs()
    add("实际生效的数据目录：%s" % dd["data"])
    if dd["data"] != paths.DATA_DIR:
        add("  （被 FENGWUSHI_DATA_DIR 或设置覆盖）")
    for k in ("scores", "jianpu", "base", "no", "yes", "out"):
        p = Path(dd[k])
        n = ""
        try:
            n = "，%d 个条目" % len(list(p.iterdir()))
        except Exception as e:
            n = "，读不到：%s" % e
        add("  %-8s %s%s" % (k, p, n))

    add(_line("四、工具脚本"))
    sd = paths.scripts_dir()
    add("获取谱子 目录：%s" % (sd if sd else "★ 未找到"))
    if sd:
        add("仓库根(推导)：%s" % paths.repo_dir())
        for name in TOOL_SCRIPTS:
            p = sd / name
            add("  %s %-22s %s"
                % ("✓" if p.is_file() else "✗", name,
                   ("%.1f KB" % (p.stat().st_size / 1024)) if p.is_file()
                   else "缺失"))
        ocr = sd / "简谱识谱"
        add("  简谱识谱/(%s)" % ("存在" if ocr.is_dir() else "★ 不存在"))
        for name in OCR_SCRIPTS:
            p = ocr / name
            add("    %s %-16s %s"
                % ("✓" if p.is_file() else "✗", name,
                   ("%.1f KB" % (p.stat().st_size / 1024)) if p.is_file()
                   else "缺失"))
    for name in ("parser.py", "player.py"):
        repo = paths.repo_dir()
        p = (repo / name) if repo else None
        add("  %s %-22s %s"
            % ("✓" if p and p.is_file() else "✗", name,
               str(p) if p and p.is_file() else "缺失（弹琴/工具要它）"))

    add(_line("五、配置落盘"))
    try:
        from . import settings as st
        add("配置文件：%s" % paths.SETTINGS_PATH)
        add("写盘模式：%s（%s）"
            % (paths.write_mode(),
               {"atomic": "优先原子替换",
                "direct": "已降级为直接覆盖写（受限环境）",
                "unknown": "本次还没写过"}.get(paths.write_mode(), "")))
        err = st.update_quiet(appearance={})
        add("试写结果：%s" % ("失败 —— %s" % err[1] if err[1] else "通过 ✓"))
        if err[1] is None:
            back = st.load()["appearance"]
            add("回读校验：accent=%s font_scale=%s"
                % (back.get("accent"), back.get("font_scale")))
    except Exception as e:
        add("！检查配置时出错：%s: %s" % (type(e).__name__, e))

    add(_line("六、环境变量覆盖"))
    for k in ("FENGWUSHI_DATA_DIR", "FENGWUSHI_CACHE_DIR", "FENGWUSHI_SCRIPTS"):
        add("  %-20s %s" % (k, os.environ.get(k) or "（未设置）"))

    add(_line())
    add("报告结束。")
    return "\n".join(out)


def write_report(dst: str | Path) -> Path:
    p = Path(dst)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    paths.write_text(p, collect())
    return p


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    dst = args[0] if args else str(Path(os.getcwd()) / "风物诗-自检报告.txt")
    try:
        p = write_report(dst)
    except Exception as e:
        sys.stderr.write("写报告失败：%s: %s\n" % (type(e).__name__, e))
        return 1
    sys.stdout.write("自检报告已写入：%s\n" % p)
    return 0
