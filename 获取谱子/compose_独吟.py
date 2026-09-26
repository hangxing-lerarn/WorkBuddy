# -*- coding: utf-8 -*-
"""
原创曲《独吟》—— 无伴奏吟唱，自然小调，4/4
生成 scores/独吟-原创.txt（可直接被 main.py / parser.py 读取演奏）

用户约束
--------
1. 谱面只允许使用中音组与高音组共 14 个键位（asdfghj + qwertyu），
   低音组 zxcvbnm 一个都不能出现；
2. 演唱乐器仅限人声，不使用任何其他乐器伴奏 —— 落到谱面上就是
   **单声部**：每行只按 1 个键，全曲 0 个和弦。
   人声的「呼吸」用休止格表示（不发声，但时间轴照常推进）；
   人声的「长音重音」用第三列表示（按满整个时值）。

修订记录（2026-09-26）
--------------------
第一版把允许集理解成了「低音组 + 中音组」（虽然与用户给的字母清单逐字
一致，但方向反了），整曲落在 A3 ~ B4。现已**整体上移一个八度**到
A4 ~ B5：音符之间的音程、时值、断句全部不变，只是换到中音区 / 高音区
去唱。实现上只改了 L / M 两个八度常量与 DEGREE_KEY 的建表范围，
曲子数据（SONG）一行没动。

音乐设计
--------
· 曲风：无伴奏吟唱抒情曲。单声部线条 + 句尾气口，接近清唱民谣的质朴感；
  因为没有任何和声支撑，旋律本身必须把调性交代清楚 —— 每句句尾都落到
  「主音 / 三音 / 五音」这类稳定音级上，让听者在无伴奏下也能听出调。
· 调式：自然小调（主音为中音组第六键，即 A4）。全白键，琴上可完整演奏。
  第三段借关系大调色彩（强调 C5 - E5 - G5 三个音）做明暗对比。
· 速度：1 格 = 八分音符 = 300 毫秒（四分 600 毫秒 ≈ 每分钟一百拍），
  中慢速，从容，适合拖腔与换气。
· 小节：4/4 拍，每小节 8 格。
· 结构：引子 2 + 第一段 8 + 第二段 8 + 第三段 8 + 再现 4 + 尾句 2 = 32 小节，
  约 77 秒。
· 音域：G4 ~ B5，共 16 个半音（一个十度多一点），是独唱最舒服的音区；
  刻意不用满 14 键的整个音域 —— 单声部贵在音区集中，铺太开反而散。
· 织体：单声部。每行恰好 1 键，没有和弦、没有伴奏声部。

旋律走向（逐段）
----------------
  引子    中音区吟起：A4 上探 C5 又落回，第二小节沉到 G4 再回主音 ——
          一个「叹息」动机，句尾留 2 格气口。
  第一段  主题：「A4-C5-E5-D5」上行后回落，四小节里重复两次，落 A4 收句；
          后半句模进上行（C5-E5-G5-F5）停在 E5 长音，末句上探 A5 停住。
  第二段  变奏：主题再唱一遍，末两小节一路级进上行（E5-F5-G5-A5），
          冲到全曲最高音 B5 并停成长音 —— 把张力留给第三段。
  第三段  高潮：高音区停留（B5 / A5 / G5 反复），句幅拉长、长音变多，
          强调 C5-E5-G5 的大调色彩，第二次冲上 B5 后落回 A5 收顶。
  再现    第一段主题压缩回来，随后 E5-D5-C5-B4 级进下行，停主音 + 整小节留白。
  尾句    最后一句级进下行落到中音区主音 A4，全音符收束。

节奏安排
--------
· 主体是八分音符的连续级进（每格 300 毫秒），偶尔用四分（2 格）拉长。
· 每两小节（约 4.8 秒）为一个乐句，句尾一定有 1~2 格休止 = 换气口；
  第三段的句尾长音拉长到 4~6 格（1.2~1.8 秒）。
· 长音的写法：音符行后面跟若干休止行。按住时长按「**本音自己的时值** − 10 毫秒」
  算，于是长音天然就是长按（重音），而且**句尾长音松手之后**剩下的休止格是真的
  松手静默 —— 那就是人声的换气口。（另一种写法是按住跨过休止一路连到下一个音，
  那样休止格只是「没有新的起音」而键还按着；本曲选了前者，因为只有松手才听得出
  换气。两种都不会累积迟到，时间轴由播放器的绝对时间决定。）

级数与按键对应（自然小调，只用中音组与高音组）
    级数   1(C)  2(D)  3(E)  4(F)  5(G)  6(A)  7(B)
    中音组  a     s     d     f     g     h     j      (C4..B4)
    高音组  q     w     e     r     t     y     u      (C5..B5)
                       ↑ 本曲最低音是 g(G4)，最高音是 u(B5)
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "scores" / "独吟-原创.txt"

TITLE = "独吟"

PER_BAR = 8            # 4/4：每小节 8 个八分音符
INTERVAL = 300         # 一个八分音符（毫秒）→ 四分 600 毫秒 ≈ 100 BPM
GAP = 10               # 与 parser.HOLD_GAP_MS 一致
HOLD_MIN = 50          # 与 parser.DEFAULT_HOLD_MS 一致
HOLD_MAX = 2400        # 本曲最长音是全音符（8 格 = 2400 毫秒），故不会截断任何长音
HOLD_LAST = 2390       # 最后一个音按满全音符

# 用户约束：只允许这 14 个键位（中音组 + 高音组）。本曲一个低音组的键都不使用。
ALLOWED = "asdfghj" + "qwertyu"
FORBIDDEN = "zxcvbnm"
ORDER = FORBIDDEN + ALLOWED     # 琴上的按键顺序：低音组 → 中音组 → 高音组

# 每个键的半音高度（C3 = 48），只用于算音程与音域
_PITCH = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71,
          72, 74, 76, 77, 79, 81, 83]
SEMITONE = dict(zip(ORDER, _PITCH))

# 级数 → 按键（八度 4 = 中音组，八度 5 = 高音组）
DEGREE_KEY = {(d, o): ALLOWED[(o - 4) * 7 + d - 1]
              for o in (4, 5) for d in range(1, 8)}

# L / M 现在指「中音组 / 高音组」。名字沿用不改，只是为了曲子数据一行都不用动。
L, M = 4, 5

# ---------------------------------------------------------------- 曲子本体
# 每项：(段落名, [小节, ...])；一个小节 = 若干 (格数, 级数, 八度)，
# 级数给 None 就是休止。所有小节的格数之和必须等于 PER_BAR。


def N(g, d, o=M):
    """一个音：占 g 格，级数 d（1~7），八度 o（4 中音组 / 5 高音组）"""
    return (g, d, o)


def R(g):
    """休止：占 g 格（人声的换气口）"""
    return (g, None, None)


SONG = [
    # ---- 引子 (1-2)：中音区吟起，「叹息」动机 + 句尾气口 ----
    ("引子：中音区吟起", [
        [N(3, 6, L), N(2, 1), N(2, 7, L), N(1, 6, L)],      # A3 C4 B3 A3
        [N(4, 5, L), N(2, 6, L), R(2)],                     # G3 A3 —— 气口
    ]),

    # ---- 第一段 (3-10)：主题 + 模进，末句上探 A4 ----
    ("第一段（主题）：", [
        [N(2, 6, L), N(2, 1), N(2, 3), N(2, 2)],            # A3 C4 E4 D4
        [N(4, 1), N(2, 7, L), N(1, 6, L), R(1)],            # C4 B3 A3 —— 气口
        [N(2, 1), N(2, 3), N(2, 5), N(2, 4)],               # C4 E4 G4 F4
        [N(6, 3), R(2)],                                    # E4 长音 —— 气口
        [N(2, 6, L), N(2, 1), N(2, 3), N(2, 2)],            # 主题重复
        [N(4, 1), N(2, 7, L), N(1, 6, L), R(1)],            # —— 气口
        [N(2, 1), N(2, 2), N(2, 3), N(2, 5)],               # C4 D4 E4 G4
        [N(4, 6), N(1, 5), N(1, 3), R(2)],                  # A4 长音后下行 —— 气口
    ]),

    # ---- 第二段 (11-18)：主题变奏，末两小节级进上行冲到 B4 ----
    ("第二段（变奏上行）：", [
        [N(2, 6, L), N(2, 1), N(2, 3), N(2, 2)],            # 主题
        [N(4, 1), N(2, 7, L), N(1, 6, L), R(1)],            # —— 气口
        [N(2, 1), N(2, 3), N(2, 5), N(2, 6)],               # C4 E4 G4 A4
        [N(4, 5), N(2, 4), N(1, 3), R(1)],                  # G4 F4 E4 —— 气口
        [N(2, 6, L), N(2, 1), N(2, 3), N(2, 5)],            # A3 C4 E4 G4
        [N(4, 4), N(2, 3), N(1, 2), R(1)],                  # F4 E4 D4 —— 气口
        [N(2, 3), N(2, 4), N(2, 5), N(2, 6)],               # E4 F4 G4 A4 级进上行
        [N(6, 7), R(2)],                                    # B4 最高音长音 —— 气口
    ]),

    # ---- 第三段 (19-26)：高潮，高音区停留 + 大调色彩（C5-E5-G5）----
    ("第三段（高潮）：", [
        [N(3, 6), N(1, 5), N(2, 6), N(2, 7)],               # A4 G4 A4 B4
        [N(4, 3), N(2, 5), N(1, 6), R(1)],                  # E4 G4 A4 —— 气口
        [N(2, 7), N(2, 6), N(2, 5), N(2, 3)],               # B4 A4 G4 E4
        [N(6, 5), R(2)],                                    # G4 长音 —— 气口
        [N(2, 3), N(2, 5), N(2, 6), N(2, 7)],               # E4 G4 A4 B4 再冲高
        [N(4, 6), N(2, 5), N(1, 3), R(1)],                  # A4 G4 E4 —— 气口
        [N(2, 2), N(2, 3), N(2, 4), N(2, 5)],               # D4 E4 F4 G4
        [N(4, 6), N(1, 5), N(1, 3), R(2)],                  # A4 顶点长音 —— 气口
    ]),

    # ---- 再现 (27-30)：主题压缩回来，级进下行 + 整小节留白 ----
    ("第一段再现：", [
        [N(2, 6, L), N(2, 1), N(2, 3), N(2, 2)],            # 主题
        [N(4, 1), N(2, 7, L), N(1, 6, L), R(1)],            # —— 气口
        [N(2, 3), N(2, 2), N(2, 1), N(2, 7, L)],            # E4 D4 C4 B3 级进下行
        [N(4, 6, L), R(4)],                                 # 主音 + 一整小节留白
    ]),

    # ---- 尾句 (31-32)：级进下行落到中音区主音，全音符收束 ----
    ("尾句：", [
        [N(2, 1), N(2, 7, L), N(4, 6, L)],                  # C4 B3 A3
        [N(8, 6, L)],                                       # A3 全音符收尾
    ]),
]


# ---------------------------------------------------------------- 展开与写出

def render():
    """
    把 SONG 展开成逐行曲谱数据 [(间隔, [按键], 备注)]，每个事件占 g 行。

    行的三种身份（备注里的 kind）：
      note    一个音的第一行 —— 发声，同时记下它的名义时值 dur_cells
      sustain 音的后续行 —— 键还按着，没有新的起音（听觉上是音的衰减尾巴）
      breath  休止行 —— 键已松开，真静默（人声的换气口）
    """
    rows = []
    for sec, bars in SONG:
        for bar in bars:
            cells = sum(g for g, _d, _o in bar)
            if cells != PER_BAR:
                raise ValueError(f"「{sec}」有一小节是 {cells} 格，应为 {PER_BAR} 格")
            bar_no = len(rows) // PER_BAR + 1
            for g, d, o in bar:
                key = DEGREE_KEY[(d, o)] if d else None
                for k in range(g):
                    if not key:
                        kind, hit = "breath", None
                    elif k == 0:
                        kind, hit = "note", key
                    else:
                        kind, hit = "sustain", None
                    rows.append((INTERVAL, [hit] if hit else [],
                                 {"bar": bar_no, "cell": k, "sec": sec,
                                  "key": hit, "kind": kind, "dur_cells": g}))
    # 末尾剩下的延长行只是把时间轴推到最后，并不发声 —— 去掉，让文件收在末音上
    while rows and not rows[-1][1]:
        rows.pop()
    return rows


def to_lines(rows):
    """
    逐行算按住时长 → 文本行。

    按住 = **本音自己的时值 − GAP**（不是「到下一个发声行」）。这样句尾长音松手之后
    剩下的休止格才是真的换了气；若按「到下一个发声行」算，键会一路按到下一个音，
    休止格就只是「没有新的起音」。
    两种写法都不会累积迟到：播放器的目标时刻是绝对的，夹在中间的休止行不睡时间、
    只把时间轴往后推，正好把长音多占的那段时间还回去。
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
        nominal = m["dur_cells"] * INTERVAL - GAP          # 本音自己的时值
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
        f"#  {TITLE} —— 原创曲（无伴奏吟唱，自然小调，4/4）",
        "#  全曲只使用中音组与高音组共十四键，单声部，无和弦、无伴奏",
        "#  结构：引子 2 + 主题 8 + 变奏 8 + 高潮 8 + 再现 4 + 尾句 2 = 32 小节",
        "#  速度：1 格 = 八分音符 = 300 毫秒（四分 600 毫秒，约每分钟一百拍）",
        "#  旋律走向：中音区吟起 → 上行模进 → 高音区停留 → 下行收束",
        "#  节奏安排：每两小节一句，句尾留气口；句末长音即长按（重音）",
        "#  按住时长 = 本音自己的时值；休止格是松手之后的真静默（换气口）",
        "#  本文件由配套作曲脚本生成，改曲请改脚本里的乐句表",
        "#" + "=" * 66,
    ]
    # 段落注释必须插在「该段第一小节」的第一行之前
    starts = {}
    seen_sec = []
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
    print("=" * 76)
    print(f"《{TITLE}》自检 —— 约束：只用 14 个键位 / 单声部无伴奏")
    print("=" * 76)

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

    # 约束的「全文」检查：文件里出现的每一个 ASCII 字母都必须属于允许的 14 键
    letters = {c for c in text if c.isascii() and c.isalpha()}
    extra = sorted(letters - set(ALLOWED))
    print(f"  全文 ASCII 字母          {''.join(sorted(letters, key=lambda c: ORDER.index(c) if c in ORDER else 99))}"
          f"   越界 {len(extra)}{'  ★ ' + ''.join(extra) if extra else ''}")

    # 旋律线条分析
    mel = [(m["bar"], m["cell"], m["key"]) for _i, _ks, m in note_rows]
    ivs = [(abs(SEMITONE[b[2]] - SEMITONE[a[2]]), a[2], b[2])
           for a, b in zip(mel, mel[1:])]
    step = [x for x in ivs if x[0] <= 2]
    skip = [x for x in ivs if 3 <= x[0] <= 7]
    leap = [x for x in ivs if x[0] >= 8]
    print(f"  相邻音程                级进 {len(step)} / 跳进 {len(skip)} / 大跳≥8 {len(leap)}"
          f"{'  ★' if leap else '  [人声可唱 ✓]'}")

    # 人声习惯：大跳之后应当反向级进解决
    unresolved = []
    for i, (d, a, b) in enumerate(ivs):
        if d >= 5 and i + 1 < len(ivs):
            nxt = SEMITONE[ivs[i + 1][2]] - SEMITONE[b]
            if nxt == 0 or (nxt > 0) == (SEMITONE[b] > SEMITONE[a]):
                unresolved.append((mel[i][0], a + "→" + b))
    print(f"  大跳后未反向解决        {len(unresolved)}"
          f"{'  ' + str(unresolved[:4]) if unresolved else ''}")

    same = sum(1 for a, b in zip(mel, mel[1:]) if a[2] == b[2])
    print(f"  相邻同音（会显呆板）     {same} 处")

    # 气口：每个乐句（2 小节）至少 1 格「真换气」= 松手静默。
    # 最后一个乐句是收尾长音，本来就不换气，豁免。
    bars = len(rows) // PER_BAR
    breath = {b: 0 for b in range(1, bars + 1)}
    sustain = {b: 0 for b in range(1, bars + 1)}
    for _i, _ks, m in rows:
        if m["kind"] == "breath":
            breath[m["bar"]] += 1
        elif m["kind"] == "sustain":
            sustain[m["bar"]] += 1
    dry = [p for p in range(1, bars + 1, 2)[:-1]
           if breath[p] + breath[p + 1] == 0]
    nb = sum(breath.values())
    print(f"  换气格（松手静默）       {nb} 格 = {nb * INTERVAL / 1000:.1f} 秒"
          f"，单句最多 {max(breath.values())} 格")
    print(f"  延长格（键仍按着）       {sum(sustain.values())} 格"
          f" = {sum(sustain.values()) * INTERVAL / 1000:.1f} 秒")
    print(f"  无气口的乐句            {len(dry)}"
          f"{'  ★ ' + str(dry) if dry else '  [每句都换气 ✓]'}")

    lo = min(SEMITONE[k] for k in keys_used)
    hi = max(SEMITONE[k] for k in keys_used)
    print(f"  音域                    {hi - lo} 个半音（最低 {min(keys_used, key=SEMITONE.get)}"
          f" / 最高 {max(keys_used, key=SEMITONE.get)}；琴上限 36）")

    holds = sorted(int(l.split()[2]) for l in text.splitlines()
                   if l and not l.startswith("#") and len(l.split()) >= 3)
    print(f"  按住时长                {holds[0]} ~ {holds[-1]} 毫秒，中位 {holds[len(holds) // 2]}"
          f"（长音即长按 = 重音）")
    # 末尾的延长行已经去掉，所以整曲时长 = 末音起点 + 末音的按住时长
    dur = times[-1] + holds[-1]
    print(f"  整曲时长                {dur / 1000:.1f} 秒"
          f"（{int(dur) // 60000} 分 {dur % 60000 / 1000:.1f} 秒）")

    # 旋律走向：逐段打印每小节首音的相对走向
    print()
    print("  旋律走向（每格 = 一个小节首音，相对上一小节：↑升 ↓降 ＝持平）")
    for sec, bars in SONG:
        bar_keys = []
        for i, (_iv, ks, m) in enumerate(rows):
            if ks and m["cell"] == 0 and m["sec"] == sec:
                bar_keys.append((m["bar"], ks[0]))
        arrow = ""
        for (b1, k1), (b2, k2) in zip(bar_keys, bar_keys[1:]):
            d = SEMITONE[k2] - SEMITONE[k1]
            arrow += "↑" if d > 0 else ("↓" if d < 0 else "＝")
        print(f"    {sec:<18} {arrow}   "
              f"（{bar_keys[0][1]} … {bar_keys[-1][1]}，{len(bars)} 小节）")

    # ---- 产物层面：编码 + parser 回读 + 真实 player 模拟 ----
    # 注意：别在 f-string 的表达式里写 b'\n' / b'\r' —— 转义层级很容易写错，
    # 先算成变量再打印。
    raw = OUT.read_bytes()
    LF, CR, BOM = b"\n", b"\r", b"\xef\xbb\xbf"
    has_bom = raw[:3] == BOM
    n_cr = raw.count(CR)
    ends_lf = raw.endswith(LF)
    print()
    print(f"  编码                    首 3 字节 {raw[:3]!r}"
          f"{'  ★ 有 BOM' if has_bom else '  [无 BOM ✓]'}，CRLF {n_cr} 个"
          f"{'  ★ 应为 0' if n_cr else '  [纯 LF ✓]'}")
    print(f"  末尾换行                {ends_lf}{'' if ends_lf else '  ★ 缺末尾换行'}")

    spec = importlib.util.spec_from_file_location("parser", ROOT / "parser.py")
    P = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(P)
    notes = P.parse(str(OUT))
    file_holds = [int(l.split()[2]) for l in text.splitlines()
                  if l and not l.startswith("#") and len(l.split()) >= 3]
    parsed_holds = [n.hold for n in notes if n.keys]
    clamped = sum(1 for a, b in zip(file_holds, parsed_holds) if a != b)
    print(f"  parser 回读             {len(notes)} 行，发声 {len(parsed_holds)}，"
          f"谱面值与解析值不一致 {clamped}{'  [谱面即真相 ✓]' if not clamped else '  ★'}")

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
    print("=" * 76)
    return problems


def main():
    text, rows, times = build_text()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"已写入 {OUT}")
    return self_check(rows, times, text)


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
