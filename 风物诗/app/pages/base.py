"""页面基类：统一的页头 + 可滚动内容区 + 任务执行入口。

每个页面自带日志视图（`Runner` 单飞），跑任务时统一禁用应用内的动作按钮，
免得用户一边转换一边又点一次。
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from ..runner import Runner
from ..widgets import Card, IconCanvas, LogView, hline


class Page(ctk.CTkFrame):
    key = ""
    title = ""
    subtitle = ""
    icon = "note"

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.theme = app.theme
        self._runners: dict[str, Runner] = {}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=self.theme.border,
            scrollbar_button_hover_color=self.theme.border2)
        self.scroll.grid(row=1, column=0, sticky="nsew",
                         padx=(self.theme.size(4), self.theme.size(2)),
                         pady=(self.theme.size(2), self.theme.size(4)))
        self.scroll.columnconfigure(0, weight=1)
        self.build()

    # ---- 页头 ----
    def _build_header(self) -> None:
        t = self.theme
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, t.size(12)))
        head.columnconfigure(1, weight=1)
        IconCanvas(head, self.icon, t.accent_hi, t.panel_t,
                   size=t.size(22)).grid(row=0, column=0, rowspan=2,
                                         padx=(0, t.size(12)))
        ctk.CTkLabel(head, text=self.title, text_color=t.text,
                     font=t.font(16, "bold"), anchor="w").grid(
            row=0, column=1, sticky="w")
        ctk.CTkLabel(head, text=self.subtitle, text_color=t.faint,
                     font=t.font(11), anchor="w", justify="left").grid(
            row=1, column=1, sticky="w")
        self.head = head
        # ⚠️ 空的 CTkFrame 默认 200×200，会把页头撑出一大块空白 —— 必须给死小尺寸
        self.head_right = ctk.CTkFrame(head, fg_color="transparent",
                                       width=1, height=1)
        self.head_right.grid(row=0, column=2, rowspan=2, sticky="e")

    # ---- 内容 ----
    def card(self, title: str = "", icon: str = "", subtitle: str = "",
             pady=(0, 12)) -> Card:
        c = Card(self.scroll, self.theme, title, icon, subtitle)
        c.grid(row=self._next_row(), column=0, sticky="ew", pady=pady)
        return c

    def plain(self, pady=(0, 12)) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self.scroll, fg_color="transparent")
        f.grid(row=self._next_row(), column=0, sticky="ew", pady=pady)
        f.columnconfigure(0, weight=1)
        return f

    def _next_row(self) -> int:
        n = getattr(self, "_row_counter", 0)
        self._row_counter = n + 1
        return n

    def columns(self, parent, n: int = 2, gap: int = 12) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        for i in range(n):
            f.columnconfigure(i, weight=1, uniform="col")
        f._gap = gap
        return f

    def log_view(self, parent, height: int = 9) -> LogView:
        lv = LogView(parent, self.theme, height=height)
        return lv

    # ---- 任务 ----
    def runner_for(self, log: LogView) -> Runner:
        key = str(id(log))
        if key not in self._runners:
            self._runners[key] = Runner(self.app, log,
                                        on_state=self.app.set_busy)
        return self._runners[key]

    def run(self, log: LogView, title: str, fn: Callable[[], object]) -> bool:
        r = self.runner_for(log)
        return r.run(title, fn)

    def busy(self) -> bool:
        return any(r.busy for r in self._runners.values())

    def on_show(self) -> None:
        pass

    def on_close(self) -> None:
        pass
