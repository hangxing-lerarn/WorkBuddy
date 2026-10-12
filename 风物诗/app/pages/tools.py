"""工具页：把 5 个零散脚本收进一个页面（下拉选工具 → 填参数 → 运行 → 看日志）。

参数表在 `toolchain.TOOL_SPECS` 里，这里只负责把表渲染成控件。
"""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from .. import paths, toolchain
from ..widgets import Field, button, entry
from .base import Page


class ToolsPage(Page):
    key = "tools"
    title = "工具"
    subtitle = "改时值 / 加按住 / 字母谱转谱 / 字母谱对账 / 原谱独立复核 —— 都在这一页"
    icon = "tools"

    def build(self) -> None:
        t = self.theme
        self._values: dict[str, dict] = {k: {} for k in toolchain.TOOL_ORDER}
        self._fields: dict[str, dict] = {}
        self._current = toolchain.TOOL_ORDER[0]

        pick = self.card("选择工具", "tools", "")
        row = ctk.CTkFrame(pick.body, fg_color="transparent")
        row.pack(fill="x")
        row.columnconfigure(0, weight=3, uniform="t")
        row.columnconfigure(1, weight=5, uniform="t")

        self.f_tool = Field(row, t, "工具", "")
        self.f_tool.grid(row=0, column=0, sticky="ew", padx=(0, t.size(12)))
        labels = [toolchain.TOOL_SPECS[k]["label"] for k in toolchain.TOOL_ORDER]
        self.tool_var = ctk.StringVar(value=labels[0])
        ctk.CTkOptionMenu(
            self.f_tool.slot, values=labels, variable=self.tool_var,
            command=lambda _v: self._switch(), fg_color=t.input_t,
            button_color=t.border, button_hover_color=t.border2,
            text_color=t.text, dropdown_fg_color=t.panel,
            dropdown_text_color=t.text, dropdown_hover_color=t.nav_active,
            font=t.font(11), dropdown_font=t.font(11),
            corner_radius=t.size(8), height=t.size(32)).pack(fill="x")

        self.hint = ctk.CTkLabel(row, text="", text_color=t.faint,
                                 font=t.font(11), anchor="w", justify="left",
                                 wraplength=t.size(430))
        self.hint.grid(row=0, column=1, sticky="w")

        # ---------------- 参数 ----------------
        self.param_card = self.card("参数", "type", "")
        self.param_body = ctk.CTkFrame(self.param_card.body, fg_color="transparent")
        self.param_body.pack(fill="x")

        self.f_extra = Field(self.param_card.body, t, "额外参数",
                             "原样拼到命令行末尾，例如 --quiet")
        self.f_extra.pack(fill="x", pady=(t.size(12), 0))
        self.extra_var = ctk.StringVar(value="")
        entry(self.f_extra.slot, t, self.extra_var, "").pack(fill="x")

        # ---------------- 执行 ----------------
        run = self.card("执行", "wave",
                        "这些脚本默认大多只「试运行」，要真正写文件得显式打开写入开关。")
        bar = ctk.CTkFrame(run.body, fg_color="transparent")
        bar.pack(fill="x")
        self.btn_run = button(bar, t, "运行", self._run, "primary", icon="play")
        self.btn_run.pack(side="left")
        self.btn_show = button(bar, t, "看这个脚本的命令&参数", self._show_help,
                               "ghost", icon="info")
        self.btn_show.pack(side="left", padx=(t.size(10), 0))
        self.app.register_action(self.btn_run)
        self.status = ctk.CTkLabel(run.body, text="", text_color=t.dim,
                                   font=t.font(11), anchor="w")
        self.status.pack(fill="x", pady=(t.size(10), 0))

        log_card = self.card("日志", "wave", "")
        self.log = self.log_view(log_card.body, height=13)
        self.log.pack(fill="both", expand=True)

        self._switch()

    # ------------------------------------------------------------------
    def _switch(self) -> None:
        label = self.tool_var.get()
        key = next((k for k in toolchain.TOOL_ORDER
                    if toolchain.TOOL_SPECS[k]["label"] == label),
                   toolchain.TOOL_ORDER[0])
        self._current = key
        spec = toolchain.TOOL_SPECS[key]
        self.hint.configure(text=spec.get("hint", ""))
        for w in self.param_body.winfo_children():
            w.destroy()
        self._fields = {}
        saved = self._values.setdefault(key, {})

        grid = ctk.CTkFrame(self.param_body, fg_color="transparent")
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="f")
        grid.columnconfigure(1, weight=1, uniform="f")

        for i, f in enumerate(spec["fields"]):
            holder = ctk.CTkFrame(grid, fg_color="transparent")
            holder.grid(row=i // 2, column=i % 2, sticky="ew",
                        padx=(0, self.theme.size(12) if i % 2 == 0 else 0),
                        pady=(0, self.theme.size(10)))
            holder.columnconfigure(0, weight=1)
            self._render_field(holder, f, saved)

    def _render_field(self, holder, spec: dict, saved: dict) -> None:
        t = self.theme
        label = spec["label"] + ("　*必填" if spec.get("required") else "")
        fld = Field(holder, t, label, spec.get("hint", ""))
        fld.pack(fill="x")

        if spec["kind"] == "bool":
            var = ctk.IntVar(value=1 if saved.get(spec["key"]) else 0)
            ctk.CTkSwitch(fld.slot, text="打开", variable=var, onvalue=1,
                          offvalue=0, font=t.font(11), text_color=t.text,
                          progress_color=t.accent, button_color=t.accent,
                          button_hover_color=t.accent_hi).pack(anchor="w")
            saved[spec["key"]] = var
            self._fields[spec["key"]] = ("bool", var)
            return

        var = ctk.StringVar(value=str(saved.get(spec["key"], spec.get("default", ""))))
        box = ctk.CTkFrame(fld.slot, fg_color="transparent")
        box.pack(fill="x")
        box.columnconfigure(0, weight=1)
        entry(box, t, var, spec.get("default", "")).grid(row=0, column=0, sticky="ew")
        if spec["kind"] in ("file", "save", "multi"):
            def pick(_e=None, s=spec, v=var):
                self._pick_path(s, v)
            button(box, t, "选择…", pick, "quiet",
                   height=t.size(32)).grid(row=0, column=1, padx=(t.size(8), 0))
        saved[spec["key"]] = var
        self._fields[spec["key"]] = ("text", var)

    def _pick_path(self, spec: dict, var: ctk.StringVar) -> None:
        root = paths.data_dirs().get(spec.get("root", "scores"))
        exts = " ".join(f"*{e}" for e in spec.get("ext", (".txt",)))
        if spec["kind"] == "save":
            got = filedialog.asksaveasfilename(
                title="选择输出文件", initialdir=str(root),
                initialfile=spec.get("default_name", "out.txt"),
                defaultextension=".txt",
                filetypes=[("文本", exts), ("全部文件", "*.*")])
        elif spec["kind"] == "multi":
            got = filedialog.askopenfilenames(
                title="可多选", initialdir=str(root),
                filetypes=[("曲谱", exts), ("全部文件", "*.*")])
            if got:
                var.set(";".join(got))
            return
        else:
            got = filedialog.askopenfilename(
                title="选择文件", initialdir=str(root),
                filetypes=[("曲谱", exts), ("全部文件", "*.*")])
        if got:
            var.set(got)

    # ------------------------------------------------------------------
    def _collect(self) -> dict:
        out = {}
        for key, (kind, var) in self._fields.items():
            if kind == "bool":
                out[key] = bool(var.get())
            else:
                out[key] = var.get()
        return out

    def _spec(self) -> dict:
        return toolchain.TOOL_SPECS[self._current]

    def _show_help(self) -> None:
        spec = self._spec()
        script = paths.script(spec["script"])
        argv = toolchain.build_tool_argv(spec, self._collect(),
                                         self.extra_var.get())
        self.log.append("", "dim")
        self.log.append(f"脚本：{script}", "info")
        self.log.append(f"参数：{' '.join(argv) or '（空，用脚本默认）'}", "info")

    def _run(self) -> None:
        spec = self._spec()
        script = paths.script(spec["script"])
        err = self.app.preflight(script)
        if err:
            self.log.append(err, "err")
            return
        values = self._collect()
        for f in spec["fields"]:
            if f.get("required") and not str(values.get(f["key"], "")).strip():
                self.log.append(f"「{f['label']}」是必填项。", "err")
                return
        argv = toolchain.build_tool_argv(spec, values, self.extra_var.get())

        def job() -> int:
            from ..runner import run_script
            print(f"工具：{spec['label']}")
            print(f"参数：{' '.join(argv) or '（空）'}")
            print("-" * 60)
            return run_script(script, argv)

        self.status.configure(text="运行中…", text_color=self.theme.info)
        self.run(self.log, f"{spec['label']}", job)
