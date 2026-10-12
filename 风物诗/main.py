"""风物诗 —— 原神乐谱工具箱（入口）。

用法：
    风物诗                      直接打开界面
    风物诗 --page ocr           打开时直接停在某一页
    风物诗 --play <曲谱> ...     以管理员身份重启后自动开始演奏（内部用）

开发期：
    python 风物诗/main.py
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# 允许 `python 风物诗/main.py` 与打包后两种跑法
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

PAGE_KEYS = ["play", "midi", "jianpu", "ocr", "tools", "settings"]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="风物诗", description="原神乐谱工具箱")
    ap.add_argument("--page", choices=PAGE_KEYS, default=None,
                    help="启动后停在哪个页面")
    ap.add_argument("--play", metavar="曲谱路径", default=None,
                    help="（内部用）提权重启后自动演奏这个曲谱")
    ap.add_argument("--start-line", type=int, default=1)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--data-dir", default=None, help="覆盖数据目录")
    ap.add_argument("--shot", metavar="PNG", default=None,
                    help="（自检用）启动后截图保存再退出")
    ap.add_argument("--shots", metavar="DIR", default=None,
                    help="（自检用）逐页截图保存到目录再退出")
    ap.add_argument("--selftest", metavar="报告文件", nargs="?", const="",
                    default=None,
                    help="（自检用）生成环境自检报告后退出；不给路径就写到当前目录")
    ap.add_argument("--version", action="version", version="风物诗 0.1.0")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    if args.data_dir:
        os.environ["FENGWUSHI_DATA_DIR"] = args.data_dir

    from app import backgrounds, paths
    from app import settings as app_settings
    from app.window import App

    # 自检：只写一份报告就退出（不起界面、不加载背景），打包后验证环境用
    if args.selftest is not None:
        from app import selfcheck
        dst = args.selftest or str(Path(os.getcwd()) / "风物诗-自检报告.txt")
        return selfcheck.main([dst])

    paths.ensure_dirs()
    try:
        copied = paths.seed_data()
    except Exception:
        copied = []

    # 只保证「当前要用的那张」先就绪，其余丢后台生成，别拖慢启动
    try:
        cfg = app_settings.load()
        preset = str(cfg["appearance"].get("bg_preset") or "")
        backgrounds.ensure_presets(only=preset or None)
    except Exception:
        pass

    app = App(vars(args))
    if copied:
        app.after(600, lambda: app.toast(
            f"首次运行：已从仓库复制 {len(copied)} 个数据条目到应用目录"))

    if args.play:
        app.current_key = "play"

        def _prefill() -> None:
            try:
                page = app._pages.get("play") or app._make_page("play")
                app.show_page("play")
                page.prefill(args.play, args.start_line, args.speed, args.delay)
                page.auto_start()
            except Exception:
                pass
        app.after(400, _prefill)

    if args.shot:
        _install_shooter(app, args.shot)
    if args.shots:
        _install_page_shooter(app, args.shots)

    app.mainloop()
    return 0


def _hwnd_of(app) -> int:
    """拿到窗口真正的顶层 HWND（overrideredirect 下 winfo_id 可能就是它）。"""
    import ctypes
    wid = app.winfo_id()
    try:
        parent = ctypes.windll.user32.GetParent(wid)
        return parent or wid
    except Exception:
        return wid


def _capture_window(app, path: str) -> tuple[bool, str]:
    """用 Win32 PrintWindow 抓窗口自身的位图。

    为什么不用 ImageGrab：它抓的是**屏幕区域**，窗口被遮挡或运行在不可见桌面上时
    只会拍到桌面壁纸。PrintWindow 直接问窗口要它的绘制结果，稳定得多。
    """
    import ctypes
    from ctypes import wintypes
    try:
        from PIL import Image
    except Exception as e:
        return False, f"没有 Pillow：{e}"

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd = _hwnd_of(app)

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False, "GetWindowRect 失败"
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return False, f"窗口尺寸异常 {w}x{h}"

    hdc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem_dc, bmp)
    ok = bool(user32.PrintWindow(hwnd, mem_dc, 2))   # 2 = PW_RENDERFULLCONTENT

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth, bmi.biHeight = w, -h          # 负数 = 自上而下
    bmi.biPlanes, bmi.biBitCount = 1, 32
    bmi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)

    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hdc)

    if not got:
        return False, "GetDIBits 失败"
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return True, f"{w}x{h}{'' if ok else '（PrintWindow 返回 0，可能是内容仍取到了）'}"


def _install_shooter(app, path: str) -> None:
    """自检用：抓一张窗口截图再退出。"""
    def shoot() -> None:
        try:
            app.attributes("-topmost", True)
            app.lift()
            app.update()
            time.sleep(0.8)
            ok, info = _capture_window(app, path)
            print(f"{'已截图' if ok else '截图失败'}：{path}　{info}")
        except Exception as e:
            print(f"截图异常：{type(e).__name__}: {e}")
        finally:
            app.after(200, app.destroy)

    app.after(3500, shoot)


def _install_page_shooter(app, out_dir: str) -> None:
    """自检用：逐页截图（一次运行拿全部页面证据）。"""
    keys = list(PAGE_KEYS)
    state = {"i": 0}

    def step() -> None:
        if state["i"] >= len(keys):
            app.after(200, app.destroy)
            return
        key = keys[state["i"]]
        state["i"] += 1
        try:
            app.show_page(key)
            app.update()
        except Exception as e:
            print(f"切到 {key} 失败：{e}")

        def grab() -> None:
            import os
            p = os.path.join(out_dir, f"{state['i']:02d}-{key}.png")
            try:
                app.update()
                ok, info = _capture_window(app, p)
                print(f"{'已截图' if ok else '截图失败'}：{p}　{info}")
            except Exception as e:
                print(f"{key} 截图异常：{type(e).__name__}: {e}")
            app.after(260, step)

        app.after(700, grab)

    app.after(3200, step)


if __name__ == "__main__":
    sys.exit(main())
