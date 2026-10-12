"""可复用控件：自绘标题栏、左侧导航、卡片、日志视图、表单行。

总原则：所有配色都从传进来的 theme 取，控件自己不持有颜色常量 ——
这样「整树重建」时换个 theme 对象就全变了，不会有漏网之鱼。
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from . import icons


# --------------------------------------------------------------------------
# 图标画布 / 图标按钮
# --------------------------------------------------------------------------


class IconCanvas(tk.Canvas):
    def __init__(self, master, name: str, color: str, bg: str,
                 size: int = 20, width: float = 1.7, **kw):
        super().__init__(master, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0, takefocus=0, **kw)
        self._name, self._color, self._size, self._width = name, color, size, width
        icons.draw(self, name, color, size, width)

    def restyle(self, color: str | None = None, name: str | None = None) -> None:
        if color:
            self._color = color
        if name:
            self._name = name
        icons.draw(self, self._name, self._color, self._size, self._width)


class IconButton(tk.Canvas):
    """标题栏上那种小图标按钮：无边框、悬停高亮、可点击。"""

    def __init__(self, master, name: str, theme, command: Callable[[], None],
                 size: int = 30, icon_size: int = 15, danger: bool = False,
                 bg: str | None = None, tooltip: str = ""):
        bg = bg or theme.title
        super().__init__(master, width=size, height=size, bg=bg,
                         highlightthickness=0, bd=0, takefocus=0, cursor="hand2")
        self._theme = theme
        self._name = name
        self._size = icon_size
        self._command = command
        self._danger = danger
        self._hover = False
        self._tooltip = tooltip
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self._render()

    def _render(self) -> None:
        t = self._theme
        if self._hover:
            fill = t.err if self._danger else t.border
            self.configure(bg=fill)
        else:
            fill = self._theme.title
            self.configure(bg=fill)
        color = ("#FFFFFF" if self._danger and self._hover else t.dim)
        self.delete("all")
        from . import icons as _ic
        _ic.draw(self, self._name, color, self._size, 1.6)

    def _on_enter(self, _e=None):
        self._hover = True
        self._render()

    def _on_leave(self, _e=None):
        self._hover = False
        self._render()

    def _on_click(self, _e=None):
        try:
            self._command()
        except Exception:
            pass


# --------------------------------------------------------------------------
# 自绘标题栏
# --------------------------------------------------------------------------


class TitleBar(ctk.CTkFrame):
    """没有系统边框，所以最小化/最大化/关闭都要自己做，拖拽也自己实现。"""

    def __init__(self, master, app, theme):
        super().__init__(master, height=theme.size(40), corner_radius=0,
                         fg_color=theme.title)
        self.app = app
        self.theme = theme
        self.grid_propagate(False)
        self.columnconfigure(1, weight=1)

        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=(12, 0))
        IconCanvas(left, "note", theme.accent_hi, theme.title, size=theme.size(18)).pack(
            side="left", pady=(theme.size(11), 0))
        ctk.CTkLabel(left, text="风物诗", text_color=theme.text,
                     font=theme.font(13, "bold")).pack(side="left", padx=(7, 6),
                                                       pady=(theme.size(10), 0))
        ctk.CTkLabel(left, text="· 原神乐谱工具箱", text_color=theme.faint,
                     font=theme.font(11)).pack(side="left", pady=(theme.size(11), 0))

        self._center = ctk.CTkFrame(self, fg_color="transparent")
        self._center.grid(row=0, column=1, sticky="")

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e", padx=(0, 6))
        IconButton(right, "minus", theme, app.minimize, bg=theme.title).pack(side="left")
        self._max_btn = IconButton(right, "square", theme, app.toggle_max,
                                   bg=theme.title)
        self._max_btn.pack(side="left")
        IconButton(right, "close", theme, app.on_close, danger=True,
                   bg=theme.title).pack(side="left")

        for w in (self, left):
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)
            w.bind("<Double-Button-1>", lambda _e: app.toggle_max())

    def set_center(self, text: str, color: str | None = None) -> None:
        for child in self._center.winfo_children():
            child.destroy()
        if text:
            ctk.CTkLabel(self._center, text=text,
                         text_color=color or self.theme.dim,
                         font=self.theme.font(11)).pack(pady=(self.theme.size(10), 0))

    def _start_drag(self, e):
        self._drag = (e.x_root - self.app.winfo_x(), e.y_root - self.app.winfo_y())

    def _do_drag(self, e):
        if self.app.is_maximized:
            return
        dx, dy = self._drag
        self.app.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")


# --------------------------------------------------------------------------
# 左侧导航
# --------------------------------------------------------------------------


class NavRail(ctk.CTkFrame):
    def __init__(self, master, app, theme, items, current: str):
        super().__init__(master, width=theme.size(186), corner_radius=0,
                         fg_color=theme.nav_t)
        self.app, self.theme, self.items = app, theme, items
        # ⚠️ 子控件用的是 pack ⇒ 必须用 pack_propagate(False) 才能守住宽度；
        #    CTkFrame 的默认尺寸是 200×200，不锁就会被撑开。
        self.pack_propagate(False)
        self._rows: dict[str, dict] = {}

        ctk.CTkLabel(self, text="功能", text_color=theme.faint,
                     font=theme.font(10), anchor="w").pack(
            fill="x", padx=theme.size(20), pady=(theme.size(14), theme.size(4)))

        for key, label, icon in items:
            self._rows[key] = self._make_row(key, label, icon)

        ctk.CTkLabel(self, text="", text_color=theme.faint).pack(fill="both", expand=True)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=theme.size(16), pady=(0, theme.size(14)))
        self._make_row("settings", "设置", "settings", parent=bottom, compact=True)

        self.set_active(current)

    def _make_row(self, key, label, icon, parent=None, compact=False) -> dict:
        t = self.theme
        holder = parent or self
        row = ctk.CTkFrame(holder, height=t.size(38), corner_radius=t.size(9),
                           fg_color="transparent")
        row.pack(fill="x", padx=t.size(10), pady=t.size(2))
        row.grid_propagate(False)
        row.columnconfigure(2, weight=1)

        # ⚠️ 这里千万别省 height：CTkFrame 默认 200 高，会把整行的网格撑到 250，
        #    文字和图标就被挤出可视区（这个坑已经踩过一次）。
        bar = ctk.CTkFrame(row, width=3, height=t.size(22), corner_radius=2,
                           fg_color="transparent")
        bar.grid(row=0, column=0, sticky="nsw", pady=t.size(7))
        holder_icon = IconCanvas(row, icon, t.dim, t.nav_t, size=t.size(17))
        holder_icon.grid(row=0, column=1, padx=(t.size(12), t.size(10)))
        text = ctk.CTkLabel(row, text=label, text_color=t.dim,
                            font=t.font(12), anchor="w")
        text.grid(row=0, column=2, sticky="w")

        state = {"row": row, "icon": holder_icon, "text": text, "bar": bar,
                 "key": key, "active": False, "hover": False}

        def enter(_e, s=state):
            if not s["active"]:
                s["row"].configure(fg_color=t.border)
                s["icon"].restyle(t.text)
                s["text"].configure(text_color=t.text)

        def leave(_e, s=state):
            if not s["active"]:
                s["row"].configure(fg_color="transparent")
                s["icon"].restyle(t.dim)
                s["text"].configure(text_color=t.dim)

        def click(_e, k=key):
            self.app.show_page(k)

        for w in (row, holder_icon, text):
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
            w.bind("<Button-1>", click)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
        return state

    def set_active(self, key: str) -> None:
        t = self.theme
        for k, s in self._rows.items():
            active = (k == key)
            s["active"] = active
            if active:
                s["row"].configure(fg_color=t.nav_active)
                s["icon"].restyle(t.accent_hi, self._icon_of(k))
                s["text"].configure(text_color=t.text, font=t.font(12, "bold"))
                s["bar"].configure(fg_color=t.accent_hi)
            else:
                s["row"].configure(fg_color="transparent")
                s["icon"].restyle(t.dim, self._icon_of(k))
                s["text"].configure(text_color=t.dim, font=t.font(12))
                s["bar"].configure(fg_color="transparent")

    def _icon_of(self, key: str) -> str:
        for k, _label, icon in self.items:
            if k == key:
                return icon
        return "settings"


# --------------------------------------------------------------------------
# 卡片 / 表单 / 分隔线
# --------------------------------------------------------------------------


class Card(ctk.CTkFrame):
    def __init__(self, master, theme, title: str = "", icon: str = "",
                 subtitle: str = "", pad: int = 16):
        super().__init__(master, corner_radius=theme.size(12), fg_color=theme.panel_t,
                         border_width=1, border_color=theme.border)
        self.theme = theme
        self.columnconfigure(0, weight=1)
        row = 0
        if title:
            head = ctk.CTkFrame(self, fg_color="transparent")
            head.grid(row=row, column=0, sticky="ew",
                      padx=theme.size(pad), pady=(theme.size(pad), 0))
            col = 0
            if icon:
                IconCanvas(head, icon, theme.accent_hi, theme.panel_t,
                           size=theme.size(16)).grid(row=0, column=col,
                                                     padx=(0, theme.size(8)))
                col += 1
            box = ctk.CTkFrame(head, fg_color="transparent")
            box.grid(row=0, column=col, sticky="w")
            ctk.CTkLabel(box, text=title, text_color=theme.text,
                         font=theme.font(13, "bold"), anchor="w").pack(anchor="w")
            if subtitle:
                ctk.CTkLabel(box, text=subtitle, text_color=theme.faint,
                             font=theme.font(11), anchor="w",
                             justify="left").pack(anchor="w")
            self.head = head
            row += 1
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=row, column=0, sticky="nsew",
                       padx=theme.size(pad), pady=(theme.size(10), theme.size(pad)))
        self.body.columnconfigure(0, weight=1)
        self.rowconfigure(row, weight=1)


def hline(master, theme, pady: int = 8):
    line = ctk.CTkFrame(master, height=1, fg_color=theme.border)
    line.pack(fill="x", pady=pady)
    return line


class Field:
    """一行「标签 + 控件」，标签在上、控件在下，宽屏下自动两列排布。"""

    def __init__(self, master, theme, label: str, hint: str = ""):
        self.theme = theme
        self.frame = ctk.CTkFrame(master, fg_color="transparent")
        top = ctk.CTkFrame(self.frame, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=label, text_color=theme.dim,
                     font=theme.font(11), anchor="w").pack(side="left")
        self.hint = ctk.CTkLabel(top, text=hint, text_color=theme.faint,
                                 font=theme.font(10), anchor="e")
        if hint:
            self.hint.pack(side="right")
        self.slot = ctk.CTkFrame(self.frame, fg_color="transparent")
        self.slot.pack(fill="x", pady=(theme.size(4), 0))

    def grid(self, **kw):
        self.frame.grid(**kw)
        return self

    def pack(self, **kw):
        self.frame.pack(**kw)
        return self

    def set_hint(self, text: str, color: str | None = None) -> None:
        self.hint.configure(text=text, text_color=color or self.theme.faint)


def solid(theme, color: str) -> str:
    """把 CustomTkinter 的 "transparent" 换成原生 tk 能认的实色。

    ⚠️ CTk 控件认 "transparent"，原生 tk.Canvas / tk.Text 不认 —— 直接把
    "transparent" 传过去会抛 `unknown color name "transparent"`。图标画布
    一律先过这个函数。
    """
    c = str(color or "")
    return theme.panel_t if c.lower() in ("transparent", "") else c


def entry(master, theme, textvariable, placeholder: str = "",
          width: int | None = None) -> ctk.CTkEntry:
    e = ctk.CTkEntry(master, textvariable=textvariable,
                     placeholder_text=placeholder,
                     fg_color=theme.input_t, border_color=theme.border,
                     text_color=theme.text, font=theme.font(12),
                     height=theme.size(32), corner_radius=theme.size(8))
    if width:
        e.configure(width=width)
    return e


class IconTextButton(ctk.CTkFrame):
    """带线性矢量图标的按钮。

    CTkButton 只接受位图 `image`，塞不进 Canvas 画的矢量图标，所以自己拼一个：
    图标 Canvas + 文字 Label，悬停 / 禁用状态一并接管。
    对外接口尽量像按钮 —— `.pack()` / `.grid()` / `.configure(state="disabled")`。
    """

    def __init__(self, master, theme, text: str, command,
                 kind: str = "primary", icon: str = "", height=None,
                 width=None, font_size: int = 12):
        colors = theme.button_colors(kind)
        self._theme = theme
        self._colors = colors
        self._command = command
        self._icon_name = icon
        self._enabled = True
        self._hover = False
        self._border_color = colors.get("border_color", theme.border)

        super().__init__(master, fg_color=colors["fg_color"],
                         corner_radius=theme.size(8),
                         border_width=colors.get("border_width", 0),
                         border_color=theme.border)
        if width:
            self.configure(width=width)

        pad_y = max(3, int(((height or theme.size(34)) - theme.size(17)) / 2))
        self._inner = ctk.CTkFrame(self, fg_color="transparent")
        self._inner.pack(expand=True, pady=pad_y, padx=theme.size(14))

        self._icon = None
        if icon:
            self._icon = IconCanvas(self._inner, icon, colors["text_color"],
                                    solid(theme, colors["fg_color"]),
                                    size=theme.size(15))
            self._icon.pack(side="left", padx=(0, theme.size(7)))
        self._label = ctk.CTkLabel(self._inner, text=text,
                                   text_color=colors["text_color"],
                                   font=theme.font(font_size))
        self._label.pack(side="left")

        targets = [self, self._inner, self._label]
        if self._icon is not None:
            targets.append(self._icon)
        for w in targets:
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)
            w.bind("<Button-1>", self._click)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
        self._paint()

    # ---- 状态 ----
    def _paint(self) -> None:
        t, c = self._theme, self._colors
        if not self._enabled:
            fg = t.panel2_t
            fg2 = t.panel2_t
            col = t.faint
        else:
            fg = c.get("hover_color") if self._hover else c["fg_color"]
            fg2 = fg
            col = c["text_color"]
        try:
            self.configure(fg_color=fg)
            self._inner.configure(fg_color=fg2)
        except Exception:
            pass
        if self._icon is not None:
            self._icon.configure(bg=solid(t, fg2))
            self._icon.restyle(col)
        try:
            self._label.configure(text_color=col)
        except Exception:
            pass

    def _enter(self, _e=None):
        if self._enabled:
            self._hover = True
            self._paint()

    def _leave(self, _e=None):
        self._hover = False
        self._paint()

    def _click(self, _e=None):
        if self._enabled and self._command:
            try:
                self._command()
            except Exception:
                pass

    # 兼容 CTkButton 的调用姿势
    def configure(self, **kw):        # type: ignore[override]
        state = kw.pop("state", None)
        if state is not None:
            self._enabled = (str(state) != "disabled")
            self._paint()
        if kw:
            super().configure(**kw)

    config = configure

    def cget(self, key):              # type: ignore[override]
        if key == "state":
            return "normal" if self._enabled else "disabled"
        return super().cget(key)

    def set_text(self, text: str) -> None:
        try:
            self._label.configure(text=text)
        except Exception:
            pass


def button(master, theme, text: str, command, kind: str = "primary",
           icon: str = "", width: int | None = None,
           height: int | None = None) -> IconTextButton:
    return IconTextButton(master, theme, text, command, kind=kind, icon=icon,
                          width=width, height=height)


def pill(master, theme, text: str, color: str | None = None) -> ctk.CTkLabel:
    c = color or theme.info
    return ctk.CTkLabel(master, text=f" {text} ", text_color=c,
                        fg_color=blend_bg(theme, c),
                        corner_radius=theme.size(6),
                        height=theme.size(22),
                        font=theme.font(10))


def blend_bg(theme, color: str) -> str:
    from . import theme as th
    return th.blend(theme.panel_t, color, 0.16 if theme.is_dark else 0.12)


# --------------------------------------------------------------------------
# 日志视图
# --------------------------------------------------------------------------

LOG_LEVELS = {
    "dim": "dim", "text": "text", "ok": "ok", "warn": "warn",
    "err": "err", "info": "info", "accent": "accent",
}


class LogView(ctk.CTkFrame):
    """跑任务时的输出窗。用原生 tk.Text：CTkTextbox 控制不了 tag 颜色。"""

    def __init__(self, master, theme, height: int = 9):
        super().__init__(master, corner_radius=theme.size(10),
                         fg_color=theme.log_t, border_width=1,
                         border_color=theme.border)
        self.theme = theme
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.text = tk.Text(self, height=height, wrap="none",
                            bg=theme.log_t, fg=theme.dim,
                            insertbackground=theme.text, relief="flat",
                            highlightthickness=0, bd=0,
                            font=(theme.mono_family, max(9, int(round(11 * theme.scale)))),
                            padx=theme.size(10), pady=theme.size(8))
        self.text.grid(row=0, column=0, sticky="nsew")
        self.bar = ctk.CTkScrollbar(self, command=self.text.yview,
                                    button_color=theme.border,
                                    button_hover_color=theme.border2,
                                    width=theme.size(10))
        self.bar.grid(row=0, column=1, sticky="ns", padx=(0, theme.size(3)),
                      pady=theme.size(3))
        self.text.configure(yscrollcommand=self.bar.set)
        self.text.configure(state="disabled")

        for level, key in LOG_LEVELS.items():
            self.text.tag_configure(level, foreground=theme.level_color(key))

    def append(self, line: str, level: str = "dim") -> None:
        if not line:
            return
        self.text.configure(state="normal")
        self.text.insert("end", line.rstrip("\n") + "\n", level if level in LOG_LEVELS else "dim")
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def get_text(self) -> str:
        return self.text.get("1.0", "end")
