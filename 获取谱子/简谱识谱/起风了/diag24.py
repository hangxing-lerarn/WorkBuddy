# -*- coding: utf-8 -*-
"""diag24.py —— 主题A 第 1 小节伴奏：第 1 系统 vs 第 5 系统的像素与块对比。"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from trans3 import build, barx  # noqa: E402


def dump(pg, y0, y1, x0, x1, tag):
    img = np.array(Image.open(HERE / ("p%d.png" % pg)).convert("L"))
    print("==== %s  (p%d x%d-%d y%d-%d)" % (tag, pg, x0, x1, y0, y1))
    for y in range(y0, y1):
        print("y%4d %s" % (y, "".join(
            "#" if v < 128 else ("+" if v < 190 else ".")
            for v in img[y, x0:x1])))


def main():
    box, systems = build()
    for seq in (0, 4):
        s = systems[seq]
        pg, sy = s["page"], s["sys"]
        it = box[(pg, sy, 1, "bas")]
        print("#" * 70)
        print("seq%d -> p%ds%d  bas bar1" % (seq + 1, pg, sy))
        for d in sorted(it["dig"], key=lambda d: d["x0"]):
            print("  DIG x%d-%d y%d-%d cl=%s" % (d["x0"], d["x1"], d["y0"],
                                                 d["y1"], d.get("cl")))
        for B in sorted(it["beam"], key=lambda b: (b["y0"], b["x0"])):
            print("  BEM x%d-%d y%d-%d w%d h%d" % (B["x0"], B["x1"], B["y0"],
                                                   B["y1"], B["w"], B["h"]))
    # 打印第 1 系统 bas 行（数字 y403..419）
    dump(1, 398, 440, 120, 260, "p1s1 bas 左半")
    dump(1, 398, 440, 250, 360, "p1s1 bas 右半")


if __name__ == "__main__":
    main()
