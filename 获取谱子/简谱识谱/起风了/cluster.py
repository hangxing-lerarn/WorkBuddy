# -*- coding: utf-8 -*-
"""把 glyphs2.json 里的数字本体聚类成 0~7 八类，产出 labels.json。

思路与《Cry For Me》一致：**归一化位图 + 贪心聚类**，不依赖任何外部 OCR。
差别在于这里的字形是印刷体（同一出版方的字体），比手写谱干净得多。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
CW, CH = 24, 34           # 归一化画布


def norm_patch(gray, b):
    """把一块的二值位图缩放到 CW×CH，返回 float 向量。"""
    sub = (gray[b["y0"]:b["y1"] + 1, b["x0"]:b["x1"] + 1] < 128)
    im = Image.fromarray((sub * 255).astype(np.uint8))
    im = im.resize((CW, CH), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32) / 255.0
    return a.ravel()


def dist(a, b):
    return float(np.abs(a - b).mean())


def main():
    data = json.loads((HERE / "glyphs2.json").read_text(encoding="utf-8"))
    gl = data["glyphs"]
    digits = [g for g in gl if g["kind"] == "glyph"]
    print("数字块", len(digits))
    feats = {}
    for pg in (1, 2, 3):
        gray = np.array(Image.open(HERE / f"p{pg}.png").convert("L"))
        for g in digits:
            if g["page"] != pg:
                continue
            feats[id(g)] = norm_patch(gray, g)

    # 贪心聚类
    clusters = []          # [{'cen':vec,'mem':[id...],'rep':glyph}]
    TH = 0.20
    for g in digits:
        v = feats[id(g)]
        best, bd = None, 1e9
        for c in clusters:
            d = dist(v, c["cen"])
            if d < bd:
                bd, best = d, c
        if best is not None and bd <= TH:
            best["mem"].append(id(g))
            n = len(best["mem"])
            best["cen"] = (best["cen"] * (n - 1) + v) / n
        else:
            clusters.append({"cen": v, "mem": [id(g)], "rep": g})
    print("聚成", len(clusters), "类")
    sizes = sorted((len(c["mem"]) for c in clusters), reverse=True)
    print("各类大小", sizes)

    # 人工判读条带：把每类的代表字形（取离中心最近的 6 个）拼成图
    from PIL import ImageDraw, ImageFont
    byid = {id(g): g for g in digits}
    grays = {p: np.array(Image.open(HERE / f"p{p}.png").convert("L"))
             for p in (1, 2, 3)}
    S = 4
    rowh = CH * S + 12
    W = 120 + 6 * (CW * S + 8)
    out = Image.new("RGB", (W, rowh * len(clusters) + 10), (255, 255, 255))
    dr = ImageDraw.Draw(out)
    f = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 15)
    for r, c in enumerate(clusters):
        y = 5 + r * rowh
        dr.text((4, y + 30), f"C{r} n{len(c['mem'])}", fill=(180, 0, 0), font=f)
        reps = sorted((byid[i] for i in c["mem"]),
                      key=lambda g: dist(feats[id(g)], c["cen"]))[:6]
        for j, g in enumerate(reps):
            sub = grays[g["page"]][g["y0"]:g["y1"] + 1, g["x0"]:g["x1"] + 1]
            im = Image.fromarray(sub.astype(np.uint8))
            im = im.resize((im.size[0] * S, im.size[1] * S), Image.LANCZOS)
            out.paste(im.convert("RGB"), (116 + j * (CW * S + 8), y))
        dr.line([0, y + rowh - 4, W, y + rowh - 4], fill=(210, 210, 210))
    out.save(HERE / "clusters.png")
    print("写出 clusters.png", out.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
