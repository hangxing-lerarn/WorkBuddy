"""线性图标：纯 tk.Canvas 矢量绘制，不引入任何图片资源、不用 emoji。

每只图标都在 24×24 的概念网格上设计，draw() 负责缩放到目标尺寸。
线条统一用圆头，观感更接近现代桌面应用。
"""
from __future__ import annotations

import tkinter as tk

GRID = 24.0


def _pts(seq, s: float, pad: float):
    out = []
    for x, y in seq:
        out += [pad + x * s, pad + y * s]
    return out


class _Painter:
    def __init__(self, canvas: tk.Canvas, size: int, color: str, width: float):
        self.c = canvas
        self.size = size
        self.s = size / GRID
        self.pad = size * 0.06
        self.color = color
        self.w = max(1.0, width * self.s * 1.35)

    def line(self, seq, close=False, width=None, color=None):
        pts = _pts(seq, self.s, self.pad)
        if close:
            pts = pts + pts[0:2]
        self.c.create_line(*pts, fill=color or self.color, width=width or self.w,
                           capstyle="round", joinstyle="round", smooth=False)

    def curve(self, seq, width=None, color=None):
        pts = _pts(seq, self.s, self.pad)
        self.c.create_line(*pts, fill=color or self.color, width=width or self.w,
                           capstyle="round", joinstyle="round", smooth=True)

    def rect(self, x0, y0, x1, y1, r=3.0, width=None, color=None):
        s, p = self.s, self.pad
        self.c.create_rectangle(p + x0 * s, p + y0 * s, p + x1 * s, p + y1 * s,
                                outline=color or self.color, width=width or self.w,
                                fill="")
        del r

    def round_rect(self, x0, y0, x1, y1, r=3.0, width=None, color=None):
        s, p = self.s, self.pad
        x0, y0, x1, y1 = p + x0 * s, p + y0 * s, p + x1 * s, p + y1 * s
        r = max(1.0, r * s)
        w = width or self.w
        col = color or self.color
        self.c.create_line(x0 + r, y0, x1 - r, y0, fill=col, width=w, capstyle="round")
        self.c.create_line(x0 + r, y1, x1 - r, y1, fill=col, width=w, capstyle="round")
        self.c.create_line(x0, y0 + r, x0, y1 - r, fill=col, width=w, capstyle="round")
        self.c.create_line(x1, y0 + r, x1, y1 - r, fill=col, width=w, capstyle="round")
        self.c.create_arc(x0, y0, x0 + 2 * r, y0 + 2 * r, start=90, extent=90,
                          style="arc", outline=col, width=w)
        self.c.create_arc(x1 - 2 * r, y0, x1, y0 + 2 * r, start=0, extent=90,
                          style="arc", outline=col, width=w)
        self.c.create_arc(x0, y1 - 2 * r, x0 + 2 * r, y1, start=180, extent=90,
                          style="arc", outline=col, width=w)
        self.c.create_arc(x1 - 2 * r, y1 - 2 * r, x1, y1, start=270, extent=90,
                          style="arc", outline=col, width=w)

    def circle(self, cx, cy, r, width=None, color=None, fill=""):
        s, p = self.s, self.pad
        self.c.create_oval(p + (cx - r) * s, p + (cy - r) * s,
                           p + (cx + r) * s, p + (cy + r) * s,
                           outline=color or self.color, width=width or self.w, fill=fill)

    def arc(self, cx, cy, r, start, extent, width=None, color=None):
        s, p = self.s, self.pad
        self.c.create_arc(p + (cx - r) * s, p + (cy - r) * s,
                          p + (cx + r) * s, p + (cy + r) * s,
                          start=start, extent=extent, style="arc",
                          outline=color or self.color, width=width or self.w)


# --------------------------------------------------------------------------
# 各图标
# --------------------------------------------------------------------------


def _play(p: _Painter):
    """弹琴：琴键。"""
    p.round_rect(3, 5, 21, 19, r=2.6)
    for x in (8.4, 13.8, 19.2):
        p.line([(x, 5.6), (x, 18.4)], width=p.w * 0.8)
    p.line([(4.2, 11.4), (7.6, 11.4)], width=p.w * 0.9)
    p.line([(9.8, 11.4), (13.0, 11.4)], width=p.w * 0.9)
    p.line([(15.2, 11.4), (18.4, 11.4)], width=p.w * 0.9)


def _midi(p: _Painter):
    """MIDI 直接转：文件 → 箭头 → 文件。"""
    p.round_rect(2.4, 6.5, 9.6, 17.5, r=2.0)
    p.line([(5.0, 10.2), (7.0, 10.2)])
    p.line([(5.0, 13.8), (7.0, 13.8)])
    p.line([(11.6, 12.0), (17.0, 12.0)])
    p.line([(14.6, 9.4), (17.4, 12.0), (14.6, 14.6)])
    p.round_rect(18.4, 6.5, 21.6, 17.5, r=1.6)


def _jianpu(p: _Painter):
    """简谱转：带横线与数字点的谱页。"""
    p.round_rect(4.0, 3.0, 20.0, 21.0, r=3.0)
    for y in (8.4, 13.2, 18.0):
        p.line([(7.4, y), (16.6, y)])
    p.circle(11.6, 8.4, 1.35, width=0)
    p.line([(13.6, 8.4), (13.6, 8.4)])


def _ocr(p: _Painter):
    """谱图识谱：图片 + 放大镜。"""
    p.round_rect(2.6, 4.6, 16.4, 18.0, r=2.6)
    p.line([(4.6, 14.6), (8.0, 10.6), (10.6, 13.4), (13.0, 10.8)])
    p.circle(7.6, 8.6, 1.5)
    p.circle(16.4, 15.4, 4.2)
    p.line([(19.4, 18.4), (22.0, 21.0)])


def _tools(p: _Painter):
    """工具：扳手。"""
    p.line([(6.2, 17.8), (14.2, 9.8)])
    p.arc(16.4, 7.6, 4.6, start=20, extent=250)
    p.line([(13.6, 12.6), (11.4, 10.4)])
    p.circle(5.0, 19.0, 1.5, width=p.w * 0.9)


def _settings(p: _Painter):
    """设置：齿轮。"""
    import math
    p.circle(12, 12, 3.6)
    p.circle(12, 12, 8.4, width=p.w * 0.9)
    for i in range(8):
        a = math.radians(i * 45)
        p.line([(12 + 8.4 * math.cos(a), 12 + 8.4 * math.sin(a)),
                (12 + 11.0 * math.cos(a), 12 + 11.0 * math.sin(a))],
               width=p.w * 0.9)


def _sun(p: _Painter):
    import math
    p.circle(12, 12, 4.6)
    for i in range(8):
        a = math.radians(i * 45)
        p.line([(12 + 7.4 * math.cos(a), 12 + 7.4 * math.sin(a)),
                (12 + 10.2 * math.cos(a), 12 + 10.2 * math.sin(a))],
               width=p.w * 0.9)


def _moon(p: _Painter):
    p.arc(12, 12, 8.0, start=60, extent=240)
    p.arc(15.6, 10.4, 6.6, start=120, extent=200)


def _palette(p: _Painter):
    p.circle(12, 12, 8.6)
    p.circle(9.0, 8.6, 1.3, width=0, fill=p.color)
    p.circle(15.0, 9.2, 1.3, width=0, fill=p.color)
    p.circle(7.6, 13.6, 1.3, width=0, fill=p.color)
    p.circle(14.2, 15.4, 1.3, width=0, fill=p.color)


def _type(p: _Painter):
    p.line([(5.6, 6.4), (18.4, 6.4)])
    p.line([(12.0, 6.4), (12.0, 18.0)])
    p.line([(8.8, 18.0), (15.2, 18.0)])
    p.line([(17.0, 12.6), (20.4, 12.6)], width=p.w * 0.7)
    p.line([(17.0, 15.6), (20.4, 15.6)], width=p.w * 0.7)


def _folder(p: _Painter):
    p.line([(3.2, 18.4), (3.2, 7.0), (9.6, 7.0), (11.4, 9.4), (20.8, 9.4), (20.8, 18.4)], close=True)


def _image(p: _Painter):
    p.round_rect(3.0, 5.0, 21.0, 19.0, r=2.6)
    p.line([(5.4, 15.8), (9.6, 11.0), (13.0, 14.6), (16.0, 11.2), (18.6, 15.8)])
    p.circle(8.4, 9.2, 1.5)


def _check(p: _Painter):
    p.line([(5.0, 12.6), (10.0, 17.4), (19.0, 6.8)])


def _wave(p: _Painter):
    """波形：音频 / 自检。"""
    for x, h in ((5.0, 4.0), (8.4, 7.4), (11.8, 9.6), (15.2, 6.2), (18.6, 3.2)):
        p.line([(x, 12 - h), (x, 12 + h)], width=p.w * 0.95)


def _save(p: _Painter):
    p.round_rect(3.6, 3.6, 20.4, 20.4, r=2.6)
    p.line([(8.0, 3.8), (8.0, 9.6), (16.0, 9.6), (16.0, 3.8)])
    p.round_rect(7.6, 13.6, 16.4, 20.2, r=1.6)


def _refresh(p: _Painter):
    p.arc(12, 12, 7.6, start=40, extent=280)
    p.line([(17.2, 5.2), (17.6, 9.6), (13.0, 9.0)])


def _upload(p: _Painter):
    p.line([(12.0, 17.0), (12.0, 5.6)])
    p.line([(7.8, 9.6), (12.0, 5.4), (16.2, 9.6)])
    p.line([(4.6, 19.4), (19.4, 19.4)])


def _minus(p: _Painter):
    p.line([(6.4, 12), (17.6, 12)])


def _square(p: _Painter):
    p.round_rect(6.4, 6.4, 17.6, 17.6, r=1.6)


def _restore(p: _Painter):
    p.round_rect(4.4, 8.4, 15.6, 19.6, r=1.8)
    p.line([(8.0, 5.6), (19.6, 5.6), (19.6, 16.4)])


def _close(p: _Painter):
    p.line([(6.8, 6.8), (17.2, 17.2)])
    p.line([(17.2, 6.8), (6.8, 17.2)])


def _note(p: _Painter):
    p.line([(9.4, 17.2), (9.4, 6.0), (18.0, 4.4), (18.0, 15.4)])
    p.circle(6.6, 17.4, 2.8)
    p.circle(15.2, 15.6, 2.8)


def _info(p: _Painter):
    p.circle(12, 12, 8.6)
    p.line([(12, 11.0), (12, 16.6)])
    p.circle(12, 7.8, 1.0, width=0, fill=p.color)


ICONS = {
    "play": _play, "midi": _midi, "jianpu": _jianpu, "ocr": _ocr,
    "tools": _tools, "settings": _settings, "sun": _sun, "moon": _moon,
    "palette": _palette, "type": _type, "folder": _folder, "image": _image,
    "check": _check, "wave": _wave, "save": _save, "refresh": _refresh,
    "upload": _upload, "minus": _minus, "square": _square, "restore": _restore,
    "close": _close, "note": _note, "info": _info,
}
ICON_ORDER = list(ICONS)


def draw(canvas: tk.Canvas, name: str, color: str, size: int | None = None,
         width: float = 1.7) -> None:
    """把 name 图标画进 canvas（清空后重画）。"""
    canvas.delete("all")
    fn = ICONS.get(name)
    if fn is None:
        return
    if size is None:
        size = min(int(canvas.winfo_reqwidth()) or 20,
                   int(canvas.winfo_reqheight()) or 20)
    fn(_Painter(canvas, int(size), color, width))
