# -*- coding: utf-8 -*-
"""split_wide.py —— 把 glyphs3.json 里被粘连的「两个数字块」切开。

⚠️ **被实拍砸出来的坑**：本谱排字很紧，相邻两个数字的笔画会**连成一个连通块**。
   实见 p1s7b1 mel 的 `6 5`（x154-178、h17、w25）被连成一块 → 超出 `kind_of` 的
   `5 <= w <= 14` 被判 junk → **整小节的 2 个音凭空消失**（mel 读出 3.50 而不是 4.00）。
   受影响的块很多，形态高度一致：**h ∈ [16,18]、w ∈ [15,34]**。

修法：对这类块，在它的 x 范围内做**纵向投影**，找**零墨迹的列**作为切点；
   若没有零墨迹列（笔画真的碰到一起），取投影最小值列（且该列两侧都还有墨）。
   切成 2~3 个子块，各自重新计算外接框，保留原块的 `staff/page/sys`。

子块仍需过 `kind_of` 的尺寸检查（h16~18、w5~14）才算有效数字。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
IMG = {p: np.array(Image.open(HERE / f"p{p}.png").convert("L"))
       for p in (1, 2, 3)}

data = json.loads((HERE / "glyphs3.json").read_text(encoding="utf-8"))
gl = data["glyphs"]
out = []
n_split = 0
for g in gl:
    h = g["y1"] - g["y0"] + 1
    w = g["x1"] - g["x0"] + 1
    if g["kind"] != "junk" or not (16 <= h <= 18) or not (15 <= w <= 34):
        out.append(g)
        continue
    img = IMG[g["page"]]
    pad = 1
    y0 = max(0, g["y0"] - pad)
    y1 = min(img.shape[0], g["y1"] + pad + 1)
    sub = (img[y0:y1, g["x0"]:g["x1"] + 1] < 160)
    col = sub.sum(axis=0)
    # 候选切点：**纵向投影的低谷**。
    # ⚠️ 两个坑：
    #  ① 阈值不能卡 0：实测 p1s7/p2s7 的 `6 5` 粘连处该列仍有 2~3 个墨点
    #     （笔画真的碰到），而数字本体的列高在 6~17 → 取 **<= 22% 峰值**。
    #  ② 低谷可能是**相邻 2 列**（实见 p2s7b3 `6 5`：col[12]=3, col[13]=3），
    #     必须**先合并连续低谷再取中点**，否则会切出 0 宽或过窄的碎片。
    cuts = []
    pk = max(1, int(col.max()))
    lo = max(1, int(pk * 0.22))
    i = 3
    while i < len(col) - 3:
        if col[i] <= lo:
            j = i
            while j + 1 < len(col) - 3 and col[j + 1] <= lo:
                j += 1
            if col[:i].sum() > 0 and col[j:].sum() > 0:
                cuts.append(((i + j) // 2, int(col[i:j + 1].min())))
            i = j + 1
        else:
            i += 1
    # 只要 1~2 个切点就够（最多切 3 块）；按「低谷深度」优先，深的先选。
    cuts.sort(key=lambda t: t[1])
    picked = []
    for i, _ in cuts:
        if all(abs(i - j) >= 6 for j in picked):
            picked.append(i)
        if len(picked) >= 2:
            break
    picked.sort()
    if not picked:
        out.append(g)
        continue
    bounds = [0] + picked + [len(col)]
    parts = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        seg = sub[:, a:b]
        if seg.sum() == 0:
            continue
        rows = np.where(seg.any(axis=1))[0]
        cols = np.where(seg.any(axis=0))[0]
        if len(rows) == 0:
            continue
        py0, py1 = int(rows[0]) + y0, int(rows[-1]) + y0
        px0, px1 = int(cols[0]) + a + g["x0"], int(cols[-1]) + a + g["x0"]
        ph, pw = py1 - py0 + 1, px1 - px0 + 1
        if not (16 <= ph <= 18 and 5 <= pw <= 14):
            continue
        parts.append({"x0": px0, "y0": py0, "x1": px1, "y1": py1,
                      "pix": int(seg.sum()), "gray": g.get("gray", False),
                      "page": g["page"], "sys": g["sys"],
                      "cx": (px0 + px1) / 2.0, "cy": (py0 + py1) / 2.0,
                      "w": pw, "h": ph, "area": pw * ph,
                      "staff": g["staff"], "kind": "glyph"})
    if len(parts) >= 2:
        parts.sort(key=lambda p: p["x0"])
        for p in parts:
            p["cl"] = g.get("cl", -1) if len(parts) == 1 else None
            if p["cl"] is None:
                p.pop("cl", None)
        out.extend(parts)
        n_split += 1
        print("split  p%s s%s  x%d-%d h%d w%d → %d 块: %s"
              % (g["page"], g["sys"], g["x0"], g["x1"], h, w, len(parts),
                 [(p["x0"], p["x1"], p["h"], p["w"]) for p in parts]))
    else:
        out.append(g)

print("共切开 %d 个粘连块；glyphs %d → %d" % (n_split, len(gl), len(out)))
data["glyphs"] = out
(HERE / "glyphs3.json").write_text(
    json.dumps(data, ensure_ascii=False), encoding="utf-8")
print("已写回 glyphs3.json（**下一步必须重跑 run.py 重新聚类 + 打标**）")
