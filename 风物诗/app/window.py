"""主窗口：自绘标题栏 + 背景层 + 左侧导航 + 页面栈。

三条硬约束：
  1. `overrideredirect(True)` 之后窗口会从任务栏消失 —— 用 Win32 的
     WS_EX_APPWINDOW 把它加回去，否则用户没法 Alt+Tab 切回来。
  2. CustomTkinter 不能热换肤 ⇒ 换外观一律走 `rebuild()`（整棵树销毁重建）。
  3. 「只在弹琴时提权」⇒ `relaunch_elevated()` 以管理员身份重启一个自己，
     参数走命令行带过去。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path

import customtkinter as ctk

from . import backgrounds, paths
from . import settings as st
from .theme import Theme
from .widgets import IconCanvas, NavRail, TitleBar

PAGES = [
    ("play", "弹琴", "play"),
    ("midi", "MIDI 直接转", "midi"),
    ("jianpu", "简谱转", "jianpu"),
    ("ocr", "谱图识谱", "ocr"),
    ("tools", "工具", "tools"),
    ("settings", "设置", "settings"),
]

GWL_EXSTYLE = -20
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080


class App(ctk.CTk):
    def __init__(self, opts: dict | None = None):
        super().__init__()
        self.opts = opts or {}
        self.settings = st.load()
        self.settings_error: str | None = None      # 上次落盘失败的信息
        self._actions: list = []
        self._pages: dict[str, object] = {}
        self._bg_photo = None
        self._bg_src = None
        self._bg_job = None
        self._busy = False
        self._toast_job = None
        self.current_key = str(self.opts.get("page") or "play")
        self.is_maximized = bool(self.settings["window"].get("maximized"))
        self._max_pending = (self.is_maximized and not self.opts.get("shot")
                             and not self.opts.get("play"))
        self._restore_geom = None

        ctk.set_appearance_mode(
            "dark" if Theme(self.settings).is_dark else "light")
        self.title("风物诗")
        self.configure(fg_color="#0E0E16")
        self.minsize(880, 580)
        self.overrideredirect(True)

        geo = self.settings["window"]
        w, h = int(geo.get("w", 1020)), int(geo.get("h", 680))
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = geo.get("x")
        y = geo.get("y")
        if x is None or y is None:
            x, y = (sw - w) // 2, max(0, (sh - h) // 2 - 20)
        self.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        if self.opts.get("shot"):
            self.maximized = False
        self._add_to_taskbar()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.build()

    # ==================================================================
    # 构建 / 重建
    # ==================================================================
    def build(self) -> None:
        self.theme = Theme(self.settings, bg_avg=self._bg_avg())
        try:
            self.configure(fg_color=self.theme.bg)
        except Exception:
            pass
        self.attributes("-alpha", max(0.85, min(1.0, self.theme.win_opacity)))

        self._load_background_source()

        self._bg_canvas = tk.Canvas(self, highlightthickness=0, bd=0,
                                    bg=self.theme.bg)
        self._bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._bg_canvas.bind("<Configure>", self._schedule_bg)

        self.shell = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.shell.place(x=0, y=0, relwidth=1, relheight=1)
        self.shell.columnconfigure(0, weight=1)
        self.shell.rowconfigure(1, weight=1)

        self.titlebar = TitleBar(self.shell, self, self.theme)
        self.titlebar.grid(row=0, column=0, sticky="ew")

        body = ctk.CTkFrame(self.shell, fg_color="transparent", corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # 导航主体不含「设置」—— 设置单独固定在最下面（见 NavRail 底部那一行）
        self.nav = NavRail(body, self, self.theme,
                           [p for p in PAGES if p[0] != "settings"],
                           self.current_key)
        self.nav.grid(row=0, column=0, sticky="ns")

        self.page_holder = ctk.CTkFrame(body, fg_color="transparent",
                                        corner_radius=0)
        self.page_holder.grid(row=0, column=1, sticky="nsew",
                              padx=self.theme.size(18),
                              pady=(self.theme.size(14), self.theme.size(10)))
        self.page_holder.columnconfigure(0, weight=1)
        self.page_holder.rowconfigure(0, weight=1)

        self._pages = {}
        self._actions = []
        self._build_grip()
        self.show_page(self.current_key, first=True)
        self.after(60, self._render_background)
        self.after(120, self._startup_notes)
        if self._max_pending:
            self.toggle_max()

    def rebuild(self) -> None:
        key = self.current_key
        self._cancel_bg_job()
        try:
            self.shell.destroy()
        except Exception:
            pass
        try:
            self._bg_canvas.destroy()
        except Exception:
            pass
        try:
            self._grip.destroy()
        except Exception:
            pass
        self._bg_photo = None
        self.current_key = key
        self.build()

    # ==================================================================
    # 背景
    # ==================================================================
    def _cancel_bg_job(self) -> None:
        """取消排队中的背景重绘。

        rebuild() 会把 _bg_canvas 整个销毁重建，若此时还有一次排队中的重绘，
        回调会打到已经失效的 Tk 图像上（`image "pyimageN" doesn't exist`）。
        """
        job, self._bg_job = self._bg_job, None
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
    def _bg_avg(self) -> str:
        api = self.settings["appearance"]
        kind = str(api.get("bg_kind", "preset"))
        if kind == "solid":
            return str(api.get("bg_solid", "#0E0E16"))
        img, avg = backgrounds.prepare(
            kind, str(api.get("bg_image", "") or api.get("bg_preset", "")),
            str(api.get("bg_preset", "")), float(api.get("bg_dim", 0.3)),
            float(api.get("bg_blur", 4)))
        return avg

    def _load_background_source(self) -> None:
        api = self.settings["appearance"]
        kind = str(api.get("bg_kind", "preset"))
        if kind == "solid":
            self._bg_src = None
            return
        img, _avg = backgrounds.prepare(
            kind, str(api.get("bg_image", "")),
            str(api.get("bg_preset", "")), float(api.get("bg_dim", 0.3)),
            float(api.get("bg_blur", 4)))
        self._bg_src = img

    def _schedule_bg(self, _e=None) -> None:
        self._cancel_bg_job()
        self._bg_job = self.after(120, self._render_background)

    def _render_background(self) -> None:
        self._bg_job = None
        try:
            from PIL import Image, ImageTk     # noqa: F401
        except Exception:
            return
        # 窗口/画布可能已经销毁（关窗、整树重建）—— 别往死控件上画
        try:
            if not self.winfo_exists() or not self._bg_canvas.winfo_exists():
                return
        except Exception:
            return
        try:
            if self._bg_src is None:
                self._bg_canvas.delete("all")
                self._bg_canvas.configure(
                    bg=self.theme.bg_solid
                    if self.theme.bg_kind == "solid" else self.theme.bg)
                return
            w = max(2, self.winfo_width())
            h = max(2, self.winfo_height())
            src = self._bg_src
            # cover：等比缩放到铺满，再居中裁
            img = self._cover(src, w, h)
            self._bg_photo = ImageTk.PhotoImage(img)
            self._bg_canvas.delete("all")
            self._bg_canvas.create_image(0, 0, anchor="nw", image=self._bg_photo)
        except tk.TclError:
            pass                                # 关窗瞬间的必然竞态，忽略
        except Exception:
            pass

    @staticmethod
    def _cover(img, w: int, h: int):
        from PIL import Image
        iw, ih = img.size
        k = max(w / iw, h / ih)
        nw, nh = max(1, int(iw * k + 0.5)), max(1, int(ih * k + 0.5))
        resized = img.resize((nw, nh), Image.BILINEAR)
        left, top = (nw - w) // 2, (nh - h) // 2
        return resized.crop((left, top, left + w, top + h))

    # ==================================================================
    # 页面
    # ==================================================================
    def _make_page(self, key: str):
        if key in self._pages:
            return self._pages[key]
        from .pages.jianpu import JianpuPage
        from .pages.midi import MidiPage
        from .pages.ocr import OcrPage
        from .pages.play import PlayPage
        from .pages.settings_page import SettingsPage
        from .pages.tools import ToolsPage
        table = {"play": PlayPage, "midi": MidiPage, "jianpu": JianpuPage,
                 "ocr": OcrPage, "tools": ToolsPage, "settings": SettingsPage}
        cls = table.get(key, PlayPage)
        page = cls(self.page_holder, self)
        self._pages[key] = page
        return page

    def show_page(self, key: str, first: bool = False) -> None:
        key = key if any(k == key for k, _l, _i in PAGES) else "play"
        self.current_key = key
        for k, page in self._pages.items():
            try:
                page.grid_forget()
            except Exception:
                pass
        page = self._make_page(key)
        page.grid(row=0, column=0, sticky="nsew",
                  pady=(0 if first else self.theme.size(10), 0))
        try:
            self.nav.set_active(key)
        except Exception:
            pass
        if self.theme.animations and not first:
            self._animate_in(page)
        try:
            page.on_show()
        except Exception:
            pass
        label = next((l for k, l, _i in PAGES if k == key), "")
        try:
            self.titlebar.set_center(f"{label}　·　{self._status_text()}")
        except Exception:
            pass

    def _animate_in(self, page, step: int = 0) -> None:
        if step >= 6:
            try:
                page.grid_configure(pady=(0, 0))
            except Exception:
                pass
            return
        pad = int((6 - step) * 2)
        try:
            page.grid_configure(pady=(self.theme.size(pad), 0))
        except Exception:
            return
        self.after(18, lambda: self._animate_in(page, step + 1))

    def _status_text(self) -> str:
        if self._busy:
            return "任务进行中…"
        return "就绪"

    # ==================================================================
    # 状态 / 提示
    # ==================================================================
    def register_action(self, widget) -> None:
        if widget not in self._actions:
            self._actions.append(widget)
            try:
                widget.configure(state="disabled" if self._busy else "normal")
            except Exception:
                pass

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        for w in list(self._actions):
            try:
                w.configure(state="disabled" if busy else "normal")
            except Exception:
                pass
        try:
            self.titlebar.set_center(
                ("任务进行中…" if busy else "") +
                (f"　·　{self._status_text()}" if not busy else ""),
                self.theme.warn if busy else None)
        except Exception:
            pass
        if self.current_key == "jianpu" and not busy:
            pass

    def toast(self, text: str) -> None:
        try:
            if getattr(self, "_toast", None) is not None:
                self._toast.destroy()
        except Exception:
            pass
        try:
            self._toast = ctk.CTkLabel(
                self.shell, text=f" {text} ", text_color=self.theme.on_accent,
                fg_color=self.theme.accent, corner_radius=self.theme.size(8),
                font=self.theme.font(11), height=self.theme.size(30))
            self._toast.place(relx=1.0, rely=1.0, x=-24, y=-20, anchor="se")
            if self._toast_job:
                self.after_cancel(self._toast_job)
            self._toast_job = self.after(2600, self._hide_toast)
        except Exception:
            pass

    def _hide_toast(self) -> None:
        try:
            self._toast.destroy()
        except Exception:
            pass
        self._toast = None

    def confirm(self, title: str, message: str) -> bool:
        try:
            return bool(messagebox.askyesno(title, message, parent=self))
        except Exception:
            return False

    def open_folder(self, path) -> None:
        try:
            p = Path(path)
            p.mkdir(parents=True, exist_ok=True)
            os.startfile(str(p))          # noqa: S606
        except Exception as e:
            self.toast(f"打不开：{e}")

    def preflight(self, script) -> str:
        from .runner import preflight as _pf
        return _pf(script)

    def update_settings(self, **sections) -> str | None:
        """局部更新配置并落盘。返回错误信息（None = 成功）。

        ★ 不再静默失败：内存里一定用新值（界面立刻生效），
          落盘失败时记在 self.settings_error 上并弹一条提示。
        """
        data, err = st.update_quiet(**sections)
        self.settings = data
        if err:
            self.settings_error = err
            try:
                self.toast(f"配置没能存盘：{err[:60]}")
            except Exception:
                pass
        else:
            self.settings_error = None
        return err

    def apply_appearance(self) -> None:
        self.rebuild()

    # ==================================================================
    # 权限与生命周期
    # ==================================================================
    def is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def relaunch_elevated(self, argv: list[str]) -> bool:
        try:
            if getattr(sys, "frozen", False):
                exe, params = sys.executable, subprocess.list2cmdline(argv)
            else:
                script = str(Path(paths.APP_DIR) / "main.py")
                exe = sys.executable
                params = subprocess.list2cmdline([script] + argv)
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, params, None, 1)
            return int(rc) > 32
        except Exception:
            return False

    def minimize(self) -> None:
        """overrideredirect 窗口没法直接 iconify，先临时去掉再最小化。"""
        try:
            self.overrideredirect(False)
            self.iconify()
            self.after(220, lambda: self.overrideredirect(True))
        except Exception:
            pass

    def toggle_max(self) -> None:
        try:
            if self.is_maximized:
                self.geometry(self._restore_geom or f"{self.settings['window']['w']}x"
                              f"{self.settings['window']['h']}")
                self.is_maximized = False
            else:
                self._restore_geom = (f"{self.winfo_width()}x{self.winfo_height()}"
                                      f"+{self.winfo_x()}+{self.winfo_y()}")
                sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
                self.geometry(f"{sw}x{sh}+0+0")
                self.is_maximized = True
            st.update(window={"maximized": self.is_maximized})
            self.after(80, self._render_background)
        except Exception:
            pass

    def on_close(self, force: bool = False) -> None:
        if self._busy and not force:
            if not self.confirm("还有任务在跑",
                               "现在关掉会中断正在进行的任务。确定要关闭吗？"):
                return
        self._cancel_bg_job()
        try:
            st.update(window={
                "w": self.winfo_width(), "h": self.winfo_height(),
                "x": self.winfo_x(), "y": self.winfo_y(),
                "maximized": self.is_maximized})
        except Exception:
            pass
        for page in self._pages.values():
            try:
                page.on_close()
            except Exception:
                pass
        try:
            self.destroy()
        except Exception:
            pass

    # ==================================================================
    # 杂项
    # ==================================================================
    def _add_to_taskbar(self) -> None:
        """让无边框窗口重新出现在任务栏 / Alt+Tab 里。"""
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            self.withdraw()
            self.after(10, self.deiconify)
        except Exception:
            pass

    def _build_grip(self) -> None:
        """右下角拖拽改大小（无边框窗口没有系统边框）。"""
        t = self.theme
        self._grip = tk.Canvas(self, width=t.size(16), height=t.size(16),
                               bg=t.bg, highlightthickness=0, bd=0,
                               cursor="sizing")
        self._grip.place(relx=1.0, rely=1.0, x=-2, y=-2, anchor="se")
        for i in range(3):
            off = 4 + i * 4
            self._grip.create_line(off, 15, 15, off, fill=t.faint, width=1)
        self._grip.bind("<Button-1>", self._grip_start)
        self._grip.bind("<B1-Motion>", self._grip_drag)

    def _grip_start(self, e):
        self._grip0 = (e.x_root, e.y_root, self.winfo_width(),
                       self.winfo_height())

    def _grip_drag(self, e):
        if self.is_maximized:
            return
        x0, y0, w0, h0 = self._grip0
        w = max(880, w0 + (e.x_root - x0))
        h = max(580, h0 + (e.y_root - y0))
        self.geometry(f"{w}x{h}")

    def _startup_notes(self) -> None:
        """启动后的第一次提示：脚本目录、种子数据、预设背景。"""
        from . import runner
        if paths.scripts_dir() is None:
            self.toast("没找到工具脚本目录 —— 请在「设置 → 数据与路径」里指定")
        if self._bg_src is None and self.theme.bg_kind != "solid":
            self.toast("预设背景还在生成，稍等一下就会出来")
