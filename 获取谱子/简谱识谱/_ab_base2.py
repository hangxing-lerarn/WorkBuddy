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
SYS_PAD_TOP = 0.42    # 「上沿救援」的带宽（× 字高）：收盒只留 3S≈6px，而有些版本把旋律行
                      # 印在小节线上沿**之上**（《诀别书》p3s8 实测：小节线顶 3635、旋律行
                      # cy 中位 3633、末小节那颗带高音点的 `3'` 更是印在 cy3621 —— 比同行
                      # 高 12px，直接被丢掉且**拍数查不出来**：它和同列的 `1'` 成和弦）。
                      # ⚠️ 该带宽只喂给 `_rescue_top` —— 它还要「离本系统某一行 ≤0.5 字高」
                      # 才捞（正例 0.27 字高，三处误捞 1.56/1.60 字高；点判据无效，实测
                      # 那三处漏下来的音**上面也都有点**）。**不能**拿它统一放宽上沿：
                      # 上一系统坠下来的低音会跟着进来长伪和弦（起风了、Da Capo 各 1 处实测回归）。
RESCUE_UP = 5.0       # 「上沿救援」**第二判据**（同小节·列对齐·纵向链接）向上够多远（× 字高）
COL_TOL = 0.5         # 列对齐容差（× 字高）：顶音与同小节某个已收进来的数字的 x 差
GAP_CHAIN = 2.2       # 逐级链接的最大纵向步长（× 字高）—— 谱内行距 60~90px = 1.4~2.0 字高，
                      # 上一系统坠下来的音隔着谱表间大空隙（《拂晓》实测 122px = 2.77 字高）
CUT_TOL = 0.40        # 「上沿切进最上一行」的判定容差（× 字高）：|sy0 − 最上一行中心| ≤ 它
                      # 才算「小节线被画短」→ 第二判据启用。合法排版的上沿停在**行间空档**
                      # 里，实测其余曲目 ≥1.4 字高，两边都很空。
BAR_PAD = 5.0         # 排除小节线本身（按 cx 归属，双竖线已合并成一列）
SPLIT_W = 20.0        # 贴着写的两个数字（`6̇3̇`）超过这个宽度就按墨量谷切开
ROW_BAND = 8.0        # 主行采样带宽
GAP_MIN = 20.0        # 离主行超过这么多像素 = 可疑的「夹层音」
DOT_MAX = 20.0        # 八度点离数字多远还算它的（减时线会把点顶得更低，实测 dd≈16）
OCT_BEAM_GAP = 12.0   # ⚠️ 点印在**减时线下方**时，允许它离最后一条横跨它的减时线这么远
                      # （单位 = S）。Bad Apple 实测 7.4~8.8S；起风了把夹在两谱表
                      # 之间的 `7'` 误判成上行的 `5',` 是 14~15S —— 12S 能分开两者。
                      # 只在 `dd > DOT_MAX*S`（本该丢弃）时当**救济**判据，绝不进排序。
DOT_H, DOT_W, DOT_A = 8.0, 7.0, 28.0          # 八度点/附点的尺寸上限
BAR_TOL = 15.0        # 小节线 x 去重容差（双竖线只隔 8px，必须并成一列）
VBAR_HF, VBAR_WF = 1.15, 0.30                 # 小节线：高 ≥1.15 字高，宽 ≤0.30 字高
VBAR_CORE_HF = 2.0                            # 「墨柱」法救被连音弧粘住的小节线：高 ≥2 字高…
VBAR_CORE_FILL = 0.9                          # …且存在连续几列（总宽 ≤VBAR_WF 字高）每列墨量 ≥0.9h
BRACE_HF, BRACE_WF = 3.0, 0.30                # 花括号：高 ≥3 字高，宽 ≥0.30 字高
BRACE_AF = 120.0 / (REF_H ** 2)
# ⚠️ 「花括号」与「波浪线（琶音/刮奏记号）」必须分开：两者都是「高 ≥3 字高、窄」，
#    但花括号是一条**平滑弧**，波浪线是一根**近竖直的锯齿**。区分办法有两个，
#    都只看组件自身的墨迹分布（与具体曲子无关）：
#      · 逐行中位 x 的**方向翻转次数** ÷ 高；
#      · **最长单列墨柱** ÷ 高（锯齿在 x 上摆幅小、上下重叠 → 单列能连续很长）。
#    实测（Da Capo，med_h=45）：真花括号 5 次/345 行 = 0.015、墨柱 76/345 = 0.22；
#    波浪线 20~24 次/180~195 行 = 0.10~0.13、墨柱 153~190/180~195 = 0.85~0.97。
#    两组相差 7~8 倍，阈值取中间，任何一侧都不会压线。
WAVE_FLIP_F = 0.030          # 方向翻转次数 ÷ 高 > 此值 → 波浪线
WAVE_RUN_F = 0.600           # 最长单列墨柱 ÷ 高 > 此值 → 近竖直墨柱（= 波浪线）
# ⚠️ 上面那两条是**为区分花括号与波浪线**标定的（med_h=45，两者相差 7~8 倍）。
#    搬到「小节线 vs 波浪线」上会翻车：花括号的墨柱 0.22、波浪线 0.85~0.97，
#    而小节线本身就是一根贯通柱（run/h = 1.00）—— 拿 0.60 当线会把波浪线当小节线
#    **漏掉**（正是《我不曾忘记》p3s1 的 bug）。所以另立一对判据，见
#    `_looks_like_barline()`：真小节线**整根贯通**，锯齿线**单列最长段只占 0.21**。
VBAR_SOLID_F = 0.85          # 小节线：最长单列连续墨段 ≥ 此值 × 高（实测真线 = 1.00）
VBAR_WAVE_FLIP_F = 0.06      # 断笔（虚线）小节线也贯通率低 → 再加「锯齿」双保险
# 增时线（`-`）印在数字行的**中线上**。实测 12 首曲子的 700+ 条真增时线，与「本格声部
# 行 cy」的偏差**全部 ≤ 1.05S**（0.00S ×402 / 0.47S ×239 / 0.48S ×117 / 1.05S ×2）。
# 旧阈值 12S 太松：连音弧被阈值化后若**一个 arc 组件都不剩**（弯头都落进 `hline`），
# `_arc_flat` 就失去前提，弧平顶那段细横条便从 12S 的缝里钻进来冒充第 4 条 `-`
# —— 《我不曾忘记》p2s3b1 的 `5 - - - -`（5 拍，应为 `5 - - -`）。全样本里 >1.05S 的
# **只有这一处**（图证 buceng/zz_37b1_all.png：黑 `5` 与灰 `5` 之间低音谱表的连音弧，
# 两端弧体 h11 落在 mel 格、中间那段 h2 平顶 cy 距 mel 行 cy 11.55S）。
# 取 3S：比实测最大值高 2.9 倍，比误判目标低 3.85 倍。
DASH_ROW_TOL_F = 3.0         # 增时线 cy 与声部行 cy 的最大偏差（单位 S）
WAVE_BAR_F = 0.50            # 波浪线里若有一根 ≥0.50 字高的连续横杠 → 里面粘着数字
WAVE_BARROWS = 3             # 该横杠至少连续这么多行才算数字（实测 `4` 的横杠 8 行）
HLINE_HF, HLINE_WF = 0.55, 0.45               # 减时线/增时线：矮而宽
GLYPH_HF = 12.0 / REF_H                       # 数字：高 ≥ 12
GLYPH_AF = 60.0 / (REF_H ** 2)
SMALL_AF = 25.0 / (REF_H ** 2)                # 小字（段落号 `(13)` / 页眉）专用面积下限
PAD_GAP = 48.0        # 谱表上方多远之内算「页眉/段落号区」，再往上就是标题了
GRAY_F = 0.43                                 # 灰色接音：dark > 纸白 × 0.43
GRAY_SLACK = 5.0        # 浅灰接音的额外容忍距离（它的笔画天生比黑字细一圈）
COLOR_DROP = 0.5        # 一个连通域里「彩色像素」占比 ≥ 这个值 → 判定为歌词/标注，剔除
                        # （Call of Silence 的红歌词与音符同为深色墨，只有饱和度分得开）
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
        self.buf, self.tint, self.W, self.H = imgio.load_gray_tint(path, raw_size)
        self.auto_ink, self.paper = imgio.ink_threshold(self.buf)
        self.ink = self.auto_ink
        self.dark = bytearray(1 if v < self.ink else 0 for v in self.buf)

    def set_ink(self, ink):
        if ink == self.ink:
            return
        self.ink = int(ink)
        self.dark = bytearray(1 if v < self.ink else 0 for v in self.buf)

    def components(self, x0=0, y0=0, x1=None, y1=None):
        """8 邻域迭代 DFS。返回每个连通域的 bbox/面积/平均灰度/彩色占比/像素表。"""
        W = self.W
        x1 = self.W if x1 is None else x1
        y1 = self.H if y1 is None else y1
        dark, buf, tint = self.dark, self.buf, self.tint
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
                    "color": (sum(tint[p] for p in pix) / n) if tint is not None else 0.0,
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


def _looks_like_barline(comp):
    """这根「细高」组件**真的是小节线**吗（而不是琶音/刮奏的波浪线）？

    ⚠️ 第 14 条已修缺陷。小节线只有 3px 宽，琶音/刮奏的波浪线也是 6px 宽的细高
    个子，**两条闸（h ≥ 1.15 字高、w ≤ 0.30 字高）它全过**。《我不曾忘记》p3s1
    实测：波浪线 `x419..424 y233..307`（w6 h75）被判成 vbar → 在 x=421 多切出
    一个 16px 的**假小节** → 该页小节计数 +1 → **段落号整体错位 1**
    （版面推值把认对的 65/69/73/77 改成 66/70/74/78），且多出一个 0 拍的空小节，
    拍数校验只报 2 条、根本看不出是编号错。放大图证：`buceng/z_400.png`。

    判据（两条都要成立才否掉，缺一不可）：
      ① **最长单列连续墨段 < 0.85h** —— 真小节线是一根笔直贯通的墨柱
         （全三页 60+ 根实测 run/h 一律 = 1.00），锯齿线逐列上下重叠不起来
         （实测 16/75 = 0.21）；
      ② **逐行中位 x 的方向翻转 > 0.06h** —— 锯齿来回。② 是给**断笔（虚线）
         小节线**留的活口：那种线 ① 也不成立，但它是直的、翻转≈0。
    与 `_wavy_tall()` 的区别：那条是给「花括号 vs 波浪线」用的（h ≥ 3 字高那一档），
    阈值标定完全不同，**不能互相搬用**（真小节线的翻转能到 4 次/55 行 = 0.073，
    比 WAVE_FLIP_F=0.030 高，直接套会把真小节线全否掉）。
    """
    h = comp["h"]
    cols = collections.defaultdict(list)
    for x, y in comp["pts"]:
        cols[x].append(y)
    longest = 0
    for yy in cols.values():
        yy.sort()
        run = 1
        for i in range(1, len(yy)):
            run = run + 1 if yy[i] == yy[i - 1] + 1 else 1
            if run > longest:
                longest = run
        if run > longest:
            longest = run
    if longest >= VBAR_SOLID_F * h:
        return True
    ys = collections.defaultdict(list)
    for x, y in comp["pts"]:
        ys[y].append(x)
    flips = 0
    prev_dir = 0
    prev_mid = None
    for y in sorted(ys):
        xs = ys[y]
        mid = (min(xs) + max(xs)) / 2.0
        if prev_mid is not None:
            d = mid - prev_mid
            if abs(d) >= 0.5:
                cur = 1 if d > 0 else -1
                if prev_dir and cur != prev_dir:
                    flips += 1
                prev_dir = cur
        prev_mid = mid
    return flips <= VBAR_WAVE_FLIP_F * h


def _vbar_core(comp, med_h):
    """连通域里有没有一根「竖长墨柱」—— 用来救**被连音弧粘住的小节线**。

    小节线只有 6px 宽，但连音弧的尾端常搭在它肩上，8 连通后并成一个 bbox
    33×121 的大组件，过不了 `w <= VBAR_WF*med_h`（=12.9px）那道闸 → 被当成
    字形送进 `_vsplit_marks`，拆出一个**假的 `1`**：Call of Silence 第 16 小节
    实测，假 `1` 与真 `5` 同列 → 变成和弦 `(5 1)` → 与下一小节的 `~5`
    「连音线两端音不一样」而整谱转不出来。

    判据：逐列数墨量，若**最宽的一段连续满柱** ≤ VBAR_WF 字高，那它就是一整根
    独立的小节线（连音弧只贡献旁边那些不满的列）。用「最宽」而不是「存在」——
    否则一段短柱 + 一段长块也会误过。
    """
    h = comp["h"]
    col = collections.Counter(x for x, _y in comp["pts"])
    need = VBAR_CORE_FILL * h
    maxw = VBAR_WF * med_h
    best = run = 0
    for x in range(comp["x0"], comp["x1"] + 1):
        run = run + 1 if col.get(x, 0) >= need else 0
        if run > best:
            best = run
    return 0 < best <= maxw


def _wavy_tall(comp, med_h):
    """这个「高 ≥3 字高、窄」的组件是**波浪线（琶音/刮奏记号）**而不是花括号吗？

    花括号（谱表左端那个 `{`）与波浪线在 bbox 上完全同类：都又高又窄，都会过
    `classify` 的花括号闸。但花括号是一条**平滑弧**（逐行中位 x 单调地鼓出去
    再收回来），波浪线是一根**近竖直的锯齿**（逐行中位 x 反复来回 + 上下重叠
    得单列能连续很长）。判据与阈值见 `WAVE_FLIP_F` / `WAVE_RUN_F` 处的实测。
    """
    ys = collections.defaultdict(list)
    for x, y in comp["pts"]:
        ys[y].append(x)
    seq = sorted(ys)
    flips = 0
    prev_dir = 0
    prev_mid = None
    for y in seq:
        xs = ys[y]
        mid = (min(xs) + max(xs)) / 2.0
        if prev_mid is not None:
            d = mid - prev_mid
            if abs(d) >= 0.5:
                cur = 1 if d > 0 else -1
                if prev_dir and cur != prev_dir:
                    flips += 1
                prev_dir = cur
        prev_mid = mid
    if flips > WAVE_FLIP_F * comp["h"]:
        return True
    # 最长单列墨柱：先按下标排好序，再扫连续段（不能只数列墨量 —— 锯齿的
    # 每一列墨量都不高，但上下是连着的）
    cols = collections.defaultdict(list)
    for x, y in comp["pts"]:
        cols[x].append(y)
    longest = 0
    for x, yy in cols.items():
        yy.sort()
        run = 1
        for i in range(1, len(yy)):
            run = run + 1 if yy[i] == yy[i - 1] + 1 else 1
            if run > longest:
                longest = run
        if run > longest:
            longest = run
    return longest > WAVE_RUN_F * comp["h"]


def _longest_run(xs):
    """一行的墨迹里**最长的连续列段**，返回 (长度, 起, 止)。断笔/噪声都容忍。"""
    ys = sorted(xs)
    best = (0, 0, 0)
    i = 0
    while i < len(ys):
        j = i
        while j + 1 < len(ys) and ys[j + 1] == ys[j] + 1:
            j += 1
        if j - i + 1 > best[0]:
            best = (j - i + 1, ys[i], ys[j])
        i = j + 1
    return best


def _wave_digit_split(comp, med_h, S):
    """从「波浪线粘住数字」的组件里把**底部那颗数字**救出来。

    琶音/刮奏的波浪线是一根近竖直的细锯齿，常常 8 连通地**粘住它旁边那个数字**
    （Da Capo p2 实测：波浪线 x1281..1295 与 `4` x1255..1288 在 y1122..1145
    重叠 → 并成 w41 h180 的组件）。横竖两条闸都拦不住它：h180 ≥ 3 字高 → 过
    花括号闸 → 被判成 `brace` 丢进「不进 box」那一类，**数字跟着一起消失**
    （低音行 `4145 5414` 变成 `4145 541`，16 分变 8 分，整小节 3.75 拍）。
    本函数只在这一种情形下拆，三条判据缺一不可：
      ① `_wavy_tall` —— 组件确实是波浪线/近竖直墨柱；
      ② 底部 med_h 行的窗口里，存在**≥WAVE_BARROWS 行**带有 ≥WAVE_BAR_F 字高
         的连续横杠 —— 那根横杠就是被粘住的那个数字的横笔。**这一条是安全闸**：
         纯波浪线的窗口里一行宽横杠都没有（Da Capo p1 那条窄波浪实测 0 行，
         `_vsplit_marks` 会把它的三段各认成一个假 `1`）；
      ③ 把窗口按那根横杠的 x 跨度**裁齐**后，能干净地认成一个数字 —— 不裁齐
         的话波浪线的外挂像素把 bbox 撑宽，`norm_cover` 归一后必然认不出
         （实测 d=53.6 越过 ACCEPT×0.75；裁齐后 d=29.1）。
    返回 (数字组件, label, dist) 或 None；找不到就返回 None（保持原样）。
    """
    y1 = comp["y1"]
    ys = collections.defaultdict(list)
    for x, y in comp["pts"]:
        ys[y].append(x)
    best = None
    for n in range(int(0.90 * med_h), int(1.10 * med_h) + 1):
        a = y1 - n + 1
        if a < comp["y0"]:
            continue
        rows = [y for y in range(a, y1 + 1) if ys.get(y)]
        if not rows:
            continue
        wide = 0
        core = (0, 0, 0)
        for y in rows:
            r = _longest_run(ys[y])
            if r[0] > core[0]:
                core = r
            if r[0] >= WAVE_BAR_F * med_h:
                wide += 1
        if wide < WAVE_BARROWS or core[0] < WAVE_BAR_F * med_h:
            continue
        win = [(x, y) for y in rows for x in ys[y] if core[1] <= x <= core[2]]
        if not win:
            continue
        cc = _mkcomp(win)
        d, lab = match_glyph_shift(norm_cover(cc))
        if d <= 0.75 * ACCEPT and (best is None or d < best[0]):
            best = (d, lab, cc)
    if best is None:
        return None
    d, lab, cc = best
    return cc, lab, d


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
    if h >= VBAR_HF * med_h and w <= VBAR_WF * med_h and _looks_like_barline(comp):
        return "vbar", None, None
    if h >= BRACE_HF * med_h and w >= BRACE_WF * med_h and a >= BRACE_AF * S * S:
        return "brace", None, None
    # 连音弧尾端搭在小节线肩上 → bbox 变宽，上面那条宽度闸过不了。放在花括号
    # 之后：再高就该是花括号（h ≥ 3 字高），不能跟它抢。
    if VBAR_CORE_HF * med_h <= h < BRACE_HF * med_h and _vbar_core(comp, med_h):
        return "vbar", None, None
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

    ⚠️ 投票前剔除「圆润小方块」（宽高比 0.7~1.4 且 ink 占比 ≥0.65）——
    群青实测：某些谱的八度点/附点印得肥（直径≈0.22×字高，10×10、area≈84、
    fill≈0.84），在附点密集页会以 10 票之差压过数字 → 众数掉到 10px、
    S 崩成 0.476、整页分类/系统检测雪崩（glyph 全进 brace/junk）。
    数字笔画有孔有隙，fill≈0.35~0.6，不会被这条误伤；全被剔光时回退全量。
    """
    def vote(pool):
        cnt = collections.Counter(c["h"] for c in pool)
        if not cnt:
            return None
        peak = max(cnt, key=lambda h: (cnt[h], -h))
        band = sorted(h for h in cnt if abs(h - peak) <= 2 for _ in range(cnt[h]))
        return band[len(band) // 2]
    base = [c for c in comps if c["w"] >= 6 and c["h"] >= 10 and c["area"] >= 40]
    slim = [c for c in base if not (0.7 <= c["w"] / c["h"] <= 1.4
                                    and c["area"] >= 0.65 * c["w"] * c["h"])]
    return vote(slim) or vote(base)


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
        # 「彩色元素」先剔除：歌词 / 力度记号 / 指法标注常常印成彩色，而音符数字是黑的。
        # 灰度化后两者都是「深色墨」，阈值分不开；饱和度才是唯一可靠的判据。
        # 必须赶在 estimate_med_h 之前 —— 歌词字形比数字矮一截，混进来会把字高中位数带偏。
        self.n_color = 0
        if sh.tint is not None:
            keep = []
            for c in comps:
                if c["color"] >= COLOR_DROP:
                    self.n_color += 1
                else:
                    keep.append(c)
            comps = keep
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
        n_trim = n_dot = n_wave = 0
        for i, c in enumerate(items):
            # ⚠️ 波浪线（琶音/刮奏记号）粘住数字：这一支**必须独立**。
            #    粘完的组件 h≈4 字高、过得了花括号闸 → kind 直接是 `brace`，
            #    会被下面那道 `kind in (glyph, junk, arc)` 的闸滤掉；而真谱表
            #    花括号也是 `brace`，绝不能一起送进通用拆分通道（实测会被拆出
            #    假 `1`）。用「是不是波浪线」把它俩分开，再走专用救援。
            if c["kind"] == "brace":
                if not _wavy_tall(c, med_h):
                    continue
                got = _wave_digit_split(c, med_h, S)
                if not got:
                    continue
                cc, lab, d = got
                cc["page"] = sh.page
                cc["dark"] = round(sum(buf[py * W + px] for px, py in cc["pts"])
                                   / len(cc["pts"]), 1)
                cc["kind"], cc["label"], cc["dist"] = "glyph", lab, d
                items[i] = cc
                n_wave += 1
                continue
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
        if n_wave:
            self.log(f"  波浪线粘字拆分：{n_wave} 个（琶音/刮奏记号旁的数字已找回）")
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
        if self.n_color:
            self.log(f"  彩色元素（歌词/标注）剔除 {self.n_color} 个"
                     f"（饱和度 ≥ {imgio.TINT_SAT}，不进数字候选）")
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
        self.sysinner = {}                   # sys → {bar: [组件]}（供重新分界）
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
        # ⚠️ 三连音括号必须**先摘掉**：否则标记 `3` 会以「小号数字」的身份混进 `box`，
        #    被 `_row_bands` 并成伪和弦、把整小节拍数从 4 顶到 5 甚至 16。
        self._find_triplets()
        # 连音弧的中段平顶会被阈值化切成 `hline`，与数字行同高时会被误当增时线
        # （见 `_arc_flat`）—— 这里先把弧收好，供 eval_bar 的增时线判定排除。
        self.arcs = [c for c in self.items if c["kind"] == "arc"]
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
            saved = self._rescue_top(si, cols)
            for c in saved:
                bar = self._bar_of_x(cols, c["cx"])
                if bar is not None:
                    inner_of[bar].append(c)
            if saved:
                self.log("  ⚠ 上沿救援 第%d系统：小节线上方捞回 %d 颗（%s）"
                         % (si, len(saved),
                            ", ".join("x%.0f/y%.0f" % (c["cx"], c["cy"]) for c in saved)))
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
            self._bind_system(si, bound, inner_of)
        # 三连音标记要在 `box` 建好之后打 —— 归属靠「括号底下最近的那一行数字」
        self._tag_triplet_digits()

    def _bind_system(self, si, bound, inner_of=None):
        """按给定分界线把**整个系统**重新入盒（可反复调用 → 必须幂等）。

        非数字元素不能按自身的 cy 或 x 硬切：旋律的增时线正下方可能就是低音的
        数字；第二条减时线会卡在分界下沿。每只手的「数字行」有 cy 与 y1 两个
        刻度 —— 增时线贴在 cy 上，减时线在 y1 下方约 12px，取更近者。

        `Transcriber` 会拿多个候选分界线各绑一次、比拍数误差，所以这里先把该
        系统已有的盒/行统计清干净再重建。
        """
        S = self.S
        sy0, sy1 = self.spans[si - 1]
        cols = bar_columns([c for c in self.items if c["kind"] == "vbar"],
                           sy0, sy1, S)
        if inner_of is None:
            inner_of = {}
            for k in range(len(cols) - 1):
                xa, xb = cols[k], cols[k + 1]
                inner_of[k + 1] = [
                    c for c in self.items
                    if c["kind"] not in ("vbar", "brace")
                    and xa + BAR_PAD * S <= c["cx"] <= xb - BAR_PAD * S
                    and sy0 - 3 * S <= c["cy"] <= sy1 + 3 * S]
            for c in self._rescue_top(si, cols):
                bar = self._bar_of_x(cols, c["cx"])
                if bar is not None:
                    inner_of[bar].append(c)
        self.sysinner[si] = inner_of
        # ⚠️ **印在数字上方的八度点会被上沿切掉**（《拂晓》p6s1b1 实测）：
        # 「短刻度小节线」让数字本身贴着上沿（cy369 vs sy0=371），而高八度点印在
        # 它上方约 25px，整颗落进 `sy0 - 3S` 之外 → 不进本小节的 `dots` →
        # `dot_map` 看不见它 → 顶上那一音丢 `'`（产物 `(3 3)×3 (4 4)`，
        # 谱面实为 `(3' 3)×3 (4' 4)`，图证 p6s1b1 八个高音点全部在案）。
        # **数字**不能用放宽的上界（会把上一系统坠下来的音收进伪和弦，见
        # `_rescue_top` 的教训），但**点**没有这个问题：它只有与数字 x 正对才算数，
        # `dot_map` 会按「x 正对 + 落在数字 y 范围内」自己二次筛。所以点单独放宽到
        # `sy0 - DOT_MAX*S`，并用「上一系统底 + 0.5 字高」封顶（与 `_rescue_top_chain`
        # 的 `lo` 同口径），绝不跨系统。
        _dlo = sy0 - DOT_MAX * S
        if si > 1:
            _dlo = max(_dlo, self.spans[si - 2][1] + 0.5 * self.med_h)
        # ⚠️ `DOT_MAX*S` 这条横线本身没有物理含义，只是「点到数字的距离上限」
        # 在「数字贴着上沿」这种版面上的粗略投影。实测《拂晓》p3s1b1 的高音点
        # 印在 sy0 之上 42px，而 `20.0*S = 41.90` —— **差 0.1px 整颗被排除**；
        # 同一份谱的 p4s2b3 同类点距上沿 41px，恰好压线过关 → **同一素材两处
        # 读音不同**（`(3 3)` vs `(3' 3)`，图证 zz49/zz83 完全相同）。
        # ⇒ 补一条**锚定在本系统数字上**的判据：点掉到带上沿之外时，只要它
        # 正对（|Δcx| ≤ 12S）本系统**已有的**某个数字、且纵向间隙 ≤ DOT_MAX*S，
        # 就照收。数字属于本系统，点自然也是；再用「上一系统底 + 0.5 字高」
        # 兜底，绝不跨系统。
        _insys = [c for inner in inner_of.values()
                  for c in inner if c["kind"] == "glyph"]
        _floor = 0.0 if si == 1 else self.spans[si - 2][1] + 0.5 * self.med_h
        _extra_dots = {}
        for c in self.items:
            if c["kind"] != "dot" or c["cy"] >= sy0 - 3 * S:
                continue
            if c["cy"] < _dlo:
                if c["cy"] < _floor or not any(
                        abs(c["cx"] - g["cx"]) <= 12 * S
                        and 0 <= g["y0"] - c["y1"] <= DOT_MAX * S
                        for g in _insys):
                    continue
            _b = self._bar_of_x(cols, c["cx"])
            if _b is not None:
                _extra_dots.setdefault(_b, []).append(c)
        for k in [k for k in self.box if k[0] == si]:
            del self.box[k]
        for st in ("mel", "bas"):
            self.rowcy.pop((si, st), None)
            self.rowy1.pop((si, st), None)
        for bar, inner in inner_of.items():
            # ⚠️ **点必须按 id 去重**：救援回来的那颗八度点会被 append 进 `inner`
            # （见 `saved` 那条路），而它本来就满足 `_extra_dots` 的条件（整颗落在
            # `sy0 - 3S` 之上）—— 两条路各收一次 → `self.dots[(si,bar)]` 里同一颗点
            # 出现两遍。`dot_map` 的「竖排和弦按序配对」靠 `len(ds) == len(col)`
            # 判定，多出来的那颗让计数对不上、**整条救援被静默跳过**：顶上那音拿到
            # `U`+`D`（不合法），下一位丢点。实测《诀别书》p3s8b4（@92）谱面
            # `(3' 1')` 被读成 `(3', 1)`（z_b92 图证：两颗点都在数字上方，且
            # `3` 已有高音点、不可能再带低音点）。去重后配对恢复 → `(3' 1')`。
            _dl = [c for c in inner if c["kind"] == "dot"]
            _seen = {id(c) for c in _dl}
            _dup = 0
            for c in _extra_dots.get(bar, []):
                if id(c) not in _seen:
                    _dl.append(c)
                    _seen.add(id(c))
                else:
                    _dup += 1
            if _dup:
                self.log("  ⚠ 点去重 第%d系统 第%d小节：剔掉 %d 颗重复点（救援路径与"
                         "点救援带各收一次）" % (si, bar, _dup))
            self.dots[(si, bar)] = _dl
            digs = [c for c in inner if c["kind"] == "glyph"]
            for c in digs:
                c["staff"] = "mel" if c["cy"] < bound else "bas"
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

    def _find_triplets(self):
        """找出**三连音括号**：把括号上的小号 `3` 与括号的两条水平段从谱面里摘掉，
        并记下每个括号覆盖的横向范围，供后面给组内音符打三连音标记。

        版面特征（三条**同时**满足；Bad Apple 实测零误判 —— 全文 52 个小号数字里
        只有 6 个命中，正好就是 6 个三连音标记）：
          ① 一个**小号数字**（h ≤ 0.85×字高）：正文音符都是满高 1.0×，标记只有 0.65×；
          ② 左右**各紧挨着一条水平段**（= 括号的两条横臂），实测 26~27px（Bad Apple）
             到 96~98px（Da Capo）不等；
          ③ 这条水平段**穿过数字的中段** —— 这一条把三连音标记和减时线彻底分开：
             减时线永远压在数字**下方**（Bad Apple 连八度点都印在减时线下方）。
        命中后标记改标 `tloop`、水平段改标 `tloopbar`。这两个 kind 都不进 `box`
        （_layout 只收 glyph/hline），于是
          · 伪和弦 `(3 6, 3)` / `(3 3 3)` 从源头消失（未处理时 16 个字形被当成 16 拍音符）；
          · 压在**下一行数字上方**的那条括号横线不会再被 eval_bar 当成减时线
            （否则整小节拍数凭空多 1 拍）。

        ⚠️ 括号横臂的长度**随排版变化很大**，而且常被阈值化切成 2~4 段同高、
        首尾相接的 `hline`（Da Capo 实测：左臂 = w33 + w66 两段，右臂 = w64 + w32）。
        所以先把**同高且相接**的水平段并成一条「臂」再判 —— 否则贴着数字的那一段
        只有 60 多 px、另一段却被当成别的；而弧（括号两端的钩）只与臂的**外端**
        相接，不并臂就永远配不上弧，括号横向范围会窄掉一半、组内音符漏标。
        """
        med_h, S = self.med_h, self.S
        self.triplets = []
        smalls = [c for c in self.items if c["kind"] == "glyph"
                  and c["h"] <= 0.85 * med_h and str(c.get("label", "")).isdigit()]
        if not smalls:
            return
        # 先把同高、首尾相接的 hline 并成一条「臂」（保留成员，命中后一起摘掉）
        raw = [c for c in self.items if c["kind"] == "hline" and c["h"] <= 5 * S]
        raw.sort(key=lambda c: (c["cy"], c["x0"]))
        arms = []
        for c in raw:
            # ⚠️ 必须按 x **顺序**相接才算同一条臂（`a.x1 <= c.x0 <= a.x1 + 2S`）。
            #    只写 `c.x0 - a.x1 <= 2S` 会把「排在前面的那条臂右边的、另一行
            #    同高（Δcy≤2S）的另一条臂」也并进来 —— Da Capo 实测 p1s5 的两组
            #    括号被并成一条 610px 的长条，整组超出臂长上限 → 一组括号全丢。
            if arms and abs(c["cy"] - arms[-1]["cy"]) <= 2 * S \
                    and arms[-1]["x1"] <= c["x0"] <= arms[-1]["x1"] + 2 * S:
                a = arms[-1]
                a["x1"] = max(a["x1"], c["x1"])
                a["y0"] = min(a["y0"], c["y0"])
                a["y1"] = max(a["y1"], c["y1"])
                a["w"] = a["x1"] - a["x0"] + 1
                a["cx"] = (a["x0"] + a["x1"]) // 2
                a["cy"] = (a["y0"] + a["y1"]) // 2
                a["members"].append(c)
            else:
                arms.append({"x0": c["x0"], "x1": c["x1"], "y0": c["y0"],
                             "y1": c["y1"], "w": c["w"], "cx": c["cx"],
                             "cy": c["cy"], "members": [c]})
        # 臂长上下限：太短是碎片；太长就已经不是括号臂（4 个 16 分的减时线 ≈3.6 字高）
        hls = [a for a in arms if 0.3 * med_h <= a["w"] <= 2.6 * med_h]
        arcs = [c for c in self.items if c["kind"] == "arc"]
        # ⚠️ 括号的「臂」不一定平 —— 《夜曲》用的是 `⌒3⌒`：两条臂本身就是**弧**，
        #    高 35px（远大于 5S=11.4，所以进不了 `raw`，被 classify 判成 `arc`）。
        #    只认 hline 就整组漏检：那颗 `3` 会以「小号数字」的身份混进 box，
        #    和紧邻的真音并成伪和弦 `(3 6)` → 该小节 4→4.25 拍。
        #    ⚠️ 弧形臂的判据**必须比平臂收紧**：平臂用「cy 落在数字中段」就够了，
        #    弧臂改成同一条会把三类东西全吃进来（旧曲 A/B 实测 3 首回归）：
        #      · 页眉英文/中文标题里紧挨的两个字母（cryforme `chita`、qifengle）
        #      · 连音弧：弧顶在数字**上方**（dacapo 4 处，弧 y578-612 而数字 y588-612）
        #    真正的括号臂是**从数字腰部往下钩**的：夜曲实测数字 y3863-3894（中腰 3878.5），
        #    两条臂都是 y3879-3913 —— 弧顶 3879 恰好压在中腰、且**不高于数字顶端**。
        #    所以判据 = 弧顶落在数字的**上半区** `[y0, y0 + 0.5h]`。这一条同时否掉
        #    「弧顶在数字上方」（连音弧、字母）与「弧顶已在数字下半」（减时线/八度点）。
        aas = [{"x0": c["x0"], "x1": c["x1"], "y0": c["y0"], "y1": c["y1"],
                "w": c["w"], "cx": c["cx"], "cy": c["cy"], "members": [c]}
               for c in arcs if 0.3 * med_h <= c["w"] <= 2.6 * med_h]

        def nbar(g, left):
            """标记数字左右两侧那条**穿过它中段**的臂（括号横臂，或弧臂）。"""
            ylo = g["y0"] + 0.22 * g["h"]
            yhi = g["y1"] - 0.22 * g["h"]
            got = []
            for L in hls:
                if left:
                    if not (L["x1"] <= g["x0"] and g["x0"] - L["x1"] <= 8 * S):
                        continue
                elif not (L["x0"] >= g["x1"] and L["x0"] - g["x1"] <= 8 * S):
                    continue
                if ylo <= L["cy"] <= yhi:
                    got.append(L)
            if not got:                       # 平臂没有 → 试弧形臂（夜曲 `⌒3⌒`）
                for L in aas:
                    if left:
                        if not (L["x1"] <= g["x0"] and g["x0"] - L["x1"] <= 8 * S):
                            continue
                    elif not (L["x0"] >= g["x1"] and L["x0"] - g["x1"] <= 8 * S):
                        continue
                    if g["y0"] <= L["y0"] <= g["y0"] + 0.5 * g["h"]:
                        got.append(L)
            if not got:
                return None
            return (max(got, key=lambda L: L["cx"]) if left
                    else min(got, key=lambda L: L["cx"]))

        def nend(L, left):
            """水平段再往外接的括号弧（弧体高、与横线同一水平）。"""
            got = []
            if any(L is a for a in aas):
                return None                   # 臂本身就是弧 → 没有「再往外接的弧」
            for a in arcs:
                if min(a["y1"], L["y1"]) - max(a["y0"], L["y0"]) \
                        < 0.5 * (L["y1"] - L["y0"] + 1):
                    continue
                if left:
                    if a["x1"] <= L["x0"] and L["x0"] - a["x1"] <= 6 * S:
                        got.append(a)
                elif a["x0"] >= L["x1"] and a["x0"] - L["x1"] <= 6 * S:
                    got.append(a)
            if not got:
                return None
            return (max(got, key=lambda a: a["cx"]) if left
                    else min(got, key=lambda a: a["cx"]))

        n = 0
        for g in smalls:
            lt, rt = nbar(g, True), nbar(g, False)
            if lt is None or rt is None:
                continue
            la, ra = nend(lt, True), nend(rt, False)
            self.triplets.append((la["x0"] if la else lt["x0"],
                                  ra["x1"] if ra else rt["x1"], rt["y1"]))
            g["kind"] = "tloop"
            for a in (lt, rt):                 # 一条臂可能是 2~4 段拼的，全摘
                for m in a["members"]:
                    m["kind"] = "tloopbar"
            n += 1
        if n:
            self.log(f"  三连音括号 {n} 个（标记 `3` 与括号横线已从谱面摘除）")

    def _tag_triplet_digits(self):
        """把落在三连音括号范围内的数字打上 `triplet` 标记（eval_bar 据此写 `*` 后缀）。

        归属判据：数字 cx 落在括号横向范围内、且 cy 在三连音标记**下方**，其中取
        **最靠上的一行**（= 括号所辖的那一行）。这一条把上下两行谱表分得很开 ——
        Bad Apple 实测：mel 括号底（y2385）离 mel 行 64px、离 bas 行 252px；
        bas 括号底（y2541）离 bas 行 96px、而 mel 行在它**上方**，两个方向都不串。
        """
        med_h, S = self.med_h, self.S
        digs = [d for (_s, _b, _t), v in self.box.items() for d in v["dig"]]
        for (x0, x1, yb) in self.triplets:
            cand = [d for d in digs if x0 - 2 * S <= d["cx"] <= x1 + 2 * S
                    and d["cy"] >= yb]
            if not cand:
                continue
            row = min(d["cy"] for d in cand)
            for d in cand:
                if abs(d["cy"] - row) <= 0.4 * med_h:
                    d["triplet"] = True

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

    def _staff_cands(self, digs):
        """双手分界的**候选**：[(bound, gap)]。数字 cy 一维聚类，切线两侧各需 ≥6 个数字。

        不加「两侧都要够多」这条，系统上方残留的段落号会抢走切线，
        把整条旋律判给低音手（实测过）。
        """
        S = self.S
        cys = sorted(d["cy"] for d in digs)
        if len(cys) < 12:
            return [((cys[0] + cys[-1]) / 2 if cys else 0, 0.0)]
        grp = [[cys[0]]]
        for c in cys[1:]:
            if c - grp[-1][-1] <= 12 * S:
                grp[-1].append(c)
            else:
                grp.append([c])
        cent = [sum(g) / len(g) for g in grp]
        n = [len(g) for g in grp]
        out = []
        for i in range(len(cent) - 1):
            if sum(n[:i + 1]) < 6 or sum(n[i + 1:]) < 6:
                continue
            out.append(((cent[i] + cent[i + 1]) / 2, cent[i + 1] - cent[i]))
        if not out:                       # 没有合法切线 → 退回最大间隙
            gi = max(range(len(cent) - 1), key=lambda i: cent[i + 1] - cent[i])
            out.append(((cent[gi] + cent[gi + 1]) / 2, cent[gi + 1] - cent[gi]))
        return out

    def _staff_bound(self, digs):
        """版面法默认分界 = 合法切线里**间隙最大**的那条（`Transcriber` 再按拍数复核）。"""
        return max(self._staff_cands(digs), key=lambda b: b[1])[0]

    @staticmethod
    def _bar_of_x(cols, x):
        """x 落在哪一小节（1 起）；落在所有小节线之外返回 None。"""
        for k in range(len(cols) - 1):
            if cols[k] < x < cols[k + 1]:
                return k + 1
        return None

    def _rescue_top(self, si, cols):
        """把**印在小节线上沿之上、但仍属于本系统某一行**的旋律音捞回来。

        《诀别书》p3s8 实测：该系统上声部的小节线只画到 y3635，而旋律行的 cy 中位
        是 3633（本来就只比上沿低 2px，全靠 `3*S≈6px` 的余量勉强收进来），
        末小节那颗带高音点的 `3'` 更是印在 cy3621 —— 比**同行的其他音**高 12px，
        正好被 `sy0 - 3*S` 挡在系统外、整颗丢掉。⚠️ **拍数查不出来**：它和同列的
        `1'` 成和弦，塞一颗音不改时值（216 小节·声部全绿也照样错）。

        ⚠️ **不能改成统一放宽上沿**（试过 `sy0 - 0.42*med_h`）：上一系统坠下来的
        音会跟着进来长伪和弦。也不能只看「正上方有一颗八度点」—— 实测那三处漏下来
        的音（起风了 p2s3/p3s2、Da Capo p1s4）**上面也都有点**。

        真正的分界是**离本系统某一行的距离**（实测四例，量纲都是字高）：

          · 《诀别书》p3s8：候选 cy3621，最近行 3633 → **12px = 0.27 字高**（同行）
          · 起风了 p2s3 ：候选 cy477 ，最近行 505  → **28px = 1.56 字高**（另一处物件）
          · 起风了 p3s2 ：候选 cy326 ，最近行 354  → **28px = 1.56 字高**
          · Da Capo p1s4：候选 cy2238，最近行 2310 → **72px = 1.60 字高**

        同行的排版抖动只有几 px，而「夹在两条谱表之间的孤立物件」至少差 1.5 字高，
        `0.5 × 字高` 这条线两边都很空。再叠两条便宜的护栏：只捞**满高**的数字
        （h ≥ 0.8 字高 → 小号的段落号 / 变拍号自动出局）且 label 是数字。

        ⚠️ **数字自己的八度点也要一起捞**，否则 `dot_map` 只看得见它**下方**那颗点：
        实测把 `3'` 单独捞回来、不带它的高音点，`3'` 会被读成 `3,`（`dot_map` 的
        「块内行间覆盖」把两行之间的点判给它），连带原地的 `1'` 也丢点变成 `1`
        —— 产物写成 `(3, 1) - - -`，比不救还糟。带上高音点后，「同一颗数字不可能
        同时带高、低八度点」的自相矛盾成立，既有的**竖排和弦按序配对救援**就会
        接手，把两颗点各归一位 → `(3' 1') - - -`。
        """
        S, med_h = self.S, self.med_h
        sy0, sy1 = self.spans[si - 1]
        lo = sy0 - SYS_PAD_TOP * med_h          # 上沿之上最多这么多（≈0.42 字高）
        hi = sy0 - 3 * S                        # 原本的收盒下界
        if hi <= lo:
            return []
        # 本系统「正常收进来」的数字行中心（与 `_staff_cands` 同一套聚类口径）
        cys = sorted(c["cy"] for c in self.items
                     if c["kind"] == "glyph" and hi <= c["cy"] <= sy1 + 3 * S
                     and cols[0] < c["cx"] < cols[-1])
        if not cys:
            return []
        cent, grp = [], [cys[0]]
        for c in cys[1:]:
            if c - grp[-1] <= 12 * S:
                grp.append(c)
            else:
                cent.append(sum(grp) / len(grp))
                grp = [c]
        cent.append(sum(grp) / len(grp))
        got = []
        for c in self.items:
            if c["kind"] != "glyph" or not (lo <= c["cy"] < hi):
                continue
            if c["h"] < 0.8 * med_h:            # 小号字（段落号 / 变拍号）不救
                continue
            if not str(c.get("label", "")).isdigit():
                continue
            if not (cols[0] < c["cx"] < cols[-1]):
                continue
            if self._bar_of_x(cols, c["cx"]) is None:
                continue
            if min(abs(c["cy"] - r) for r in cent) <= 0.5 * med_h:
                got.append(c)
        got += self._rescue_top_chain(si, cols, hi, got)
        if not got:
            return []
        for p in self.items:                    # 与救援音正对、印在上沿之上的八度点
            if p["kind"] != "dot":
                continue
            for c in got:
                if abs(p["cx"] - c["cx"]) <= 3 * S and 0 < c["y0"] - p["cy"] <= DOT_MAX * S:
                    got.append(p)
                    break
        return got

    def _rescue_top_chain(self, si, cols, hi, base):
        """「上沿救援」第二判据 —— 小节线是**短刻度**样式时用（《拂晓》实测）。

        有些谱把系统内的小节线画成一根固定 125px 的小竖杠、**居中于该谱表的
        最末一行**（花括号同样只罩住下半截）。这时 `find_systems` 由小节线得到的
        上沿会比谱表顶行低 1~2 整行：五行的谱表挡掉顶行、四行的挡掉顶两行，
        顶音（含三音/四音叠置的最上一音）整颗丢，而**拍数查不出来**（塞音不改时值）。
        `SYS_PAD_TOP` 的 0.42 字高只够 0.27~0.42 字高，够不着差一整行的顶音。

        判据（三条同时满足，**逐级链接**：可从已认定的数字往上一步步爬）：
          ① x 与**同一小节内**某个已收进系统的数字对齐（≤ COL_TOL 字高）；
          ② 纵向在那个数字**正上方**、且间距 ≤ GAP_CHAIN 字高；
          ③ 落在（上一系统底 + 0.5 字高，本系统上沿）之内 —— 上一系统坠下来的音
             隔着谱表间的大空隙，链接走不到（《拂晓》实测 122px = 2.77 字高 → 拒）。
        再叠两条护栏：只捞**满高**数字、且 label 是数字（段落号 / 变拍号自动出局）。
        页眉的曲目/改编信息同样落在上沿之上，但它在乐谱列上**没有同列数字**对得齐，
        ① 直接把它挡在门外（实测《拂晓》p1 右上角三行小字全部落选）。

        ⚠️ **另外三条护栏都是 A/B 回归逼出来的**（只按上面三条跑，10 首里 1 首误捞、
        1 首内容可疑、1 首出现重复音）：
          · **门控：上沿必须切进最上一行**（`|sy0 − 最上一行中心| ≤ CUT_TOL 字高`）。
            小节线的上端**合法**地停在两行之间的空档里是完全正常的排版；只有停在
            **某一行正中**才说明竖线被画短了、真实谱表顶行被挡在外面 —— 那才是本条
            判据要处理的情形。加上它，《夜曲》《Sincerely》不触发（上沿都在空档里）。
            ⚠️ **门控是逐系统判的，不是逐曲**：同一份谱里可以既有合法排版的系统
            （上沿离最上一行 −1.4 字高）、**也有**短刻度系统（+0.05~0.07 字高）——
            《经过》34 个系统里实测 **13 个触发**。所以「某某曲不触发」这种说法本身
            就不成立，回归必须逐曲看产物，不能看门控。
          · **被链接的对象也必须是满高数字**。`Sincerely` p2s4 的 `(40)` 段落号
            右括号 `)` 被 OCR 成 `1`（w13/h49），它正下方同列的是**拍号 `4/4` 的
            分子**（h30 = 0.67 字高）—— 三条判据全过，产物凭空多一颗 `1`。
            把「满高」这条从「只约束候选」扩到「也约束被链接的数字」，分子出局。
          · **候选池里要剔掉 `base`（第一判据已救回的字形）**。`base` 落在同一条
            救援带上、也在 `self.items` 里，不剔出去就会「链接」到下方某个已收数字
            而**二次追加**，产物里同一个音出现两遍（《诀别书》实测
            `(3' 1')` → `(3' 3' 1')`）。判据 = `id(c) not in {id(x) for x in base}`。
        """
        S, med_h = self.S, self.med_h
        sy0, sy1 = self.spans[si - 1]
        lo = sy0 - RESCUE_UP * med_h
        if si > 1:
            lo = max(lo, self.spans[si - 2][1] + 0.5 * med_h)
        if hi <= lo:
            return []
        insys = [c for c in self.items
                 if c["kind"] == "glyph" and hi <= c["cy"] <= sy1 + 3 * S
                 and cols[0] < c["cx"] < cols[-1]
                 and c["h"] >= 0.8 * med_h]
        if not insys:
            return []
        # 本系统**最上一行**（满高数字按 cy 聚类的第一簇，与 `_rescue_top` 同一口径）
        _cys = sorted(c["cy"] for c in insys)
        _top = [_cys[0]]
        for _y in _cys[1:]:
            if _y - _top[-1] <= 12 * S:
                _top.append(_y)
            else:
                break
        first_cy = sum(_top) / len(_top)
        # ⚠️ **门控**：只有「本系统上沿切进了最上一行」时才启用第二判据。
        # 小节线（系统起始竖线）**合法**的上端可以停在两行之间的空档里 —— 那种
        # 情况下「上沿之上还有一行音」是看不出来的（本质不可判定）；但小节线
        # **不可能**停在某一行的**正中**：那只能是竖线被画短了（《拂晓》的短刻度
        # 小节线，顶端只到旋律行中线，花括号也只罩下半截）。所以拿
        # `|sy0 − 最上一行中心| ≤ CUT_TOL 字高` 当「上沿被切短」的判据。
        # 实测：拂晓 36 个系统的上沿全部压在旋律行中线附近（3px 级、≤0.1 字高）。
        # ⚠️ 这条门控**逐系统**判：同一份谱里既有合法排版（离最上一行 −1.4 字高）、
        # 也有短刻度系统（+0.05~0.07 字高）——《经过》34 个系统里 13 个触发。
        # 「某曲不触发」这种记录是错的（曾据此写下「其余曲目 ≥1.4 字高」）；回归
        # 只能逐曲比产物，不能拿门控当免检牌。
        if abs(sy0 - first_cy) > CUT_TOL * med_h:
            return []
        # ⚠️ **段落号带必须排除**：`(N)` 印在系统上沿之上、左端，而且是**满高数字**，
        # 正好落进救援带。本谱三位数段落号的 `25)` 会越过首条小节线伸进第 1 小节
        # （`read_sections` 早就为此把上界松到 `left + 60S`），于是被当顶音捞回：
        # 《拂晓》实测 @113 凭空多一颗 `3`、@125 多出 `5` 与 `1`（@125 首小节本该是
        # `(3' 3)×3 (4' 4)`，被读成 `5 (1 3 3) …`，小节 5 拍）。
        #
        # ⚠️ 但**不能直接把整条带子砍掉**：`left + 60S` 这条宽带是 `read_sections`
        # 拿来**搜索**段落号的，右端要容下三位数的 `)`；而真实顶音就印在 `)` 紧右边
        # （《拂晓》p1s1 实测：`(1)` 的 `)` 在 x272、顶音 `1'` 在 x347，只差 75px
        # = 36S）。整条砍掉 → @1 丢 `1'`、多处丢和弦顶音（改这条时 A/B 当场暴露）。
        #
        # ✅ 用**组件串**判据：段落号是 `(` + 数字 + `)` **横向连续**的一串（实测串内
        # 相邻间距 19~32px = 9~15S 且 cy 齐平）；顶音与 `)` 之间隔着一整段空白
        # （36S，是串内间距的 2.4 倍）。只有**与括号同串**的候选才算段落号。
        # （`0`/`9` 这类窄字符常被 OCR 判成 `arc`，所以串要把 **arc** 也算进去，
        # 否则 `(101)` 的 `1` 会因中间夹着一颗弧而与串断开、被当顶音捞回。）
        pool = insys + list(base)
        # ⚠️ `base`（第一判据已救回的字形）就落在同一条带上，**它也在 `self.items` 里**
        # —— 若不从候选里剔掉，它会被「链接」到下方某个已收数字而**二次追加**，
        # 产物里同一个音出现两遍（《诀别书》实测 `(3' 1')` → `(3' 3' 1')`）。
        _base_ids = {id(c) for c in base}
        cand = [c for c in self.items
                if c["kind"] == "glyph" and lo <= c["cy"] < hi
                and cols[0] < c["cx"] < cols[-1]
                and c["h"] >= 0.8 * med_h
                and str(c.get("label", "")).isdigit()
                and id(c) not in _base_ids
                and self._bar_of_x(cols, c["cx"]) is not None]
        _vb = [c["cx"] for c in self.items if c["kind"] == "vbar"]
        left = min(_vb) if _vb else None
        if left is not None:
            _slo, _shi = sy0 - PAD_GAP * S, sy0 - 2 * S
            _band = sorted((c for c in self.items
                            if c["cx"] < left + 60 * S and _slo <= c["cy"] <= _shi),
                           key=lambda c: c["cx"])
            _linked = set()
            for _i, _c in enumerate(_band):
                if _i and _c["cx"] - _band[_i - 1]["cx"] <= 20 * S \
                        and abs(_c["cy"] - _band[_i - 1]["cy"]) <= 12 * S:
                    _linked.add(id(_c))
                    _linked.add(id(_band[_i - 1]))
            cand = [c for c in cand if id(c) not in _linked]
        got = []
        changed = True
        while changed:
            changed = False
            for c in list(cand):
                cbar = self._bar_of_x(cols, c["cx"])
                for di, d in enumerate(pool):
                    if self._bar_of_x(cols, d["cx"]) != cbar:
                        continue
                    if abs(c["cx"] - d["cx"]) > COL_TOL * med_h:
                        continue
                    if not 0 < d["cy"] - c["cy"] <= GAP_CHAIN * med_h:
                        continue
                    got.append(c)
                    pool.append(c)
                    cand.remove(c)
                    changed = True
                    break
        return got


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


def _dot_bottom(g, p, lines, S):
    """低音点的参考底线 = 数字底边，或它下方**横跨该点 x** 的最后一条减时线底边。

    有的谱面把八度点印在减时线**下方**（Bad Apple 实测）：一条减时线把点推到
    数字底边下 ~33px，两条推到 ~46px —— 恰好越过 DOT_MAX*S（20 × 2.286 = 45.7），
    于是同一份谱里「只差 0.7px」的系统保住点、差 1.3px 的系统整组丢点
    （p1s2 的 4 个十六分音符）。改按减时线的实际底边量，就与减时线条数无关了。

    ⚠️ 只能拿它做**救济判据**（`dd > DOT_MAX*S` 本该丢弃时再看一眼），**绝不能进排序分**：
    旋律行的减时线会把旋律数字的参考底边也推下去，让它"看起来"离下一行伴奏的低音点
    很近 —— 一旦用 `p.cy - _dot_bottom(...)` 当排序分，旋律数字就会抢走本该属于伴奏的
    低音点（Cry For Me 实测大面积 `3` → `3,`，共 54 处）。
    """
    base = g["y1"]
    for l in lines:
        if l["x0"] - 2 * S <= p["cx"] <= l["x1"] + 2 * S and \
                base <= l["y0"] <= p["cy"]:
            base = max(base, l["y1"])
    return base


def _arc_flat(L, arcs, S):
    """这条 hline 是不是**连音弧（圆滑线）的中段平顶**。

    印刷体的连音弧常画成「两头圆弧 + 中间一段直平线」的 `⎴`：阈值化后弧的两个
    弯头各成一颗 `arc`，平顶被切成 1~2 条同高、首尾相接的 `hline`。
    Da Capo 实测（p1 s4 b3 低音行 `4 4` 上方的连音弧）：
        arc(1896..1916) + hline(1917..1938) + hline(1939..1960) + arc(1961..1983)
    四段同高 y0≈2482。这些平顶的水平高度恰好等于该声部**另一行数字的行 cy**
    （实测 cy2483 vs 上行 `1` 的 cy2486，只差 3px）→ 被 eval_bar 当成增时线 `-`，
    一小节凭空多 2 拍。

    判据：hline 的 cy 与某条 `arc` 的**顶部**同高（弧在平顶处最直、y 最小），
    且与那条弧**横向相接**。真增时线压在数字行的 cy 上，圆弧顶在它上方约
    半个字高 —— 两者不会同高（实测差 22px = 0.5 字高，阈值 4S 有 2.5 倍余量）。
    """
    for a in arcs:
        if abs(a["y0"] - L["cy"]) > 4 * S:
            continue
        if (a["x1"] <= L["x0"] and L["x0"] - a["x1"] <= 8 * S) \
                or (a["x0"] >= L["x1"] and a["x0"] - L["x1"] <= 8 * S):
            return True
    return False


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
        lines = [l for (s, b, t), v in pg.box.items() if s == si and b == bar
                 for l in (v.get("line") or [])]
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
                    # 否则隔壁数字**上方**的高音点会落进窄数字（如 `1`）的 a 窗。
                    # ⚠️ 曾试过放宽到 20S 并加「点不落在其他数字横向范围（±3S）」
                    # 的排除，想救《Sincerely》里离窄字符 27.5px 的那类附点
                    # —— **实测失败**：拍数错从 2/118 暴涨到 25/118。根因是下面
                    # `if ac:` 的优先级：某颗八度点只要多出一个 a 候选，就整颗从
                    # `U`/`D` 改判成附点；而 a 的纵向条件（落在数字 y 范围内）
                    # 本来就能被**贴着数字上沿**的点满足，横向排除式挡不住斜对角。
                    # ⇒ 要救这类附点请走「拍数配平」（有唯一解约束），别动这里。
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
            if t == "a" or dd <= DOT_MAX * S or \
                    (t == "D"
                     and p["cy"] - _dot_bottom(g, p, lines, S) <= OCT_BEAM_GAP * S):
                out.setdefault(id(g), []).append(t)
        # ⚠️ 竖排和弦的「按序配对」救援 —— 只在出现**自相矛盾**时才启用。
        # 一颗数字不可能**同时**带高八度点与低八度点；一旦出现（`out[x]` 里
        # 同时有 `U` 和 `D`），说明「离哪条边近就给谁」这列上行不通：竖排和弦
        # 里相邻两个数字只隔 ~0.9 字高，八度点正落在两者之间的空档，到上数字
        # 底边与到下数字顶边只差 2px（实测 39 vs 41、38 vs 41）——纯属硬币面。
        # Da Capo 实测（p2 s4 b2 低音行的琶音和弦 `5 2 1`）：三颗点被「就近」
        # 法全判给上面那个数字 → `5` 拿到 U+D、`2` 拿到 D、`1` 一颗没有 →
        # 产物写出 `5',`（**不合法**，一颗音两个方向）与 `2,`。按序配对后三颗
        # 点各自落在其数字上方 40px、间距与数字完全同步 → `5' 2' 1'`。
        # 采纳条件四条缺一不可：① 该列**确实矛盾**；② 该列范围内点的个数与
        # 数字个数**相等**；③ 每颗点都**落在所有数字的墨块之外**（不沾笔画）；
        # ④ 按序配对后方向**一致**（全是 U 或全是 D，不会左右横跳）。
        for st in ("mel", "bas"):
            gs = sorted([g for g in glyphs if g.get("staff") == st],
                        key=lambda g: g["cx"])
            groups, cur = [], []
            for g in gs:
                if cur and g["cx"] - cur[-1]["cx"] > 6 * S:
                    groups.append(cur)
                    cur = []
                cur.append(g)
            if cur:
                groups.append(cur)
            for col in groups:
                if len(col) < 2:
                    continue
                col.sort(key=lambda g: g["cy"])
                if not any("U" in out.get(id(g), []) and "D" in out.get(id(g), [])
                           for g in col):
                    continue
                cxm = _median([g["cx"] for g in col])
                band0 = min(g["y0"] for g in col) - 1.1 * pg.med_h
                band1 = max(g["y1"] for g in col) + 1.1 * pg.med_h
                ds = [p for p in pg.dots.get((si, bar), [])
                      if abs(p["cx"] - cxm) <= 6 * S
                      and band0 <= p["cy"] <= band1]
                if len(ds) != len(col):
                    continue
                ds.sort(key=lambda p: p["cy"])
                if not all(p["y1"] < g["y0"] - S or p["y0"] > g["y1"] + S
                           for p in ds for g in col):
                    continue
                up = all(p["cy"] < g["cy"] for p, g in zip(ds, col))
                dn = all(p["cy"] > g["cy"] for p, g in zip(ds, col))
                if not (up or dn):
                    continue
                tag = "U" if up else "D"
                self.log("  ⚠ 竖排和弦八度点按序配对 p%d s%d b%d %s "
                         "x%d：%s（就近法自相矛盾）"
                         % (pg.sh.page, si + 1, bar,
                            st, int(cxm), " ".join(g["label"] for g in col)
                            + " → " + " ".join(g["label"] + ("'" if up else ",")
                                               for g in col)))
                for g in col:
                    out.pop(id(g), None)
                for _p, g in zip(ds, col):
                    out.setdefault(id(g), []).append(tag)
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
        # ⚠️ 同一条「弧平顶 ≠ 减时线」也要挡（《Sincerely》实测）：本行的 beam 搜索
        # 窗很深（ry1 + 34S ≈ 数字底往下 75px），**下一行声部的连音弧平顶**会落进来
        # —— 弧顶离数字底 60px（数字底 886、弧顶 946-948），厚度 3px 也过闸。它横跨
        # 两三个数字列（实测 x1072-1150 正好压住 `1 2`、x1375-1453 压住 `1 1`）→ 这两
        # 列凭空多一条减时线 → 16 分误作 32 分（一小节少 0.625 拍）。与增时线那边
        # （见 dashes 的同一判据）是**同一个字形**，用同一个 `_arc_flat` 挡掉，
        # ⚠️ 但 `_arc_flat` 只认「与 arc 横向相接」的那一段，弧平顶被切多段时后续
        # 全部漏网 —— 所以实际过滤在下面用**链式**判据一次做完（含 `_arc_flat` 首判）。
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
        # ⚠️ **弧平顶被切成多段 hline** 时，`_arc_flat` 只能认出**紧贴弧头**的那一段
        # （它的判据要求与 arc **横向相接**，±8S）。同一条弧的后续平顶段与弧头之间
        # 隔着一两段 hline，全部漏网。《拂晓》实测：`arc x350-385` + 5 段同高
        # （cy1566）hline 一直铺到 x920，横跨 535px = 整个小节 → 每一列都与它横向
        # 重叠 ≥4S → **每列凭空多一条减时线**（附点四分误作附点八分、八分误作十六分、
        # 四分误作八分），一小节整体少 1.5 拍，而**拍数除不尽 4 看不出来**
        # （2.5 拍的音型在别的曲子里合法）。
        # 补一条**链式**判据：与「已认定为弧平顶」的线同高（|Δcy| ≤ 2S）且横向相邻
        # （间隙 ≤ 8S）→ 同属一条弧。按 x 排序单遍传播（无需递归）。
        # 真减时线不受影响：它贴在数字底边下方约 6S，而弧平顶在数字底边下方 20S+
        # （实测 1524 vs 1566，差 42px = 20S，frozenset 阈值 2S 有 10 倍余量）。
        _flat_ids, _flats = set(), []
        for L in sorted(beams, key=lambda l: l["x0"]):
            if _arc_flat(L, pg.arcs, S) or any(
                    abs(M["cy"] - L["cy"]) <= 2 * S
                    and max(M["x0"], L["x0"]) - min(M["x1"], L["x1"]) <= 8 * S
                    for M in _flats):
                _flat_ids.add(id(L))
                _flats.append(L)
        beams = [L for L in beams if id(L) not in _flat_ids]
        # ⚠️ 容差用 `DASH_ROW_TOL_F`（=3S）而不是旧的 12S：增时线一定压在**数字行的
        # 中线**上（实测 700+ 条全部 ≤1.05S），12S 会放进「弧平顶」冒充的第 4 条 `-`
        # （见常量区注释与 `zz_37b1_all.png`）。
        dashes = [L for L in lines if dash_cys
                  and min(abs(L["cy"] - c) for c in dash_cys) <= DASH_ROW_TOL_F * S
                  and 8 * S <= L["w"] <= 45 * S
                  and L["y1"] - L["y0"] + 1 <= 5 * S
                  and not _arc_flat(L, pg.arcs, S)]
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
            # 三连音：整列只要沾上括号就是 `*`（时值 ×2/3）。同一三连音组里各音的
            # 减时线条数相同，所以「一列」就是「一个组员」。
            trip = any(d.get("triplet") for d in col["mem"])
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
            if trip:
                tok += "*"
            dur = (1.0 / (2 ** nb_c)) * (1.5 if aug else 1.0)
            if trip:
                dur *= 2.0 / 3.0
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
        lines = [l for (s, b, t), v in pg.box.items() if s == si and b == bar
                 for l in (v.get("line") or [])]
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
            if t != "a" and dd > DOT_MAX * S and not (
                    t == "D"
                    and p["cy"] - _dot_bottom(g, p, lines, S) <= OCT_BEAM_GAP * S):
                out.append(p)
        return out

    def _pick_bounds(self, beats):
        """按「拍数误差最小」在候选双手分界线里复核，而不是只看版面最大间隙。

        ⚠️ 版面间隙法有个已知翻边：某声部在**整个系统里只出现一两颗音**（稀疏行）
        又贴得离旋律行很近时，真正的谱表间隔会被这条稀疏行切成两段，反而输给
        伴奏块内部的行距。实测《诀别书》p3s3：三组间隙 44.8 / 65.4 / 66.6，选了
        66.6 → 伴奏的上声部整排判给旋律，且 mel 的「数字行下沿」被稀疏行拖到
        伴奏行 → 减时线搜索窗整体下移、一条都找不到 → 每小节 6 拍（本应 4 拍）。
        同素材的 p2s1 因为稀疏行恰好离得远（114.8）才没中招 —— 说明**几何本身
        不足以定案**，得用印刷谱自己的硬约束：每小节拍数必须严格等于拍号。

        评分相同时保留版面法的原选择 → 只有真有错小节的系统才可能改动。
        """
        n_chg = 0
        for pi, pg in enumerate(self.pages):
            for si in range(1, pg.n_sys + 1):
                inner_of = pg.sysinner.get(si)
                if not inner_of:
                    continue
                digs = [c for inner in inner_of.values() for c in inner
                        if c["kind"] == "glyph"]
                if not digs:
                    continue
                cands = pg._staff_cands(digs)
                if len(cands) < 2:
                    continue
                default = max(cands, key=lambda b: b[1])[0]

                def score(bound):
                    pg._bind_system(si, bound, inner_of)
                    for k in [k for k in self._dotcache if k[:2] == (pi, si)]:
                        del self._dotcache[k]
                    tot = 0
                    for (s, bar) in pg.bars:
                        if s != si:
                            continue
                        exp = pg.meters.get((si, bar), beats)
                        for st in ("mel", "bas"):
                            b, _ = self.eval_bar(pi, si, bar, st)
                            tot += abs(b - exp)
                    return tot

                # 平局优先「间隙更大」= 版面法原选择，保证无错系统逐字节不变
                scored = sorted(((score(b), -g, b) for b, g in cands))
                best_score, _, best_b = scored[0]
                pg._bind_system(si, best_b, inner_of)
                for k in [k for k in self._dotcache if k[:2] == (pi, si)]:
                    del self._dotcache[k]
                if abs(best_b - default) > 1e-9:
                    n_chg += 1
                    self.log("  ⚠ 双手分界复核 p%d s%d：版面间隙法选 %.1f → 改 %.1f"
                             "（剩余拍数误差 %.2f）" % (pi + 1, si, default, best_b,
                                                    best_score))
        if n_chg:
            self.log(f"  双手分界按拍数复核：改动 {n_chg} 个系统")

    def run(self, beats=4.0):
        t0 = time.time()
        pages = self.pages
        repairs = []
        keys = sorted({(pi, si, bar) for pi, pg in enumerate(pages) for (si, bar) in pg.bars})
        self._pick_bounds(beats)
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
                    # ⚠️ `staff` 必须**在试算之前**就切过去。`dot_map` 按 `staff`
                    # 分组（竖排和弦的八度点归属），而 `eval_bar` 走的是 box 列表；
                    # 两者若不同步，试算期间算出的结果会被写进 `_dotcache`，等到
                    # 试算成功、循环退出后就没有任何调用再重算 —— 输出直接命中
                    # 这份**按旧归属算出的**陈旧缓存（Da Capo p2 s4 b2 实测：
                    # 低音行 `5` 早已移入 bas，却仍按 mel 分组 → 八度点全判给
                    # 上面那个音 → 写出非法的 `5',`）。
                    d["staff"] = other
                    self._dotcache.pop((pi, si, bar), None)
                    nm, _ = self.eval_bar(pi, si, bar, "mel")
                    nb_, _ = self.eval_bar(pi, si, bar, "bas")
                    if abs(nm - exp) + abs(nb_ - exp) < \
                       abs(tm - exp) + abs(tb - exp):
                        hit = (st, other, d, tm, tb, nm, nb_)
                        break
                    pg.box[(si, bar, st)]["dig"].append(d)
                    pg.box[(si, bar, other)]["dig"].remove(d)
                    d["staff"] = st
                    self._dotcache.pop((pi, si, bar), None)
                if hit is None:
                    break
                st, other, d, tm, tb, nm, nb_ = hit
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
                # ⚠️ 试过在这里做优先级：让「有孤儿点 → 加附点」（直接证据）压过
                # 「有厚粘连尸体 → 减一条线」（间接证据），想救《Sincerely》那两处
                # 附点 —— **没生效**（产物逐字节不变）。说明那两处的点连
                # `_unattributed_dots` 都没当成孤儿（很可能压根没进 `pg.dots`，
                # 而不是没进窗口 [x-4S, x+22S]）。⇒ 想走这条路，先确认孤儿点
                # 真的存在，别从 `dot_map` 的推理去断言。
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


def head_beats(head):
    """从首行 `1=C 6/8 116` 解析**每小节拍数**，口径 = 「四分音符 = 1 拍」。
    ⚠️ 必须乘 4 ÷ 分母：6/8 = 6×4÷8 = 3（拍/小节）。4/4 碰巧等于分子，
    曾因此写错两处 —— ① `run()` 的默认参数 4.0 从不读 head；② `self_check`
    直接拿分子当拍数（`beats = float(分子)`）。对 4/4 无影响，对 6/8 双双
    全曲报废（《经过》实测 272/272 全 ✗，且双手分界/拍数配平按错期望工作）。"""
    m = re.search(r"\b(\d+)\s*/\s*(\d+)\b", head)
    if not m:
        return 4.0
    return float(m.group(1)) * 4.0 / float(m.group(2))


def self_check(rows, pages, head, sections, log):
    beats = head_beats(head)
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
    rows, repairs = tr.run(head_beats(head))
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
