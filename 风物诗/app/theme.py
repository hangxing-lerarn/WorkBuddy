"""主题：把 settings 里的外观参数翻译成一套颜色 / 字体 token。

⚠️ CustomTkinter **不支持运行时热换肤**（配色在控件创建时定下），所以应用里
任何一次「换主题 / 换强调色 / 调字号 / 换背景」都走 **整树重建** —— 见 window.py
的 App.rebuild()。为此这里刻意做成「一个函数算出全部 token」的单一入口，
不让 configure() 调用散落到各个页面里。
"""
from __future__ import annotations

try:
    import darkdetect            # customtkinter 的依赖，已随它装好
except Exception:
    darkdetect = None

# --------------------------------------------------------------------------
# 调色板（深色霓虹 / 浅色）
# --------------------------------------------------------------------------

DARK = {
    "bg":      "#0E0E16",   # 窗口底
    "panel":   "#16161F",   # 卡片
    "panel2":  "#1C1C27",   # 卡片内的次级块
    "nav":     "#0A0A12",   # 左侧导航底
    "title":   "#0B0B13",   # 标题栏底
    "border":  "#2A2A3E",
    "border2": "#3A3A52",
    "text":    "#E8E8F0",
    "dim":     "#9A9AB0",
    "faint":   "#5F5F78",
    "input":   "#12121C",
    "log":     "#0B0B13",
    "ok":      "#5DCAA5",
    "warn":    "#EF9F27",
    "err":     "#F09595",
    "info":    "#AFA9EC",
    "shadow":  "#000000",
}

LIGHT = {
    "bg":      "#EFEFF5",
    "panel":   "#FFFFFF",
    "panel2":  "#F6F6FA",
    "nav":     "#E6E6EE",
    "title":   "#F7F7FB",
    "border":  "#D8D8E2",
    "border2": "#BFBFCE",
    "text":    "#1A1A22",
    "dim":     "#5F5F6E",
    "faint":   "#9A9AA8",
    "input":   "#FFFFFF",
    "log":     "#F3F3F8",
    "ok":      "#0F6E56",
    "warn":    "#854F0B",
    "err":     "#A32D2D",
    "info":    "#534AB7",
    "shadow":  "#C9C9D6",
}

# 强调色（用户可选）
ACCENTS: dict[str, str] = {
    "紫": "#7F77DD",
    "青": "#1D9E75",
    "粉": "#D4537E",
    "橙": "#D85A30",
    "蓝": "#378ADD",
    "琥珀": "#BA7517",
}
ACCENT_ORDER = list(ACCENTS)

MODES = ("深色霓虹", "浅色", "跟随系统")
MODE_KEYS = {"深色霓虹": "dark", "浅色": "light", "跟随系统": "system"}
MODE_LABELS = {v: k for k, v in MODE_KEYS.items()}

# --------------------------------------------------------------------------
# 颜色小工具
# --------------------------------------------------------------------------


def to_rgb(c: str) -> tuple[int, int, int]:
    c = (c or "#000000").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except Exception:
        return (0, 0, 0)


def to_hex(rgb) -> str:
    r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def blend(a: str, b: str, t: float) -> str:
    """a → b 线性插值，t=0 取 a、t=1 取 b。"""
    t = max(0.0, min(1.0, float(t)))
    ra, ga, ba = to_rgb(a)
    rb, gb, bb = to_rgb(b)
    return to_hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def lighten(c: str, t: float) -> str:
    return blend(c, "#FFFFFF", t)


def darken(c: str, t: float) -> str:
    return blend(c, "#000000", t)


def readable_on(bg: str) -> str:
    """在给定底色上取可读的文字色（按相对亮度挑黑或白）。"""
    r, g, b = to_rgb(bg)
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return "#101018" if lum > 0.62 else "#FFFFFF"


# --------------------------------------------------------------------------
# 字体：优先挑系统里真实存在的中文 UI 字体
# --------------------------------------------------------------------------

_PREF_UI = ("Microsoft YaHei UI", "微软雅黑", "Microsoft YaHei",
            "Segoe UI", "PingFang SC", "Noto Sans CJK SC", "Arial")
_PREF_MONO = ("Cascadia Mono", "Consolas", "JetBrains Mono", "Sarasa Mono SC",
              "Courier New")

_family_cache: dict[str, str] = {}


def _pick(prefs: tuple[str, ...], cache_key: str) -> str:
    if cache_key in _family_cache:
        return _family_cache[cache_key]
    chosen = prefs[0]
    try:
        import tkinter.font as tkfont
        available = {f.lower() for f in tkfont.families()}
        for name in prefs:
            if name.lower() in available:
                chosen = name
                break
    except Exception:
        pass
    _family_cache[cache_key] = chosen
    return chosen


# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------


class Theme:
    """一次算齐所有外观 token。构造廉价，重建时直接 new 一个。"""

    def __init__(self, cfg: dict, bg_avg: str | None = None):
        api = dict(cfg.get("appearance") or {})
        mode = str(api.get("mode", "dark"))
        if mode == "system":
            try:
                is_dark = bool(darkdetect.isDark()) if darkdetect else True
            except Exception:
                is_dark = True
        else:
            is_dark = (mode != "light")
        self.is_dark = is_dark
        self.mode_key = "dark" if is_dark else "light"

        for k, v in (DARK if is_dark else LIGHT).items():
            setattr(self, k, v)

        self.accent = ACCENTS.get(str(api.get("accent", "紫")), ACCENTS["紫"])
        self.accent_name = str(api.get("accent", "紫"))
        self.accent_hi = lighten(self.accent, 0.22 if is_dark else 0.10)
        self.accent_lo = darken(self.accent, 0.18)
        self.on_accent = readable_on(self.accent)
        # 导航选中态：强调色调成很暗的底，深色下才好看
        self.nav_active = (blend(self.nav, self.accent, 0.30) if is_dark
                           else blend(self.nav, self.accent, 0.16))

        self.bg_kind = str(api.get("bg_kind", "preset"))
        self.bg_preset = str(api.get("bg_preset", "深空紫"))
        self.bg_image = str(api.get("bg_image", "") or "")
        self.bg_solid = str(api.get("bg_solid", self.bg))
        self.bg_dim = float(api.get("bg_dim", 0.30))
        self.bg_blur = max(0, int(api.get("bg_blur", 4)))
        self.animations = bool(api.get("animations", True))
        self.win_opacity = float(api.get("win_opacity", 1.0) or 1.0)

        self.scale = max(0.8, min(1.5, float(api.get("font_scale", 1.0))))
        self.ui_family = _pick(_PREF_UI, "ui")
        self.mono_family = _pick(_PREF_MONO, "mono")

        # 背景图的平均色：用来做「半透明面板」的假透明（Tk 没有真 alpha）
        self.bg_avg = bg_avg or self.bg
        if self.bg_kind != "solid":
            self.panel_t = blend(self.panel, self.bg_avg, 0.16 if is_dark else 0.08)
            self.panel2_t = blend(self.panel2, self.bg_avg, 0.16 if is_dark else 0.08)
            self.nav_t = blend(self.nav, self.bg_avg, 0.10 if is_dark else 0.06)
        else:
            self.panel_t, self.panel2_t, self.nav_t = self.panel, self.panel2, self.nav

        self.input_t = blend(self.input, self.bg_avg, 0.10) if self.bg_kind != "solid" else self.input
        self.log_t = blend(self.log, self.bg_avg, 0.10) if self.bg_kind != "solid" else self.log

    # ---- 字体 ----
    def font(self, size: int, weight: str = "normal", mono: bool = False):
        import customtkinter as ctk
        return ctk.CTkFont(
            family=self.mono_family if mono else self.ui_family,
            size=max(9, int(round(size * self.scale))),
            weight=weight,
        )

    def size(self, base: float) -> int:
        return max(1, int(round(base * self.scale)))

    # ---- 状态色 ----
    def level_color(self, level: str) -> str:
        return {"ok": self.ok, "warn": self.warn, "err": self.err,
                "info": self.info, "dim": self.dim,
                "accent": self.accent_hi}.get(level, self.text)

    def button_colors(self, kind: str = "primary") -> dict:
        if kind == "primary":
            return {"fg_color": self.accent, "hover_color": self.accent_hi,
                    "text_color": self.on_accent, "border_width": 0}
        if kind == "ghost":
            return {"fg_color": "transparent", "hover_color": self.panel2_t,
                    "text_color": self.text, "border_width": 1,
                    "border_color": self.border}
        # quiet：低调的次级按钮
        return {"fg_color": self.panel2_t, "hover_color": self.border,
                "text_color": self.text, "border_width": 1,
                "border_color": self.border}
