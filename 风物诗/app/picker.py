"""文件列表选择器：带搜索过滤、悬停、选中态。曲目/简谱/MIDI 队列都用它。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import customtkinter as ctk

from .icons import draw as draw_icon
from .widgets import IconCanvas


class ListPicker(ctk.CTkFrame):
    def __init__(self, master, theme, items: list[Path] | None = None,
                 on_select: Callable[[list[Path]], None] | None = None,
                 height: int = 190, icon: str = "note",
                 multi: bool = False, searchable: bool = True,
                 subtitle_of: Callable[[Path], str] | None = None):
        super().__init__(master, fg_color="transparent")
        self.theme = theme
        self.icon_name = icon
        self.multi = multi
        self.on_select = on_select
        self.subtitle_of = subtitle_of
        self._all: list[Path] = []
        self._items: list[Path] = []
        self._selected: set[str] = set()
        self._rows: list[dict] = []
        self.columnconfigure(0, weight=1)

        row = 0
        if searchable:
            self.search = ctk.CTkEntry(
                self, placeholder_text="输入关键字过滤…", height=theme.size(30),
                fg_color=theme.input_t, border_color=theme.border,
                text_color=theme.text, font=theme.font(11),
                corner_radius=theme.size(8))
            self.search.grid(row=row, column=0, sticky="ew", pady=(0, theme.size(8)))
            self.search.bind("<KeyRelease>", lambda _e: self._apply_filter())
            row += 1

        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color=theme.panel2_t, corner_radius=theme.size(9),
            height=theme.size(height), border_width=1, border_color=theme.border,
            scrollbar_button_color=theme.border,
            scrollbar_button_hover_color=theme.border2)
        self.scroll.grid(row=row, column=0, sticky="nsew")
        self.scroll.columnconfigure(0, weight=1)
        self.rowconfigure(row, weight=1)

        self.empty = ctk.CTkLabel(
            self.scroll, text="（空）", text_color=theme.faint,
            font=theme.font(11))
        self.empty.grid(row=0, column=0, pady=theme.size(18))
        self._row_holder = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self._row_holder.grid(row=0, column=0, sticky="ew")
        self._row_holder.columnconfigure(0, weight=1)

        self.set_items(items or [])

    # ---- 数据 ----
    def set_items(self, items: list[Path]) -> None:
        self._all = list(items)
        self._selected &= {str(p) for p in self._all}
        self._apply_filter()

    def _apply_filter(self) -> None:
        kw = ""
        try:
            kw = self.search.get().strip().lower()
        except Exception:
            kw = ""
        self._items = [p for p in self._all if kw in p.name.lower()] if kw else list(self._all)
        self._render()

    def selected(self) -> list[Path]:
        return [p for p in self._all if str(p) in self._selected]

    def first(self) -> Path | None:
        got = self.selected()
        return got[0] if got else None

    def clear_selection(self) -> None:
        self._selected.clear()
        self._paint()

    def select_first(self) -> None:
        if self._items and not self._selected:
            self._selected = {str(self._items[0])}
            self._paint()
            self._notify()

    def select_named(self, name: str) -> bool:
        for p in self._all:
            if p.name == name or p.stem == name:
                self._selected = {str(p)} if not self.multi else (self._selected | {str(p)})
                self._paint()
                self._notify()
                return True
        return False

    # ---- 渲染 ----
    def _render(self) -> None:
        for w in self._row_holder.winfo_children():
            w.destroy()
        self._rows = []
        if not self._items:
            self.empty.grid()
        else:
            self.empty.grid_remove()
        t = self.theme
        for i, p in enumerate(self._items):
            self._row_holder.rowconfigure(i, weight=0)
            # ⚠️ 这里**不要**写死 height + grid_propagate(False)：有的行带摘要
            #    （两行文字），写死高度会把内容盒顶出可视区、图标与文字错位。
            #    让行高跟着内容走，图标与文字各靠自己的 sticky/pady 对齐。
            row = ctk.CTkFrame(self._row_holder, fg_color="transparent",
                               corner_radius=t.size(7))
            row.grid(row=i, column=0, sticky="ew", padx=t.size(4),
                     pady=t.size(1.5))
            row.columnconfigure(2, weight=1)
            bar = ctk.CTkFrame(row, width=3, height=t.size(20),
                               corner_radius=2, fg_color="transparent")
            bar.grid(row=0, column=0, sticky="ns", padx=(t.size(4), 0),
                     pady=t.size(8))
            ic = IconCanvas(row, self.icon_name, t.faint, t.panel2_t,
                            size=t.size(14))
            # sticky="n" + 与标题行等高的 pady：让图标跟着**第一行文字**对齐，
            # 而不是跟着「标题+摘要」整块的垂直中心（那样看着会偏下）
            ic.grid(row=0, column=1, padx=(t.size(8), t.size(9)),
                    pady=(t.size(9), 0), sticky="n")
            box = ctk.CTkFrame(row, fg_color="transparent")
            box.grid(row=0, column=2, sticky="ew", pady=t.size(7))
            title = ctk.CTkLabel(box, text=p.stem, text_color=t.dim,
                                 font=t.font(12), anchor="w")
            title.pack(anchor="w")
            sub_text = ""
            if self.subtitle_of:
                try:
                    sub_text = self.subtitle_of(p) or ""
                except Exception:
                    sub_text = ""
            sub = ctk.CTkLabel(box, text=sub_text, text_color=t.faint,
                               font=t.font(10), anchor="w")
            if sub_text:
                sub.pack(anchor="w")
            state = {"path": p, "row": row, "icon": ic, "title": title,
                     "sub": sub, "bar": bar}

            def enter(_e, s=state):
                if str(s["path"]) not in self._selected:
                    s["row"].configure(fg_color=t.border)

            def leave(_e, s=state):
                if str(s["path"]) not in self._selected:
                    s["row"].configure(fg_color="transparent")

            def click(_e, s=state):
                key = str(s["path"])
                if self.multi:
                    self._selected ^= {key}
                else:
                    self._selected = {key}
                self._paint()
                self._notify()

            for w in (row, ic, title, sub, box):
                w.bind("<Enter>", enter)
                w.bind("<Leave>", leave)
                w.bind("<Button-1>", click)
                try:
                    w.configure(cursor="hand2")
                except Exception:
                    pass
            self._rows.append(state)
        self._paint()

    def _paint(self) -> None:
        t = self.theme
        for s in self._rows:
            on = str(s["path"]) in self._selected
            if on:
                s["row"].configure(fg_color=t.nav_active)
                s["icon"].restyle(t.accent_hi)
                s["title"].configure(text_color=t.text,
                                     font=t.font(12, "bold"))
                s["bar"].configure(fg_color=t.accent_hi)
            else:
                s["row"].configure(fg_color="transparent")
                s["icon"].restyle(t.faint)
                s["title"].configure(text_color=t.dim, font=t.font(12))
                s["bar"].configure(fg_color="transparent")

    def _notify(self) -> None:
        if self.on_select:
            try:
                self.on_select(self.selected())
            except Exception:
                pass
