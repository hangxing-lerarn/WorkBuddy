#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简谱谱图 → 机器谱（通用识谱工具）

把「风物之诗琴」类的**双手钢琴简谱图片**读成 `scores/*.txt` 能直接弹的机器谱。
与一次性脚本的区别：**所有版面参数都是自动检测的**，换曲子 / 换扫描分辨率都不用改代码。

链路：
    图片 → 灰度 → 自适应阈值 → 连通域 → 字形模板匹配
         → 小节线（细高竖线）→ 系统 → 小节 → 两只手 → 数字行
         → token（音级/八度点/减时线/附点/增时线）→ 拍数配平 → 简谱文本
         →（可选）jianpu_to_score.py → scores/*.txt

自动检测的东西（旧版全是硬编码）：
    · 墨阈值       = 纸白 × 0.81（纸白取亮度直方图最亮主峰）
    · 字号尺度 S   = 数字行高 / 21，**所有长度常量都乘 S**
    · 小节线 x     = 细高连通域（h ≥ 1.15×字高 且 w ≤ 0.30×字高）按 x 聚类
    · 系统 y 区间  = 小节线的纵向连续段
    · 小节数/系统  = 该系统内小节线 x 的个数 − 1（**不再假设「每系统 4 小节」**）
    · 两只手分界   = 数字 cy 一维聚类的最大间隙（两侧各需 ≥6 个数字）
    · 段落号 @N    = 系统上方左端的 `(数字)`，用同一套字模认
    · 页眉调号/拍号/速度 = 第 1 页左上角的 `1=C` + 竖排 `4/4` + `♩=91`
    · 字形类别     = 与 `字模.json` 的 L1 最近邻（**不写手写几何规则**）
    · 灰度接音     = dark > 纸白 × 0.43（跨小节连音线的接音，不重弹）

用法：
    python 识谱.py 1.png 2.png 3.png 4.png
    python 识谱.py *.png -o 简谱示例/曲子.txt --bass 简谱示例/曲子-左手.txt
    python 识谱.py p.png --raw 1400x1980       # 裸 8 位灰度字节（.gray/.raw）
    python 识谱.py p.png --head "1=C 4/4 91"   # 手动指定首行
    python 识谱.py p.png --score scores/曲.txt # 顺带产出机器谱
    python 识谱.py p.png --debug-dir out/      # 落版面调试图
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                    # imgio
sys.path.insert(0, str(HERE.parent))             # jianpu_to_score

import imgio                                     # noqa: E402

# ---------------------------------------------------------------------------
# 常量：全部以「数字行高 = 21px」标定，运行时一律乘尺度 S
# ---------------------------------------------------------------------------
REF_H = 21.0

SYS_PAD = 25.0        # 系统上下各留多少余量给八度点 / 减时线
BAR_PAD = 5.0         # 排除小节线本身（按 cx 归属，双竖线已合并成一列）
SPLIT_W = 20.0        # 贴着写的两个数字（`6̇3̇`）超过这个宽度就按墨量谷切开
ROW_BAND = 8.0        # 主行采样带宽
GAP_MIN = 20.0        # 离主行超过这么多像素 = 可疑的「夹层音」
DOT_MAX = 20.0        # 八度点离数字多远还算它的（减时线会把点顶得更低，实测 dd≈16）
DOT_H, DOT_W, DOT_A = 8.0, 7.0, 28.0          # 八度点/附点的尺寸上限
BAR_TOL = 15.0        # 小节线 x 去重容差（双竖线只隔 8px，必须并成一列）
VBAR_HF, VBAR_WF = 1.15, 0.30                 # 小节线：高 ≥1.15 字高，宽 ≤0.30 字高
BRACE_HF, BRACE_WF = 3.0, 0.30                # 花括号：高 ≥3 字高，宽 ≥0.30 字高
BRACE_AF = 120.0 / (REF_H ** 2)
HLINE_HF, HLINE_WF = 0.55, 0.45               # 减时线/增时线：矮而宽
GLYPH_HF = 12.0 / REF_H                       # 数字：高 ≥ 12
GLYPH_AF = 60.0 / (REF_H ** 2)
SMALL_AF = 25.0 / (REF_H ** 2)                # 小字（段落号 `(13)` / 页眉）专用面积下限
PAD_GAP = 48.0        # 谱表上方多远之内算「页眉/段落号区」，再往上就是标题了
GRAY_F = 0.43                                 # 灰色接音：dark > 纸白 × 0.43
GRAY_SLACK = 5.0        # 浅灰接音的额外容忍距离（它的笔画天生比黑字细一圈）
MIN_SAMPLES = 2         # 自校准：一个字形至少要几个样本才敢当模板
SPREAD_MAX = 0.65       # 自校准：样本离散上限 ÷ 接受阈值

BEAMSTR = {0: "", 1: "/", 2: "//", 3: "///", 4: "////"}

TPL = json.loads((HERE / "字模.json").read_text(encoding="utf-8"))
GW, GH = TPL["grid"]
ACCEPT = float(TPL.get("accept", 65.0))
ATLAS = dict(TPL["digits"])          # 正文层：音级 0~7（笔画常规粗细）
SYMBOLS = dict(TPL["symbols"])       # `(` `)` `C`（本身就是细体，与小字层同风格）
SMALL = dict(TPL.get("small", {}))   # 细体层：谱表上方（小节号 / 页眉）专用的 0~9
SECTION_HINT = {}                    # (页号-1, 系统号) → 版面推出的段落号，自校准填
_TEMPLATES = []


def rebuild_templates():
    """正文层模板表 = **只有音级 0~7**。

    ⚠️ 正文层**绝不能带 `(` `)` 这类符号模板**：谱表内部不可能出现括号，而连音线的
    弧被切开后的碎片恰好是弯的，实测会以 L1 距离 64.8（阈值 65）匹配上 `(` →
    和真音符并进同一列，拼出 `(( 3')` 这种伪和弦。因为伪音与原音同列、时值不变，
    **每小节拍数自检完全抓不到**，只有逐字节对账才暴露。符号只留给谱表上方那一层。
    """
    global _TEMPLATES
    _TEMPLATES = list(ATLAS.items())


def small_templates():
    """谱表上方区域（小节号 / 页眉）的模板表：细体数字 + 符号。

    ⚠️ **必须与正文层分开**。小字号的字形比正文细，同一字形在 14×18 网格上的
    L1 距离天然就有 45~60（接近接受阈值 65）。把细体 8/9 混进正文层实测过：
    小节号里的细体 `3` 被 `8` 抢走（`13`→`18`）、细体 `0` 被 `9` 抢走（`101`→`191`），
    而小节号自身用细体层则留一 50/51。所以两个区域两套模板。
    """
    base = SMALL if SMALL else ATLAS
    return list(base.items()) + list(SYMBOLS.items())


rebuild_templates()


# ---------------------------------------------------------------------------
# 连通域
# ---------------------------------------------------------------------------
class Sheet:
    """一页图：灰度 + 二值掩码。

    墨阈值可以**跨页统一**（`ink=`）：纸白是扫描/导出设置的属性，不该逐页跳。
    本系列图第 1 页纸白 253、其余 255 —— 逐页各算会得到 205/207 两个值，
    同一批谱面的判读就不一致了。默认取**全批次最深的纸白**。
    """

    def __init__(self, path, page_no, raw_size=None):
        self.path, self.page = str(path), page_no
        self.buf, self.W, self.H = imgio.load_gray(path, raw_size)
        self.auto_ink, self.paper = imgio.ink_threshold(self.buf)
        self.ink = self.auto_ink
        self.dark = bytearray(1 if v < self.ink else 0 for v in self.buf)

    def set_ink(self, ink):
        if ink == self.ink:
            return
        self.ink = int(ink)
        self.dark = bytearray(1 if v < self.ink else 0 for v in self.buf)

    def components(self, x0=0, y0=0, x1=None, y1=None):
        """8 邻域迭代 DFS。返回每个连通域的 bbox/面积/平均灰度/像素表。"""
        W = self.W
        x1 = self.W if x1 is None else x1
        y1 = self.H if y1 is None else y1
        dark, buf = self.dark, self.buf
        seen = bytearray(W * self.H)
        out = []
        for sy in range(y0, y1):
            base = sy * W
            for sx in range(x0, x1):
                i = base + sx
                if seen[i] or not dark[i]:
                    continue
                seen[i] = 1
                stack, pix = [i], []
                while stack:
                    p = stack.pop()
                    pix.append(p)
                    py, px = divmod(p, W)
                    for ny in (py - 1, py, py + 1):
                        if ny < y0 or ny >= y1:
                            continue
                        nb = ny * W
                        for nx in (px - 1, px, px + 1):
                            if nx < x0 or nx >= x1:
                                continue
                            q = nb + nx
                            if not seen[q] and dark[q]:
                                seen[q] = 1
                                stack.append(q)
                xs = [p % W for p in pix]
                ys = [p // W for p in pix]
                a, b, c, d = min(xs), max(xs), min(ys), max(ys)
                n = len(pix)
                out.append({
                    "x0": a, "x1": b, "y0": c, "y1": d,
                    "w": b - a + 1, "h": d - c + 1, "area": n,
                    "cx": (a + b) // 2, "cy": (c + d) // 2,
                    "dark": round(sum(buf[p] for p in pix) / n, 1),
                    "pts": list(zip(xs, ys)),
                })
        return out


# ---------------------------------------------------------------------------
# 字形：归一化 / 模板匹配 / 几何粗筛
# ---------------------------------------------------------------------------
def norm_cover(comp):
    """bbox 归一到 GW×GH 网格（保持长宽比、居中）→ GW*GH 维浮点，**与字号无关**。"""
    bw, bh = comp["w"], comp["h"]
    x0, y0 = comp["x0"], comp["y0"]
    pts = set(comp["pts"])
    if bh / bw >= GH / GW:
        hh = GH
        ww = max(1, round(bw * GH / bh))
    else:
        ww = GW
        hh = max(1, round(bh * GW / bw))
    ww, hh = min(ww, GW), min(hh, GH)
    grid = [[0.0] * ww for _ in range(hh)]
    for gy in range(hh):
        yA = y0 + gy * bh // hh
        yB = max(y0 + (gy + 1) * bh // hh, yA + 1)
        for gx in range(ww):
            xA = x0 + gx * bw // ww
            xB = max(x0 + (gx + 1) * bw // ww, xA + 1)
            k = sum(1 for x in range(xA, xB) for y in range(yA, yB) if (x, y) in pts)
            grid[gy][gx] = k / ((xB - xA) * (yB - yA))
    canvas = [[0.0] * GW for _ in range(GH)]
    ox, oy = (GW - ww) // 2, (GH - hh) // 2
    for y in range(hh):
        for x in range(ww):
            canvas[oy + y][ox + x] = grid[y][x]
    return [v for row in canvas for v in row]


def _shift_bm(bm, dx, dy):
    """把 GW×GH 扁平位图平移 (dx,dy)，越界部分补 0。"""
    out = [0.0] * (GW * GH)
    for y in range(GH):
        ny = y + dy
        if ny < 0 or ny >= GH:
            continue
        base = y * GW
        nbase = ny * GW
        for x in range(GW):
            nx = x + dx
            if nx < 0 or nx >= GW:
                continue
            out[nbase + nx] = bm[base + x]
    return out


def match_glyph_shift(bm, tl=None):
    """在 ±1 像素平移内找最近模板，抵消 PNG 抗锯齿造成的 1px 抖动。

    注意：包含 (0,0)，所以结果不会比 norm_cover 更差。
    """
    best = (float("inf"), None)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            s = _shift_bm(bm, dx, dy)
            for lab, t in (_TEMPLATES if tl is None else tl):
                d = 0.0
                for i in range(len(s)):
                    d += abs(s[i] - t[i])
                if d < best[0]:
                    best = (d, lab)
    return best


def match_glyph(bm, tl=None):
    best, bd = None, 1e18
    for lab, t in (_TEMPLATES if tl is None else tl):
        d = 0.0
        for i in range(len(bm)):
            d += abs(bm[i] - t[i])
        if d < bd:
            bd, best = d, lab
    return best, bd


def match_glyph_top2(bm, tl=None):
    """返回最佳与次佳 (lab1,d1,lab2,d2)。"""
    b1, d1, b2, d2 = None, float("inf"), None, float("inf")
    for lab, t in (_TEMPLATES if tl is None else tl):
        d = 0.0
        for i in range(len(bm)):
            d += abs(bm[i] - t[i])
        if d < d1:
            b2, d2 = b1, d1
            b1, d1 = lab, d
        elif d < d2:
            b2, d2 = lab, d
    return b1, d1, b2, d2


def classify(comp, med_h, S, glyph_af=None, tl=None):
    """kind ∈ {dot, vbar, brace, hline, glyph, arc, junk}，并带 label/dist。

    **几何只做粗筛，字形一律交给模板**。
    旧版用「面积/填充率」手写规则判连音弧，把页眉那个细体的 `1`（10×18、面积 74）
    误判成弧线整颗丢掉 —— 模板匹配不会犯这种错。

    `glyph_af` 可放宽：小节号 `(13)` 与页眉用的是**更细的小字**，
    面积 57~63 卡在正文数字的面积下限 60 上，不放宽会把 `(` 整颗丢掉。
    `tl` 可换一套模板表（谱表上方用 `small_templates()` 那套细体的）。
    """
    glyph_af = GLYPH_AF if glyph_af is None else glyph_af
    tl = _TEMPLATES if tl is None else tl
    h, w, a = comp["h"], comp["w"], comp["area"]
    if h <= 2 * S or a < 12 * S * S:
        return "junk", None, None
    if h <= DOT_H * S and w <= DOT_W * S and a <= DOT_A * S * S:
        return "dot", None, None
    if h >= VBAR_HF * med_h and w <= VBAR_WF * med_h:
        return "vbar", None, None
    if h >= BRACE_HF * med_h and w >= BRACE_WF * med_h and a >= BRACE_AF * S * S:
        return "brace", None, None
    if h <= HLINE_HF * med_h and w >= HLINE_WF * med_h:
        return "hline", None, None
    if h < GLYPH_HF * S or w < 4 * S or a < glyph_af * S * S:
        return "junk", None, None
    bm = norm_cover(comp)
    lab, d, lab2, d2 = match_glyph_top2(bm, tl)
    # bbox 居中拿不准时，在 ±1px 平移里再搜一次（PNG 抗锯齿常见 1px 偏移）
    if d <= ACCEPT and d > 0.45 * ACCEPT and (d2 - d) < 0.25 * ACCEPT:
        d_c, lab_c = match_glyph_shift(bm, tl)
        if d_c < d - 5 and d_c <= 0.55 * ACCEPT:
            lab, d = lab_c, d_c
    if d <= ACCEPT:
        return "glyph", lab, d
    if a < 0.5 * w * h:                 # 认不出又细又弯 —— 多半是连音弧碎片
        return "arc", None, d
    return "junk", None, d


def split_wide(comp, maxw, depth=0, med_h=None, S=None):
    """贴着写的两个数字（`6̇3̇`）会连成一个连通域 → 切开。

    **两级策略**：先按「列墨量谷」递归切（快、对正常粘连足够），只有在
    「整块是一排实心数字、且其中一片明显是数字却认不出」时才改用**按识别代价**
    重新切（慢，但能救回「笔画互相咬合」的情形）。

    ⚠️ 触发条件与采纳门槛都必须卡得很死。放开来实测过：灰度那条**已经逐字节
    对齐**的链路上会凭空长出 `(1 1)`、`(3 1)` 这种伪和弦与 `1'` 伪八度号
    （慢路径把减时线的碎片「认」成了数字），旋律因此多出 1 个拍数错。
    """
    if comp["w"] <= maxw or depth >= 4:
        return [comp]
    fast = _split_valley(comp, maxw, depth)
    if med_h is None or S is None:
        return fast
    # ① 整块必须像「一排实心数字」：字高、够填实。减时线/增时线块又扁又空（实测
    #    填充率 0.17~0.36、高只有 0.6 字高），在这一步就被挡掉。
    if not (0.9 * med_h <= comp["h"] <= 1.35 * med_h
            and comp["area"] >= 0.45 * comp["w"] * comp["h"]):
        return fast
    # ② 快路径里必须真有「数字形状却认不出」的碎片
    if not any(_digitish(p, med_h) and _glyph_dist(p) > ACCEPT for p in fast):
        return fast
    smart = _split_by_recog(comp, maxw, len(fast), S)
    if smart and _clearly_better(fast, smart):
        return smart
    return fast


def _glyph_dist(p):
    return match_glyph(norm_cover(p))[1]


def _digitish(p, med_h):
    """这一片**长得**像不像一个数字（只看几何，不看识别结果）。"""
    return (0.9 * med_h <= p["h"] <= 1.35 * med_h and p["w"] <= 1.4 * med_h
            and p["area"] >= 0.45 * p["w"] * p["h"])


def _clearly_better(fast, smart):
    """慢路径必须**明显**更好才采纳：每片都认得很牢（≤0.7 阈值）且总代价降到 3/4 以下。

    这个双重门槛是实测调出来的：只有「每片 ≤0.7×阈值」能把灰度上那些
    「把减时线碎片认成数字」的假成功全部挡掉（它们的碎片距离普遍在 47~65）。
    """
    d_fast = [_glyph_dist(p) for p in fast]
    d_smart = [_glyph_dist(p) for p in smart]
    return max(d_smart) <= 0.7 * ACCEPT and sum(d_smart) <= 0.75 * sum(d_fast)


def _split_valley(comp, maxw, depth=0):
    """快速路径：按列的墨量谷递归切。

    ⚠️ 数字互相咬合时（同一个 `4` 的横笔伸到隔壁字里）墨量谷会落在**别人的笔画**上，
    切出来的碎片就认不出了（实测 PNG 下 `4 4 3` 粘连块 → 第 2 片对 `4` 的 L1 距 93）。
    """
    if comp["w"] <= maxw or depth >= 4:
        return [comp]
    col = {}
    for x, _ in comp["pts"]:
        col[x] = col.get(x, 0) + 1
    x0, x1 = comp["x0"], comp["x1"]
    span = x1 - x0 + 1
    cand = list(range(x0 + int(span * 0.30), x0 + int(span * 0.70) + 1))
    if not cand:
        return [comp]
    top = max(col.values())
    xm = min(cand, key=lambda x: (col.get(x, 0), abs(x - (x0 + x1) / 2)))
    if col.get(xm, 0) > 0.55 * top:
        return [comp]
    out = []
    for part in ([p for p in comp["pts"] if p[0] < xm],
                 [p for p in comp["pts"] if p[0] >= xm]):
        if part:
            out.extend(_split_valley(_mkcomp(part), maxw, depth + 1))
    return out


def _split_by_recog(comp, maxw, k, S):
    """慢速路径：把 `comp` 切成 **k 段**，让「每段与正文层模板的最小 L1 距离之和」最小。

    ⚠️ 段数 k 沿用快路径的结果 —— 只修**切在哪**，不修**切几段**。
    这样即使误入这条路径（比如某条连音线被切出认不出的碎片），也绝不会凭空多出音符。
    每段都必须认得出（`d ≤ ACCEPT`）才承认这个方案，否则返回 None 退回快路径。
    """
    x0, x1 = comp["x0"], comp["x1"] + 1
    span = x1 - x0
    wmin = max(3, int(3 * S))
    wmax = max(wmin + 1, int(1.8 * maxw))
    cols = collections.defaultdict(list)
    for p in comp["pts"]:
        cols[p[0]].append(p)

    INF = float("inf")
    memo = {}

    def seg(a, b):                                     # 相对下标，区间 [a, b)
        key = (a, b)
        if key in memo:
            return memo[key]
        if b - a < wmin or b - a > wmax:
            memo[key] = INF
            return memo[key]
        pts = []
        for x in range(x0 + a, x0 + b):
            pts.extend(cols.get(x, ()))
        if not pts:
            memo[key] = INF
            return memo[key]
        c = _mkcomp(pts)
        if c["h"] < GLYPH_HF * S or c["area"] < GLYPH_AF * S * S:
            memo[key] = INF
            return memo[key]
        d = match_glyph(norm_cover(c))[1]
        memo[key] = d if d <= ACCEPT else INF
        return memo[key]

    f = [[INF] * (k + 1) for _ in range(span + 1)]
    back = [[0] * (k + 1) for _ in range(span + 1)]
    f[0][0] = 0.0
    for j in range(1, k + 1):
        for b in range(1, span + 1):
            best = INF
            for a in range(0, b):
                if f[a][j - 1] == INF:
                    continue
                d = seg(a, b)
                if f[a][j - 1] + d < best:
                    best, back[b][j] = f[a][j - 1] + d, a
            f[b][j] = best
    if f[span][k] == INF:
        return None
    out, b, j = [], span, k
    while j:
        a = back[b][j]
        pts = []
        for x in range(x0 + a, x0 + b):
            pts.extend(cols.get(x, ()))
        out.append(_mkcomp(pts))
        b, j = a, j - 1
    out.reverse()
    return out


def _mkcomp(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    a, b, c, d = min(xs), max(xs), min(ys), max(ys)
    return {"x0": a, "x1": b, "y0": c, "y1": d, "w": b - a + 1, "h": d - c + 1,
            "area": len(pts), "cx": (a + b) // 2, "cy": (c + d) // 2,
            "dark": 0.0, "pts": pts}


def _dot_like_edge(comp, med_h, S):
    """字形顶部/底部多出来的那几行，是否只有一颗点的尺寸。

    低音点印在数字正下方、距下一行数字只有 2~4px，会与下面的数字粘成
    **一个**连通域（One Last Kiss 实测：`(6, 4, 1,)` 的 `4,` 低音点粘进
    下方 `1` 的顶部，`1` 被撑到 h22）。粘完仍认得出 `1`（dist 21 vs
    干净 8）→ dist 守卫会放过它，点就此消失，和弦悄悄变成 `(6, 4 1,)`，
    直到连音线校验才炸。这里只回答「顶/底像不像粘了颗点」，真拆分交给
    `_vsplit_marks`（任何一段认不出就整组放弃，安全）。
    """
    byy = collections.defaultdict(list)
    for x, y in comp["pts"]:
        byy[y].append(x)
    maxk = min(comp["h"] - med_h, int(DOT_H * S))
    for k in range(2, maxk + 1):
        for band_y0 in (comp["y0"], comp["y1"] + 1 - k):
            xs_all, area = [], 0
            for y in range(band_y0, band_y0 + k):
                row = byy.get(y)
                if row:
                    xs_all.extend(row)
                    area += len(row)
            if not area:
                continue
            w = max(xs_all) - min(xs_all) + 1
            if w <= 1.6 * DOT_W * S and 6 * S * S <= area <= 2 * DOT_A * S * S \
                    and area >= 0.4 * w * k:
                return True
    return False


def _vsplit_marks(comp, med_h, S):
    """竖直方向分段：把「点+数字+点+数字…」竖着粘成一串的连通域拆开。

    One Last Kiss 实测：低音点印在数字正下方、距下一行数字只有 2~4px，
    阈值化后常与下面的数字粘成一个连通域（h 被撑到 21~30，正常 18）——
    bbox 归一后字形变形，`4` 被认成 `1`，甚至整颗变成 junk 从小节里消失。
    只在「整块明显偏高」时启用：从上往下找**数字高度的窗口**逐段认字，
    认不出数字的高度段若只有点的尺寸就当作点还回去，其余丢弃。
    返回 [(kind, comp)]，kind ∈ {"glyph", "dot"}；拆不动返回 None。
    """
    pts = comp["pts"]
    y0, y1 = comp["y0"], comp["y1"]
    if y1 - y0 + 1 <= int(1.15 * med_h):
        return None
    byy = collections.defaultdict(list)
    for x, y in pts:
        byy[y].append(x)
    out = []
    seg_lo = y0                                # 当前未处理段的起点
    while y1 - seg_lo + 1 >= int(0.85 * med_h):
        best = None                            # (d, a, b, lab)
        for a in range(seg_lo, seg_lo + int(0.6 * med_h) + 1):
            for n in range(int(0.85 * med_h), int(1.08 * med_h) + 1):
                b = a + n                       # 窗口 [a, b)
                if b > y1 + 1:
                    break
                win = [(x, y) for y in range(a, b) for x in byy.get(y, ())]
                if len(win) < 0.45 * n * (comp["w"] * 0.5):
                    continue
                c = _mkcomp(win)
                # ⚠️ 必须 ±1px 平移匹配：叠印在数字顶上的高音点会占掉数字顶部
                # 一行（净体 17 行 vs 干净 18 行），归一化后错半格，
                # 不平移的 match_glyph 距离暴涨 45~50 直接全灭（One Last Kiss 实测）。
                d, lab = match_glyph_shift(norm_cover(c))
                if d <= 0.75 * ACCEPT and (best is None or d < best[0]):
                    best = (d, a, b, lab)
        if best is None:
            break
        d, a, b, lab = best
        win = [(x, y) for y in range(a, b) for x in byy.get(y, ())]
        cc = _mkcomp(win)
        cc["dark"] = comp["dark"]
        out.append(("glyph", cc))
        if a > seg_lo:
            top = _mkcomp([(x, y) for y in range(seg_lo, a) for x in byy.get(y, ())])
            if top["pts"] and top["h"] <= DOT_H * S and top["w"] <= 1.6 * DOT_W * S \
                    and 6 * S * S <= top["area"] <= 2 * DOT_A * S * S \
                    and top["area"] >= 0.3 * top["w"] * top["h"]:
                out.append(("dot", top))
        seg_lo = b
    if not out:
        return None
    # 剩余尾段若只有点的尺寸也还回去
    if seg_lo <= y1:
        tail = _mkcomp([(x, y) for y in range(seg_lo, y1 + 1)
                        for x in byy.get(y, ())])
        if tail["pts"] and tail["h"] <= DOT_H * S and tail["w"] <= 1.6 * DOT_W * S \
                and 6 * S * S <= tail["area"] <= 2 * DOT_A * S * S \
                and tail["area"] >= 0.3 * tail["w"] * tail["h"]:
            out.append(("dot", tail))
    return out


# ---------------------------------------------------------------------------
# 版面
# ---------------------------------------------------------------------------
def _median(v):
    v = sorted(v)
    return v[len(v) // 2] if v else None


def merge_runs(vals, gap):
    out = []
    for a, b in sorted(vals):
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [tuple(r) for r in out]


def estimate_med_h(comps):
    """数字行高 = 连通域高度的**众数**。

    数字是页面上数量最多的等高元素（本例 1779 个 h≈21），标题字/小节线/花括号
    都远少于它 → 众数比中位数稳。峰值 ±2 内再取中位，吸收抗锯齿抖动。
    """
    cnt = collections.Counter(c["h"] for c in comps
                              if c["w"] >= 6 and c["h"] >= 10 and c["area"] >= 40)
    if not cnt:
        return None
    peak = max(cnt, key=lambda h: (cnt[h], -h))
    band = sorted(h for h in cnt if abs(h - peak) <= 2 for _ in range(cnt[h]))
    return band[len(band) // 2]


def find_systems(vbars, S):
    """系统 y 区间 = 小节线的纵向连续段。

    小节线只在一个系统内部连续，系统之间必然断开 → 无阈值、无歧义。
    （行剖面法会被左侧花括号和段落号污染，把整页粘成一片。）
    """
    runs = merge_runs([(c["y0"], c["y1"]) for c in vbars], gap=20 * S)
    out = []
    for a, b in runs:
        if b - a + 1 < 60 * S:
            continue
        if sum(1 for c in vbars if c["y0"] <= b and c["y1"] >= a) >= 2:
            out.append((a, b))
    return out


def bar_columns(vbars, sy0, sy1, S):
    """该系统内小节线的 x 位置；**双竖线（末小节）必须并成一列**，否则会凭空多出一个小节。"""
    xs = [c["cx"] for c in vbars
          if c["y1"] >= sy0 + 4 * S and c["y0"] <= sy1 - 4 * S]
    return [round((a + b) / 2) for a, b in merge_runs([(x, x) for x in xs], BAR_TOL * S)]


# ---------------------------------------------------------------------------
# 一页
# ---------------------------------------------------------------------------
class Page:
    def __init__(self, sh, quiet=False):
        self.sh, self.quiet = sh, quiet
        self.logbuf = []          # 日志行缓存：静默分析时也留一份，之后可补印
        t0 = time.time()
        comps = sh.components()
        med_h = estimate_med_h(comps)
        if not med_h:
            raise SystemExit(f"{sh.path}: 找不到任何字形 —— 图反色了？还是空白？")
        self.med_h = med_h
        self.S = S = med_h / REF_H

        items = []
        for c in comps:
            items.extend(split_wide(c, SPLIT_W * S, med_h=med_h, S=S))
        # 切分碎片是 _mkcomp 造的，dark 是占位 0.0 —— 而浅灰接音、灰和弦的判定
        # 全靠 dark（One Last Kiss 实测：灰 `6` 与黑 `6` 只差 1px 粘连被切开，
        # 灰色判定失效 → 跨小节连音线 `~` 丢失）。用原图重新算一遍。
        buf, W = sh.buf, sh.W
        for c in items:
            if c["dark"] == 0.0 and c["pts"]:
                c["dark"] = round(sum(buf[py * W + px] for px, py in c["pts"])
                                  / len(c["pts"]), 1)
        for c in items:
            c["page"] = sh.page
            c["kind"], c["label"], c["dist"] = classify(c, med_h, S)
        # 「数字竖着粘了小记号」第二次机会：低音点印在数字正下方、距下一行数字
        # 只有 2~4px，阈值化后常粘成一个连通域（h 被撑到 21~30，正常 18）——
        # bbox 归一后字形变形（`4` 被认成 `1`），甚至整颗变 junk 从小节里消失。
        # 垂直分段：逐段认出数字，点尺寸的碎片当作点还回去。
        n_trim = n_dot = 0
        for i, c in enumerate(items):
            if c["kind"] not in ("glyph", "junk", "arc"):
                continue
            if c["h"] <= 1.15 * med_h:
                continue
            # ⚠️ 触发线不能降到 1.05×：h19~20 的组件进拆分通道会扰动静默
            # probe 遍的字形分布 → 细体字模自校准学偏 → 段落号整批识别退化
            # （Cry For Me 实测 29 → 23 个；A/B 二分钉死）。灰 `3`+粘点那类
            # h20 的丢失改由产物级定点修复兜底。
            if c["kind"] == "glyph" and (c["dist"] is None
                                         or c["dist"] <= 0.55 * ACCEPT) \
                    and not _dot_like_edge(c, med_h, S):
                # 认得很干净的字形不拆 —— 除非它顶/底多出来的几行只有点的
                # 尺寸（低音点粘进相邻数字，见 _dot_like_edge 注释）。
                continue
            parts = _vsplit_marks(c, med_h, S)
            if not parts:
                continue
            digs = [cc for kind, cc in parts if kind == "glyph"]
            dots = [cc for kind, cc in parts if kind == "dot"]
            for cc in digs + dots:
                cc["page"] = sh.page
                cc["dark"] = round(sum(buf[py * W + px] for px, py in cc["pts"])
                                   / len(cc["pts"]), 1)
            # 复认拆出的数字：±1px 平移匹配；任何一段超 ACCEPT 就整组放弃
            # （拆错比不拆更糟），保持原组件走 junk/arc 的后续救援通道。
            digs_ok = []
            for cc in digs:
                d, lab = match_glyph_shift(norm_cover(cc))
                if d > ACCEPT:
                    digs_ok = None
                    break
                digs_ok.append((cc, lab, d))
            if digs_ok is None:
                continue
            # 原本就认得出的字形，只有拆完**明显更干净**才采纳：
            # 干净的高字（如 `1`）底部 4 行是 2~3px 的细竖笔画，尺寸上就是
            # 一颗点 —— 会被 _dot_like_edge 放进拆分通道，但拆完 dist 不会
            # 变好；不设这道闸会把假点拆出来（One Last Kiss 实测）。
            if c["kind"] == "glyph" and c["dist"] is not None:
                if max(d for _, _, d in digs_ok) >= c["dist"] - 3:
                    continue
            for cc, lab, d in digs_ok:
                cc["kind"], cc["label"], cc["dist"] = "glyph", lab, d
            for cc in dots:
                cc["kind"], cc["label"], cc["dist"] = "dot", None, None
            n_dot += len(dots)
            items[i] = digs[0]
            items.extend(digs[1:])
            items.extend(dots)
            n_trim += 1
        if n_trim:
            self.log(f"  竖粘记号拆分：{n_trim} 个，拆出/找回粘连的点 {n_dot} 个")
        # 「裂字重聚」：一个数字被 1px 竖向白痕（扫描伪影）劈成两半时，两半都是
        # 窄条、各自像 `1`（One Last Kiss 实测 `0`/`5` 在 x≈878 处被劈开，各半
        # 以 dist 39~50 认成 `1`）。同排、缝隙 ≤ 2S、合成宽 ≈ 一个字宽的相邻
        # glyph 对 → 合并后用 ±1px 平移匹配重认。
        # ⚠️ med_w 只统计正文字高的字形：items 里混着小节号等小字号数字，
        # 会把中位宽度拉低、卡死合并守卫
        med_w = _median([c["w"] for c in items if c["kind"] == "glyph"
                         and 0.8 * med_h <= c["h"] <= 1.3 * med_h]) or med_h
        n_re = 0
        merged_ids = set()
        gs = sorted((c for c in items if c["kind"] == "glyph"),
                    key=lambda c: c["cy"])
        row = [gs[0]] if gs else []
        rows_out = []
        for c in gs[1:]:
            if c["cy"] - row[-1]["cy"] <= 3 * S:
                row.append(c)
            else:
                rows_out.append(row)
                row = [c]
        if row:
            rows_out.append(row)
        for band in rows_out:
            band = sorted(band, key=lambda c: c["x0"])
            for a, b in zip(band, band[1:]):
                if id(a) in merged_ids or id(b) in merged_ids:
                    continue
                # 与左右顺序无关：两半在 x 上几乎重叠或仅隔 ≤2S
                lo, hi = min(a["x0"], b["x0"]), max(a["x1"], b["x1"])
                gap = max(a["x0"], b["x0"]) - min(a["x1"], b["x1"])
                if 0 <= gap <= 2 * S and a["h"] >= 0.7 * med_h \
                        and b["h"] >= 0.7 * med_h \
                        and hi - lo + 1 <= 1.35 * med_w:
                    m = _mkcomp(sorted(a["pts"] + b["pts"]))
                    m["page"], m["dark"] = a["page"], min(a["dark"], b["dark"])
                    d, lab = match_glyph_shift(norm_cover(m))
                    # 白痕挖掉一列墨会使距离略涨，放宽到 ACCEPT+10
                    # （几何守卫已保证合并体就是一个数字的宽度）
                    if d <= ACCEPT + 10:
                        m["kind"], m["label"], m["dist"] = "glyph", lab, d
                        items[items.index(a)] = m
                        items.remove(b)
                        merged_ids.update((id(a), id(b), id(m)))
                        n_re += 1
        if n_re:
            self.log(f"  裂字重聚：{n_re} 对（竖向白痕劈开的数字合并重认）")
        # 「黑字贴线救援」：正文层黑字里有一小撮 dist 卡在 ACCEPT 线上 0~3
        # （One Last Kiss 实测 65.4 / 66.4 / 68.0，几何完全正常：h=17~18、
        # area≈115~120），整颗丢掉导致小节少音。用 ±1px 平移匹配复认——
        # 平移往往能把贴线距离拉回阈值内；仍超限的真垃圾（实测 ≥80）进不来。
        n_blk = 0
        for c in items:
            if c["kind"] not in ("junk", "arc") or c["dist"] is None:
                continue
            if c["dark"] > sh.paper * GRAY_F or not _digitish(c, med_h):
                continue
            d, lab = match_glyph_shift(norm_cover(c))
            if d <= ACCEPT:
                c["kind"], c["label"], c["dist"] = "glyph", lab, d
                n_blk += 1
        if n_blk:
            self.log(f"  黑字贴线救援：{n_blk} 个（±1px 平移复认）")
        # 「数字顶上粘了连音弧」的旧裁剪逻辑已被上面的竖直分段 _vsplit_marks
        # 覆盖：弧端搭在数字肩上撑高 bbox 的情况会走同一分支，数字窗口逐段认出、
        # 剩余碎片按点尺寸判定或丢弃。
        # 「浅灰接音」第二次机会：谱上把「接音」（前一个音的延长）印得比黑字**浅**，
        # 二值化后笔画天生细一圈，同一字形的 L1 距会比黑字高 10~25（实测同一个 `3`：
        # 黑字 ≈40，浅灰 ≈65）。给浅灰一点额外宽容，黑字不给 —— 灰度的逐字节参照链路上
        # 黑字最大 59（离阈值还有 6），浅灰垃圾最小 72（差 7 才到），这条缝正好卡得住。
        n_gray = 0
        for c in items:
            if c["kind"] not in ("junk", "arc") or c["dist"] is None:
                continue
            if c["dark"] <= sh.paper * GRAY_F or not _digitish(c, med_h):
                continue
            lab, d = match_glyph(norm_cover(c))
            if d <= ACCEPT + GRAY_SLACK:
                c["kind"], c["label"], c["dist"] = "glyph", lab, d
                n_gray += 1
        if n_gray:
            self.log(f"  浅灰接音第二次机会：{n_gray} 个（宽容 +{GRAY_SLACK:g} 距离）")
        self.items = items
        kind_n = collections.Counter(c["kind"] for c in items)
        self.log(f"  连通域 {len(comps)} → 切开后 {len(items)}；"
                 f"字高 {med_h}px → 尺度 S={S:.3f}")
        self.log("  类别：" + " ".join(f"{k}={v}" for k, v in kind_n.most_common()))
        unk = [c for c in items if c["kind"] in ("arc", "junk")
               and c["area"] >= 12 * S * S and c["h"] >= 8 * S]
        if unk:
            self.log(f"  未归因组件 {len(unk)} 个（连音弧/噪声；最小面积 "
                     f"{min(c['area'] for c in unk)}，最大 {max(c['area'] for c in unk)}）")

        vb = [c for c in items if c["kind"] == "vbar"]
        self.spans = find_systems(vb, S)
        self.n_sys = len(self.spans)
        self.log(f"  小节线 {len(vb)} 段 → 系统 {len(self.spans)} 个")
        for i, (a, b) in enumerate(self.spans, 1):
            cols = bar_columns(vb, a, b, S)
            self.log(f"    第{i}系统 y{a}-{b}  小节线 x={cols} → {max(0, len(cols) - 1)} 小节")

        self.bars = []                       # [(sys, bar)]
        self.box = {}                        # (sys, bar, staff) → {dig, line}
        self.dots = {}                       # (sys, bar) → [dot]
        self.meters = {}                     # (sys, bar) → 该小节拍数（变拍号）
        self.strays = []                     # 落在系统外沿、没进任何小节的组件
        self.rowcy, self.rowy1 = {}, {}
        self._layout(vb)
        self.sections = read_sections(self, self.log)
        self.log(f"  版面用时 {time.time() - t0:.1f}s")

    def log(self, msg):
        self.logbuf.append(msg)
        if not self.quiet:
            print(msg, flush=True)

    def _layout(self, vb):
        S = self.S
        for si, (sy0, sy1) in enumerate(self.spans, 1):
            cols = bar_columns(vb, sy0, sy1, S)
            for k in range(len(cols) - 1):
                self.bars.append((si, k + 1))
            inner_of = {}
            for k in range(len(cols) - 1):
                xa, xb, bar = cols[k], cols[k + 1], k + 1
                inner_of[bar] = [c for c in self.items
                                 if c["kind"] not in ("vbar", "brace")
                                 and xa + BAR_PAD * S <= c["cx"] <= xb - BAR_PAD * S
                                 and sy0 - 3 * S <= c["cy"] <= sy1 + 3 * S]
            # ⚠️ 变拍号必须**先于**双手分界与入盒识别：它由「上下两个小号数字 +
            #    中间一条分数线」构成，不先剔掉就会 (a) 被当成伪和弦 `(4 4)`、
            #    (b) 分数线被当成伪增时线 `-`，一小节凭空多 2 拍（实测《起风了》
            #    4 个变拍号全部中招，mel/bas 各一份 → 8 个小节报错）。
            for bar, inner in inner_of.items():
                for got in self._detect_meter(inner):
                    self.meters[(si, bar)] = got
            # ⚠️ 两只手的分界**必须按整个系统算，不能按小节**。
            # 夹在两行正中的音（每个谱表上方的第二声部）离两边只差 1~2px，
            # 单小节里数字太少，「最大间隙」在 38/40 这种近似平局上会翻边：
            # 实测 p3s6b1 按小节得 cys {1227×8,1265×1,1305×8} → 间隙 38<40 → 判给旋律；
            # 按整系统聚合后变成 {1227×24,1272×4,1305×34} → 间隙 46>32 → 判给低音（与谱面一致）。
            bound = self._staff_bound([c for inner in inner_of.values()
                                       for c in inner if c["kind"] == "glyph"])
            for bar, inner in inner_of.items():
                self.dots[(si, bar)] = [c for c in inner if c["kind"] == "dot"]
                digs = [c for c in inner if c["kind"] == "glyph"]
                for c in digs:
                    c["staff"] = "mel" if c["cy"] < bound else "bas"
                # 非数字元素不能按自身的 cy 或 x 硬切：旋律的增时线正下方可能就是
                # 低音的数字；第二条减时线会卡在分界下沿。每只手的「数字行」有 cy 与
                # y1 两个刻度 —— 增时线贴在 cy 上，减时线在 y1 下方约 12px，取更近者。
                row = {}
                for st in ("mel", "bas"):
                    ds = [d for d in digs if d["staff"] == st]
                    if ds:
                        row[st] = (_median([d["cy"] for d in ds]),
                                   _median([d["y1"] for d in ds]))
                for c in inner:
                    if c["kind"] == "glyph":
                        continue
                    best, bs = None, 1e18
                    for st, (rcy, ry1) in row.items():
                        s = min(abs(c["cy"] - rcy), abs(c["y0"] - ry1 - 12 * S))
                        if s < bs:
                            bs, best = s, st
                    c["staff"] = best or ("mel" if c["cy"] < bound else "bas")
                for c in inner:
                    c.setdefault("staff", "mel" if c["cy"] < bound else "bas")
                    c["sys"], c["bar"] = si, bar
                    if c["kind"] == "glyph" or c["kind"] == "hline":
                        slot = self.box.setdefault(
                            (si, bar, c["staff"]), {"dig": [], "line": []})
                        slot["dig" if c["kind"] == "glyph" else "line"].append(c)
            # 主行按「整系统·声部」统计（不能按小节：琶音和弦会把 cy 中位拉偏 44px）
            for st in ("mel", "bas"):
                allg = [c for (s, b, t), v in self.box.items() if s == si and t == st
                        for c in v["dig"]]
                self.rowcy[(si, st)], self.rowy1[(si, st)] = _main_row(allg, ROW_BAND * S)

    def _detect_meter(self, inner):
        """识别谱表内部的**变拍号**（如 `2/4`、`4/4`），返回识别出的拍数列表。

        版面特征（三个条件必须同时满足，缺一不可）：
          ① 上下两个**小号数字**（h ≤ 0.8×字高 —— 正文音符都是满高 1.0×，
             实测变拍号数字只有 0.61~0.67×，分界干净）；
          ② 两数字 x 投影重叠 ≥ 0.5×较窄者宽，垂直空隙 ≤ 1 字高（上下紧挨着堆叠）；
          ③ 两数字之间有一条**分数线**（hline，cy 夹在两者之间，与数字 x 重叠
             足够、宽度不超过数字的 2.5 倍 —— 排除恰好路过的减时线/增时线）。
        分子 = cy 较小者（上面的），拍数 = 分子 × 4 ÷ 分母（x/8 拍号也自动正确）。

        ⚠️ 命中后把两个数字改标 `tsig`、分数线改标 `tsigbar` —— 这些 kind 不会
        进 `box`（_layout 只收 glyph/hline），也不会参与双手分界统计，
        于是伪和弦与伪 `-` 从源头消失。
        ⚠️ 一份谱面通常把变拍号**上下谱表各印一份**，两份都会命中并写同一个
        (sys, bar) 键 —— 值相同，字典覆盖无害。
        """
        med_h = self.med_h
        found = []
        smalls = [c for c in inner if c["kind"] == "glyph"
                  and c["h"] <= 0.8 * med_h and str(c.get("label", "")).isdigit()]
        if len(smalls) < 2:
            return found
        hls = [c for c in inner if c["kind"] == "hline"]
        used = set()
        for i, A in enumerate(smalls):
            if id(A) in used:
                continue
            for B in smalls[i + 1:]:
                if id(B) in used or A["cy"] >= B["cy"]:
                    continue
                ox = min(A["x1"], B["x1"]) - max(A["x0"], B["x0"])
                if ox < 0.5 * min(A["w"], B["w"]):
                    continue
                if not 0 < B["y0"] - A["y1"] <= med_h:
                    continue
                ln = [L for L in hls
                      if A["y1"] <= L["cy"] <= B["y0"]
                      and min(L["x1"], max(A["x1"], B["x1"]))
                      - max(L["x0"], min(A["x0"], B["x0"]))
                      >= 0.6 * min(A["w"], B["w"])
                      and L["w"] <= 2.5 * max(A["w"], B["w"])]
                if not ln:
                    continue
                num, den = int(A["label"]), int(B["label"])
                if num <= 0 or den <= 0:
                    continue
                A["kind"] = B["kind"] = "tsig"
                ln[0]["kind"] = "tsigbar"
                used.update((id(A), id(B), id(ln[0])))
                found.append(num * 4.0 / den)
                break
        return found

    def _staff_bound(self, digs):
        """两只手的分界：数字 cy 一维聚类取最大间隙，**切线两侧各需 ≥6 个数字**。

        不加「两侧都要够多」这条，系统上方残留的段落号会抢走切线，
        把整条旋律判给低音手（实测过）。
        """
        S = self.S
        cys = sorted(d["cy"] for d in digs)
        if len(cys) < 12:
            return (cys[0] + cys[-1]) / 2 if cys else 0
        grp = [[cys[0]]]
        for c in cys[1:]:
            if c - grp[-1][-1] <= 12 * S:
                grp[-1].append(c)
            else:
                grp.append([c])
        cent = [sum(g) / len(g) for g in grp]
        best, gi = -1, None
        for i in range(len(cent) - 1):
            if sum(len(g) for g in grp[:i + 1]) < 6 or \
               sum(len(g) for g in grp[i + 1:]) < 6:
                continue
            if cent[i + 1] - cent[i] > best:
                best, gi = cent[i + 1] - cent[i], i
        if gi is None:
            gi = max(range(len(cent) - 1), key=lambda i: cent[i + 1] - cent[i])
        return (cent[gi] + cent[gi + 1]) / 2


def _main_row(digs, band):
    """数字行基线：先取 cy 的众数桶（和弦成员被自动排除），再在带内取中位。"""
    if not digs:
        return None, None
    hist = collections.Counter(d["cy"] // 3 for d in digs)
    peak = max(hist.items(), key=lambda kv: kv[1])[0] * 3
    grp = [d for d in digs if abs(d["cy"] - peak) <= band] or digs
    return _median([d["cy"] for d in grp]), _median([d["y1"] for d in grp])


# ---------------------------------------------------------------------------
# 转写
# ---------------------------------------------------------------------------
def _columns(digs, tol):
    digs = sorted(digs, key=lambda d: (d["x0"], d["cy"]))
    cols = []
    for d in digs:
        if cols and min(cols[-1]["x1"], d["x1"]) - max(cols[-1]["x0"], d["x0"]) >= tol:
            c = cols[-1]
            c["x0"], c["x1"] = min(c["x0"], d["x0"]), max(c["x1"], d["x1"])
            c["mem"].append(d)
        else:
            cols.append({"x0": d["x0"], "x1": d["x1"], "mem": [d]})
    return cols


def _row_bands(digs, med_h):
    """把一框数字按 cy 聚成「行」，行距 ≤ 1.8×字高 的相邻行再并成同一「块」。

    块 = 同一个声部内的多行排版（One Last Kiss：一行旋律 + 三行和弦分解，
    同一列的几个音**同时发声**、减时线共享受底一行）；两块之间是上下谱表的间隔。
    返回 [(cy, y0, y1, 块号)] 按 cy 升序。
    """
    if not digs:
        return []
    ds = sorted(digs, key=lambda d: d["cy"])
    groups = [[ds[0]]]
    for d in ds[1:]:
        if d["cy"] - groups[-1][-1]["cy"] > 0.45 * med_h:
            groups.append([d])
        else:
            groups[-1].append(d)
    rows = [(_median([d["cy"] for d in g]), min(d["y0"] for d in g),
             max(d["y1"] for d in g)) for g in groups]
    out, blk = [], 0
    for i, r in enumerate(rows):
        if i and r[0] - rows[i - 1][0] > 1.8 * med_h:
            blk += 1
        out.append((r[0], r[1], r[2], blk))
    return out


class Transcriber:
    def __init__(self, pages, log=None):
        self.pages = pages
        self.log = log or (lambda m: None)
        self._dotcache = {}
        # 拍数配平（单列变异）的结果：(pi, si, bar, st, col_x0) -> (nb, aug)
        self._fixes = {}

    # -- 点贴到最近的数字 ------------------------------------------------
    def dot_map(self, pi, si, bar):
        key = (pi, si, bar)
        if key in self._dotcache:
            return self._dotcache[key]
        pg = self.pages[pi]
        S = pg.S
        glyphs = [c for (s, b, t), v in pg.box.items() if s == si and b == bar
                  for c in v["dig"]]
        rows = _row_bands(glyphs, pg.med_h)
        out = {}
        for p in pg.dots.get((si, bar), []):
            cands = []
            for g in glyphs:
                dcx = abs(p["cx"] - g["cx"])
                if dcx <= 12 * S and p["cy"] < g["y0"] - 2 * S:
                    cands.append((g["y0"] - p["cy"], g, "U", dcx))
                elif dcx <= 12 * S and p["cy"] > g["y1"] + 2 * S:
                    cands.append((p["cy"] - g["y1"], g, "D", dcx))
                elif g["x1"] < p["cx"] <= g["x1"] + 8 * S and \
                        g["y0"] - 3 * S <= p["cy"] <= g["y1"] + 3 * S:
                    # 附点紧贴数字右缘（实测 gap 3~5px）；只限 x1 右 8S，
                    # 否则隔壁数字**上方**的高音点会落进窄数字（如 `1`）的 a 窗
                    cands.append((0.0, g, "a", dcx))
            if not cands:
                continue
            # 优先级：① 同行右侧（a，附点）——附点印在数字正右方同行，几乎不会错；
            # ② 正对（|Δcx| ≤ 6S）的八度点优先于斜对角数字的附点窗：
            #    低音点印在数字正下方，会同时落进更靠右数字的附点窗
            #    （实测 cx190 cy425 的点被 19px 外的 `1` 抢成附点，`4` 丢低音点）。
            #    ⚠️ 但上方**隔行**数字的正对候选不算：高音点叠印在数字头顶时，
            #    点与上面**隔一行**的数字 |Δcx| 可能 ≤ 6S，抢走后 dd 超限被丢
            #    （实测 cx1016 的附点被上一谱表行 mel 数字抢走，bas 丢 3 颗附点）。
            ac = [c for c in cands if c[2] == "a"]
            dead = [c for c in cands if c[3] <= 6 * S and c[2] in ("U", "D")]
            if ac:
                dd, g, t, _ = min(ac, key=lambda c: c[3])
            else:
                dd, g, t, _ = min(dead if dead else cands, key=lambda c: c[0])
            # 块内行间覆盖：同一块（多行和弦分解排版）两行之间的点，是**上一行**
            # 数字的低音点 —— 它印在数字正下方，距上一行 y1 只有 4~10px，
            # 「最近者胜」会错判给下一行当高音点（实测 `(6 4 1,)` 全成 `4'` `1'`）。
            # 上一行/下一行不同块（= 上下谱表间隔）时维持「最近者胜」不动，
            # 否则会抢走低音谱表自己的高音点（Cry For Me 的 `1'` 这类）。
            if t == "U" and len(rows) > 1:
                up = [r for r in rows if r[0] < p["cy"]]
                dn = [r for r in rows if r[0] > p["cy"]]
                if up and dn and up[-1][3] == dn[0][3]:
                    row = up[-1]
                    fix = [g2 for g2 in glyphs
                           if row[1] - 3 * S <= g2["cy"] <= row[2] + 3 * S
                           and abs(p["cx"] - g2["cx"]) <= 12 * S
                           and p["cy"] >= g2["y1"] - 1 * S
                           and p["cy"] - g2["y1"] <= DOT_MAX * S]
                    if fix:
                        g2 = min(fix, key=lambda g3: abs(p["cx"] - g3["cx"]))
                        g, dd, t = g2, p["cy"] - g2["y1"], "D"
            if t == "a" or dd <= DOT_MAX * S:
                out.setdefault(id(g), []).append(t)
        self._dotcache[key] = out
        return out

    def eval_bar(self, pi, si, bar, st):
        pg = self.pages[pi]
        S = pg.S
        slot = pg.box.get((si, bar, st)) or {"dig": [], "line": []}
        digs, lines = slot["dig"], slot["line"]
        if not digs and not lines:
            return 0.0, []
        rcy, ry1 = pg.rowcy.get((si, st)), pg.rowy1.get((si, st))
        rows = _row_bands(digs, pg.med_h)
        dash_cys = [rcy] if rcy is not None else []
        if len(rows) > 1:
            # 多行声部（One Last Kiss：三行和弦分解同列同响）：减时线**共享受底
            # 一行**，只贴在最下面一行的下方；增时线则每行各画一条（同 x 去重）。
            rcy, ry1 = rows[-1][0], rows[-1][2]
            dash_cys = [r[0] for r in rows]
        # ⚠️ 厚度过滤：真减时线只有 2~3px 厚；两行谱表之间的连音弧碎块
        # （One Last Kiss 实测 h≈9px）高度落在 beam 搜索窗内会被误认 —— 弧碎块排除。
        beams = [L for L in lines if ry1 is not None
                 and ry1 + 2 * S <= L["y0"] <= ry1 + 34 * S
                 and L["y1"] - L["y0"] + 1 <= 5 * S]
        # 同一条物理线被切成两段/碎片+合成双计会重复计数 nb —— 同高（|Δcy|≤2S）
        # 且横向重叠的 beam 合并保留更宽的一条。
        ded = []
        for B in sorted(beams, key=lambda b: b["w"]):
            if any(abs(B["cy"] - D["cy"]) <= 2 * S
                   and min(B["x1"], D["x1"]) - max(B["x0"], D["x0"]) >= 3 * S
                   for D in ded):
                continue
            ded.append(B)
        beams = ded
        # ⚠️ 弧尖粘连减时线：连音弧的端头搭上减时线会并成一个组件（arc/junk/
        # 超厚的 hline 都有可能），整条被上面的厚度过滤丢掉（One Last Kiss 实测
        # `0` 的第二条减时线与弧尖粘连 → 16 分误作 8 分，每小节凭空多 0.25 拍）。
        # 从组件**顶部/底部**抽「整宽横杠」（≥2 行且每行墨宽 ≥ 0.8×组件宽，
        # 总高 ≤ 4px）还原成减时线；弧体本身是曲线，顶/底行必然窄，不会误抽。
        if ry1 is not None and digs:
            bx_lo = min(d["x0"] for d in digs) - 20 * S
            bx_hi = max(d["x1"] for d in digs) + 20 * S
            for c in pg.items:
                if c["kind"] not in ("arc", "junk", "hline") \
                        or c["page"] != pg.sh.page \
                        or not (ry1 + 2 * S <= c["y0"] and c["y1"] <= ry1 + 34 * S) \
                        or c["x1"] < bx_lo or c["x0"] > bx_hi:
                    continue
                roww = {}
                for x, y in c["pts"]:
                    roww.setdefault(y, []).append(x)
                ys = sorted(roww)
                for edge in ("top", "bot"):
                    seq = ys if edge == "top" else ys[::-1]
                    k = 0
                    for y in seq:
                        if len(roww[y]) >= 0.8 * c["w"]:
                            k += 1
                        else:
                            break
                    if not (2 <= k <= 4 and len(seq) - k >= 2):
                        continue
                    rr = [x for y in seq[:k] for x in roww[y]]
                    run = {"x0": min(rr), "x1": max(rr),
                           "y0": min(seq[:k]), "y1": max(seq[:k]),
                           "cy": sum(seq[:k]) / k,
                           "w": max(rr) - min(rr) + 1}
                    # 去重：与已有 beam 同高（|Δcy| ≤ 2S）且横向重叠 → 跳过
                    if any(abs(B["cy"] - run["cy"]) <= 2 * S
                           and min(B["x1"], run["x1"]) - max(B["x0"], run["x0"])
                           >= 3 * S for B in beams):
                        continue
                    beams.append(run)
        dashes = [L for L in lines if dash_cys
                  and min(abs(L["cy"] - c) for c in dash_cys) <= 12 * S
                  and 8 * S <= L["w"] <= 45 * S
                  and L["y1"] - L["y0"] + 1 <= 5 * S]
        if len(rows) > 1:                     # 同一格的增时线每行各一条 → 只记一次
            dedup = []
            for L in sorted(dashes, key=lambda l: l["x0"]):
                if dedup and (min(dedup[-1]["x1"], L["x1"])
                              - max(dedup[-1]["x0"], L["x0"]) >= 3 * S):
                    dedup[-1] = {"x0": min(dedup[-1]["x0"], L["x0"]),
                                 "x1": max(dedup[-1]["x1"], L["x1"]),
                                 "cy": L["cy"], "w": L["w"], "y0": L["y0"],
                                 "y1": L["y1"]}
                else:
                    dedup.append(L)
            dashes = dedup
        dmap = self.dot_map(pi, si, bar)
        out = []
        for col in _columns(digs, 3 * S):
            nb = sum(1 for B in beams
                     if min(B["x1"], col["x1"]) - max(B["x0"], col["x0"]) >= 4 * S)
            aug = False
            gray = all(d["dark"] > pg.sh.paper * GRAY_F for d in col["mem"])
            per = {}
            for d in col["mem"]:
                ups = dns = False
                for t in dmap.get(id(d), []):
                    if t == "U":
                        ups = True
                    elif t == "D":
                        dns = True
                    else:
                        aug = True
                per[id(d)] = (ups, dns)
            toks = []
            # ⚠️ 和弦成员按 cy **自上而下**（= 高音在前）：交付版口径是 `(3 6,)`，
            # 不是 `(6, 3)`。y 越小越靠上、音越高。
            for d in sorted(col["mem"], key=lambda d: d["cy"]):
                t = d["label"]
                if per[id(d)][0]:
                    t += "'"
                if per[id(d)][1]:
                    t += ","
                toks.append(t)
            tok = toks[0] if len(toks) == 1 else "(" + " ".join(toks) + ")"
            nb_c = min(nb, 4)
            aug_f = self._fixes.get((pi, si, bar, st, col["x0"]))
            if aug_f is not None:
                nb_c, aug = aug_f
            # ⚠️ 减时线/附点的后缀**和弦也要写**：解析器只认 `)` 后面的 `/` 和 `.`，
            # 不写就把 `(6 1)/` 读成四分音符，每小节凭空多 0.5 拍。
            tok += BEAMSTR[nb_c]
            if aug:
                tok += "."
            dur = (1.0 / (2 ** nb_c)) * (1.5 if aug else 1.0)
            out.append((col["x0"], ("~" if gray else "") + tok, dur))
        for L in dashes:
            out.append((L["x0"], "-", 1.0))
        out.sort(key=lambda t: t[0])
        return sum(t[2] for t in out), out

    def _unattributed_dots(self, pi, si, bar):
        """复刻 dot_map 的判定，返回没能归属到任何数字的点（孤儿点）。"""
        pg = self.pages[pi]
        S = pg.S
        glyphs = [c for (s, b, t), v in pg.box.items() if s == si and b == bar
                  for c in v["dig"]]
        out = []
        for p in pg.dots.get((si, bar), []):
            cands = []
            for g in glyphs:
                dcx = abs(p["cx"] - g["cx"])
                if dcx <= 12 * S and p["cy"] < g["y0"] - 2 * S:
                    cands.append((g["y0"] - p["cy"], g, "U", dcx))
                elif dcx <= 12 * S and p["cy"] > g["y1"] + 2 * S:
                    cands.append((p["cy"] - g["y1"], g, "D", dcx))
                elif g["x1"] < p["cx"] <= g["x1"] + 8 * S and \
                        g["y0"] - 3 * S <= p["cy"] <= g["y1"] + 3 * S:
                    cands.append((0.0, g, "a", dcx))
            if not cands:
                out.append(p)
                continue
            ac = [c for c in cands if c[2] == "a"]
            dead = [c for c in cands if c[3] <= 6 * S and c[2] in ("U", "D")]
            dd, g, t, _ = (min(ac, key=lambda c: c[3]) if ac else
                           min(dead if dead else cands, key=lambda c: c[0]))
            if t != "a" and dd > DOT_MAX * S:
                out.append(p)
        return out

    def run(self, beats=4.0):
        t0 = time.time()
        pages = self.pages
        repairs = []
        keys = sorted({(pi, si, bar) for pi, pg in enumerate(pages) for (si, bar) in pg.bars})
        for pi, si, bar in keys:
            pg = pages[pi]
            # ⚠️ 变拍号小节（如 2/4 插段）按版面识别的期望拍数配平，缺省才是全曲拍号
            exp = pg.meters.get((si, bar), beats)
            for _ in range(3):
                tm, _ = self.eval_bar(pi, si, bar, "mel")
                tb, _ = self.eval_bar(pi, si, bar, "bas")
                if abs(tm - exp) <= 1e-6 and abs(tb - exp) <= 1e-6:
                    break
                cands = []
                for st in ("mel", "bas"):
                    rc = pg.rowcy.get((si, st))
                    if rc is None:
                        continue
                    for d in pg.box.get((si, bar, st), {}).get("dig", []):
                        if abs(d["cy"] - rc) > GAP_MIN * pg.S:
                            cands.append((st, d))
                hit = None
                for st, d in cands:
                    other = "bas" if st == "mel" else "mel"
                    pg.box[(si, bar, st)]["dig"].remove(d)
                    pg.box.setdefault((si, bar, other),
                                      {"dig": [], "line": []})["dig"].append(d)
                    self._dotcache.pop((pi, si, bar), None)
                    nm, _ = self.eval_bar(pi, si, bar, "mel")
                    nb_, _ = self.eval_bar(pi, si, bar, "bas")
                    if abs(nm - exp) + abs(nb_ - exp) < \
                       abs(tm - exp) + abs(tb - exp):
                        hit = (st, other, d, tm, tb, nm, nb_)
                        break
                    pg.box[(si, bar, st)]["dig"].append(d)
                    pg.box[(si, bar, other)]["dig"].remove(d)
                    self._dotcache.pop((pi, si, bar), None)
                if hit is None:
                    break
                st, other, d, tm, tb, nm, nb_ = hit
                d["staff"] = other
                repairs.append((pg.sh.page, si, bar, d["label"], d["cy"],
                                st, other, tm, tb, nm, nb_))
        # 拍数配平（单列变异）：声部归属修复后仍不齐的小节，逐列尝试三种变异
        # —— ±1 条减时线 / 增删附点。除算术唯一解外还要求**物理证据**：
        # · 减时线 -1（时值变长）：该列下方有厚粘连组件（5S<h≤10S 的 hline/arc/junk，
        #   = 减时线和弧/相邻组件粘连后被厚度过滤剔除的尸体）；
        # · 附点 +（时值变长）：该列附近有未归属的孤儿点；
        # 依据：印刷谱每小节拍数必须严格等于拍号，而粘连吞线正是本谱实测最主要的
        # 残余误差来源。仍有多解就不动，留给人工。
        n_fix = 0
        for pi, si, bar in keys:
            pg = pages[pi]
            exp = pg.meters.get((si, bar), beats)
            for st in ("mel", "bas"):
                tm, out = self.eval_bar(pi, si, bar, st)
                if abs(tm - exp) <= 1e-6 or not out:
                    continue
                slot = pg.box.get((si, bar, st)) or {"dig": [], "line": []}
                rows = _row_bands(slot["dig"], pg.med_h)
                S = pg.S
                multi = len(rows) > 1
                if multi:
                    thick = orphan = None      # 多行声部不做物理过滤
                else:
                    ry1 = pg.rowy1.get((si, st))
                    thick = [c for c in pg.items
                             if c["page"] == pg.sh.page
                             and c["kind"] in ("hline", "arc", "junk")
                             and 5 * S < c["h"] <= 10 * S
                             and ry1 is not None
                             and ry1 + 2 * S <= c["y0"] <= ry1 + 38 * S]
                    orphan = self._unattributed_dots(pi, si, bar)
                cands = []
                for x, tok, dur in out:
                    base = tok.lstrip("~")
                    if base.startswith("("):
                        continue          # 和弦列变异自由度太大，歧义高，不动
                    aug = base.endswith(".")
                    core = base[:-1] if aug else base
                    nb = len(core) - len(core.rstrip("/"))
                    win_lo, win_hi = x - 4 * S, x + 22 * S
                    has_thick = thick is not None and any(
                        min(c["x1"], win_hi) - max(c["x0"], win_lo) >= 3 * S
                        for c in thick)
                    has_orphan = orphan is not None and any(
                        win_lo <= p["cx"] <= win_hi for p in orphan)
                    opts = []
                    if nb > 0 and (multi or has_thick):
                        opts.append((nb - 1, aug, dur * 2))
                    if not aug and (multi or has_orphan):
                        opts.append((nb, True, dur * 1.5))
                    # 加一条减时线：该列下方必须有厚粘连尸体（被吞的线）
                    if nb < 4 and (multi or has_thick):
                        opts.append((nb + 1, aug, dur / 2))
                    # 去附点：只在该列的附点证据可疑（灰点 = 隔壁数字的高音点
                    # 误挂）时才允许；黑附点是真的，不许动。
                    if aug:
                        ok = multi
                        if not ok:
                            dg = next((d for d in slot["dig"] if d["x0"] == x),
                                      None)
                            if dg is not None:
                                adot = [p for p in pg.dots.get((si, bar), [])
                                        if dg["x1"] < p["cx"] <= dg["x1"] + 8 * S
                                        and dg["y0"] - 3 * S <= p["cy"]
                                        <= dg["y1"] + 3 * S]
                                ok = any(p["dark"] > 120 for p in adot)
                        if ok:
                            opts.append((nb, False, dur / 1.5))
                    for nb2, aug2, d2 in opts:
                        if abs(tm - dur + d2 - exp) <= 1e-6:
                            cands.append((st, x, nb2, aug2))
                if len(cands) == 1:
                    st, x, nb2, aug2 = cands[0]
                    self._fixes[(pi, si, bar, st, x)] = (nb2, aug2)
                    n_fix += 1
                    self.log(f"  ⚠ 拍数配平 p{pi+1} s{si+1} b{bar} {st} "
                             f"x{x}: {nb2} 线{'带附点' if aug2 else ''}")
        if n_fix:
            self.log(f"  拍数配平：修复 {n_fix} 列（物理证据 + 唯一解才采纳）")
        rows = {}
        for pi, pg in enumerate(pages):
            for (si, bar) in pg.bars:
                for st in ("mel", "bas"):
                    _, out = self.eval_bar(pi, si, bar, st)
                    rows.setdefault((pi, si, st), {})[bar] = out
        self.log(f"  转写用时 {time.time() - t0:.1f}s")
        return rows, repairs


# ---------------------------------------------------------------------------
# 段落号 / 页眉
# ---------------------------------------------------------------------------
def region_glyphs(pg, band, tl=None):
    """把某个区域（小节号区 / 页眉区）的组件**用细体层重认**一遍。

    正文数字面积下限是 60（REF 单位），而小节号 `(13)`、页眉 `1=C` 用的是**更细的小字**：
    `(` / `)` 面积只有 57~63，`(` 会被整颗当噪声丢掉 → 只认出 `(1` 认不出 `)`。
    这里对**谱表外**的小区域统一放宽面积下限、并换用细体模板表；
    正文转写仍走正文层，不会把细体模板放进音符里。
    ⚠️ 必须**全部重认**（连已经判成 glyph 的也要重判）：正文层会把细体 `0` 认成 `9`、
    细体 `3` 认成 `8`（距离都低于接受阈值，是「认得出但认错」）。
    """
    tl = small_templates() if tl is None else tl
    out = []
    for c in band:
        if c["kind"] in ("vbar", "brace"):
            continue
        k, lab, d = classify(c, pg.med_h, pg.S, glyph_af=SMALL_AF, tl=tl)
        if k == "glyph":
            out.append({**c, "kind": "glyph", "label": lab, "dist": d})
    return out


def _anchor(comps, pg, tl, want, after=-1):
    """带内最像 `want` 的那个组件下标（按 cx 升序、且认出距离 ≤ 阈值）。"""
    best, bi = None, None
    for i, c in enumerate(comps):
        if i <= after:
            continue
        k, lab, d = classify(c, pg.med_h, pg.S, glyph_af=SMALL_AF, tl=tl)
        if k == "glyph" and lab == want and (best is None or d < best):
            best, bi = d, i
    return bi


def section_slots(pg, band, tl):
    """在「小节号带」里定位一对 `(` … `)`，返回它们**之间**的全部组件（按 x 升序）。

    ⚠️ 两条都不能用（都被实拍反例砸过）：
    · 「带内组件数 == 期望串长」—— 跨系统的连音线尾弧会伸进谱表左上角，实测
      第 1 页 s2/s3 的带里各多出 1 段横线 + 1 段弧，组件数一多整条就作废；
    · 「数字本身要认得出」—— 自校准的**目的**正是学出正文层没有的 8/9，
      它们在打标阶段本来就认不出（实测 `9` 的 L1 距 68.8 > 阈值 65）。
    所以只认 `(` `)` 当锚点（这两个符号在正文层里根本没有，不会被音符抢走），
    中间的一切按位置取。
    """
    comps = sorted(band, key=lambda c: c["cx"])
    iL = _anchor(comps, pg, tl, "(")
    if iL is None:
        return None
    iR = _anchor(comps, pg, tl, ")", after=iL)
    if iR is None or iR <= iL + 1:
        return None
    return comps[iL + 1:iR]


def read_sections(pg, log):
    """系统上方左端的 `(N)`。段落号印在**谱表上方**，不在系统内部。

    如果自校准已经验证过「本谱 `(N)` = 小节号」（见 `calibrate` 的版面假设检验），
    就用版面推值当准绳：识别值与它不符时以版面为准并记一条 ⚠。
    这一步是**有依据的**而不是绕过识别 —— 假设本身是被数据检验过的（29/29 对齐）。
    """
    S = pg.S
    vbars = [c for c in pg.items if c["kind"] == "vbar"]
    if not vbars:
        return {}
    left = min(c["cx"] for c in vbars)
    tl = small_templates()
    out = {}
    for si, (sy0, sy1) in enumerate(pg.spans, 1):
        key = (pg.sh.page - 1, si)
        hint = SECTION_HINT.get(key)
        # x 上界必须松到 first_bar + 60px：三位数小节号 `(101)` 的右括号在 x147，
        # 已经**越过**首条小节线 x118 近 30px，卡在 left+14 会把 `)` 切掉（实测认出 `(20`）。
        band = [c for c in pg.items
                if c["cx"] < left + 60 * S and sy0 - PAD_GAP * S <= c["cy"] <= sy0 - 2 * S]
        digs = section_slots(pg, band, tl)
        s = ""
        if digs is not None:
            labs = []
            for c in digs:
                k, lab, _ = classify(c, pg.med_h, S, glyph_af=SMALL_AF, tl=tl)
                labs.append(lab if k == "glyph" else "?")
            s = "".join(labs)
            m = re.match(r"^(\d+)$", s)
            if m:
                val = int(m.group(1))
                if hint is not None and val != hint:
                    log(f"  ⚠ 第 {pg.sh.page} 页第 {si} 系统段落号认出 {val}，"
                        f"版面推值 {hint} → 采用版面推值")
                    val = hint
                out[key] = val
                continue
        if not s.strip():
            # 锚点没找到 → 退回「整带拼接」的老办法
            band2 = region_glyphs(pg, band)
            band2.sort(key=lambda c: c["cx"])
            s = "".join(c["label"] for c in band2)
            m = re.match(r"^\((\d+)\)$", s)
            if m:
                out[key] = int(m.group(1))
                continue
        if hint is not None:
            if s.strip():
                log(f"  ⚠ 第 {pg.sh.page} 页第 {si} 系统段落号没认全（「{s}」）"
                    f"→ 采用版面推值 {hint}")
            out[key] = hint
        elif s.strip():
            log(f"  ⚠ 第 {pg.sh.page} 页第 {si} 系统段落号没认全：「{s}」")
    return out


def read_head(pg, log):
    """第 1 页左上角 `1=C` + 竖排 `4/4` + `♩=91`。"""
    S = pg.S
    vbars = [c for c in pg.items if c["kind"] == "vbar"]
    if not vbars:
        return None
    top = min(c["y0"] for c in vbars)
    # 下界必须退到「段落号区」之上（PAD_GAP），否则第 1 系统的 `(1)`
    # 会被当成页眉的一部分混进识别串（实测过，得到「(11/)=C44)=(」）。
    band = [c for c in pg.items
            if c["cy"] < top - PAD_GAP * S and c["cx"] < pg.sh.W * 0.35]
    if not band:
        return None
    glyphs = region_glyphs(pg, band)
    glyphs.sort(key=lambda c: c["cx"])
    lines = [c for c in band if c["kind"] == "hline"]
    if not glyphs:
        return None
    eqs = []
    for i, A in enumerate(lines):
        for B in lines[i + 1:]:
            if abs(A["x0"] - B["x0"]) <= 3 * S and abs(A["w"] - B["w"]) <= 4 * S \
                    and 0 < abs(A["cy"] - B["cy"]) <= 8 * S:
                eqs.append(A["x0"])
    stack = None
    for i, A in enumerate(glyphs):
        for B in glyphs[i + 1:]:
            ov = min(A["x1"], B["x1"]) - max(A["x0"], B["x0"])
            if ov >= 0.5 * min(A["w"], B["w"]) and abs(A["cy"] - B["cy"]) > 12 * S:
                stack = (A, B)
                break
        if stack:
            break
    parts = []
    for c in glyphs:
        if stack and c is stack[1]:
            continue
        if stack and c is stack[0]:
            up, dn = sorted(stack, key=lambda z: z["cy"])
            parts.append((c["x0"], f"{up['label']}/{dn['label']}"))
            continue
        parts.append((c["x0"], c["label"]))
    parts += [(x, "=") for x in eqs]
    parts.sort()
    s = "".join(p[1] for p in parts)
    # 页眉区**结构上不可能出现括号**，所以这里的 `(` / `)` 必然是把细体数字看错
    # （页眉的音符符号比正文略宽，`1` 在 14×18 网格下与 `(` 的 L1 距离只差 4）。
    # 于是把括号当「数字」再试一遍。
    cands = [s]
    if "(" in s or ")" in s:
        cands.append(s.replace("(", "1").replace(")", "1"))
    best = None
    for cand in cands:
        km = re.search(r"(\d)\s*=\s*([A-Ga-g][#b]?)", cand)
        if not km:
            continue
        bm = re.search(r"(\d)\s*/\s*(\d)", cand)
        tm = re.search(r"=\s*(\d{1,3})\s*$", cand)
        head = f"{km.group(1)}={km.group(2)}"
        head += f" {bm.group(1)}/{bm.group(2)}" if bm else " 4/4"
        if tm:
            head += f" {int(tm.group(1))}"
        if best is None:
            best = (head, cand)
        if tm:                                    # 认出了速度才停；只认调号不算成功
            best = (head, cand)
            break
    if best:
        log(f"  页眉识别：「{best[1]}」→ {best[0]}")
        return best[0]
    log(f"  ⚠ 页眉没认出调号（识别串「{s}」），请用 --head 指定")
    return None


# ---------------------------------------------------------------------------
# 字模自校准
# ---------------------------------------------------------------------------
def _representative(bms):
    """模板 = 样本**均值**，返回 (模板, 样本对均值的平均离散)。

    ⚠️ 试过改用「中位样本」（真实字形，不受量化模糊影响），**更差**：实测灰度下
    `9` 的中位样本会被认成 `0`、`65` 被认成 `85`（段落号 9→0、65→85），
    而均值版本全对。小字号下单个样本本身就带量化噪声，均值反而更接近「理想字形」。
    所以这里坚持均值，只把离散阈值放宽到 0.65×ACCEPT（实测 PNG 下 `3`/`9` 是 36/38，
    0.5 倍时会被误弃用 → 页眉与段落号跟着崩）。
    """
    if len(bms) == 1:
        return bms[0], 0.0
    mean = [sum(b[i] for b in bms) / len(bms) for i in range(len(bms[0]))]
    spread = sum(sum(abs(b[i] - mean[i]) for i in range(len(mean))) for b in bms) / len(bms)
    return mean, spread


def calibrate(pages, log=None):
    """用**版面结构**给小节号打标，学出「细体层」字模（谱表上方专用的 0~9）。

    为什么必须学：简谱正文的音级只有 0~7，所以内置字模**没有 8 / 9**；而小节号
    `(93)(109)(113)` 与速度 `♩=91` 一定要用到它们。缺了就会被强行匹配成 `0`
    （L1 距离 59~63，恰好低于接受阈值 65）或 `3`（48~50）—— 认得出、但认错，
    比认不出更危险。

    为什么只能学出「细体层」而不是补进正文层：小字号的笔画比正文细，同一字形在
    14×18 网格上的 L1 距离天然差 45~60。把细体 8/9 补进正文层实测过：小节号里的
    细体 `3` 被 `8` 抢走（`13`→`18`）、细体 `0` 被 `9` 抢走（`101`→`191`）。
    分两层后小节号用细体层自比，留一 50/51。

    打标依据是纯版面事实：**第 k 个系统的小节号 = 1 + 它之前所有系统的小节数之和**，
    每个系统的小节数 = 该系统内小节线个数 − 1。全是数出来的，不依赖 OCR，
    所以换字体也能学。返回 {字符: 模板}（细体层），无法标定则返回 {}。
    """
    log = log or (lambda m: None)
    harvest = collections.defaultdict(list)
    # ⚠️ 打标一律用「正文层 + 符号」当模板（不用当前细体层），否则结果是**初始状态的函数**：
    # 预置了细体层时对齐率会从 25/29 升到 29/29，样本集变了，学出来的均值也就变了。
    tl = list(ATLAS.items()) + list(SYMBOLS.items())
    n_ok = n_all = cum = 0
    layout_sec = {}
    for pi, pg in enumerate(pages):
        S = pg.S
        vb = [c for c in pg.items if c["kind"] == "vbar"]
        if not vb:
            continue
        left = min(c["cx"] for c in vb)
        for si, (sy0, sy1) in enumerate(pg.spans, 1):
            expect = 1 + cum
            cum += max(0, len(bar_columns(vb, sy0, sy1, S)) - 1)
            n_all += 1
            layout_sec[(pi, si)] = expect
            # y 带在小节线之上，里面只可能有小节号；x 上界要松到 60px，
            # 三位数小节号的 `)` 会越到首条小节线右侧很远（实测 `(101)` 的 `)` 在 x147）。
            band = [c for c in pg.items
                    if c["cx"] < left + 60 * S
                    and sy0 - PAD_GAP * S <= c["cy"] <= sy0 - 2 * S]
            # 只认 `(` `)` 当锚点、取夹在中间的一切 —— 带里的连音弧碎片与「数字本身
            # 认不出（8/9）」都不会再让这一处作废（详见 section_slots 的注释）。
            digs = section_slots(pg, band, tl)
            if digs is None:
                continue
            exp = f"({expect})"
            if len(digs) != len(exp) - 2:     # 中间件数与期望数字个数不等 → 这一处不可信
                continue
            n_ok += 1
            for c, ch in zip(digs, exp[1:-1]):
                harvest[ch].append(norm_cover(c))
    if n_all == 0:
        return {}
    if n_ok < 0.8 * n_all:
        log(f"  细体字模自校准跳过：小节号与版面推值对不齐（{n_ok}/{n_all}）—— "
            f"这套谱的小节号不是「累计小节数」？")
        return {}
    out, thin = {}, []
    for ch, bms in sorted(harvest.items()):
        if len(bms) < MIN_SAMPLES:
            thin.append(f"{ch}({len(bms)})")
            continue
        med, spread = _representative(bms)     # 模板取样本均值（见 _representative）
        if spread > SPREAD_MAX * ACCEPT:       # 样本相互不聚拢 → 弃用
            log(f"  细体字模自校准：字形 {ch} 样本离散 {spread:.0f}（>"
                f"{SPREAD_MAX * ACCEPT:.0f}），弃用")
            continue
        out[ch] = [round(v, 4) for v in med]
    if out:
        log(f"  细体字模自校准 {n_ok}/{n_all} 个系统对齐；学到 "
            f"{' '.join(sorted(out))}（{len(out)} 个字形）")
    if thin:
        log(f"  细体字模自校准：{' '.join(thin)} 样本不足 2，本轮无法学出")
    # 对齐率达标 ⇒ 「本谱 `(N)` = 小节号」这个版面假设被数据证实了，
    # 于是把它交给 read_sections 当准绳（识别值不符时以它为准并记 ⚠）。
    SECTION_HINT.clear()
    SECTION_HINT.update(layout_sec)
    return out


def save_atlas(path, small=None):
    """把当前两层字模写成一份新的 `字模.json`。"""
    data = {"grid": [GW, GH],
            "digits": ATLAS,                       # 正文层（笔画常规）
            "small": {**SMALL, **(small or {})},   # 细体层（谱表上方）
            "symbols": SYMBOLS,
            "accept": ACCEPT,
            "meta": {"generated_by": "识谱.py --save-atlas"}}
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# 输出与自检
# ---------------------------------------------------------------------------
def render(rows, pages, head, sections):
    """拼简谱文本。⚠️ 段落标记 `@N` 必须**独占一行**，否则解析器会把整行当自由文本吞掉。"""
    out = {"mel": [head], "bas": [head]}
    # 变拍号说明用 `#` 注释行写进产物（`#` 行解析器不计时，安全）
    mchg = [(pi, si, bar, v) for pi, pg in enumerate(pages)
            for (si, bar), v in sorted(pg.meters.items())]
    if mchg:
        note = "# 变拍号（拍数配平按此核验）：" + "；".join(
            f"第{pi + 1}页第{si}系统第{bar}小节 = {v:g}拍" for pi, si, bar, v in mchg)
        out["mel"].append(note)
        out["bas"].append(note)
    for pi, pg in enumerate(pages):
        for si in range(1, pg.n_sys + 1):
            sec = sections.get((pi, si))
            for st in ("mel", "bas"):
                bs = rows.get((pi, si, st))
                if not bs:
                    continue
                if sec is not None:
                    out[st].append(f"@{sec}")
                body = [" ".join(t[1] for t in bs.get(bar, []))
                        for (s, bar) in pg.bars if s == si]
                out[st].append(" | ".join(body) + " |")
    return {k: "\n".join(v) + "\n" for k, v in out.items()}


def self_check(rows, pages, head, sections, log):
    beats = 4.0
    m = re.search(r"\b(\d+)\s*/\s*(\d+)\b", head)
    if m:
        beats = float(m.group(1))
    problems, infos = [], []

    bad = []
    total = 0
    for pi, pg in enumerate(pages):
        for (si, bar) in pg.bars:
            for st in ("mel", "bas"):
                total += 1
                bs = rows.get((pi, si, st), {})
                b = sum(t[2] for t in bs.get(bar, []))
                exp = pg.meters.get((si, bar), beats)
                if abs(b - exp) > 1e-6:
                    bad.append((pg.sh.page, si, bar, st, b,
                                " ".join(t[1] for t in bs.get(bar, []))))
    if bad:
        problems.append(f"拍数不对的小节 {len(bad)}/{total}")
        for r in bad[:20]:
            log(f"  ✗ 第{r[0]}页 第{r[1]}系统 第{r[2]}小节 {r[3]} = {r[4]:.2f} 拍 | {r[5]}")
    else:
        infos.append(f"每小节拍数 = {beats:g}（{total} 个小节·声部，**0 错**）")

    # 变拍号：报给用户（配平时已按 pg.meters 逐小节取期望拍数）
    mchg = [(pi, si, bar, v) for pi, pg in enumerate(pages)
            for (si, bar), v in sorted(pg.meters.items())]
    if mchg:
        infos.append("变拍号小节 " + "；".join(
            f"第{pi + 1}页第{si}系统第{bar}小节 = {v:g}拍" for pi, si, bar, v in mchg))

    # 同素材段落一致性：骨架相同（去掉连音线 `~`）的系统，全串也应当相同
    for st in ("mel", "bas"):
        groups = {}
        for pi, pg in enumerate(pages):
            for si in range(1, pg.n_sys + 1):
                bs = rows.get((pi, si, st))
                if not bs:
                    continue
                toks = [t[1] for b in sorted(bs) for t in bs[b]]
                if toks:
                    groups.setdefault(tuple(t.lstrip("~") for t in toks), []).append(
                        (pi, si, tuple(toks)))
        dup = {k: v for k, v in groups.items() if len(v) > 1}
        diff = [v for v in dup.values() if len({x[2] for x in v}) > 1]
        if dup:
            infos.append(f"{st}：同素材段落 {len(dup)} 组"
                         + (f"，其中 {len(diff)} 组连音线写法不同" if diff
                            else "，全部逐字相同"))
            if diff:
                problems.append(f"{st} 有 {len(diff)} 组同素材段落写法不同")
                for v in diff[:5]:
                    log("  · 同素材但写法不同：" +
                        " / ".join(f"p{pi + 1}s{si}" for pi, si, _ in v))

    if sections:
        v = sorted(sections.values())
        src = "版面推值" if SECTION_HINT else "识别值"
        infos.append(f"段落号 {len(v)} 个（{src}）：{v[0]}…{v[-1]}")
        if SECTION_HINT:
            miss = [k for k in sections if k not in SECTION_HINT]
            n_hint = len(set(sections) & set(SECTION_HINT))
            if miss:
                infos.append(f"其中 {len(miss)} 个不由版面推得（共 {n_hint} 个由版面推得）")
    return problems, infos


def write_debug(pages, outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    lines = []
    for pi, pg in enumerate(pages):
        lines.append(f"=== 第 {pi + 1} 页  {Path(pg.sh.path).name}  "
                     f"{pg.sh.W}×{pg.sh.H}  纸白={pg.sh.paper}  墨阈值={pg.sh.ink}  "
                     f"字高={pg.med_h}  S={pg.S:.3f}")
        for si, (a, b) in enumerate(pg.spans, 1):
            vb = [c for c in pg.items if c["kind"] == "vbar"]
            cols = bar_columns(vb, a, b, pg.S)
            lines.append(f"  系统{si}  y{a}-{b}  小节线 {cols}")
            for (s, bar) in pg.bars:
                if s != si:
                    continue
                for st in ("mel", "bas"):
                    digs = pg.box.get((si, bar, st), {}).get("dig", [])
                    if not digs:
                        continue
                    rcy = pg.rowcy.get((si, st))
                    lines.append(f"    b{bar} {st} 行cy={rcy} 数字: " + "  ".join(
                        f"{d['label']}@{d['cx']},{d['cy']}(d{d['dist']:.0f})"
                        for d in sorted(digs, key=lambda d: d["cx"])))
        unk = [c for c in pg.items if c["kind"] in ("arc", "junk")
               and c["area"] >= 12 * pg.S * pg.S and c["h"] >= 8 * pg.S]
        lines.append(f"  未归因组件 {len(unk)} 个：")
        for c in sorted(unk, key=lambda c: -c["area"])[:20]:
            lines.append(f"    {c['kind']} x{c['x0']}-{c['x1']} y{c['y0']}-{c['y1']} "
                         f"w{c['w']} h{c['h']} a{c['area']} dist={c['dist']}")
    (outdir / "版面.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  调试图 → {outdir / '版面.txt'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="识谱.py", description="简谱图片 → 机器谱（通用识谱工具）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("images", nargs="+", help="按页顺序的图片（PNG/PGM；其他格式走 PIL/ffmpeg）")
    ap.add_argument("--raw", metavar="WxH", help="把输入当裸 8 位灰度读（.gray/.raw）")
    ap.add_argument("--ink", type=int, help="手动指定墨阈值（默认 纸白×0.81）")
    ap.add_argument("--accept", type=float,
                    help="字形模板接受的 L1 距离上限（默认用字模.json 里的值）")
    ap.add_argument("--head", help='首行调号/拍号/速度，如 "1=C 4/4 91"（默认自动识别）')
    ap.add_argument("-o", "--out", default="简谱-旋律.txt", help="旋律声部简谱输出")
    ap.add_argument("--bass", default="简谱-左手.txt", help="伴奏声部简谱输出")
    ap.add_argument("--score", help="顺带跑 jianpu_to_score.py 产出机器谱")
    ap.add_argument("--debug-dir", help="落版面调试图")
    ap.add_argument("--save-atlas", metavar="PATH",
                    help="把自校准后的字模写成新的 字模.json（换字体时用）")
    ap.add_argument("--eol", choices=("lf", "crlf"), default="lf",
                    help="产物的行尾（默认 lf，与项目约定一致；旧链路产物是 crlf）")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.accept:
        globals()["ACCEPT"] = float(a.accept)

    t0 = time.time()
    sheets = [Sheet(p, i, a.raw) for i, p in enumerate(a.images, 1)]
    # 墨阈值跨页统一：纸白是扫描/导出设置的属性，逐页各算会得到 205/207 两个值，
    # 同一批谱面的判读就不一致了 → 取全批次**最深的纸白**。
    ink = a.ink if a.ink else min(sh.auto_ink for sh in sheets)
    for sh in sheets:
        sh.set_ink(ink)
    if not a.quiet:
        for i, sh in enumerate(sheets, 1):
            print(f"[{i}/{len(sheets)}] {Path(sh.path).name}  {sh.W}×{sh.H}  "
                  f"纸白 {sh.paper}  墨阈值 {sh.ink}")

    # 第一遍：静默分析，只为拿版面结构做**细体字模自校准**（学出 8/9 这类正文没有的字形）
    probe = [Page(sh, quiet=True) for sh in sheets]
    learned = calibrate(probe, lambda m: None if a.quiet else print(m))
    if learned:
        SMALL.update(learned)
        pages = [Page(sh, a.quiet) for sh in sheets]      # 用补全后的细体层重认
    else:
        pages = probe
        if not a.quiet:                                   # 复用静默那遍的结果，补印日志
            for pg in pages:
                print("\n".join(pg.logbuf), flush=True)
    if a.save_atlas:
        save_atlas(a.save_atlas, learned)
        print(f"  字模 → {a.save_atlas}")

    head = a.head
    if not head:
        for pg in pages:
            head = read_head(pg, pg.log)
            if head:
                break
    if not head:
        print("⚠ 页眉没认出来，用默认 1=C 4/4 91（可用 --head 指定）", file=sys.stderr)
        head = "1=C 4/4 91"
    if not head.strip().startswith("1="):
        head = "1=" + head

    sections = {}
    for pg in pages:
        sections.update(pg.sections)

    tr = Transcriber(pages, lambda m: None if a.quiet else print(m))
    rows, repairs = tr.run()
    if repairs and not a.quiet:
        print(f"夹层音归属修复 {len(repairs)} 处（拍数配平驱动）：")
        for pgno, si, bar, lab, cy, s1, s2, t1, t2, n1, n2 in repairs:
            print(f"   p{pgno}s{si}b{bar}  数字 {lab}(cy{cy})  {s1} → {s2}"
                  f"   ({t1:.2f}/{t2:.2f} → {n1:.2f}/{n2:.2f})")

    texts = render(rows, pages, head, sections)
    nl = "\r\n" if a.eol == "crlf" else "\n"
    for path, key in ((a.out, "mel"), (a.bass, "bas")):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(texts[key], encoding="utf-8", newline=nl)

    problems, infos = self_check(rows, pages, head, sections,
                                 lambda m: None if a.quiet else print(m))
    print("\n=== 自检 ===")
    for s in infos:
        print(f"  ✓ {s}")
    for s in problems:
        print(f"  ✗ {s}")
    print(f"  首行 {head}；旋律 {sum(1 for l in texts['mel'].splitlines() if not l[:1] in ('#', '@') and l.strip())} "
          f"系统 / 伴奏 {sum(1 for l in texts['bas'].splitlines() if not l[:1] in ('#', '@') and l.strip())} 系统")

    if a.debug_dir:
        write_debug(pages, a.debug_dir)

    if a.score:
        cmd = [sys.executable, str(HERE.parent / "jianpu_to_score.py"), a.out,
               "--overlay", a.bass, "-o", a.score]
        print("\n=== 生成机器谱 ===\n  " + " ".join(str(c) for c in cmd))
        if subprocess.run(cmd).returncode:
            print("  ✗ 转换失败", file=sys.stderr)
            problems.append("机器谱转换失败")

    print(f"\n总用时 {time.time() - t0:.1f}s\n  旋律 → {a.out}\n  伴奏 → {a.bass}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
