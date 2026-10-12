"""谱图识谱页：谱图 → 简谱文本（原来是网页界面的功能，搬进应用里）。

⚠️ 本机的页眉**自动识别基本失效**（45/46 首读不出），所以这一页把页眉做成
**必填项**并默认给 1=C 4/4 91 —— 这是应用侧对「手动填页眉」决定的落地。
"""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from .. import paths, toolchain
from ..picker import ListPicker
from ..widgets import Field, button, entry
from .base import Page

IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff",
           ".pgm", ".gray", ".raw")


class OcrPage(Page):
    key = "ocr"
    title = "谱图识谱"
    subtitle = "把简谱图片按页顺序喂进来，产出简谱文本（旋律 + 伴奏两个声部）"
    icon = "ocr"

    def build(self) -> None:
        t = self.theme
        self._images: list[Path] = []
        self._mel: Path | None = None
        self._bass: Path | None = None
        self._score: Path | None = None

        # ---------------- 选图 ----------------
        card = self.card("谱图", "image", "按页顺序选图；选整个文件夹时会自动按文件名里的数字排序。")
        top = ctk.CTkFrame(card.body, fg_color="transparent")
        top.pack(fill="x", pady=(0, t.size(10)))
        self.btn_files = button(top, t, "选择图片…", self._pick_files, "quiet",
                                icon="image")
        self.btn_files.pack(side="left")
        self.btn_dir = button(top, t, "选择整个文件夹…", self._pick_dir, "quiet",
                              icon="folder")
        self.btn_dir.pack(side="left", padx=(t.size(10), 0))
        self.btn_clear = button(top, t, "清空", self._clear, "ghost",
                                icon="close")
        self.btn_clear.pack(side="left", padx=(t.size(10), 0))
        self.count_label = ctk.CTkLabel(top, text="还没选图", text_color=t.faint,
                                        font=t.font(10))
        self.count_label.pack(side="left", padx=(t.size(14), 0))

        self.picker = ListPicker(card.body, t, [], None, height=150,
                                 icon="image", multi=True, searchable=False,
                                 subtitle_of=lambda p: f"{p.parent}")
        self.picker.pack(fill="both", expand=True)

        # ---------------- 页眉与输出 ----------------
        card2 = self.card("页眉与输出", "type",
                          "本机的页眉自动识别基本失效（实测 46 首里只有 1 首读出）—— 请手动填。")
        row = ctk.CTkFrame(card2.body, fg_color="transparent")
        row.pack(fill="x")
        row.columnconfigure(0, weight=3, uniform="o")
        row.columnconfigure(1, weight=2, uniform="o")
        row.columnconfigure(2, weight=2, uniform="o")

        self.f_head = Field(row, t, "页眉 （--head）", "1=C 4/4 ♩=91")
        self.f_head.grid(row=0, column=0, sticky="ew", padx=(0, t.size(10)))
        self.head_var = ctk.StringVar(
            value=self.app.settings["behaviour"].get("last_head")
            or self.app.settings["behaviour"].get("default_head", "1=C 4/4 91"))
        entry(self.f_head.slot, t, self.head_var, "1=C 4/4 91").pack(fill="x")

        self.f_name = Field(row, t, "输出名", "留空 = 用第一张图的名字")
        self.f_name.grid(row=0, column=1, sticky="ew", padx=(0, t.size(10)))
        self.name_var = ctk.StringVar(value="")
        entry(self.f_name.slot, t, self.name_var, "自动").pack(fill="x")

        self.f_extra = Field(row, t, "额外参数", "原样拼到末尾")
        self.f_extra.grid(row=0, column=2, sticky="ew")
        self.extra_var = ctk.StringVar(value="")
        entry(self.f_extra.slot, t, self.extra_var, "").pack(fill="x")

        sw = ctk.CTkFrame(card2.body, fg_color="transparent")
        sw.pack(fill="x", pady=(t.size(12), 0))
        self.also_score = ctk.IntVar(value=1)
        ctk.CTkSwitch(sw, text="顺带跑一遍转谱，直接产出机器谱（--score）",
                      variable=self.also_score, onvalue=1, offvalue=0,
                      font=t.font(11), text_color=t.text,
                      progress_color=t.accent, button_color=t.accent,
                      button_hover_color=t.accent_hi).pack(side="left")
        self.remember = ctk.IntVar(value=1)
        ctk.CTkSwitch(sw, text="记住这次页眉", variable=self.remember,
                      onvalue=1, offvalue=0, font=t.font(11), text_color=t.text,
                      progress_color=t.accent, button_color=t.accent,
                      button_hover_color=t.accent_hi).pack(side="left",
                                                           padx=(t.size(20), 0))

        # ---------------- 执行 ----------------
        run = self.card("执行", "wave", "识谱比较慢（每页几秒到几十秒），跑的时候别关窗口。")
        bar = ctk.CTkFrame(run.body, fg_color="transparent")
        bar.pack(fill="x")
        self.btn_go = button(bar, t, "开始识谱", self._run, "primary", icon="ocr")
        self.btn_go.pack(side="left")
        self.btn_save = button(bar, t, "保存到 简谱/ 与 scores/", self._save,
                              "quiet", icon="upload")
        self.btn_save.pack(side="left", padx=(t.size(10), 0))
        self.btn_sync = button(bar, t, "同步回仓库", self._sync_back, "ghost",
                               icon="refresh")
        self.btn_sync.pack(side="left", padx=(t.size(10), 0))
        for b in (self.btn_go, self.btn_save, self.btn_sync):
            self.app.register_action(b)
        self.btn_save.configure(state="disabled")
        self.status = ctk.CTkLabel(run.body, text="", text_color=t.dim,
                                   font=t.font(11), anchor="w")
        self.status.pack(fill="x", pady=(t.size(10), 0))

        log_card = self.card("日志", "wave", "")
        self.log = self.log_view(log_card.body, height=12)
        self.log.pack(fill="both", expand=True)
        self.log.append("就绪。先选谱图（按页顺序），填好页眉，再点「开始识谱」。", "dim")

    # ------------------------------------------------------------------
    def _pick_files(self) -> None:
        got = filedialog.askopenfilenames(
            title="选择简谱图片（按页顺序多选）",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"),
                       ("全部文件", "*.*")])
        if not got:
            return
        for g in got:
            p = Path(g)
            if p not in self._images:
                self._images.append(p)
        self._images = toolchain.sort_pages(self._images)
        self._sync_list()

    def _pick_dir(self) -> None:
        d = filedialog.askdirectory(title="选择装着谱图的文件夹")
        if not d:
            return
        folder = Path(d)
        files = [p for p in folder.iterdir()
                 if p.is_file() and p.suffix.lower() in IMG_EXT]
        if not files:
            self.log.append(f"这个文件夹里没有图片：{folder}", "warn")
            return
        self._images = toolchain.sort_pages(files)
        self.log.append(f"已载入 {len(self._images)} 张：{folder.name}", "ok")
        self._sync_list()

    def _clear(self) -> None:
        self._images = []
        self._sync_list()

    def _sync_list(self) -> None:
        self.picker.set_items(self._images)
        n = len(self._images)
        self.count_label.configure(
            text="还没选图" if not n else f"已选 {n} 页")

    def on_show(self) -> None:
        self._sync_list()

    # ------------------------------------------------------------------
    def _run(self) -> None:
        if not self._images:
            self.status.configure(text="先选谱图", text_color=self.theme.warn)
            return
        script = paths.ocr_script()
        err = self.app.preflight(script)
        if err:
            self.log.append(err, "err")
            self.status.configure(text="环境不完整", text_color=self.theme.err)
            return

        head = self.head_var.get().strip()
        if self.remember.get():
            self.app.update_settings(behaviour={"last_head": head})

        name = self.name_var.get().strip() or self._images[0].stem
        mel = toolchain.ensure_parent(toolchain.preview_out(name, "（旋律）"))
        bass = toolchain.ensure_parent(toolchain.preview_out(name, "（伴奏）"))
        score = (toolchain.ensure_parent(toolchain.preview_out(name, "（简谱转）"))
                 if self.also_score.get() else None)
        extra = self.extra_var.get().strip().split() if self.extra_var.get().strip() else []
        images = list(self._images)

        def job() -> int:
            from ..runner import run_script
            print(f"谱图：{len(images)} 页")
            for p in images:
                print(f"  · {p.name}")
            print(f"页眉：{head}")
            print("-" * 60)
            rc = run_script(script, toolchain.build_ocr_argv(
                images, out=mel, bass=bass, head=head, score=score,
                extra=extra))
            if rc == 0 and mel.is_file():
                self._mel, self._bass, self._score = mel, bass, score
                self.app.after(0, lambda: self.btn_save.configure(state="normal"))
                self.app.after(0, lambda: self.status.configure(
                    text=f"已产出：{mel.name}" + (f" + {bass.name}" if bass.is_file() else ""),
                    text_color=self.theme.ok))
            else:
                self.app.after(0, lambda: self.status.configure(
                    text="识谱未成功，请看日志", text_color=self.theme.err))
            return rc

        self.status.configure(text=f"识谱中（{len(images)} 页）…",
                              text_color=self.theme.info)
        self.run(self.log, f"谱图识谱：{name}", job)

    # ------------------------------------------------------------------
    def _save(self) -> None:
        d = paths.data_dirs()
        pairs = [(self._mel, d["jianpu"]), (self._bass, d["jianpu"]),
                 (self._score, d["scores"])]
        saved = []
        for src, dst_dir in pairs:
            if src and Path(src).is_file():
                try:
                    saved.append(toolchain.save_product(src, dst_dir))
                except Exception as e:
                    self.log.append(f"保存失败：{e}", "err")
        if not saved:
            self.status.configure(text="还没有可保存的产物", text_color=self.theme.warn)
            return
        for s in saved:
            self.log.append(f"已保存：{s}", "ok")
        self.status.configure(text=f"已保存 {len(saved)} 个产物", text_color=self.theme.ok)

    def _sync_back(self) -> None:
        repo = paths.repo_dir()
        if repo is None:
            self.log.append("找不到仓库目录，无法同步。", "err")
            return
        targets = [(self._mel, repo / "简谱"), (self._bass, repo / "简谱"),
                   (self._score, repo / "scores")]
        names = [Path(s).name for s, _ in targets if s and Path(s).is_file()]
        if not names:
            self.log.append("还没有可同步的产物。", "warn")
            return
        msg = ("把产物写入仓库？\n\n" + "\n".join(names)
               + "\n\n仓库里已存在的同名文件不会被覆盖（会自动加序号）。")
        if not self.app.confirm("同步回仓库", msg):
            self.log.append("已取消同步。", "dim")
            return
        for src, dst_dir in targets:
            if src and Path(src).is_file():
                try:
                    self.log.append(f"已同步：{toolchain.save_product(src, dst_dir)}", "ok")
                except Exception as e:
                    self.log.append(f"同步失败：{e}", "err")
