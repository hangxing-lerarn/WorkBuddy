"""简谱转机器谱页。

★ 关键事实（决定这一页怎么写）：
`jianpu_to_score.py` **没有 --head 参数** —— 调号 / 拍号 / BPM 都从简谱 txt 的
**首行**读。所以「页眉手动填入」的正确做法是：把原文件**复制**到缓存目录并改写副本的
首行，再把副本喂给脚本。原简谱一个字都不动（用户铁律：不改已有的谱子）。
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from .. import paths, toolchain
from ..picker import ListPicker
from ..widgets import Field, button, entry
from .base import Page

HOLD_CHOICES = {"按住 = 本音自己的时值（默认）": "own",
                "按住 = 到下一个发声行的间隔": "next",
                "不写按住时长": "none"}


class JianpuPage(Page):
    key = "jianpu"
    title = "简谱转"
    subtitle = ("简谱 txt → 机器谱（scores/）· 页眉自动识别先填好，你确认或改掉再转；"
                "改动只写进缓存副本，原简谱不动")
    icon = "jianpu"

    def build(self) -> None:
        t = self.theme
        self._auto_header: dict = {}
        self._preview: Path | None = None

        # ---------------- 输入 ----------------
        card = self.card("输入", "jianpu", "简谱文本放数据目录的 简谱/ 下；同名对声部会自动认出来。")
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
        self.picker = ListPicker(left, t, toolchain.list_jianpu(), self._on_pick,
                                 height=196, icon="jianpu",
                                 subtitle_of=toolchain.jianpu_summary)
        self.picker.pack(fill="both", expand=True)

        right = ctk.CTkFrame(wrap, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")

        self.f_overlay = Field(right, t, "叠加声部（伴奏）", "同名对声部自动带出")
        self.f_overlay.pack(fill="x", pady=(0, t.size(10)))
        self.use_overlay = ctk.IntVar(value=1)
        self.overlay_sw = ctk.CTkSwitch(
            self.f_overlay.slot, text="一起叠加成和弦", variable=self.use_overlay,
            onvalue=1, offvalue=0, font=t.font(11), text_color=t.text,
            progress_color=t.accent, button_color=t.accent,
            button_hover_color=t.accent_hi)
        self.overlay_sw.pack(anchor="w")
        self.overlay_label = ctk.CTkLabel(right, text="—", text_color=t.faint,
                                          font=t.font(10), anchor="w",
                                          justify="left", wraplength=t.size(250))
        self.overlay_label.pack(fill="x", pady=(0, t.size(4)))

        self.f_out = Field(right, t, "输出文件名", "存到 scores/ 时用这个名字")
        self.f_out.pack(fill="x", pady=(0, t.size(10)))
        self.out_var = ctk.StringVar(value="")
        entry(self.f_out.slot, t, self.out_var, "自动：<简谱名>（简谱转）").pack(fill="x")

        # ---------------- 页眉 ----------------
        head = self.card("页眉", "type",
                         "自动识别先填进来；改过的值会写进缓存里的副本，不会碰原简谱。")
        head_row = ctk.CTkFrame(head.body, fg_color="transparent")
        head_row.pack(fill="x")
        for i in range(4):
            head_row.columnconfigure(i, weight=1, uniform="h")

        self.f_key = Field(head_row, t, "调号", "如 C / F# / Bb")
        self.f_key.grid(row=0, column=0, sticky="ew", padx=(0, t.size(8)))
        self.key_var = ctk.StringVar(value="C")
        entry(self.f_key.slot, t, self.key_var, "C").pack(fill="x")

        self.f_beats = Field(head_row, t, "拍号", "每小节拍数")
        self.f_beats.grid(row=0, column=1, sticky="ew", padx=(0, t.size(8)))
        self.beats_var = ctk.StringVar(value="4")
        entry(self.f_beats.slot, t, self.beats_var, "4").pack(fill="x")

        self.f_bpm = Field(head_row, t, "BPM", "20~320 之外判为误读")
        self.f_bpm.grid(row=0, column=2, sticky="ew", padx=(0, t.size(8)))
        self.bpm_var = ctk.StringVar(value="91")
        entry(self.f_bpm.slot, t, self.bpm_var, "91").pack(fill="x")

        self.f_headraw = Field(head_row, t, "原首行", "对照用")
        self.f_headraw.grid(row=0, column=3, sticky="ew")
        self.raw_label = ctk.CTkLabel(
            self.f_headraw.slot, text="—", text_color=t.faint,
            font=t.font(11, mono=True), anchor="w", fg_color=t.input_t,
            corner_radius=t.size(8), height=t.size(32))
        self.raw_label.pack(fill="x")

        self.head_hint = ctk.CTkLabel(head.body, text="", text_color=t.faint,
                                      font=t.font(10), anchor="w", justify="left")
        self.head_hint.pack(fill="x", pady=(t.size(10), 0))

        # ---------------- 选项 ----------------
        opt = self.card("转换选项", "tools", "默认参数就是平时用的那套；不确定就别改。")
        orow = ctk.CTkFrame(opt.body, fg_color="transparent")
        orow.columnconfigure(0, weight=2, uniform="o")
        orow.columnconfigure(1, weight=1, uniform="o")
        orow.columnconfigure(2, weight=1, uniform="o")
        orow.pack(fill="x")

        self.f_hold = Field(orow, t, "按住时长", "")
        self.f_hold.grid(row=0, column=0, sticky="ew", padx=(0, t.size(10)))
        self.hold_var = ctk.StringVar(value=list(HOLD_CHOICES)[0])
        ctk.CTkOptionMenu(
            self.f_hold.slot, values=list(HOLD_CHOICES), variable=self.hold_var,
            fg_color=t.input_t, button_color=t.border,
            button_hover_color=t.border2, text_color=t.text,
            dropdown_fg_color=t.panel, dropdown_text_color=t.text,
            dropdown_hover_color=t.nav_active, font=t.font(11),
            dropdown_font=t.font(11), corner_radius=t.size(8),
            height=t.size(32)).pack(fill="x")

        self.f_speed = Field(orow, t, "倍速", "写进机器谱首行")
        self.f_speed.grid(row=0, column=1, sticky="ew", padx=(0, t.size(10)))
        self.speed_var = ctk.StringVar(value="1.0")
        entry(self.f_speed.slot, t, self.speed_var, "1.0").pack(fill="x")

        self.f_fold = Field(orow, t, "最大移调", "折叠八度上限")
        self.f_fold.grid(row=0, column=2, sticky="ew")
        self.fold_var = ctk.StringVar(value="1")
        entry(self.f_fold.slot, t, self.fold_var, "1").pack(fill="x")

        sw_row = ctk.CTkFrame(opt.body, fg_color="transparent")
        sw_row.pack(fill="x", pady=(t.size(12), 0))
        self.force_var = ctk.IntVar(value=0)
        ctk.CTkSwitch(sw_row, text="自检有问题也照样落盘（--force）",
                      variable=self.force_var, onvalue=1, offvalue=0,
                      font=t.font(11), text_color=t.text,
                      progress_color=t.warn, button_color=t.warn,
                      button_hover_color=t.warn).pack(side="left")
        self.direct_var = ctk.IntVar(value=0)
        ctk.CTkSwitch(sw_row, text="转完直接落盘到 scores/（不用再点保存）",
                      variable=self.direct_var, onvalue=1, offvalue=0,
                      font=t.font(11), text_color=t.text,
                      progress_color=t.accent, button_color=t.accent,
                      button_hover_color=t.accent_hi).pack(side="left",
                                                           padx=(t.size(20), 0))

        # ---------------- 执行 ----------------
        run = self.card("执行", "wave", "先「仅自检」看一遍有没有问题，再真正转换，最稳。")
        bar = ctk.CTkFrame(run.body, fg_color="transparent")
        bar.pack(fill="x")
        self.btn_go = button(bar, t, "开始转换", self._convert, "primary",
                             icon="save")
        self.btn_go.pack(side="left")
        self.btn_dry = button(bar, t, "仅自检（不落盘）", self._dry_run, "quiet",
                              icon="check")
        self.btn_dry.pack(side="left", padx=(t.size(10), 0))
        self.btn_save = button(bar, t, "保存到 scores/", self._save, "quiet",
                               icon="upload")
        self.btn_save.pack(side="left", padx=(t.size(10), 0))
        self.btn_sync = button(bar, t, "同步回仓库", self._sync_back, "ghost",
                               icon="refresh")
        self.btn_sync.pack(side="left", padx=(t.size(10), 0))
        for b in (self.btn_go, self.btn_dry, self.btn_save, self.btn_sync):
            self.app.register_action(b)
        self.btn_save.configure(state="disabled")

        self.status = ctk.CTkLabel(run.body, text="", text_color=t.dim,
                                   font=t.font(11), anchor="w")
        self.status.pack(fill="x", pady=(t.size(10), 0))

        # ---------------- 日志 ----------------
        log_card = self.card("日志", "wave", "")
        self.log = self.log_view(log_card.body, height=12)
        self.log.pack(fill="both", expand=True)
        self.log.append("就绪。选一个简谱文件，页眉会自动填好，确认后点「开始转换」。", "dim")

        self._refresh_count()

    # ------------------------------------------------------------------
    def _refresh_count(self) -> None:
        self.count_label.configure(text=f"共 {len(self.picker._all)} 个简谱（简谱/）")

    def on_show(self) -> None:
        self.picker.set_items(toolchain.list_jianpu())
        self._refresh_count()

    # ------------------------------------------------------------------
    def _on_pick(self, picked: list[Path]) -> None:
        if not picked:
            return
        p = picked[0]
        got = toolchain.read_jianpu_header(p)
        self._auto_header = got
        if got.get("ok"):
            self.key_var.set(got["key"])
            self.beats_var.set(str(got["beats"]))
            self.bpm_var.set(str(got["bpm"]))
            self.raw_label.configure(text=got["raw"])
            notes = []
            if not got.get("tempo_ok", True):
                notes.append(f"⚠ BPM {got['bpm']} 超出合理范围 20~320，多半是误读，请核对")
            self.head_hint.configure(
                text="　".join(notes) or "自动识别成功，确认无误就可以转。",
                text_color=self.theme.warn if notes else self.theme.faint)
        else:
            d = self.app.settings["behaviour"].get("default_head", "1=C 4/4 91")
            fallback = toolchain.parse_header(d)
            if fallback["ok"]:
                self.key_var.set(fallback["key"])
                self.beats_var.set(str(fallback["beats"]))
                self.bpm_var.set(str(fallback["bpm"]))
            self.raw_label.configure(text=toolchain.read_head_line(p) or "（空）")
            self.head_hint.configure(
                text="没认出这道页眉，已填入默认值 —— 请手动改成谱面上的真实值。",
                text_color=self.theme.warn)

        if not self.out_var.get().strip():
            self.out_var.set("")

        ov = toolchain.sibling_overlay(p)
        if ov:
            self.overlay_label.configure(text=f"找到：{ov.name}")
        else:
            self.overlay_label.configure(text="没有同名对声部，将只转主声部")
            self.use_overlay.set(0)

    # ------------------------------------------------------------------
    def _collect(self) -> dict | None:
        p = self.picker.first()
        if p is None:
            self.status.configure(text="请先选一个简谱文件", text_color=self.theme.warn)
            return None
        key = self.key_var.get().strip() or "C"
        try:
            beats = max(1, int(float(self.beats_var.get() or 4)))
        except ValueError:
            beats = 4
        try:
            bpm = int(float(self.bpm_var.get() or 91))
        except ValueError:
            bpm = 91
        try:
            speed = float(self.speed_var.get() or 1.0)
        except ValueError:
            speed = 1.0
        try:
            fold = max(0, int(float(self.fold_var.get() or 1)))
        except ValueError:
            fold = 1

        src = p
        changed = False
        auto = self._auto_header or {}
        if auto.get("ok"):
            if (key != auto.get("key") or beats != auto.get("beats")
                    or bpm != auto.get("bpm")):
                changed = True
        header_line = toolchain.format_header(key, beats, bpm)
        if changed or not auto.get("ok"):
            try:
                src = toolchain.header_path_for(p, header_line)
            except Exception as e:
                self.log.append(f"写页眉副本失败：{e}", "err")
                return None

        stem = p.stem
        name = self.out_var.get().strip() or f"{stem}（简谱转）"
        if not name.lower().endswith(".txt"):
            name += ".txt"
        out = toolchain.ensure_parent(toolchain.preview_out(
            Path(name).stem, "", ".txt"))

        overlays = []
        if self.use_overlay.get():
            ov = toolchain.sibling_overlay(p)
            if ov:
                overlays.append(ov)

        return {
            "src": src, "original": p, "overlays": overlays, "out": out,
            "header": header_line, "bpm": bpm, "changed": changed,
            "hold": HOLD_CHOICES.get(self.hold_var.get(), "own"),
            "speed": speed, "fold": fold,
            "force": bool(self.force_var.get()),
            "name": Path(name).name,
        }

    # ------------------------------------------------------------------
    def _convert(self) -> None:
        cfg = self._collect()
        if not cfg:
            return
        script = paths.script("jianpu_to_score.py")
        err = 0

        def job() -> int:
            from ..runner import run_script
            print(f"简谱：{cfg['original'].name}")
            print(f"页眉：{cfg['header']}"
                  + ("（你改过，已写缓存副本，原文件未动）" if cfg["changed"]
                     else "（沿用原文件首行）"))
            if cfg["overlays"]:
                print("叠加声部：" + "、".join(o.name for o in cfg["overlays"]))
            print(f"输出：{cfg['out']}")
            print("-" * 60)
            rc = run_script(script, toolchain.build_jianpu_argv(
                cfg["src"], overlays=cfg["overlays"], out=cfg["out"],
                bpm=None, hold=cfg["hold"], speed=cfg["speed"],
                max_fold=cfg["fold"], force=cfg["force"], dry_run=False))
            if rc == 0 and cfg["out"].is_file():
                self._preview = cfg["out"]
                self.app.after(0, lambda: self.btn_save.configure(state="normal"))
                self._print_head(cfg["out"])
                self.app.after(0, lambda: self.status.configure(
                    text=f"已生成预览：{cfg['out'].name}", text_color=self.theme.ok))
                if self.direct_var.get():
                    self.app.after(0, lambda: self._save(auto=True))
            else:
                self.app.after(0, lambda: self.status.configure(
                    text="转换未成功，请看日志", text_color=self.theme.err))
            return rc if rc is not None else 0

        self.status.configure(text="转换中…", text_color=self.theme.info)
        self.run(self.log, f"简谱转：{cfg['original'].stem}", job)

    def _dry_run(self) -> None:
        cfg = self._collect()
        if not cfg:
            return
        script = paths.script("jianpu_to_score.py")

        def job() -> int:
            from ..runner import run_script
            print(f"仅自检：{cfg['original'].name}　页眉 {cfg['header']}")
            print("-" * 60)
            return run_script(script, toolchain.build_jianpu_argv(
                cfg["src"], overlays=cfg["overlays"], out=cfg["out"],
                hold=cfg["hold"], speed=cfg["speed"], max_fold=cfg["fold"],
                force=cfg["force"], dry_run=True))

        self.status.configure(text="自检中…", text_color=self.theme.info)
        self.run(self.log, f"仅自检：{cfg['original'].stem}", job)

    def _print_head(self, path: Path) -> None:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[:8]
        except Exception:
            return
        self.log.append("产物开头预览：", "info")
        for ln in lines:
            self.log.append("  " + ln, "dim")

    # ------------------------------------------------------------------
    def _save(self, auto: bool = False) -> None:
        if self._preview is None or not self._preview.is_file():
            self.status.configure(text="还没有可保存的产物", text_color=self.theme.warn)
            return
        if not auto:
            p = self.picker.first()
            if p is None:
                return
        dst_dir = paths.data_dirs()["scores"]
        try:
            dst = toolchain.save_product(self._preview, dst_dir)
        except Exception as e:
            self.log.append(f"保存失败：{e}", "err")
            return
        self.log.append(f"已保存到：{dst}", "ok")
        if self.app.settings["behaviour"].get("sync_back"):
            self.log.append("「同步回仓库」是打开的 —— 但仍需要你点一次「同步回仓库」才会写。",
                            "dim")
        self.status.configure(text=f"已保存：{dst.name}", text_color=self.theme.ok)

    def _sync_back(self) -> None:
        """把预览产物写回仓库的 scores/。**每次都要确认**，且绝不覆盖。"""
        if self._preview is None or not self._preview.is_file():
            self.status.configure(text="还没有可同步的产物", text_color=self.theme.warn)
            return
        repo = paths.repo_dir()
        if repo is None:
            self.log.append("找不到仓库目录，无法同步。", "err")
            return
        dst_dir = repo / "scores"
        target = dst_dir / self._preview.name
        msg = (f"把产物写入仓库？\n\n{self._preview.name}\n→ {target}\n\n"
               "仓库里已存在的同名文件不会被覆盖（会自动改名加序号）。")
        if not self.app.confirm("同步回仓库", msg):
            self.log.append("已取消同步。", "dim")
            return
        try:
            dst = toolchain.save_product(self._preview, dst_dir)
        except Exception as e:
            self.log.append(f"同步失败：{e}", "err")
            return
        self.log.append(f"已同步到仓库：{dst}", "ok")
        self.status.configure(text=f"已同步：{dst.name}", text_color=self.theme.ok)
