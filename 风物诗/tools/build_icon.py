# -*- coding: utf-8 -*-
"""生成应用图标 assets/风物诗.ico（多尺寸）。

为什么用代码画而不是塞一张 png：图标要跟着主色调走，且多尺寸 .ico 用脚本生成
比手工维护二进制更可复现。跑法：

    python 风物诗/tools/build_icon.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent          # 风物诗/tools
APP_DIR = HERE.parent                            # 风物诗
OUT = APP_DIR / "assets" / "风物诗.ico"

BG = (14, 14, 22, 255)          # #0E0E16 深色霓虹底
EDGE = (46, 46, 66, 255)        # #2E2E42 描边
ACCENT = (127, 119, 221, 255)   # #7F77DD 紫（默认强调色）
ACCENT2 = (93, 202, 165, 255)   # #5DCAA5 青（收尾渐层）
INK = (232, 232, 240, 255)

FONTS = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]


def _font(size: int):
    for p in FONTS:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw(size: int) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = max(2, int(size * 0.20))                 # 圆角，跟应用的卡片圆角一致
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=r, fill=BG)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=r,
                        outline=EDGE, width=max(1, size // 64))

    # 中央「风」字
    fs = int(size * 0.62)
    f = _font(fs)
    txt = "风"
    box = d.textbbox((0, 0), txt, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(((size - tw) / 2 - box[0], (size - th) / 2 - box[1]), txt,
           font=f, fill=INK)

    # 底部一条强调色渐变横线（呼应界面里的标题栏）
    y = int(size * 0.80)
    h = max(1, int(size * 0.055))
    x0, x1 = int(size * 0.24), int(size * 0.76)
    for x in range(x0, x1):
        k = (x - x0) / max(1, x1 - x0)
        c = tuple(int(ACCENT[i] + (ACCENT2[i] - ACCENT[i]) * k)
                  for i in range(3)) + (255,)
        d.rectangle((x, y, x + 1, y + h), fill=c)
    return im


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [draw(s) for s in sizes]
    imgs[-1].save(OUT, format="ICO",
                  sizes=[(s, s) for s in sizes], append_images=imgs[:-1])
    print("已生成 %s（%.1f KB，%d 个尺寸）"
          % (OUT, OUT.stat().st_size / 1024, len(sizes)))
    # 顺手存一张 png 供 Inno Setup 向导页用
    png = OUT.with_suffix(".png")
    imgs[-1].save(png)
    print("已生成 %s（%.1f KB）" % (png, png.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
