# -*- coding: utf-8 -*-
"""《起风了》→ glyphs2.json（修正版）

上一次的错：把 `7/ 1'/ 2'/ …` 当成 4 分音符串读出来了，与印刷谱对不上。
6 倍放大逐字核对后，**第一小节低音行真实内容是 `4 1 3　5 2 5`（六音）**，
记谱模型与《Cry For Me》完全一致：

    拍数 = (1/2^减时线数) × (附点 ? 1.5 : 1)
    1 小节 = 4 拍 = **8 个八分格 = 16 个十六分格**

第一小节低音实测：`4/`+`1/`+`3`(无减时线) + `5/`+`2/`+`5`
  = 0.5+0.5+1 + 0.5+0.5+1 = **4.0 ✓**

两个必须处理的坑（都由实拍反例砸出来）：

  ① **同一 x 的竖线会跨系统纵向连成一片**（x355 从 y304 连到 y1486），
     「找长竖线定系统」在 Cry For Me 上管用、在这里失效 → 改成按数字主行切系统。

  ② **附点（`.`）与八度点（`·`）会以极小碎片形态散落**（w1~2、h1~2 的 `junk`），
     必须**并回**它所属的那个数字，否则数字本体旁边会多出一堆噪声块、
     列分组也会被切碎。合并规则：与数字的 x 区间重叠（容差 1px）且距离 ≤6px。

产出的 blocks 只保留五类：
  glyph（数字本体）| beam（减时线，含增时线）| dot（八度点）| aug（附点）| bar（小节线）
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent

# 每页的 (上方手数字主行 y, 下方手数字主行 y)，实测自 scan4.py
ROWS = {
    1: [(319, 403), (498, 584), (679, 757), (851, 935),
        (1029, 1114), (1206, 1285), (1380, 1455)],
    2: [(158, 224), (319, 403), (498, 577), (672, 751),
        (847, 926), (1021, 1100), (1195, 1280), (1369, 1449)],
    3: [(158, 237), (346, 429)],
}


def blobs(mask, ox=0, oy=0):
    H, W = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    for yy in range(H):
        for xx in range(W):
            if mask[yy, xx] and not seen[yy, xx]:
                st = [(yy, xx)]
                seen[yy, xx] = True
                xs, ys = [], []
                while st:
                    cy, cx = st.pop()
                    xs.append(cx)
                    ys.append(cy)
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] \
                                and not seen[ny, nx]:
                            seen[ny, nx] = True
                            st.append((ny, nx))
                out.append({"x0": min(xs) + ox, "y0": min(ys) + oy,
                            "x1": max(xs) + ox, "y1": max(ys) + oy,
                            "pix": len(xs)})
    return out


def kind_of(b):
    h = b["y1"] - b["y0"] + 1
    w = b["x1"] - b["x0"] + 1
    if 16 <= h <= 18 and 5 <= w <= 14:
        return "glyph"
    if 44 <= h <= 52 and w <= 3:
        return "bar"
    # ⚠️ **增时线 `-` 与减时线长得一样（都是 h1~3 的横线），只能靠 y 区分**：
    #    减时线贴在本行数字**下方**（y≈340/344，数字 y319..335）；
    #    增时线画在**数字行的中线高度**（y≈327，即数字的 y 中点 327）。
    #    所以这里先一律标 beam，实际归属留给 trans 阶段按行 y 判。
    if h <= 3 and 8 <= w <= 60:
        return "beam"
    if 2 <= h <= 6 and w <= 8:
        return "dot"          # 八度点 / 附点（都是小实心块）
    return "junk"


def detect_bars(img, top, bot):
    """在 (top-16, bot+16) 带上用纵向墨迹剖面找小节线。

    实测判据（带高 H≈107~116，墨迹像素数）：
      x≈100.5 = 左侧花括号内沿连接线，**贯穿双手** → 107~115（≈1.00 H）
      355.5 / 603.5 / 851.5 / 1099.5 = 真实小节线，**各手各半根**
                                    → 76~84（≈0.70 H）
      谱内长竖线（x521 / x656 / x881 之类长音符杆）→ 44~54（≈0.45 H）
    故阈值取 **0.66 H**：既收下 0.70 的小节线，又排除 0.45 的音符杆。

    ⚠️ **不能用「固定带高 90」** —— 小节线只有「上手下半 + 下手上半」两段，
    带宽必须覆盖双手才凑得够高度。也别用 0.80：会漏掉所有真实小节线。
    """
    a, b = max(0, top - 16), min(img.shape[0], bot + 16)
    col = (img[a:b, :] < 128).sum(axis=0)
    thr = (b - a) * 0.66
    tall = [x for x in range(len(col)) if col[x] >= thr]
    mg = []
    for x in tall:
        if mg and x - mg[-1][1] <= 3:
            mg[-1][1] = x
        else:
            mg.append([x, x])
    xs = [(p[0] + p[1]) / 2.0 for p in mg]
    # 花括号区（x<130）只保留最后一根 = 左边界
    left = [x for x in xs if x < 130]
    right = [x for x in xs if x >= 130]
    # ⚠️ 右边界偶发双检（p3s2 出现 1091.5 与 1098.0 两笔）→ 用 12px 容差再合一次
    dedup = []
    for x in right:
        if dedup and x - dedup[-1] <= 12:
            continue
        dedup.append(x)
    return left[-1:] + dedup


def merge_fragments(bs):
    """把 1~2px 的碎片并回最近的本体；3~6px 的小块（八度点/附点）**保留**。

    ⚠️ 第一次做错的地方：把 `h 2..6 w<=5` 一律当 dot 之外还让 dot 也被并进数字，
    结果条带图里出现 `6̇` `4̣` `2̣` 这种「数字+点」混合类 —— 那是并过头了。
    正确的边界是：**点数 ≥6 个像素、且独立成块**的才是符号；1~2px 的是抗锯齿碎屑。
    """
    keep = []
    for b in bs:
        k = kind_of(b)
        if k == "junk" and b["pix"] <= 12:
            # 找一个能吞掉它的本体
            tgt = None
            for g, kg in keep:
                if kg not in ("glyph",):
                    continue
                if min(g["x1"], b["x1"]) - max(g["x0"], b["x0"]) < -1:
                    continue
                if b["y1"] >= g["y0"] - 2 and b["y0"] <= g["y1"] + 2:
                    tgt = g
                    break
            if tgt is not None:
                tgt["x0"] = min(tgt["x0"], b["x0"])
                tgt["x1"] = max(tgt["x1"], b["x1"])
                tgt["y0"] = min(tgt["y0"], b["y0"])
                tgt["y1"] = max(tgt["y1"], b["y1"])
                tgt["pix"] += b["pix"]
                continue
        keep.append((b, k))
    return keep


def gray_blobs(mask, ox=0, oy=0):
    """**8 连通**版 blobs，专供灰点使用。

    ⚠️ 灰音符的八度点画的是**空心小圆圈**（像素形如
       `+#+ / #+# / +#+`），4 连通时对角线不相连 →
       会碎成 3~6 个 `w1 h1 pix1` 的孤点（实见 p1s1 的灰 `3`，
       它的上点被切成 x190/191/192 三个 1px 块）。
       8 连通能把它们重新粘成一个 `w3 h4` 的实心块，凑够 `kind_of`
       的 dot 判据。**黑数字的点本来就是实心方块，不需要这个**。
    """
    H, W = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    for yy in range(H):
        for xx in range(W):
            if mask[yy, xx] and not seen[yy, xx]:
                st = [(yy, xx)]
                seen[yy, xx] = True
                xs, ys = [], []
                while st:
                    cy, cx = st.pop()
                    xs.append(cx)
                    ys.append(cy)
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            if not (dy or dx):
                                continue
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] \
                                    and not seen[ny, nx]:
                                seen[ny, nx] = True
                                st.append((ny, nx))
                out.append({"x0": min(xs) + ox, "y0": min(ys) + oy,
                            "x1": max(xs) + ox, "y1": max(ys) + oy,
                            "pix": len(xs)})
    return out


def gray_dots(img, ya, yb, top, bot, grays):
    """【补第三次扫描】抓**灰音符的八度点**。

    ⚠️ 这是「连音线两端音高不一致」的**第二个根因**（第一个是 `dns` 无距离上限）。
       灰音的上/下点也是灰的、且是**空心小圈** → `<128` 二值化后碎成 1px 孤点，
       `merge_fragments` 又吞不掉它们（灰数字本体 y319-335，点 y311-313，
       `313 >= 319-2` 为假）→ 点被静默丢弃。
       症状：p1s1b1 的 `1' 2' 3' 5' 3'` 全部带点，唯独**灰 `3` 漏点** →
       读成 `~3`（中音），与同小节的高音 `3'` 不是同一个音 → 解析器报
       `连音线两端的音不一样`。

    判据：在「灰数字所在行的数字带」内用 `<190`（灰点最深深到 100 左右，
    但边缘有 150~190 的抗锯齿）做 8 连通，取 `2<=h<=6 and 2<=w<=8` 的小块。
    """
    band = img[ya:yb, :]
    m = (band < 190)
    m[:, :105] = False
    lo = max(0, top - ya - 16)                  # 八度点最高不超过数字上方 ~12px
    hi = min(m.shape[0], bot - ya + 16)
    mm = np.zeros_like(m)
    mm[lo:hi] = m[lo:hi]
    out = []
    for b in gray_blobs(mm, 0, ya):
        h = b["y1"] - b["y0"] + 1
        w = b["x1"] - b["x0"] + 1
        if not (2 <= h <= 6 and 2 <= w <= 8):
            continue
        if b["pix"] < 4:
            continue
        # 必须紧挨着某个灰数字（x 投影重叠 ±3、垂直间隙 ≤ 12）
        for g in grays:
            if min(g["x1"], b["x1"]) - max(g["x0"], b["x0"]) < -3:
                continue
            gap = (g["y0"] - b["y1"]) if b["y1"] < g["y0"] \
                else (b["y0"] - g["y1"])
            if 0 <= gap <= 12:
                out.append(b)
                break
    return out


def gray_glyphs(img, ya, yb, top, bot, black):
    """【补第二次扫描】抓**灰色连音线音符**。

    ⚠️ 被实拍砸出来的坑：本谱的**连音线接音（tie 音）印成灰色**（实测最深只有
    106~135，大部分在 140~190），用 `< 128` 二值化时会碎成一堆小片，被
    `kind_of` 判为 junk 后又被 `merge_fragments` 当碎屑吃掉 —— **整个 tie 音凭空消失**。
    症状：`7123` `3`(tie) `53` `3`(tie) 只读出 6 个音，每小节少 0.5~1 拍。

    ⚠️⚠️ **第二个坑（更难）**：谱面**下方还有一整行中文歌词**，也是灰色，
    字形尺寸 w12~14 × h13~14 —— 与灰音符（w11~13 × **h17**）只差 3~4px。
    第一版只卡 `13<=h<=21` → 一次捞进 327 个灰块，其中 208 个是歌词字
    （`走漂流的片刻笑近`…），聚类直接炸到 184 类。
    **判据必须卡死在数字本体高度**：`h ∈ [16,18]`（黑字实测 h17）。
    """
    band = img[ya:yb, :]
    m = (band < 190)
    m[:, :105] = False
    # 只留数字本体的 y 范围（上下各留 4px 容差）
    lo = max(0, top - ya - 4)
    hi = min(m.shape[0], bot - ya + 4)
    mm = np.zeros_like(m)
    mm[lo:hi] = m[lo:hi]
    out = []
    for b in blobs(mm, 0, ya):
        h = b["y1"] - b["y0"] + 1
        w = b["x1"] - b["x0"] + 1
        # 数字本体高度固定 h17；歌词字 h13~14 → 被这条卡掉
        if not (16 <= h <= 18 and 4 <= w <= 16):
            continue
        # 实心度：灰字笔画细，密度阈值要低；用「块内 <190 的像素 / 外接框面积」
        fill = b["pix"] / float(w * h)
        if fill < 0.28:
            continue
        # 与黑色字形重叠太多 → 是黑字的抗锯齿边
        dup = False
        for g in black:
            ox = min(g["x1"], b["x1"]) - max(g["x0"], b["x0"])
            oy = min(g["y1"], b["y1"]) - max(g["y0"], b["y0"])
            if ox > 0 and oy > 0 and ox * oy > 0.5 * (w * h):
                dup = True
                break
        if dup:
            continue
        out.append(b)
    return out


def main():
    out = {"glyphs": [], "systems": []}
    for pg in (1, 2, 3):
        img = np.array(Image.open(HERE / f"p{pg}.png").convert("L"))
        for si, (top, bot) in enumerate(ROWS[pg], 1):
            ya, yb = max(0, top - 34), min(img.shape[0], bot + 36)
            m = (img[ya:yb] < 128)
            m[:, :105] = False
            bs = blobs(m, 0, ya)
            keep = merge_fragments(bs)
            recs = []
            for b, k in keep:
                b = dict(b)
                b.update(page=pg, sys=si, kind=k, staff=None,
                         cx=(b["x0"] + b["x1"]) / 2.0,
                         cy=(b["y0"] + b["y1"]) / 2.0,
                         w=b["x1"] - b["x0"] + 1, h=b["y1"] - b["y0"] + 1)
                b["area"] = b["w"] * b["h"]
                recs.append(b)
            # staff：以数字本体为准，按 cy 贴到手
            mid = (top + bot) / 2.0
            for b in recs:
                b["staff"] = "mel" if b["cy"] < mid else "bas"
            # ---- 第二次扫描：灰色 tie 音 ----
            gb = gray_glyphs(img, ya, yb, top, bot,
                             [r for r in recs if r["kind"] == "glyph"])
            for b in gb:
                b = dict(b)
                b.update(page=pg, sys=si, kind="glyph", gray=True,
                         cx=(b["x0"] + b["x1"]) / 2.0,
                         cy=(b["y0"] + b["y1"]) / 2.0,
                         w=b["x1"] - b["x0"] + 1, h=b["y1"] - b["y0"] + 1)
                b["area"] = b["w"] * b["h"]
                b["staff"] = "mel" if b["cy"] < mid else "bas"
                recs.append(b)
            # ---- 第三次扫描：灰音符的八度点（空心小圈，4 连通会碎） ----
            gdots = gray_dots(img, ya, yb, top, bot,
                              [r for r in recs if r.get("gray")])
            for b in gdots:
                b = dict(b)
                b.update(page=pg, sys=si, kind="dot", gray=True,
                         cx=(b["x0"] + b["x1"]) / 2.0,
                         cy=(b["y0"] + b["y1"]) / 2.0,
                         w=b["x1"] - b["x0"] + 1, h=b["y1"] - b["y0"] + 1)
                b["area"] = b["w"] * b["h"]
                b["staff"] = "mel" if b["cy"] < mid else "bas"
                recs.append(b)
            # 小节线：把上下两半（每手一根）按 x 合并
            xs = sorted(b["cx"] for b in recs if b["kind"] == "bar")
            bars = []
            for x in xs:
                if bars and x - bars[-1] <= 3:
                    bars[-1] = (bars[-1] + x) / 2
                else:
                    bars.append(x)
            # ⚠️ **左边界的坑**：`m[:, :105] = False` 把左侧大括号剃掉了，
            #    但**左边界的竖线就在 x≈100（花括号内沿）**，于是 bars 只剩 4 根
            #    → `build()` 按 bars[i]..bars[i+1] 只能切出 3 段 + 1 段尾巴，
            #    **第 1 小节的内容会掉进 b=1 并与第 2 小节合并**（拍数翻倍）。
            #    修法：用纵向墨迹剖面在整行高度上重找「接近满高」的竖线，
            #    含左边界；判据用**绝对墨迹数 ≥ 0.72×带高**（谱内长音符竖线约 0.5×）。
            bars = detect_bars(img, top, bot)
            out["systems"].append({"page": pg, "sys": si, "top": top,
                                   "bot": bot, "ya": ya, "yb": yb,
                                   "bars": bars})
            out["glyphs"].extend(recs)
            c = {}
            for b in recs:
                c[b["kind"]] = c.get(b["kind"], 0) + 1
            print("p%ds%d y%d..%d bars%d %s" % (pg, si, ya, yb, len(bars), c))
    (HERE / "glyphs3.json").write_text(
        json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print("块", len(out["glyphs"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
