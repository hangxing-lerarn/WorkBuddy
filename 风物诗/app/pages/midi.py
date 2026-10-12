"""MIDI 直接转页。

⚠️ `midi_to_score.py` 的**批量模式把目录写死在仓库里**（change_base/no|yes、scores/）。
这一页因此不调它的批量模式，而是**自己遍历应用数据目录的队列**，逐个用
「单文件模式 + 显式 -o」转换，成功后再把 .mid 移到 yes/ —— 脚本一行都不用改。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import customtkinter as ctk

from .. import paths, toolchain
from ..picker import ListPicker
from ..widgets import Field, button, entry
from .base import Page

MODES = {
    "voicing（按声部）": "voicing",
    "highest（只取最高音）": "highest",
    "track（指定轨）": "track",
    "merge（合并）": "merge",
}
HOLDS = {"不写按住（默认）": "none", "按 MIDI 时值写按住": "midi"}


class MidiPage(Page):
    key = "midi"
    title = "MIDI 直接转"
    subtitle = ("把 .mid 丢进 change_base/no/，转成机器谱进 scores/，"
                "转成功的源文件自动移进 yes/")
    icon = "midi"

    def build(self) -> None:
        t = self.theme

        card = self.card("待转队列", "folder",
                         "队列目录：change_base/no/　转成功的会被移到 change_base/yes/")
        wrap = ctk.CTkFrame(card.body, fg_color="transparent")
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(0, weight=3, uniform="p")
        wrap.columnconfigure(1, weight=2, uniform="p")

        left = ctk.CTkFrame(wrap, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, t.size(16)))
        left.columnconfigure(0, weight=1)
        self.count_label = ctk.CTkLabel(left, text="", text_color=t.faint,
                                        font=t.font(10), anchor="w")
        self.count_label.pack(fill="x", pady=(0, t.size(4)))
        self.picker = ListPicker(left, t, toolchain.list_midis(), None,
                                 height=212, icon="midi", multi=True,
                                 subtitle_of=toolchain.midi_summary)
        self.picker.pack(fill="both", expand=True)

        right = ctk.CTkFrame(wrap, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")

        self.f_mode = Field(right, t, "声部模式 --mode", "")
        self.f_mode.pack(fill="x", pady=(0, t.size(10)))
        self.mode_var = ctk.StringVar(value=list(MODES)[0])
        ctk.CTkOptionMenu(self.f_mode.slot, values=list(MODES),
                          variable=self.mode_var, fg_color=t.input_t,
                          button_color=t.border, button_hover_color=t.border2,
                          text_color=t.text, dropdown_fg_color=t.panel,
                          dropdown_text_color=t.text,
                          dropdown_hover_color=t.nav_active, font=t.font(11),
                          dropdown_font=t.font(11), corner_radius=t.size(8),
                          height=t.size(32)).pack(fill="x")

        self.f_hold = Field(right, t, "按住时长 --hold", "")
        self.f_hold.pack(fill="x", pady=(0, t.size(10)))
        self.hold_var = ctk.StringVar(value=list(HOLDS)[0])
        ctk.CTkOptionMenu(self.f_hold.slot, values=list(HOLDS),
                          variable=self.hold_var, fg_color=t.input_t,
                          button_color=t.border, button_hover_color=t.border2,
                          text_color=t.text, dropdown_fg_color=t.panel,
                          dropdown_text_color=t.text,
                          dropdown_hover_color=t.nav_active, font=t.font(11),
                          dropdown_font=t.font(11), corner_radius=t.size(8),
                          height=t.size(32)).pack(fill="x")

        self.f_voices = Field(right, t, "音轨上限 --max-voices", "auto = 自动")
        self.f_voices.pack(fill="x", pady=(0, t.size(10)))
        self.voices_var = ctk.StringVar(value="auto")
        entry(self.f_voices.slot, t, self.voices_var, "auto").pack(fill="x")

        self.f_extra = Field(right, t, "额外参数", "原样拼到命令行末尾")
        self.f_extra.pack(fill="x")
        self.extra_var = ctk.StringVar(value="")
        entry(self.f_extra.slot, t, self.extra_var, "--tonic auto").pack(fill="x")

        run = self.card("执行", "wave", "批量时单个失败不会中断整批；失败的文件留在 no/ 里。")
        bar = ctk.CTkFrame(run.body, fg_color="transparent")
        bar.pack(fill="x")
        self.btn_all = button(bar, t, "转换队列里全部", self._convert_all,
                              "primary", icon="save")
        self.btn_all.pack(side="left")
        self.btn_sel = button(bar, t, "只转选中的", self._convert_selected,
                              "quiet", icon="check")
        self.btn_sel.pack(side="left", padx=(t.size(10), 0))
        self.btn_open = button(bar, t, "打开队列目录", self._open_no_dir,
                               "ghost", icon="folder")
        self.btn_open.pack(side="left", padx=(t.size(10), 0))
        for b in (self.btn_all, self.btn_sel):
            self.app.register_action(b)
        self.status = ctk.CTkLabel(run.body, text="", text_color=t.dim,
                                   font=t.font(11), anchor="w")
        self.status.pack(fill="x", pady=(t.size(10), 0))

        log_card = self.card("日志", "wave", "")
        self.log = self.log_view(log_card.body, height=11)
        self.log.pack(fill="both", expand=True)
        self.log.append("把 .mid 放进队列目录后，回这里点「转换队列里全部」。", "dim")

        self._refresh_count()

    # ------------------------------------------------------------------
    def _refresh_count(self) -> None:
        n = len(self.picker._all)
        self.count_label.configure(text=f"队列里 {n} 个 MIDI（change_base/no/）")

    def on_show(self) -> None:
        self.picker.set_items(toolchain.list_midis())
        self.picker.clear_selection()
        self._refresh_count()

    def _open_no_dir(self) -> None:
        self.app.open_folder(paths.data_dirs()["no"])

    # ------------------------------------------------------------------
    def _argv(self, midi: Path, out: Path) -> list[str]:
        extra = self.extra_var.get().strip().split() if self.extra_var.get().strip() else []
        return toolchain.build_midi_argv(
            midi, out,
            mode=MODES.get(self.mode_var.get(), "voicing"),
            hold=HOLDS.get(self.hold_var.get(), "none"),
            max_voices=self.voices_var.get().strip() or "auto",
            extra=extra)

    def _targets(self, selected_only: bool) -> list[Path]:
        if selected_only:
            return self.picker.selected()
        return list(self.picker._all)

    def _convert_all(self) -> None:
        self._convert(self._targets(False))

    def _convert_selected(self) -> None:
        self._convert(self._targets(True))

    def _convert(self, files: list[Path]) -> None:
        if not files:
            self.status.configure(text="队列里没有可转的 MIDI", text_color=self.theme.warn)
            return
        script = paths.script("midi_to_score.py")
        d = paths.data_dirs()
        scores_dir = d["scores"]
        yes_dir = d["yes"]

        def job() -> int:
            from ..runner import run_script
            ok, failed = 0, 0
            for i, m in enumerate(files, 1):
                print(f"=== [{i}/{len(files)}] {m.name} ===")
                out = scores_dir / f"{m.stem}.txt"
                rc = run_script(script, self._argv(m, out))
                if rc == 0 and out.is_file():
                    try:
                        dest = yes_dir / m.name
                        if dest.exists():
                            k = 2
                            while (yes_dir / f"{m.stem}_{k}{m.suffix}").exists():
                                k += 1
                            dest = yes_dir / f"{m.stem}_{k}{m.suffix}"
                        shutil.move(str(m), str(dest))
                        print(f"  -> 已移入 yes：{dest.name}")
                    except Exception as e:
                        print(f"  ⚠ 移动源文件失败：{e}")
                    ok += 1
                else:
                    failed += 1
                    print("  -> 失败，文件保留在 no/")
            print(f"成功 {ok} 个，失败 {failed} 个")
            self.app.after(0, self._after_convert, ok, failed)
            return 0 if failed == 0 else 1

        self.status.configure(text=f"转换中（{len(files)} 个）…",
                              text_color=self.theme.info)
        self.run(self.log, f"MIDI 转 {len(files)} 个", job)

    def _after_convert(self, ok: int, failed: int) -> None:
        self.picker.set_items(toolchain.list_midis())
        self._refresh_count()
        color = self.theme.ok if failed == 0 else self.theme.warn
        self.status.configure(text=f"完成：成功 {ok}，失败 {failed}", text_color=color)
