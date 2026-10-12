"""弹琴页：选曲 → 起始行 / 倍速 → 提权 → F8 开始。

关于提权：`keyboard` 模拟按键必须管理员权限。用户明确要求「只在弹琴时提权」，
所以这里不是让整个应用以管理员身份启动，而是**点了开始演奏之后**再
以管理员身份重启一个自己，参数通过命令行带过去，重启后自动接着跑。
"""
from __future__ import annotations

import sys
from pathlib import Path

import customtkinter as ctk

from .. import paths, toolchain
from ..picker import ListPicker
from ..widgets import Field, button, entry
from .base import Page


class PlayPage(Page):
    key = "play"
    title = "弹琴"
    subtitle = ("模拟按键演奏 · 选曲 → 设起始行与倍速 → 打开原神并装备琴 → 按 F8 开始"
                "（空格暂停；暂停后按 P 返回）")
    icon = "play"

    def build(self) -> None:
        t = self.theme

        # ---------------- 选曲与参数 ----------------
        card = self.card(
            "选曲与参数", "note",
            "弹琴读的是 scores/ 里的机器谱。页眉在这里只作参考显示 —— "
            "实际演奏用的是谱子首行的 #N倍速。")
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
        self.picker = ListPicker(left, t, toolchain.list_scores(),
                                 self._on_pick, height=232, icon="note",
                                 subtitle_of=toolchain.score_summary)
        self.picker.pack(fill="both", expand=True)

        right = ctk.CTkFrame(wrap, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")

        self.f_start = Field(right, t, "起始行号", "从第几行开始弹")
        self.f_start.pack(fill="x", pady=(0, t.size(10)))
        self.start_var = ctk.StringVar(value="1")
        entry(self.f_start.slot, t, self.start_var, "1").pack(fill="x")

        self.f_speed = Field(right, t, "倍速", "越大越快")
        self.f_speed.pack(fill="x", pady=(0, t.size(10)))
        self.speed_var = ctk.StringVar(value="1.0")
        entry(self.f_speed.slot, t, self.speed_var, "1.0").pack(fill="x")

        self.f_delay = Field(right, t, "F8 缓冲（秒）", "留给切窗口的时间")
        self.f_delay.pack(fill="x", pady=(0, t.size(10)))
        self.delay_var = ctk.StringVar(value="2.0")
        entry(self.f_delay.slot, t, self.delay_var, "2.0").pack(fill="x")

        self.f_head = Field(right, t, "页眉（参考）", "只显示，不参与演奏")
        self.f_head.pack(fill="x", pady=(0, t.size(10)))
        self.head_value = ctk.CTkLabel(
            right, text="—", text_color=t.info, font=t.font(12, mono=True),
            anchor="w", fg_color=t.input_t, corner_radius=t.size(8),
            height=t.size(32))
        self.head_value.pack(fill="x")
        self.head_note = ctk.CTkLabel(right, text="", text_color=t.faint,
                                      font=t.font(10), anchor="w",
                                      justify="left", wraplength=t.size(240))
        self.head_note.pack(fill="x", pady=(t.size(4), 0))

        # ---------------- 演奏 ----------------
        run = self.card("演奏", "play", "点下面这个按钮后，Windows 会弹一次 UAC —— 那是键盘模拟必需的权限。")
        bar = ctk.CTkFrame(run.body, fg_color="transparent")
        bar.pack(fill="x")
        self.btn_play = button(bar, t, "开始演奏", self._start, "primary",
                               icon="play")
        self.btn_play.pack(side="left")
        self.app.register_action(self.btn_play)
        self.status = ctk.CTkLabel(bar, text="", text_color=t.dim,
                                   font=t.font(11), anchor="w")
        self.status.pack(side="left", padx=(t.size(14), 0))

        steps = ctk.CTkLabel(
            run.body,
            text="1. 选好曲目与参数　2. 打开原神、装备风物之诗琴　3. 按 F8 开始（按下后缓冲若干秒）",
            text_color=t.faint, font=t.font(10), anchor="w", justify="left")
        steps.pack(fill="x", pady=(t.size(10), 0))

        # ---------------- 日志 ----------------
        log_card = self.card("日志", "wave", "演奏时会逐行打印进度，切到游戏窗口也能回来看。")
        self.log = self.log_view(log_card.body, height=10)
        self.log.pack(fill="both", expand=True)
        self.log.append("就绪。选一首曲子，然后点「开始演奏」。", "dim")

        self._refresh_count()

    # ------------------------------------------------------------------
    def _on_pick(self, picked: list[Path]) -> None:
        if not picked:
            self.head_value.configure(text="—", text_color=self.theme.faint)
            self.head_note.configure(text="")
            return
        p = picked[0]
        # 读机器谱注释里的 BPM（弹琴本身不用它，仅参考）
        summary = toolchain.score_summary(p) or "（读不到注释）"
        self.head_value.configure(text=summary, text_color=self.theme.info)
        self.head_note.configure(text=f"曲谱：{p.name}")

    def _refresh_count(self) -> None:
        n = len(self.picker._all)
        self.count_label.configure(text=f"共 {n} 首可用曲谱（scores/）")

    def on_show(self) -> None:
        self.picker.set_items(toolchain.list_scores())
        self._refresh_count()

    # ------------------------------------------------------------------
    def prefill(self, score: str, start_line: int, speed: float, delay: float) -> None:
        """提权重启后，把参数填回去（并在稍后自动开跑）。"""
        if self.picker.select_named(Path(score).stem):
            self._on_pick(self.picker.selected())
        self.start_var.set(str(start_line))
        self.speed_var.set(f"{speed:g}")
        self.delay_var.set(f"{delay:g}")

    def auto_start(self) -> None:
        self.log.append("已以管理员身份启动，正在自动开始演奏…", "ok")
        self.after(900, self._start)

    # ------------------------------------------------------------------
    def _start(self) -> None:
        p = self.picker.first()
        if p is None:
            self.status.configure(text="请先选一首曲子", text_color=self.theme.warn)
            return
        try:
            start = max(1, int(float(self.start_var.get() or 1)))
        except ValueError:
            start = 1
        try:
            speed = float(self.speed_var.get() or 1.0)
            if speed <= 0:
                speed = 1.0
        except ValueError:
            speed = 1.0
        try:
            delay = max(0.0, float(self.delay_var.get() or 2.0))
        except ValueError:
            delay = 2.0

        if not self.app.is_admin():
            self.status.configure(text="正在申请管理员权限…", text_color=self.theme.info)
            ok = self.app.relaunch_elevated([
                "--play", str(p),
                "--start-line", str(start),
                "--speed", f"{speed:g}",
                "--delay", f"{delay:g}",
            ])
            if ok:
                self.app.on_close(force=True)
            else:
                self.status.configure(text="提权失败，请右键以管理员身份运行本应用",
                                      text_color=self.theme.err)
            return
        self._run(p, start, speed, delay)

    def _run(self, p: Path, start: int, speed: float, delay: float) -> None:
        repo = paths.repo_dir()
        if repo is None:
            self.log.append("找不到仓库根目录（parser.py / player.py 所在处）。", "err")
            return
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))

        def job():
            try:
                import keyboard       # noqa: F401
            except Exception as e:
                print(f"!! 缺少依赖 keyboard：{e}")
                print("   装法：python -m pip install -r requirements.txt")
                return 1
            import parser as P
            import player as PLAYER

            notes = P.parse(str(p), start)
            if not notes:
                print(f"!! 从第 {start} 行起没有可演奏的音符，换个起始行试试")
                return 1
            self.app.after(0, lambda: self.status.configure(
                text=f"{len(notes)} 个音符 · 等待 F8", text_color=self.theme.info))
            print(f"曲目：{p.name}")
            print(f"音符：{len(notes)} 个，起始行 {start}，倍速 {speed:g}，缓冲 {delay:g} 秒")
            print("按 F8 开始演奏（空格暂停，暂停后 P 返回）")
            result = PLAYER.play(notes, speed, notes[0][0], start, delay)
            if result == PLAYER.FINISHED:
                print("整首弹完了")
            else:
                print("已中止演奏")
            self.app.after(0, lambda: self.status.configure(
                text="已结束", text_color=self.theme.dim))
            return 0

        self.status.configure(text="准备中…", text_color=self.theme.info)
        self.run(self.log, f"演奏：{p.stem}", job)
