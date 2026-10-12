"""设置页：外观自定义（主题/强调色/字号/背景）+ 路径 + 行为 + 关于。

★ CustomTkinter 不支持运行时热换肤，所以这里每次改外观都调 app.apply_appearance()，
由它把整个界面**销毁重建**。为了不让回调把自己的控件拆掉，统一用 after(30, ...) 推迟。
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog

import customtkinter as ctk

from .. import backgrounds, paths, settings as st, theme as theme_mod, toolchain
from ..widgets import Field, IconCanvas, button, entry
from .base import Page

BG_KINDS = {"内置预设": "preset", "自选图片": "image", "纯色": "solid"}


class SettingsPage(Page):
    key = "settings"
    title = "设置"
    subtitle = "外观、目录与行为。改外观会重建整个界面，属正常现象"
    icon = "settings"

    def build(self) -> None:
        t = self.theme
        self._thumb_refs = []

        # ==================== 外观 ====================
        c = self.card("主题", "palette", "深色霓虹是默认；跟随系统会跟着 Windows 的浅色/深色切换。")

        mrow = ctk.CTkFrame(c.body, fg_color="transparent")
        mrow.pack(fill="x")
        mrow.columnconfigure(0, weight=1, uniform="g")
        mrow.columnconfigure(1, weight=1, uniform="g")

        self.f_mode = Field(mrow, t, "配色模式", "")
        self.f_mode.grid(row=0, column=0, sticky="ew", padx=(0, t.size(14)),
                         pady=(0, t.size(14)))
        cur_mode = theme_mod.MODE_LABELS.get(
            str(self.cfg("mode", "dark")), "深色霓虹")
        self.mode_var = ctk.StringVar(value=cur_mode)
        ctk.CTkSegmentedButton(
            self.f_mode.slot, values=list(theme_mod.MODES),
            variable=self.mode_var, font=t.font(11),
            selected_color=t.accent, selected_hover_color=t.accent_hi,
            unselected_color=t.input_t, unselected_hover_color=t.panel2_t,
            text_color=t.text, corner_radius=t.size(8),
            command=lambda v: self._set("mode", theme_mod.MODE_KEYS.get(v, "dark"))
        ).pack(fill="x")

        self.f_accent = Field(mrow, t, "强调色", "按钮、选中态、图标都跟着它变")
        self.f_accent.grid(row=0, column=1, sticky="ew", pady=(0, t.size(14)))
        sw = ctk.CTkFrame(self.f_accent.slot, fg_color="transparent")
        sw.pack(anchor="w")
        cur_accent = str(self.cfg("accent", "紫"))
        for name, color in theme_mod.ACCENTS.items():
            self._swatch(sw, name, color, name == cur_accent)

        # ---- 字号 ----
        cur_scale = float(self.cfg("font_scale", 1.0))
        self.f_scale = Field(mrow, t, "界面字号", "0.8× ~ 1.5×，松手即生效")
        self.f_scale.grid(row=1, column=0, sticky="ew", padx=(0, t.size(14)))
        self.scale_label = ctk.CTkLabel(self.f_scale.slot, text="",
                                        text_color=t.text,
                                        font=t.font(12, "bold"), anchor="w")
        self.scale_label.pack(anchor="w")
        self.scale_slider = ctk.CTkSlider(
            self.f_scale.slot, from_=0.8, to=1.5, number_of_steps=14,
            progress_color=t.accent, button_color=t.accent,
            button_hover_color=t.accent_hi, fg_color=t.border,
            command=self._on_scale_move)
        self.scale_slider.pack(fill="x", pady=(t.size(4), 0))
        self.scale_slider.set(cur_scale)
        self._on_scale_move(cur_scale)
        self.scale_slider.bind("<ButtonRelease-1>",
                               lambda _e: self._set("font_scale",
                                                    round(float(self.scale_slider.get()), 2)))

        # ---- 窗口不透明度 ----
        cur_op = float(self.cfg("win_opacity", 1.0) or 1.0)
        self.f_opacity = Field(mrow, t, "窗口不透明度", "0.85 ~ 1.0，太低会看不清")
        self.f_opacity.grid(row=1, column=1, sticky="ew")
        self.opacity_label = ctk.CTkLabel(self.f_opacity.slot, text="",
                                          text_color=t.text,
                                          font=t.font(12, "bold"), anchor="w")
        self.opacity_label.pack(anchor="w")
        self.opacity_slider = ctk.CTkSlider(
            self.f_opacity.slot, from_=0.85, to=1.0, number_of_steps=15,
            progress_color=t.accent, button_color=t.accent,
            button_hover_color=t.accent_hi, fg_color=t.border,
            command=self._on_opacity_move)
        self.opacity_slider.pack(fill="x", pady=(t.size(4), 0))
        self.opacity_slider.set(cur_op)
        self._on_opacity_move(cur_op)
        self.opacity_slider.bind("<ButtonRelease-1>",
                                 lambda _e: self._set("win_opacity",
                                                      round(float(self.opacity_slider.get()), 2)))

        arow = ctk.CTkFrame(c.body, fg_color="transparent")
        arow.pack(fill="x", pady=(t.size(14), 0))
        self.anim_var = ctk.IntVar(value=1 if self.cfg("animations", True) else 0)
        ctk.CTkSwitch(arow, text="过渡动效（切页淡入、按钮反馈）",
                      variable=self.anim_var, onvalue=1, offvalue=0,
                      font=t.font(11), text_color=t.text,
                      progress_color=t.accent, button_color=t.accent,
                      button_hover_color=t.accent_hi,
                      command=lambda: self._set("animations",
                                                bool(self.anim_var.get()))
                      ).pack(side="left")
        button(arow, t, "恢复默认外观", self._reset_appearance, "ghost",
               icon="refresh", height=t.size(30)).pack(side="left",
                                                       padx=(t.size(20), 0))

        # ==================== 背景 ====================
        b = self.card("背景", "image",
                      "内置预设是现场渲染出来的（六张，随主题压暗/模糊）；也可以选自己的图。")

        krow = ctk.CTkFrame(b.body, fg_color="transparent")
        krow.pack(fill="x")
        self.f_kind = Field(krow, t, "背景类型", "")
        self.f_kind.grid(row=0, column=0, sticky="ew", padx=(0, t.size(14)))
        cur_kind = str(self.cfg("bg_kind", "preset"))
        self.kind_var = ctk.StringVar(
            value=next((k for k, v in BG_KINDS.items() if v == cur_kind), "内置预设"))
        ctk.CTkSegmentedButton(
            self.f_kind.slot, values=list(BG_KINDS), variable=self.kind_var,
            font=t.font(11), selected_color=t.accent,
            selected_hover_color=t.accent_hi, unselected_color=t.input_t,
            unselected_hover_color=t.panel2_t, text_color=t.text,
            corner_radius=t.size(8),
            command=lambda v: self._set("bg_kind", BG_KINDS.get(v, "preset"))
        ).pack(fill="x")

        self.f_dim = Field(krow, t, "压暗", "让面板上的字更好读")
        self.f_dim.grid(row=0, column=1, sticky="ew", padx=(0, t.size(14)))
        self.dim_label = ctk.CTkLabel(self.f_dim.slot, text="", text_color=t.text,
                                      font=t.font(11), anchor="w")
        self.dim_label.pack(anchor="w")
        self.dim_slider = ctk.CTkSlider(
            krow, from_=0.0, to=0.8, number_of_steps=16,
            progress_color=t.accent, button_color=t.accent,
            button_hover_color=t.accent_hi, fg_color=t.border,
            command=self._on_dim_move)
        self.dim_slider.grid(row=1, column=1, sticky="ew", padx=(0, t.size(14)))
        self.dim_slider.set(float(self.cfg("bg_dim", 0.30)))
        self._on_dim_move(float(self.cfg("bg_dim", 0.30)))
        self.dim_slider.bind("<ButtonRelease-1>",
                             lambda _e: self._set("bg_dim",
                                                  round(float(self.dim_slider.get()), 2)))

        self.f_blur = Field(krow, t, "模糊", "背景越糊，界面越清爽")
        self.f_blur.grid(row=0, column=2, sticky="ew")
        self.blur_label = ctk.CTkLabel(self.f_blur.slot, text="", text_color=t.text,
                                       font=t.font(11), anchor="w")
        self.blur_label.pack(anchor="w")
        self.blur_slider = ctk.CTkSlider(
            krow, from_=0, to=20, number_of_steps=20,
            progress_color=t.accent, button_color=t.accent,
            button_hover_color=t.accent_hi, fg_color=t.border,
            command=self._on_blur_move)
        self.blur_slider.grid(row=1, column=2, sticky="ew")
        self.blur_slider.set(float(self.cfg("bg_blur", 4)))
        self._on_blur_move(float(self.cfg("bg_blur", 4)))
        self.blur_slider.bind("<ButtonRelease-1>",
                              lambda _e: self._set("bg_blur",
                                                   int(float(self.blur_slider.get()))))

        ctk.CTkLabel(b.body, text="内置预设", text_color=t.dim,
                     font=t.font(11), anchor="w").pack(fill="x",
                                                       pady=(t.size(14), t.size(6)))
        tiles = ctk.CTkFrame(b.body, fg_color="transparent")
        tiles.pack(fill="x")
        backgrounds.ensure_presets()
        cur_preset = str(self.cfg("bg_preset", backgrounds.PRESET_ORDER[0]))
        for i, name in enumerate(backgrounds.PRESET_ORDER):
            self._preset_tile(tiles, i, name, name == cur_preset)

        crow = ctk.CTkFrame(b.body, fg_color="transparent")
        crow.pack(fill="x", pady=(t.size(14), 0))
        self.btn_img = button(crow, t, "选择自己的图片…", self._pick_bg_image,
                              "quiet", icon="image")
        self.btn_img.pack(side="left")
        self.btn_color = button(crow, t, "选择纯色…", self._pick_bg_color,
                               "quiet", icon="palette")
        self.btn_color.pack(side="left", padx=(t.size(10), 0))
        self.bg_info = ctk.CTkLabel(
            crow, text="", text_color=t.faint, font=t.font(10, mono=True),
            anchor="w")
        self.bg_info.pack(side="left", padx=(t.size(14), 0))
        self._refresh_bg_info()

        # ==================== 数据与路径 ====================
        p = self.card("数据与路径", "folder",
                      "曲谱与队列在文档目录，缓存与配置在用户缓存目录；仓库里的老谱子不会被碰。")
        for label, path in (("数据目录", paths.data_dirs()["data"]),
                            ("缓存目录", paths.CACHE_DIR),
                            ("工具脚本", paths.scripts_dir()),
                            ("仓库目录", paths.repo_dir())):
            self._path_row(p.body, label, path)

        # 配置落盘自检：一眼看出「改了设置到底存没存进去」
        sr = ctk.CTkFrame(p.body, fg_color="transparent")
        sr.pack(fill="x", pady=(t.size(12), 0))
        self.store_lbl = ctk.CTkLabel(
            sr, text="", text_color=t.dim, font=t.font(11),
            anchor="w", justify="left", wraplength=t.size(540))
        self.store_lbl.pack(side="left", fill="x", expand=True)
        button(sr, t, "测试写入", self._test_store, "quiet",
               height=t.size(30)).pack(side="right")
        self._refresh_store()

        prow = ctk.CTkFrame(p.body, fg_color="transparent")
        prow.pack(fill="x", pady=(t.size(12), 0))
        self.f_scripts = Field(prow, t, "自定义工具脚本目录", "留空 = 自动查找 获取谱子/")
        self.f_scripts.pack(fill="x")
        self.scripts_var = ctk.StringVar(
            value=str(self.app.settings["paths"].get("scripts", "")))
        box = ctk.CTkFrame(self.f_scripts.slot, fg_color="transparent")
        box.pack(fill="x")
        box.columnconfigure(0, weight=1)
        entry(box, t, self.scripts_var, "自动").grid(row=0, column=0, sticky="ew")
        button(box, t, "浏览…", self._pick_scripts, "quiet",
               height=t.size(32)).grid(row=0, column=1, padx=(t.size(8), 0))
        button(box, t, "保存并重载", self._save_scripts, "quiet",
               height=t.size(32)).grid(row=0, column=2, padx=(t.size(8), 0))

        # ==================== 行为 ====================
        beh = self.card("行为", "check", "")
        brow = ctk.CTkFrame(beh.body, fg_color="transparent")
        brow.pack(fill="x")
        self.f_defhead = Field(brow, t, "默认页眉", "自动识别失败时用它")
        self.f_defhead.grid(row=0, column=0, sticky="ew", padx=(0, t.size(14)))
        self.defhead_var = ctk.StringVar(
            value=str(self.app.settings["behaviour"].get("default_head", "1=C 4/4 91")))
        entry(self.f_defhead.slot, t, self.defhead_var,
              "1=C 4/4 91").pack(fill="x")
        button(brow, t, "保存页眉默认值", self._save_default_head, "quiet",
               height=t.size(32)).grid(row=1, column=0, sticky="w",
                                       pady=(t.size(8), 0))

        srow = ctk.CTkFrame(beh.body, fg_color="transparent")
        srow.pack(fill="x", pady=(t.size(14), 0))
        self.sync_var = ctk.IntVar(
            value=1 if self.app.settings["behaviour"].get("sync_back") else 0)
        ctk.CTkSwitch(srow, text="允许「同步回仓库」（每次仍要你点确认）",
                      variable=self.sync_var, onvalue=1, offvalue=0,
                      font=t.font(11), text_color=t.text,
                      progress_color=t.accent, button_color=t.accent,
                      button_hover_color=t.accent_hi,
                      command=self._save_sync).pack(side="left")
        self.prev_var = ctk.IntVar(
            value=1 if self.app.settings["behaviour"].get("keep_preview") else 0)
        ctk.CTkSwitch(srow, text="转换产物先预览、再保存（两段式）",
                      variable=self.prev_var, onvalue=1, offvalue=0,
                      font=t.font(11), text_color=t.text,
                      progress_color=t.accent, button_color=t.accent,
                      button_hover_color=t.accent_hi,
                      command=self._save_preview).pack(side="left",
                                                       padx=(t.size(20), 0))

        # ==================== 关于 ====================
        ab = self.card("关于", "info", "")
        info = [
            f"风物诗 v{paths.APP_VERSION}　·　数据：{len(toolchain.list_scores())} 首曲谱 / "
            f"{len(toolchain.list_jianpu())} 个简谱 / {len(toolchain.list_midis())} 个待转 MIDI",
            self._deps_line(),
        ]
        for line in info:
            ctk.CTkLabel(ab.body, text=line, text_color=t.dim, font=t.font(11),
                         anchor="w", justify="left", wraplength=t.size(560)).pack(
                fill="x", pady=(0, t.size(4)))

        arow = ctk.CTkFrame(ab.body, fg_color="transparent")
        arow.pack(fill="x", pady=(t.size(10), 0))
        button(arow, t, "打开配置目录", lambda: self.app.open_folder(paths.CACHE_DIR),
               "ghost", icon="folder").pack(side="left")
        button(arow, t, "重新生成预设背景", self._regen_presets, "ghost",
               icon="refresh").pack(side="left", padx=(t.size(10), 0))
        button(arow, t, "打开数据目录",
               lambda: self.app.open_folder(paths.data_dirs()["data"]),
               "ghost", icon="folder").pack(side="left", padx=(t.size(10), 0))
        button(arow, t, "导出自检报告", self._export_report, "ghost",
               icon="save").pack(side="left", padx=(t.size(10), 0))

    def _export_report(self) -> None:
        """把「运行环境到底对不对」摊成一份文本，出问题时直接发这个。"""
        from .. import selfcheck
        dst = Path(paths.CACHE_DIR) / "风物诗-自检报告.txt"
        try:
            selfcheck.write_report(dst)
        except Exception as e:
            self.app.toast("导出失败：%s" % e)
            return
        self.app.toast("已导出：%s" % dst.name)
        try:
            self.app.open_folder(dst.parent)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------
    def cfg(self, key: str, default=None):
        return self.app.settings["appearance"].get(key, default)

    def _set(self, key: str, value, apply_now: bool = True) -> None:
        self.app.update_settings(appearance={key: value})
        if apply_now:
            self.after(30, self.app.apply_appearance)

    def _swatch(self, parent, name: str, color: str, selected: bool) -> None:
        t = self.theme
        holder = tk.Canvas(parent, width=t.size(30), height=t.size(30),
                           bg=t.panel_t, highlightthickness=0, bd=0,
                           cursor="hand2")
        holder.pack(side="left", padx=(0, t.size(6)))
        ring = t.accent_hi if selected else t.border
        holder.create_oval(2, 2, t.size(28), t.size(28), outline=ring,
                           width=2 if selected else 1)
        holder.create_oval(6, 6, t.size(24), t.size(24), fill=color, outline="")

        def click(_e=None, n=name):
            self._set("accent", n)
        holder.bind("<Button-1>", click)

    def _preset_tile(self, parent, index: int, name: str, selected: bool) -> None:
        t = self.theme
        holder = ctk.CTkFrame(parent, fg_color="transparent")
        holder.grid(row=0, column=index, padx=(0, t.size(8)))
        try:
            from PIL import Image
            p = backgrounds.preset_path(name)
            if p.is_file():
                img = Image.open(p).convert("RGB")
                img.thumbnail((112, 68))
                cimg = ctk.CTkImage(light_image=img, dark_image=img,
                                    size=(img.width, img.height))
                self._thumb_refs.append(cimg)
                lbl = ctk.CTkLabel(holder, text="", image=cimg,
                                   corner_radius=t.size(8), cursor="hand2")
                lbl.pack()
                lbl.bind("<Button-1>", lambda _e, n=name: self._set("bg_preset", n))
        except Exception:
            pass
        ctk.CTkLabel(holder, text=name,
                     text_color=t.accent_hi if selected else t.faint,
                     font=t.font(10)).pack(pady=(t.size(4), 0))

    def _path_row(self, parent, label: str, path) -> None:
        t = self.theme
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=t.size(2))
        ctk.CTkLabel(row, text=label, text_color=t.dim, font=t.font(11),
                     width=t.size(72), anchor="w").pack(side="left")
        ctk.CTkLabel(row, text=str(path) if path else "—", text_color=t.faint,
                     font=t.font(10, mono=True), anchor="w").pack(side="left")
        if path:
            def open_it(_e=None, p=path):
                self.app.open_folder(p)
            b = ctk.CTkLabel(row, text="打开", text_color=t.accent_hi,
                             font=t.font(10), cursor="hand2")
            b.pack(side="left", padx=(t.size(10), 0))
            b.bind("<Button-1>", open_it)

    def _deps_line(self) -> str:
        bits = []
        for mod, name in (("customtkinter", "CustomTkinter"), ("PIL", "Pillow"),
                          ("keyboard", "keyboard"), ("numpy", "numpy")):
            try:
                __import__(mod)
                bits.append(f"{name} ✓")
            except Exception:
                bits.append(f"{name} ✗")
        return "依赖：" + "　".join(bits)

    # ---- 配置落盘自检 --------------------------------------------------

    def _store_text(self) -> str:
        """一行说明：配置到底存不存得进去。

        受限环境（例如沙箱）里 `os.replace` 改名覆盖会被拒，程序会自动降级为
        直接覆盖写；这里把这个状态显示出来，避免「改了设置其实没存上」而不自知。
        """
        mode = paths.write_mode()
        err = self.app.settings_error or st.LAST_ERROR
        if err:
            return f"⚠ 配置落盘失败：{err[:90]}"
        if mode == "atomic":
            return "配置存储：正常（原子替换）"
        if mode == "direct":
            return ("配置存储：正常（受限环境，已降级为直接覆盖写）"
                    "——设置能存住，但断电时可能写坏，属环境限制")
        return "配置存储：尚未写入过（改动一次外观即可验证）"

    def _refresh_store(self) -> None:
        try:
            self.store_lbl.configure(text=self._store_text())
        except Exception:
            pass

    def _test_store(self) -> None:
        """真的写一次盘再读回来，把结果直接告诉用户。"""
        from .. import settings as st
        want = {"accent": self.cfg("accent", "紫"),
                "font_scale": self.cfg("font_scale", 1.0)}
        err = self.app.update_settings(appearance=want)
        if err:
            msg = f"写入失败：{err}"
        else:
            back = st.load()["appearance"]
            ok = (back.get("accent") == want["accent"]
                  and abs(float(back.get("font_scale", 1.0))
                          - float(want["font_scale"])) < 1e-6)
            msg = ("写入并回读一致 ✓（模式：%s）" % paths.write_mode()
                   if ok else "写入好像没生效，请把配置目录里的 settings.json 发我看看")
        self._refresh_store()
        self.app.toast(msg)

    def _refresh_bg_info(self) -> None:
        kind = str(self.cfg("bg_kind", "preset"))
        if kind == "image":
            v = str(self.cfg("bg_image", "")) or "（还没选图）"
        elif kind == "solid":
            v = str(self.cfg("bg_solid", "#0E0E16"))
        else:
            v = str(self.cfg("bg_preset", ""))
        self.bg_info.configure(text=v)

    # ------------------------------------------------------------------
    # 回调
    # ------------------------------------------------------------------
    def _on_scale_move(self, value) -> None:
        self.scale_label.configure(text=f"{float(value):.2f}×")

    def _on_dim_move(self, value) -> None:
        self.dim_label.configure(text=f"{float(value):.2f}")

    def _on_blur_move(self, value) -> None:
        self.blur_label.configure(text=f"{int(float(value))}")

    def _on_opacity_move(self, value) -> None:
        self.opacity_label.configure(text=f"{float(value):.2f}")

    def _pick_bg_image(self) -> None:
        got = filedialog.askopenfilename(
            title="选一张图片当背景",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp"), ("全部", "*.*")])
        if got:
            self.app.update_settings(appearance={"bg_kind": "image",
                                                 "bg_image": got})
            self.after(30, self.app.apply_appearance)

    def _pick_bg_color(self) -> None:
        cur = str(self.cfg("bg_solid", "#0E0E16"))
        rgb, hexc = colorchooser.askcolor(color=cur, title="选背景纯色")
        if hexc:
            self.app.update_settings(appearance={"bg_kind": "solid",
                                                 "bg_solid": hexc})
            self.after(30, self.app.apply_appearance)

    def _pick_scripts(self) -> None:
        got = filedialog.askdirectory(title="选择 获取谱子 目录")
        if got:
            self.scripts_var.set(got)

    def _save_scripts(self) -> None:
        self.app.update_settings(paths={"scripts": self.scripts_var.get().strip()})
        paths._SCRIPTS_CACHE = False          # 让 paths 重新查找
        self.app.toast("已保存，脚本目录将在下次使用时重新加载")
        self.after(200, self.app.rebuild)

    def _save_default_head(self) -> None:
        self.app.update_settings(
            behaviour={"default_head": self.defhead_var.get().strip() or "1=C 4/4 91"})
        self.app.toast("已保存默认页眉")

    def _save_sync(self) -> None:
        self.app.update_settings(behaviour={"sync_back": bool(self.sync_var.get())})

    def _save_preview(self) -> None:
        self.app.update_settings(
            behaviour={"keep_preview": bool(self.prev_var.get())})

    def _regen_presets(self) -> None:
        backgrounds.ensure_presets(force=True)
        self.app.toast("预设背景已重新生成")
        self.after(200, self.app.rebuild)

    def _reset_appearance(self) -> None:
        from ..settings import DEFAULTS
        self.app.update_settings(appearance=dict(DEFAULTS["appearance"]))
        self.after(30, self.app.apply_appearance)
