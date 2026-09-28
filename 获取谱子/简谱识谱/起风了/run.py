# -*- coding: utf-8 -*-
"""《起风了》完整识别管线（一条命令跑通）

  seg2.py  → glyphs3.json   （连通块 + 分类 + 合并小节线）
  classify → 追加 cl        （聚类贴数字标签）
  trans3.py→ 转写 + 拍数自检

用法：python run.py [dump 页 系统]
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
PY = r"C:\Users\HUAWEI\AppData\Local\Microsoft\WindowsApps\python.exe"
CW, CH = 24, 34
# 由 clusters4.png + raw_C*.png（NEAREST 放大）人工判读确定（类号 → 数字）
# ⚠️ 加上「灰色 tie 音」后本谱共 **14 类**（原 10 类）：
#    C3 / C7 / C8 都是 `3`（同一数字的三种字体变体）；
#    C4 / C11 都是 `5`；C1 / C9 / C10 都是 `1`（`1` 只有 w6~7，最易被切碎，故分裂最多）；
#    C12 是 `0`（休止符）；C13 是 `2` 的变体。
# ⚠️ **曾被低分条带图骗过一次**：`clusters4.png` 里 C8 看起来像 `5`，
#    用 NEAREST 放大原图后其实是 `3`（弯曲的上半部 + 下弧）。**判字形必须看原始像素**，
#    条带图的 LANCZOS 缩放会把 `3` 的弯折抹平成 `5` 的横折。
LABELS = {0: "7", 1: "1", 2: "2", 3: "3", 4: "5", 5: "4", 6: "6",
          7: "3", 8: "3", 9: "1", 10: "1", 11: "5", 12: "4", 13: "2",
          14: "0", 15: "2", 16: "2"}
# ⚠️ **C12 / C14 是「粘连块被切开后」新长出来的类**（原 14 类 → 17 类），
#    判读方式：**逐类打印归一化后的像素图**（ASCII 或 NEAREST 放大）人工确认。
#    · **C12 = `4`**（撇 + 竖 + 中横），**不是 `0`** —— 它只出现在变拍号 `4/4` 的
#      周边（p1s7 x943、p2s8 x447），是**被切开的 `4/4` 里的 `4`**。
#    · **C14 = `0`**（**空心椭圆**，中间有真空洞），**不是 `5`** ——
#      `5` 是「上横 + 左竖 + 下弧」没有封闭空洞。这一条最初标错，
#      导致 p2s2b2 bas / p3s1b4 bas 的休止符被读成 `5 5`（而不是 `0 0`）。
#    · **判别手法**：`0` 的内部有**封闭空洞**、`4` 有**满宽中横**，
#      二者与 `5` 在 24×34 归一化后的欧氏距离并不大 → **不能只靠聚类**，
#      必须回原始像素核对。
#    ⚠️ **曾被低分条带图骗过一次**：`clusters4.png` 里 C8 看起来像 `5`，
#    用 NEAREST 放大原图后其实是 `3`（弯曲的上半部 + 下弧）。**判字形必须看原始像素**，
#    条带图的 LANCZOS 缩放会把 `3` 的弯折抹平成 `5` 的横折。


def feat(gray, b):
    """⚠️ 阈值不能写死 —— 本谱的**灰色 tie 音**最深只有约 106、主体在 140~190，
    黑字则接近 0。用 128 截会把灰字抽成近乎空白（10 类 → 189 类）；用 190 截
    灰字又比黑字细一圈（189 → 156 类，仍不成 10 类）。

    正确做法：**按每个字自己的对比度归一化** —— 取该字外接框内的最小值 vmin
    与背景 255，把 `< vmin + 0.45×(255−vmin)` 判为笔画。这样黑字（vmin≈0
    → 阈值 115）与灰字（vmin≈106 → 阈值 173）都得到**同样粗细**的字形。
    """
    sub = gray[b["y0"]:b["y1"] + 1, b["x0"]:b["x1"] + 1].astype(np.float32)
    vmin = float(sub.min())
    thr = vmin + 0.45 * (255.0 - vmin)
    m = (sub < thr)
    im = Image.fromarray((m * 255).astype(np.uint8)).resize(
        (CW, CH), Image.LANCZOS)
    return (np.asarray(im).astype(np.float32) / 255.0).ravel()


def dist(a, b):
    return float(np.abs(a - b).mean())


def classify():
    d = json.loads((HERE / "glyphs3.json").read_text(encoding="utf-8"))
    dig = [g for g in d["glyphs"] if g["kind"] == "glyph"]
    gray = {p: np.array(Image.open(HERE / f"p{p}.png").convert("L"))
            for p in (1, 2, 3)}
    cl = []
    for g in dig:
        v = feat(gray[g["page"]], g)
        best, bd = None, 1e9
        for c in cl:
            x = dist(v, c["cen"])
            if x < bd:
                bd, best = x, c
        if best is not None and bd <= 0.18:
            best["mem"].append(g)
            n = len(best["mem"])
            best["cen"] = (best["cen"] * (n - 1) + v) / n
        else:
            cl.append({"cen": v, "mem": [g]})
    for i, c in enumerate(cl):
        for g in c["mem"]:
            g["cl"] = i
    # 条带图（每类取 6 个最近中心的真实字形）
    S = 4
    rowh = CH * S + 12
    W = 120 + 6 * (CW * S + 8)
    out = Image.new("RGB", (W, rowh * len(cl) + 10), (255, 255, 255))
    dr = ImageDraw.Draw(out)
    f = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 15)
    for r, c in enumerate(cl):
        y = 5 + r * rowh
        dr.text((4, y + 30), "C%d n%d = %s" % (r, len(c["mem"]),
                LABELS.get(r, "?")), fill=(180, 0, 0), font=f)
        reps = sorted(c["mem"], key=lambda g: dist(feat(gray[g["page"]], g),
                                                   c["cen"]))[:6]
        for j, g in enumerate(reps):
            sub = gray[g["page"]][g["y0"]:g["y1"] + 1,
                                  g["x0"]:g["x1"] + 1].astype(np.float32)
            vmin = float(sub.min())
            thr = vmin + 0.45 * (255.0 - vmin)
            m = (sub < thr)
            im = Image.fromarray((m * 255).astype(np.uint8))
            im = im.resize((im.size[0] * S, im.size[1] * S), Image.LANCZOS)
            out.paste(im.convert("RGB"), (116 + j * (CW * S + 8), y))
        dr.line([0, y + rowh - 4, W, y + rowh - 4], fill=(210, 210, 210))
    out.save(HERE / "clusters4.png")
    (HERE / "glyphs3.json").write_text(
        json.dumps(d, ensure_ascii=False), encoding="utf-8")
    json.dump({str(k): v for k, v in LABELS.items()},
              open(HERE / "labels.json", "w", encoding="utf-8"))
    print("聚类 %d 类，块 %d" % (len(cl), len(dig)))
    return len(cl)


def main():
    r = subprocess.run([PY, "seg2.py"], cwd=HERE, capture_output=True,
                       text=True, encoding="utf-8")
    if r.returncode:
        print(r.stdout, r.stderr)
        return 1
    # ⚠️ seg2 之后必须再跑一次 split_wide：本谱写得很紧，**相邻两个数字的笔画会
    #    连成一个连通块**（实见 p1s7b1 mel 的 `6 5` = x154-178 h17 w25），超出
    #    `kind_of` 的 `w <= 14` 被判 junk → 整小节 2 个音凭空消失。
    r = subprocess.run([PY, "split_wide.py"], cwd=HERE, capture_output=True,
                       text=True, encoding="utf-8")
    if r.returncode:
        print(r.stdout, r.stderr)
        return 1
    print(r.stdout.strip().splitlines()[-1])
    n = classify()
    if n != len(LABELS):
        print("!! 类数变了（%d ≠ %d），labels.json 需重判读" % (n, len(LABELS)))
    r = subprocess.run([PY, "trans3.py"] + sys.argv[1:], cwd=HERE,
                       capture_output=True, text=True, encoding="utf-8")
    print(r.stdout, r.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
