# -*- coding: utf-8 -*-
"""
原创曲《晴风》—— 轻快动漫风，C 大调，4/4
生成 scores/晴风-原创.txt（可直接被 main.py / parser.py 读取演奏）

想改曲子只需要改下面的 BARS 表（每小节：和弦根音级数 + 旋律 + 伴奏模式 +
间隔毫秒），然后重跑本脚本。脚本会自检结构、音域、音簇、按键排序，并用
parser.py 回读确认产物可演奏。

音乐设计
--------
· 速度：1 格 = 八分音符 = 240ms（四分音符 480ms ≈ 125 BPM）
· 结构：前奏 2 + A 8 + B 8 + A' 8 + 尾奏 6 = 32 小节，约 67 秒
· 调性：C 大调（只用 21 键自然音阶，琴上没有升降号也能完整演奏）
· 织体：右手旋律（高音组）+ 左手八分音符分解和弦（低音组 + 中音组）
· 和弦：I-iii-vi-ii-V-I-IV-V 这类动漫常用进行；和弦最多 5 键
· 配器纪律：旋律与伴奏若相距 ≤2 半音（音簇，听感刺耳），伴奏音自动让位
· 按住时长自动算成「弹满到下一个发声行 − 10ms」，乐句收尾自然拖长

级数与按键对应（C 大调）
    级数   1    2    3    4    5    6    7
    低音组 z    x    c    v    b    n    m     (C3..B3)
    中音组 a    s    d    f    g    h    j     (C4..B4)
    高音组 q    w    e    r    t    y    u     (C5..B5)
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "scores" / "晴风-原创.txt"

TITLE = "晴风"
INTERVAL = 240          # 一个八分音符（毫秒）
SLOW = 480              # 尾奏放慢一档
GAP = 10                # 与 parser.HOLD_GAP_MS 一致
HOLD_MIN = 50
HOLD_MAX = 2000         # 与 midi_to_score.py 的 --hold-max 默认值一致
HOLD_LAST = 1900        # 最后一个和弦让它自然拖长

# ---------------------------------------------------------------- 音高与和弦

DEGREE_KEY = {
    (1, 3): "z", (2, 3): "x", (3, 3): "c", (4, 3): "v", (5, 3): "b",
    (6, 3): "n", (7, 3): "m",
    (1, 4): "a", (2, 4): "s", (3, 4): "d", (4, 4): "f", (5, 4): "g",
    (6, 4): "h", (7, 4): "j",
    (1, 5): "q", (2, 5): "w", (3, 5): "e", (4, 5): "r", (5, 5): "t",
    (6, 5): "y", (7, 5): "u",
}

# 每个键的半音高度（C3 = 48），只用于算音程、查音簇
SEMITONE = {
    "z": 48, "x": 50, "c": 52, "v": 53, "b": 55, "n": 57, "m": 59,
    "a": 60, "s": 62, "d": 64, "f": 65, "g": 67, "h": 69, "j": 71,
    "q": 72, "w": 74, "e": 76, "r": 77, "t": 79, "y": 81, "u": 83,
}

# 琴上的按键顺序：低音组 → 中音组 → 高音组（和弦必须按这个顺序连写）
ORDER = "zxcvbnm" + "asdfghj" + "qwertyu"

CHORD_NAME = {1: "C", 2: "Dm", 3: "Em", 4: "F", 5: "G", 6: "Am", 7: "Bdim"}


def triad_degrees(root):
    """自然音阶三和弦的级数：根音、三音、五音（级数 1..7，会自动绕回）"""
    return [(root - 1 + k) % 7 + 1 for k in (0, 2, 4)]


# 伴奏型：每小节的 8 个八分音符各放什么（左右手分工）
#   (格, 和弦音角色, 八度)
ACC_FULL = [
    (1, 0, 3),   # 低音根音
    (2, 2, 3),   # 低音五音
    (3, 0, 4),   # 中音根音
    (4, 1, 4),   # 中音三音
    (5, 2, 4),   # 中音五音
    (6, 1, 4),   # 中音三音
    (7, 0, 4),   # 中音根音
    (8, 2, 4),   # 中音五音
]
ACC_MODES = {
    "full": ACC_FULL,
    "short": [a for a in ACC_FULL if a[0] <= 5],      # 乐句收尾：留出呼吸
    "thin": [a for a in ACC_FULL if a[0] in (1, 5)],  # 尾奏：稀疏
    "one": [a for a in ACC_FULL if a[0] == 1],
    "none": [],
}

# ---------------------------------------------------------------- 曲子本体

O = 5  # 旋律主八度（高音组）


def m(*pairs):
    """(格, 级数) 序列 → 八度 5 的旋律；三元组 (格, 级数, 八度) 可指定低八度"""
    out = []
    for p in pairs:
        out.append((p[0], p[1], p[2] if len(p) > 2 else O))
    return out


# 每项：(和弦根音级数, 旋律, 伴奏模式, 间隔毫秒)
BARS = [
    # ---- 前奏 (1-2)：只铺伴奏，第 2 小节末尾两格给个上行起句 ----
    (1, m(), "full", INTERVAL),
    (5, m((7, 5, 4), (8, 6, 4)), "full", INTERVAL),

    # ---- A 段主题 (3-10)：动机 1-2-3-5-3-2，随后模进上行再落下 ----
    (1, m((1, 1), (3, 2), (4, 3), (5, 5), (7, 3), (8, 2)), "full", INTERVAL),
    (3, m((1, 3), (3, 5), (4, 6), (5, 7), (7, 6), (8, 5)), "full", INTERVAL),
    (6, m((1, 3), (3, 2), (4, 1), (5, 2), (7, 3), (8, 5)), "full", INTERVAL),
    (2, m((1, 6), (3, 5), (4, 4), (5, 3), (7, 2), (8, 1)), "full", INTERVAL),
    (5, m((1, 5), (3, 6), (4, 7), (5, 6), (7, 5), (8, 3)), "full", INTERVAL),
    (1, m((1, 4), (3, 3), (4, 2), (5, 1), (7, 2), (8, 3)), "full", INTERVAL),
    (4, m((1, 1), (3, 2), (4, 3), (5, 5), (7, 6), (8, 5)), "full", INTERVAL),
    (5, m((1, 4), (3, 3), (5, 2)), "short", INTERVAL),   # 半收束，留气口

    # ---- B 段对比 (11-18)：连线八分音符跑动，音区抬高 ----
    (6, m((1, 6), (2, 5), (3, 3), (4, 5), (5, 6), (6, 7), (7, 6), (8, 5)), "full", INTERVAL),
    (4, m((1, 4), (2, 3), (3, 1), (4, 3), (5, 4), (6, 5), (7, 4), (8, 3)), "full", INTERVAL),
    (1, m((1, 5), (2, 3), (3, 1), (4, 3), (5, 5), (6, 6), (7, 5), (8, 3)), "full", INTERVAL),
    (5, m((1, 7), (2, 6), (3, 5), (4, 6), (5, 7), (6, 6), (7, 5), (8, 2)), "full", INTERVAL),
    (6, m((1, 6), (2, 7), (3, 1), (4, 2), (5, 1), (6, 2), (7, 3), (8, 5)), "full", INTERVAL),
    (4, m((1, 4), (2, 5), (3, 6), (4, 5), (5, 4), (6, 3), (7, 2), (8, 1)), "full", INTERVAL),
    (2, m((1, 2), (3, 4), (5, 6)), "short", INTERVAL),
    (5, m((1, 5), (3, 4), (5, 2)), "short", INTERVAL),

    # ---- A 段再现 (19-26)：主题回来，末句上行冲高，为尾奏蓄势 ----
    (1, m((1, 1), (3, 2), (4, 3), (5, 5), (7, 3), (8, 2)), "full", INTERVAL),
    (3, m((1, 3), (3, 5), (4, 6), (5, 7), (7, 6), (8, 5)), "full", INTERVAL),
    (6, m((1, 3), (3, 2), (4, 1), (5, 2), (7, 3), (8, 5)), "full", INTERVAL),
    (2, m((1, 6), (3, 5), (4, 4), (5, 3), (7, 2), (8, 1)), "full", INTERVAL),
    (5, m((1, 5), (3, 6), (4, 7), (5, 6), (7, 5), (8, 3)), "full", INTERVAL),
    (1, m((1, 4), (3, 3), (4, 2), (5, 1), (7, 2), (8, 3)), "full", INTERVAL),
    (4, m((1, 1), (3, 2), (4, 3), (5, 5), (7, 6), (8, 7)), "full", INTERVAL),  # 冲到 B5
    (5, m((1, 7), (3, 6), (5, 5)), "short", INTERVAL),

    # ---- 尾奏 (27-32)：下行收束 + 放慢 + 长音拖尾 ----
    (4, m((1, 6), (3, 5), (5, 4)), "short", INTERVAL),
    (5, m((1, 5), (3, 4), (5, 2)), "short", INTERVAL),
    (1, m((1, 3), (3, 2), (5, 1)), "short", INTERVAL),
    (1, m((1, 1)), "one", SLOW),        # 主音长音
    (4, m(), "thin", SLOW),             # Ⅳ 级稀疏铺垫
    (1, m(), "final", SLOW),            # C 大三和弦收尾
]

FINAL_CHORD = ["z", "a", "d", "g", "q"]   # C3 C4 E4 G4 C5


def acc_note(root, role, octave):
    """伴奏音：role 0=根音 1=三音 2=五音"""
    deg = triad_degrees(root)[role]
    return DEGREE_KEY[(deg, octave)]


def render():
    """把 BARS 展开成逐行曲谱数据 [(间隔, [按键], 备注 dict)]"""
    rows = []
    for bar_no, (root, melody, acc_mode, interval) in enumerate(BARS, start=1):
        meta = {"bar": bar_no, "root": root}
        if acc_mode == "final":
            rows.append((interval, list(FINAL_CHORD),
                         {**meta, "cell": 1, "mel": None, "acc": list(FINAL_CHORD)}))
            continue

        mel = {c: (d, o) for c, d, o in melody}
        acc = {a[0]: acc_note(root, a[1], a[2]) for a in ACC_MODES[acc_mode]}
        for cell in range(1, 9):
            keys = []
            mel_key = DEGREE_KEY[mel[cell]] if cell in mel else None
            if mel_key:
                keys.append(mel_key)
            acc_keys = []
            if cell in acc:
                a = acc[cell]
                # 配器纪律：伴奏音与旋律相距 ≤2 半音（音簇）就让位
                if mel_key is None or abs(SEMITONE[a] - SEMITONE[mel_key]) > 2:
                    keys.append(a)
                    acc_keys.append(a)
            # 按琴上的按键顺序排好（和弦必须低音组 → 高音组）
            keys = sorted(set(keys), key=ORDER.index)
            rows.append((interval, keys,
                         {**meta, "cell": cell, "mel": mel_key, "acc": acc_keys}))
    return rows


def to_lines(rows):
    """逐行算按住时长 → 写成文本行。按住 = 弹满到下一个发声行 − GAP"""
    times, t = [], 0
    for interval, _keys, _cell in rows:
        t += interval
        times.append(t)

    next_sound = [None] * len(rows)
    seen = None
    for i in range(len(rows) - 1, -1, -1):
        next_sound[i] = seen
        if rows[i][1]:
            seen = i

    lines = []
    for i, (interval, keys, _cell) in enumerate(rows):
        if not keys:
            lines.append(f"{interval}")
            continue
        j = next_sound[i]
        hold = HOLD_LAST if j is None else (times[j] - times[i] - GAP)
        hold = max(HOLD_MIN, min(hold, HOLD_MAX))
        lines.append(f"{interval} {''.join(keys)} {hold}")
    return lines, times


def build_text():
    rows = render()
    body, times = to_lines(rows)

    # 按小节切回去，插入分节注释
    per_bar = 8
    markers = {
        1: "前奏：", 3: "A 段（主题）：", 11: "B 段（对比）：",
        19: "A 段再现：", 27: "尾奏：",
    }
    out = [
        "#1.0倍速",
        "#" + "=" * 66,
        f"#  {TITLE} —— 原创曲（轻快动漫风，C 大调，4/4）",
        "#  结构：前奏 2 + A 8 + B 8 + A' 8 + 尾奏 6 = 32 小节",
        "#  1 格 = 八分音符 = 240ms（尾奏放慢到 480ms）",
        "#  右手旋律（高音组）+ 左手八分音符分解和弦（低音组 + 中音组）",
        "#  本文件由 获取谱子/compose_晴风.py 生成，改曲请改那边的 BARS 表",
        "#" + "=" * 66,
    ]
    for idx, line in enumerate(body):
        bar = idx // per_bar + 1
        if idx % per_bar == 0 and bar in markers:
            out.append("#" + markers[bar])
        out.append(line)
    return "\n".join(out) + "\n", rows, times


def self_check(rows, times, text):
    print("=" * 74)
    print(f"《{TITLE}》自检")
    print("=" * 74)

    keys_used = {k for _i, ks, _c in rows for k in ks}
    bad = keys_used - set(ORDER)
    print(f"  行数            {len(rows)}（32 小节 × 8 格；含尾奏收尾行）")
    print(f"  发声行          {sum(1 for r in rows if r[1])}")
    print(f"  休止行          {sum(1 for r in rows if not r[1])}")
    print(f"  用到按键        {len(keys_used)} / 21  {''.join(sorted(keys_used, key=ORDER.index))}")
    print(f"  非法按键        {len(bad)}")

    sizes = [len(ks) for _i, ks, _c in rows if ks]
    print(f"  每行按键数      min {min(sizes)} / max {max(sizes)}（琴上 5 键实测可同时发声）")

    # 和弦内部音簇（相邻音程 ≤2 半音 = 刺耳）
    clusters, unsorted = [], []
    for i, (_iv, ks, _c) in enumerate(rows):
        if len(ks) < 2:
            continue
        p = [SEMITONE[k] for k in ks]
        if any(b - a <= 2 for a, b in zip(p, p[1:])):
            clusters.append((i + 1, "".join(ks)))
        if ks != sorted(ks, key=ORDER.index):
            unsorted.append(i + 1)
    print(f"  和弦音簇(≤2半音) {len(clusters)}")
    print(f"  未排序和弦      {len(unsorted)}")

    # 琴的音**衰减很慢**，上一个音还在响 —— 所以相邻旋律音、以及旋律与和弦
    # 根音的关系都要看，光看「同时按下」的音簇不够
    mel_seq = [(m["bar"], m["cell"], m["mel"]) for _i, _k, m in rows if m["mel"]]
    steps = [(a[0], a[2], b[2], abs(SEMITONE[b[2]] - SEMITONE[a[2]]))
             for a, b in zip(mel_seq, mel_seq[1:])]
    semis = [s for s in steps if s[3] == 1]
    leaps = [s for s in steps if s[3] >= 12]
    print(f"  旋律相邻半音     {len(semis)} 处"
          + (f"  {[(s[0], s[1] + '→' + s[2]) for s in semis]}" if semis else ""))
    print(f"  旋律跳进≥八度    {len(leaps)} 处"
          + (f"  {[(s[0], s[1] + '→' + s[2]) for s in leaps]}" if leaps else ""))

    clash = []
    for _i, ks, m in rows:
        if not m["mel"]:
            continue
        d = abs(SEMITONE[m["mel"]] - SEMITONE[DEGREE_KEY[(m["root"], 3)]])
        if d in (1, 13):      # 旋律是根音的小二度 / 小九度 —— 最刺耳的一种
            clash.append((m["bar"], m["cell"], "".join(ks)))
    print(f"  旋律撞根音小二/小九 {len(clash)} 处"
          + (f"  {clash[:4]}" if clash else ""))

    # 按住时长分布
    holds = [int(l.split()[2]) for l in text.splitlines()
             if l and not l.startswith("#") and len(l.split()) >= 3]
    holds_s = sorted(holds)
    print(f"  按住时长        {holds_s[0]}~{holds_s[-1]}ms，中位 {holds_s[len(holds_s) // 2]}ms")

    dur = times[-1]
    print(f"  整曲时长        {dur / 1000:.1f} 秒（{dur // 60000}分{dur % 60000 / 1000:.1f}秒）")

    # 音域
    lo = min(SEMITONE[k] for k in keys_used)
    hi = max(SEMITONE[k] for k in keys_used)
    print(f"  音域            {hi - lo} 个半音（琴上限 36）")

    # 用 parser.py 回读 + 用真实 player.py 模拟播放
    spec = importlib.util.spec_from_file_location("parser", ROOT / "parser.py")
    P = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(P)
    notes = P.parse(str(OUT))
    print(f"  parser 回读     {len(notes)} 个音符，首音 {notes[0].time}ms，末音 {notes[-1].time}ms")

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
    print(f"  模拟播放        返回 {ret}，音符起点 {len(onsets)} 个，"
          f"全程最大偏差 {max(drift) * 1000:.1f}ms")

    problems = len(bad) + len(clusters) + len(unsorted) + len(clash)
    print()
    print("  全部合法，可直接实弹" if problems == 0 else f"  ★ 有 {problems} 处问题")
    print("=" * 74)
    return problems


def main():
    text, rows, times = build_text()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"已写入 {OUT}")
    return self_check(rows, times, text)


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
