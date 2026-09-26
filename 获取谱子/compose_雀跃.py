# -*- coding: utf-8 -*-
"""
原创曲《雀跃》—— 单声部哼唱，大调，4/4，灵动活泼
生成 scores/雀跃-原创.txt（可直接被 main.py / parser.py 读取演奏）

沿用的用户约束
--------------
1. 谱面只允许使用中音组与高音组共 14 个键位（asdfghj + qwertyu），
   低音组 zxcvbnm 一个都不能出现；
2. 演唱乐器仅限人声，不使用任何其他乐器伴奏 —— 落到谱面上就是
   **单声部**：每行只按 1 个键，全曲 0 个和弦。

怎么在「单声部」里做出「更丰富」
--------------------------------
没有和声可铺，丰富度只能从线条内部来：

· 十六分跑动为主 —— 单线条也能「满」起来（《独吟》是慢吟，本曲密度约 4 倍）；
· 音区交替做**隐伏低音线** —— 旋律主体在高音组，句尾落到中音组当落点，
  单声部听出两个层次（对比段甚至一路下探到中音组最低的 C4 再跳回高音组）；
· 用满全部 14 个允许键位，音域跨 23 个半音（C4 ~ B5）；
· 三种触键对比 —— 连奏（按满时值）/ 长音（句尾重音）/ **断音点音**（只按 70 毫秒），
  断音让快速的音型有「跳」起来的感觉。断音出现在三处并形成呼应：
  变奏段的整句点音（第 15 小节）、同一句上行冲高的点音（第 16 小节末拍）、
  尾句推进到主音前两个八分的点音（第 43 小节末拍）；
· 材料更多：17 段不同的两小节乐句，靠模进、加花、再现变奏串成 44 小节；
· 调式色彩三段变化：主调 → 属方向（强调下属音）→ 华彩段回到主调收束。

音乐设计
--------
· 曲风：灵动的单声部哼唱 / 雀跃的民谣性快板，像一个人边走边唱、脚步轻快。
· 速度：1 格 = 十六分音符 = 110 毫秒（四分 440 毫秒 ≈ 每分钟 136 拍），
  快板但不赶，十六分跑动落在手上是舒服的。
· 小节：4/4 拍，每小节 16 格。
· 结构：引子 4 + 主题 8 + 变奏 8 + 对比 8 + 华彩 4 + 再现 8 + 尾句 4 = 44 小节，
  约 77 秒。
· 旋律走向：快速上行起句（动机是「上-上-落」的三音组）→ 雀跃动机反复模进上移
  → 断音跳跃句 → 低音区下探 + 切分节奏作对比 → 十六分华彩上下跑动
  → 主题加花再现 → 上行冲高后落在主音收束。

级数与按键对应（只用中音组与高音组）
    级数   1    2    3    4    5    6    7
    中音组 a    s    d    f    g    h    j      (C4..B4)
    高音组 q    w    e    r    t    y    u      (C5..B5)
    低音组 z    x    c    v    b    n    m      (C3..B3) ← 本曲禁用，一个都不出现

旋律主体落在高音组（C5~B5），句尾与对比段下探到中音组（C4~B4）当落点 ——
单声部音区交替，能听出「上面一条线 + 下面一条线」的层次（隐伏低音线）。
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "scores" / "雀跃-原创.txt"

TITLE = "雀跃"

PER_BAR = 16           # 4/4：每小节 16 个十六分音符
INTERVAL = 110         # 一个十六分音符（毫秒）→ 四分 440 毫秒 ≈ 136 BPM
GAP = 10               # 与 parser.HOLD_GAP_MS 一致
HOLD_MIN = 50          # 与 parser.DEFAULT_HOLD_MS 一致
HOLD_MAX = 2000        # 与 midi_to_score.py 的 --hold-max 默认值一致
HOLD_LAST = 1400       # 最后一个音拖长收尾
SHORT_MS = 70          # 断音（点音）：只按这么短，剩下的格子松手

# 用户约束：只允许这 14 个键位（中音组 + 高音组）。本曲一个低音组的键都不使用。
ALLOWED = "asdfghj" + "qwertyu"
FORBIDDEN = "zxcvbnm"
ORDER = FORBIDDEN + ALLOWED     # 琴上的按键顺序：低音组 → 中音组 → 高音组

_PITCH = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71,
          72, 74, 76, 77, 79, 81, 83]
SEMITONE = dict(zip(ORDER, _PITCH))

# 级数 → 按键（八度 4 = 中音组，八度 5 = 高音组）
DEGREE_KEY = {(d, o): ALLOWED[(o - 4) * 7 + d - 1]
              for o in (4, 5) for d in range(1, 8)}

L, M = 4, 5            # L = 中音组（做低音落点），M = 高音组（做旋律主体）


def n(g, d, o=M):
    """连奏音：占 g 格，按住整个时值"""
    return (g, d, o, "full")


def s(g, d, o=M):
    """断音（点音）：占 g 格，但只按 SHORT_MS，其余格子松手 → 跳起来"""
    return (g, d, o, "short")


def r(g):
    """休止：占 g 格（换气口，键已松开）"""
    return (g, None, None, None)


# ---------------------------------------------------------------- 曲子本体
# 每个乐句 = 2 小节 = 32 格。一个小节 16 格（4 拍 × 4 个十六分），
# 注释里的竖线就是拍的位置，方便核对格数。

# ---- 引子 (1-4)：快速上行起句，三次上探、两次冲最高音 ----
I1 = [
    # 小节 1：E5 G5 A5 G5 | E5 G5 A5 | G5 A5 B5 | A5
    [n(1, 3), n(1, 5), n(1, 6), n(1, 5),
     n(1, 3), n(1, 5), n(2, 6),
     n(1, 5), n(1, 6), n(2, 7),
     n(4, 6)],
    # 小节 2：G5 E5 D5 | C5 D5 E5 | G5 E5 | C5 + 气口
    [n(1, 5), n(1, 3), n(2, 2),
     n(1, 1), n(1, 2), n(2, 3),
     n(2, 5), n(2, 3),
     n(2, 1), r(2)],
]

I2 = [
    # 小节 3：A5 B5 A5 G5 | E5 G5 A5 | B5 A5 | G5
    [n(1, 6), n(1, 7), n(1, 6), n(1, 5),
     n(1, 3), n(1, 5), n(2, 6),
     n(2, 7), n(2, 6),
     n(4, 5)],
    # 小节 4：E5 D5 C5 | D5 E5 G5 | E5 C5 | C5 + 气口
    [n(1, 3), n(1, 2), n(2, 1),
     n(1, 2), n(1, 3), n(2, 5),
     n(2, 3), n(2, 1),
     n(2, 1), r(2)],
]

# ---- 主题 (5-12)：雀跃动机「do-mi-sol-mi」反复 + 上行模进 + 低音落点 ----
A1 = [
    # 小节 5：C5 E5 G5 E5 | C5 E5 G5 | A5 G5 E5 | D5 C5
    [n(1, 1), n(1, 3), n(1, 5), n(1, 3),
     n(1, 1), n(1, 3), n(2, 5),
     n(1, 6), n(1, 5), n(2, 3),
     n(2, 2), n(2, 1)],
    # 小节 6：E5 G5 E5 C5 | F4 C5（下探中音组当落点）| D5 E5 D5 C5 | C5 + 气口
    [n(1, 3), n(1, 5), n(1, 3), n(1, 1),
     n(2, 6, L), n(2, 1),
     n(1, 2), n(1, 3), n(1, 2), n(1, 1),
     n(2, 1), r(2)],
]

A2 = [
    # 小节 7：整体上移三度做模进（E5 G5 B5 G5 | …）
    [n(1, 3), n(1, 5), n(1, 7), n(1, 5),
     n(1, 3), n(1, 5), n(2, 7),
     n(1, 6), n(1, 5), n(2, 3),
     n(2, 4), n(2, 3)],
    # 小节 8：G5 B5 G5 E5 | C5 E5 | D5 E5 F5 G5 | E5 + 气口
    [n(1, 5), n(1, 7), n(1, 5), n(1, 3),
     n(2, 1), n(2, 3),
     n(1, 2), n(1, 3), n(1, 4), n(1, 5),
     n(2, 3), r(2)],
]

A3 = [
    # 小节 11：主题收束，落主音
    [n(1, 1), n(1, 3), n(1, 5), n(1, 6),
     n(1, 5), n(1, 3), n(2, 1),
     n(1, 2), n(1, 3), n(2, 5),
     n(2, 3), n(2, 2)],
    # 小节 12：上行后落中音组五级再回主音，末尾一小格气口
    [n(1, 1), n(1, 2), n(1, 3), n(1, 5),
     n(1, 3), n(1, 2), n(2, 1),
     n(2, 5, L), n(2, 1),
     n(3, 1), r(1)],
]

# ---- 变奏 (13-20)：主题加花 + 一整句断音跳跃 ----
A4 = [
    # 小节 13：主题前半 + 十六分加花（每拍四个音，跑起来）
    [n(1, 1), n(1, 3), n(1, 5), n(1, 3),
     n(1, 1), n(1, 2), n(1, 3), n(1, 5),
     n(1, 6), n(1, 5), n(1, 6), n(1, 7),
     n(2, 6), n(2, 5)],
    # 小节 14：回落 + 中音组落点
    [n(1, 3), n(1, 1), n(1, 3), n(1, 5),
     n(2, 6, L), n(2, 1),
     n(1, 2), n(1, 3), n(1, 2), n(1, 7, L),
     n(2, 1), r(2)],
]

A5 = [
    # 小节 15：整句断音（点音）—— 蹦跳感，和前后连奏句形成对比
    [s(1, 5), s(1, 3), s(1, 5), s(1, 3),
     s(2, 1), s(2, 3),
     s(1, 6), s(1, 7), s(1, 6), s(1, 5),
     s(2, 3), r(2)],
    # 小节 16：八分起句 + 断音点音冲高（D5 E5 G5 B5 一个个蹦上去）再落 A5^4
    [n(1, 1), n(1, 3), n(1, 5), n(1, 6),
     n(2, 5), n(2, 3),
     s(1, 2), s(1, 3), s(1, 5), s(1, 7),
     n(4, 6)],
]

A6 = [
    # 小节 19：级进上行冲高
    [n(1, 3), n(1, 5), n(1, 6), n(1, 7),
     n(2, 6), n(2, 5),
     n(1, 3), n(1, 4), n(1, 5), n(1, 6),
     n(4, 7)],
    # 小节 20：落回后停在属音上，留气口接下一段
    [n(1, 6), n(1, 5), n(1, 3), n(1, 2),
     n(2, 3), n(2, 5),
     n(2, 6), n(2, 7),
     n(2, 7), r(2)],
]

# ---- 对比段 (21-28)：转属方向，强调下属音；切分节奏 + 中音组下探 ----
B1 = [
    # 小节 21：属音起句，强调下属音（大调里最跳的音级）
    [n(1, 5), n(1, 7), n(1, 6), n(1, 5),
     n(2, 4), n(2, 5),
     n(1, 3), n(1, 2), n(1, 3), n(1, 4),
     n(4, 5)],
    # 小节 22
    [n(1, 6), n(1, 5), n(1, 4), n(1, 2),
     n(2, 3), n(2, 5),
     n(1, 2), n(1, 1), n(1, 2), n(1, 4),
     n(2, 5), r(2)],
]

B2 = [
    # 小节 23：高音组一路下探到中音组最低音 C4，再跳回高音组 —— 隐伏低音线
    [n(1, 5), n(1, 3), n(1, 2), n(1, 1),
     n(1, 5, L), n(1, 4, L), n(1, 3, L), n(1, 2, L),
     n(2, 1, L), n(2, 1),
     n(2, 2), n(2, 7, L)],
    # 小节 24：回到高音组
    [n(2, 1), n(2, 3),
     n(2, 5, L), n(2, 1),
     n(1, 2), n(1, 3), n(1, 5), n(1, 3),
     n(2, 1), r(2)],
]

B3 = [
    # 小节 25：切分节奏（长-短-短），跳着走
    [n(2, 3), n(1, 5), n(1, 5),
     n(2, 6), n(1, 5), n(1, 3),
     n(2, 2), n(1, 3), n(1, 2),
     n(4, 1)],
    # 小节 26：上行后跳到中音组，末尾气口
    [n(2, 2), n(1, 3), n(1, 4),
     n(2, 5), n(1, 6), n(1, 5),
     n(1, 4), n(1, 3), n(1, 2), n(1, 7, L),
     n(3, 5), r(1)],
]

B5 = [
    # 小节 27：级进下行，把调性带回主调
    [n(1, 5), n(1, 4), n(1, 3), n(1, 1),
     n(2, 2), n(2, 3),
     n(2, 4), n(2, 3),
     n(2, 2), n(2, 1)],
    # 小节 28：落主音 + 气口
    [n(1, 3), n(1, 2), n(1, 1), n(1, 7, L),
     n(2, 1), n(2, 2),
     n(2, 3), n(2, 5),
     n(2, 1), r(2)],
]

# ---- 华彩 (29-32)：整小节十六分跑动，把张力推到最高音 ----
C1 = [
    # 小节 29：上行音阶冲高再回落（全十六分）
    [n(1, 1), n(1, 2), n(1, 3), n(1, 4),
     n(1, 5), n(1, 6), n(1, 7), n(1, 6),
     n(1, 5), n(1, 6), n(1, 5), n(1, 3),
     n(1, 2), n(1, 3), n(2, 1)],
    # 小节 30：琶音上下行，末尾一小格气口
    [n(1, 1), n(1, 3), n(1, 5), n(1, 7),
     n(1, 6), n(1, 5), n(1, 3), n(1, 1),
     n(1, 2), n(1, 4), n(1, 6), n(1, 5),
     n(1, 4), n(1, 2), n(1, 7, L), r(1)],
]

C2 = [
    # 小节 31：三音组模进上行 —— 同样的音型往上挪三次
    [n(1, 3), n(1, 5), n(2, 7),
     n(1, 6), n(1, 5), n(2, 3),
     n(1, 4), n(1, 6), n(2, 5),
     n(2, 6), n(2, 7)],
    # 小节 32：停在最高音，留气口
    [n(2, 7), n(1, 6), n(1, 5),
     n(2, 3), n(2, 5),
     n(1, 6), n(1, 7), n(1, 6), n(1, 5),
     n(2, 7), r(2)],
]

# ---- 再现收尾句 (39-40) ----
A7 = [
    # 小节 39：主题冲高到最高音
    [n(1, 1), n(1, 3), n(1, 5), n(1, 6),
     n(2, 7), n(1, 6), n(1, 5),
     n(1, 6), n(1, 5), n(1, 3), n(1, 2),
     n(4, 5)],
    # 小节 40：落主音 + 气口
    [n(1, 3), n(1, 2), n(2, 1),
     n(1, 2), n(1, 3), n(2, 5),
     n(2, 3), n(2, 2),
     n(2, 1), r(2)],
]

# ---- 尾句 (41-44)：上行冲高后落在主音收束 ----
F1 = [
    # 小节 41：上行音阶 + 冲到最高音
    [n(1, 1), n(1, 3), n(1, 5), n(1, 6),
     n(1, 7), n(1, 6), n(2, 5),
     n(1, 3), n(1, 5), n(1, 6), n(1, 7),
     n(2, 6), n(2, 5)],
    # 小节 42：回落 + 中音组落点 + 一小格气口
    [n(1, 3), n(1, 2), n(2, 1),
     n(2, 5, L), n(2, 1),
     n(1, 2), n(1, 3), n(1, 5), n(1, 6),
     n(2, 7), n(1, 6), r(1)],
]

F2 = [
    # 小节 43：最后一次雀跃动机，末尾两个八分改断音点音，蹦着推进到主音收束
    [n(1, 5), n(1, 3), n(1, 5), n(1, 7),
     n(1, 6), n(1, 5), n(1, 3), n(1, 1),
     n(1, 2), n(1, 3), n(2, 5),
     s(2, 3), s(2, 2)],
    # 小节 44：落主音，全曲收束
    [n(1, 1), n(1, 3), n(1, 5), n(1, 3),
     n(2, 1), n(2, 5, L),
     n(1, 1), n(1, 3), n(2, 1),
     n(4, 1)],
]

SONG = [
    ("引子：快速上行起句", I1 + I2),
    ("第一段（主题）：", A1 + A2 + A1 + A3),
    ("第二段（变奏加花）：", A4 + A5 + A4 + A6),
    ("第三段（对比）：", B1 + B2 + B3 + B5),
    ("华彩（十六分跑动）：", C1 + C2),
    ("第一段再现：", A1 + A2 + A4 + A7),
    ("尾句：", F1 + F2),
]


# ---------------------------------------------------------------- 展开与写出

def render():
    """
    把 SONG 展开成逐行曲谱数据 [(间隔, [按键], 备注)]，每个事件占 g 行。

    行的三种身份（备注里的 kind）：
      note    一个音的第一行 —— 发声，记下名义时值 dur_cells 与触键 touch
      sustain 音的后续行 —— 键还按着，没有新的起音
      breath  休止行 —— 键已松开，真静默（换气口）
    """
    rows = []
    for sec, bars in SONG:
        for bar in bars:
            cells = sum(g for g, _d, _o, _t in bar)
            if cells != PER_BAR:
                raise ValueError(f"「{sec}」有一小节是 {cells} 格，应为 {PER_BAR} 格")
            bar_no = len(rows) // PER_BAR + 1
            for g, d, o, touch in bar:
                key = DEGREE_KEY[(d, o)] if d else None
                for k in range(g):
                    if not key:
                        kind, hit = "breath", None
                    elif k == 0:
                        kind, hit = "note", key
                    else:
                        kind, hit = "sustain", None
                    rows.append((INTERVAL, [hit] if hit else [],
                                 {"bar": bar_no, "cell": k, "sec": sec, "key": hit,
                                  "kind": kind, "dur_cells": g, "touch": touch}))
    # 末尾剩下的延长行只是把时间轴推到最后，并不发声 —— 去掉，让文件收在末音上
    while rows and not rows[-1][1]:
        rows.pop()
    return rows


def to_lines(rows):
    """
    逐行算按住时长 → 文本行。

      连奏：按住 = 本音自己的时值 − GAP
      断音：按住 = SHORT_MS（固定短促，剩下的格子松手静默）

    同时受「到下一个发声行 − GAP」这个**时间安全上限**约束（parser 的钳制
    条件），所以谱面写的就是实际按住的，两边不会打架。
    """
    times, t = [], 0
    for interval, _keys, _m in rows:
        t += interval
        times.append(t)

    lines = []
    for i, (interval, keys, m) in enumerate(rows):
        if not keys:
            lines.append(f"{interval}")
            continue
        j = i + 1
        while j < len(rows) and not rows[j][1]:
            j += 1
        nominal = SHORT_MS if m["touch"] == "short" else m["dur_cells"] * INTERVAL - GAP
        cap = HOLD_LAST if j >= len(rows) else (times[j] - times[i] - GAP)
        hold = max(HOLD_MIN, min(nominal, cap, HOLD_MAX))
        lines.append(f"{interval} {''.join(keys)} {hold}")
    return lines, times


def build_text():
    rows = render()
    body, times = to_lines(rows)

    out = [
        "#1.0倍速",
        "#" + "=" * 66,
        f"#  {TITLE} —— 原创曲（单声部哼唱，大调，4/4，灵动活泼）",
        "#  全曲只使用中音组与高音组共十四键，单声部，无和弦、无伴奏",
        "#  结构：引子 4 + 主题 8 + 变奏 8 + 对比 8 + 华彩 4 + 再现 8 + 尾句 4 = 44 小节",
        "#  速度：1 格 = 十六分音符 = 110 毫秒（四分 440 毫秒，约每分钟一百三十六拍）",
        "#  旋律走向：快速上行起句 → 雀跃动机反复模进 → 断音跳跃与中音组下探",
        "#           → 十六分华彩跑动 → 再现加花 → 上行冲高收束",
        "#  节奏安排：以十六分跑动为主，插八分长音与断音点音；每两小节一个换气口",
        "#  按住时长 = 本音自己的时值（断音只按 70 毫秒）；休止格是松手后的真静默",
        "#  本文件由配套作曲脚本生成，改曲请改脚本里的乐句表",
        "#" + "=" * 66,
    ]
    starts, seen_sec = {}, []
    for i, (_iv, _ks, m) in enumerate(rows):
        if m["cell"] == 0 and (not seen_sec or seen_sec[-1] != m["sec"]):
            starts[i] = m["sec"]
            seen_sec.append(m["sec"])
    for i, line in enumerate(body):
        if i in starts:
            out.append("#" + starts[i])
        out.append(line)
    return "\n".join(out) + "\n", rows, times


# ---------------------------------------------------------------- 自检

def self_check(rows, times, text):
    print("=" * 78)
    print(f"《{TITLE}》自检 —— 约束：只用中音组 + 高音组 14 键 / 单声部无伴奏")
    print("=" * 78)

    note_rows = [r for r in rows if r[1]]
    keys_used = {k for _i, ks, _m in note_rows for k in ks}
    illegal = sorted(keys_used - set(ALLOWED), key=ORDER.index)
    banned = sorted(keys_used & set(FORBIDDEN), key=ORDER.index)
    sizes = [len(ks) for _i, ks, _m in note_rows]

    print(f"  行数 / 发声行 / 其余行   {len(rows)} / {len(note_rows)} / {len(rows) - len(note_rows)}")
    print(f"  每行按键数              {min(sizes)} ~ {max(sizes)}"
          f"   {'[单声部 ✓]' if max(sizes) == 1 else '[★ 出现了和弦]'}")
    print(f"  用到键位                {len(keys_used)} / 允许 14："
          f"{''.join(sorted(keys_used, key=ORDER.index))}")
    print(f"  越界键位 / 禁用组       {len(illegal)} / {len(banned)}"
          f"{'  ' + ''.join(banned) if banned else ''}")

    letters = {c for c in text if c.isascii() and c.isalpha()}
    extra = sorted(letters - set(ALLOWED))
    shown = ''.join(sorted(letters, key=lambda c: ORDER.index(c) if c in ORDER else 99))
    print(f"  全文 ASCII 字母          {shown}   越界 {len(extra)}"
          f"{'  ★ ' + ''.join(extra) if extra else ''}")

    # ---- 旋律线条：灵动活泼靠的是跳进多、跑动多、长短对比明显 ----
    mel = [(m["bar"], m["cell"], m["key"]) for _i, _ks, m in note_rows]
    ivs = [(abs(SEMITONE[b[2]] - SEMITONE[a[2]]), a[2], b[2])
           for a, b in zip(mel, mel[1:])]
    step = [x for x in ivs if x[0] <= 2]
    skip = [x for x in ivs if 3 <= x[0] <= 7]
    leap = [x for x in ivs if x[0] >= 8]
    print(f"  相邻音程                级进 {len(step)} / 跳进 {len(skip)} / 大跳≥8 {len(leap)}"
          f"   → 跳进率 {(len(skip) + len(leap)) * 100 // max(1, len(ivs))}%"
          f"（《独吟》是 35%）")

    # 连续同向跑动（≥6 个同方向移动）：活泼曲允许，但太多会失控，只做提示
    runs, cur = [], 1
    for a, b in zip(ivs, ivs[1:]):
        d1 = SEMITONE[a[2]] - SEMITONE[a[1]]
        d2 = SEMITONE[b[2]] - SEMITONE[b[1]]
        cur = cur + 1 if (d1 > 0) == (d2 > 0) and d1 and d2 else 1
        if cur >= 6:
            runs.append(cur)
    print(f"  连续同向 ≥6 个          {len(runs)} 处"
          f"{'（音阶跑动，属本曲风格）' if runs else ''}")
    print(f"  相邻同音                 {sum(1 for a, b in zip(mel, mel[1:]) if a[2] == b[2])} 处")

    # ---- 触键：连奏 / 长音 / 断音 ----
    touches = {}
    for _i, _ks, m in note_rows:
        touches[m["touch"]] = touches.get(m["touch"], 0) + 1
    short_audible = sum(1 for _i, _ks, m in note_rows
                        if m["touch"] == "short" and m["dur_cells"] >= 2)
    print(f"  连奏 / 断音音数          {touches.get('full', 0)} / {touches.get('short', 0)}"
          f"（其中 {short_audible} 个时值 ≥2 格，听得出断开）")

    # ---- 气口：每个 2 小节乐句至少 1 格真换气（末句收尾豁免）----
    bars = len(rows) // PER_BAR + (1 if len(rows) % PER_BAR else 0)
    breath = {b: 0 for b in range(1, bars + 1)}
    sustain = {b: 0 for b in range(1, bars + 1)}
    for _i, _ks, m in rows:
        if m["kind"] == "breath":
            breath[m["bar"]] += 1
        elif m["kind"] == "sustain":
            sustain[m["bar"]] += 1
    dry = [p for p in range(1, bars + 1, 2)[:-1] if breath[p] + breath[p + 1] == 0]
    nb = sum(breath.values())
    print(f"  换气格（松手静默）       {nb} 格 = {nb * INTERVAL / 1000:.1f} 秒")
    print(f"  延长格（键仍按着）       {sum(sustain.values())} 格"
          f" = {sum(sustain.values()) * INTERVAL / 1000:.1f} 秒")
    print(f"  无气口的乐句            {len(dry)}"
          f"{'  ★ ' + str(dry) if dry else '  [每句都换气 ✓]'}")

    lo = min(SEMITONE[k] for k in keys_used)
    hi = max(SEMITONE[k] for k in keys_used)
    print(f"  音域                    {hi - lo} 个半音（最低 {min(keys_used, key=SEMITONE.get)}"
          f" / 最高 {max(keys_used, key=SEMITONE.get)}；琴上限 36）")

    note_lines = [l for l in text.splitlines()
                  if l and not l.startswith("#") and len(l.split()) >= 3]
    file_holds = [int(l.split()[2]) for l in note_lines]
    holds = sorted(file_holds)
    print(f"  按住时长                {holds[0]} ~ {holds[-1]} 毫秒，中位 {holds[len(holds) // 2]}")
    dur = times[-1] + file_holds[-1]          # 末音起点 + 末音自己的按住时长
    per_sec = len(note_rows) / (dur / 1000)
    print(f"  整曲时长                {dur / 1000:.1f} 秒"
          f"（{int(dur) // 60000} 分 {dur % 60000 / 1000:.1f} 秒）")
    print(f"  音符密度                {len(note_rows)} 音 / {dur / 1000:.0f} 秒 = "
          f"{per_sec:.1f} 音/秒，{len(note_rows) / bars:.1f} 音/小节"
          f"（《独吟》是 1.3 音/秒）")

    # ---- 旋律走向：每小节取第一个音作该小节的「落点」，看整段的起伏方向 ----
    print()
    print("  旋律走向（每行 = 一段；每格 = 该段一个小节的起音，相对上一小节 ↑升 ↓降 ＝持平）")
    for sec, sec_bars in SONG:
        picked, seen = [], set()
        for _i, ks, m in rows:
            if ks and m["sec"] == sec and m["bar"] not in seen:
                seen.add(m["bar"])
                picked.append((m["bar"], ks[0]))
        picked.sort()
        arrow = ""
        for (_b1, k1), (_b2, k2) in zip(picked, picked[1:]):
            d = SEMITONE[k2] - SEMITONE[k1]
            arrow += "↑" if d > 0 else ("↓" if d < 0 else "＝")
        if picked:
            lo = min(SEMITONE[k] for _b, k in picked)
            hi = max(SEMITONE[k] for _b, k in picked)
            print(f"    {sec:<22} {arrow}   （{len(picked)} 小节，"
                  f"起音跨度 {hi - lo} 半音）")

    # ---- 产物层面：编码 + parser 回读 + 真实 player 模拟 ----
    raw = OUT.read_bytes()
    LF, CR, BOM = b"\n", b"\r", b"\xef\xbb\xbf"
    has_bom = raw[:3] == BOM
    n_cr = raw.count(CR)
    ends_lf = raw.endswith(LF)
    print()
    print(f"  编码                    首 3 字节 {raw[:3]!r}"
          f"{'  ★ 有 BOM' if has_bom else '  [无 BOM ✓]'}，CRLF {n_cr} 个"
          f"{'  ★ 应为 0' if n_cr else '  [纯 LF ✓]'}，末尾换行 {ends_lf}")

    spec = importlib.util.spec_from_file_location("parser", ROOT / "parser.py")
    P = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(P)
    notes = P.parse(str(OUT))
    parsed_holds = [n.hold for n in notes if n.keys]
    clamped = sum(1 for a, b in zip(file_holds, parsed_holds) if a != b)
    print(f"  parser 回读             {len(notes)} 行，发声 {len(parsed_holds)}，"
          f"谱面值与解析值不一致 {clamped}"
          f"{'  [谱面即真相 ✓]' if not clamped else '  ★'}")

    import contextlib
    import io
    import time as _t
    import types
    pressed = []
    fake = types.ModuleType("keyboard")
    VC = [0.0]
    fake.press = lambda k: pressed.append((VC[0], k))
    fake.release = lambda k: None
    fake.wait = lambda *a, **k: None
    fake.is_pressed = lambda *a, **k: False
    sys.modules["keyboard"] = fake
    rt, rs = _t.time, _t.sleep
    _t.time, _t.sleep = (lambda: VC[0]), (lambda x: VC.__setitem__(0, VC[0] + x))
    spec = importlib.util.spec_from_file_location("player", ROOT / "player.py")
    PL = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(PL)
    with contextlib.redirect_stdout(io.StringIO()):
        ret = PL.play(notes, speed=1.0, start_delay=0)
    _t.time, _t.sleep = rt, rs
    onsets, prev = [], None
    for t, _k in pressed:
        if prev is None or t != prev:
            onsets.append(t)
        prev = t
    targets = [n.time / 1000 for n in notes if n.keys]
    drift = [a - onsets[0] - (b - targets[0]) for a, b in zip(onsets, targets)]
    print(f"  模拟播放                返回 {ret}，起点 {len(onsets)} 个，"
          f"全程最大偏差 {max(drift) * 1000:.1f} 毫秒")

    problems = (len(illegal) + len(extra) + len(dry) + clamped
                + (0 if max(sizes) == 1 else 1)
                + (1 if (has_bom or n_cr or not ends_lf) else 0))
    print()
    print("  约束全部满足，可直接实弹" if problems == 0 else f"  ★ 有 {problems} 处问题")
    print("=" * 78)
    return problems


def main():
    text, rows, times = build_text()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"已写入 {OUT}")
    return self_check(rows, times, text)


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
