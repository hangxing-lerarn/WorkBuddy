# -*- coding: utf-8 -*-
"""
原创谱独立复核 —— 只读产物文件，不引用任何作曲脚本的代码。

存在的意义：作曲脚本的 self_check 是「自己检查自己」，它对自己算出来的行
下断言。本工具反过来，从**已经落盘的字节**重新推一遍约束，两边独立得出
同一结论才算数。

两种档位（按曲目约束不同，别拿人声约束去卡「旋律+分解和弦」那首）
  vocal  人声单声部：只用中音组 + 高音组 14 键、每行恰好 1 键、无和弦。
         字母白名单连**注释**一起查 —— 注释里写个 mido 或「A 段」都会被抓出来。
  free   不受键位约束：允许全部 21 键、允许和弦。只做结构检查。

复核项
  A 行语法     每行严格匹配  `数字` 或 `数字 空格 小写字母串 [空格 数字]`
  B 键位合法   发声行的键都在 21 键内（vocal 档另加 14 键白名单 + 注释也查）
  C 单声部     vocal 档：每个发声行恰好 1 个键，全曲 0 个和弦
  D 首行       必须是 `#数字倍速`
  E 编码       UTF-8 无 BOM、纯 LF、末尾有换行
  F 按住时长   全部 ≥ parser 下限，且 ≤ 到下一个发声行的间隔 − 10
  G 回读一致   parser 解析出的行数 / 发声数 / 按住值 与谱面逐项相同
  H 音域       按键都在 21 键内，跨度 ≤ 36 半音
  I 时长       按绝对时间轴算出总时长

用法
  python verify_original.py                  # 复核 scores/ 下所有 *-原创.txt
  python verify_original.py 某个.txt ...      # 复核指定文件
"""

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ORDER = "zxcvbnm" + "asdfghj" + "qwertyu"      # 琴上的键序：低音 → 中音 → 高音
VOCAL = "asdfghj" + "qwertyu"                  # 人声约束允许的 14 键
BANNED = "zxcvbnm"
PITCH = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65, 67, 69, 71,
         72, 74, 76, 77, 79, 81, 83]
SEMITONE = dict(zip(ORDER, PITCH))
POOL_SPAN = 35

HOLD_MIN = 50
HOLD_GAP = 10

# 曲目 → 档位。没登记的按 free 处理（只做结构检查，不做键位断言）
PROFILE = {
    "独吟-原创": "vocal",
    "雀跃-原创": "vocal",
    "晴风-原创": "free",
}

LINE_RE = re.compile(r"^(\d+)(?: ([a-z]+)(?: (\d+))?)?$")
SPEED_RE = re.compile(r"^#(\d+(?:\.\d+)?)(?:倍速)?")


def load_parser():
    spec = importlib.util.spec_from_file_location("parser", ROOT / "parser.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check(path, P):
    level = PROFILE.get(path.stem, "free")
    strict = level == "vocal"
    bad = []

    raw = path.read_bytes()

    # ---- E 编码 ----
    has_bom = raw[:3] == b"\xef\xbb\xbf"
    cr = raw.count(b"\r")
    ends_lf = raw.endswith(b"\n")
    if has_bom:
        bad.append("有 BOM")
    if cr:
        bad.append(f"含 {cr} 个 CR（不是纯 LF）")
    if not ends_lf:
        bad.append("末尾缺换行")
    text = raw.decode("utf-8-sig")

    # ---- 逐行解析（自己推，不用作曲脚本）----
    lines = text.split("\n")
    if ends_lf:
        lines = lines[:-1]
    notes, rests, comments = [], [], 0
    for no, line in enumerate(lines, 1):
        if not line:
            bad.append(f"第 {no} 行是空行")
            continue
        if line.startswith("#"):
            comments += 1
            continue
        if line != line.strip() or "  " in line:
            bad.append(f"第 {no} 行有多余空白：{line!r}")
        m = LINE_RE.match(line)
        if not m:
            bad.append(f"第 {no} 行语法不合规：{line!r}")
            continue
        if m.group(2) is None:
            rests.append((no, m.group(1)))
        else:
            notes.append((no, m.group(1), m.group(2), m.group(3)))

    # ---- D 首行 ----
    if not lines or not SPEED_RE.match(lines[0]):
        bad.append(f"首行不是「#N倍速」：{lines[0] if lines else '(空文件)'!r}")

    # ---- B 键位合法 ----
    used = {k for _n, _i, ks, _h in notes for k in ks}
    if used - set(ORDER):
        bad.append(f"出现琴上没有的键 {''.join(sorted(used - set(ORDER)))}")
    if strict:
        letters = {c for c in text if c.isascii() and c.isalpha()}
        extra = letters - set(VOCAL)
        banned = letters & set(BANNED)
        if extra:
            bad.append(f"出现 14 键白名单外的字母 {''.join(sorted(extra))}")
        if banned:
            bad.append(f"出现禁用低音组 {''.join(sorted(banned))}")

    # ---- C 单声部 ----
    sizes = sorted({len(k) for _n, _i, k, _h in notes}) or [0]
    if strict and sizes != [1]:
        bad.append(f"每行按键数出现 {sizes}，单声部应恒为 1")
    max_chord = max(sizes) if notes else 0

    # ---- F 按住时长：下限 + 到下一个发声行的安全上限 ----
    # 间隔语义（容易算反，多间隔的曲子才会暴露）：parser 是先 `current_time += interval`
    # 再记音符，所以**第 i 行的间隔是给第 i+1 行的时间**。于是从发声行 x 到下一个
    # 发声行 y 的间隔 = 第 x+1 行 … 第 y 行（含）的间隔之和 —— 含 y 的、不含 x 的。
    holds, cap_fails = [], []
    for x, y in zip(notes, notes[1:]):
        between = sum(int(lines[j].split()[0])
                      for j in range(x[0], y[0])          # 0 基：即第 x+1 … y 行
                      if lines[j] and not lines[j].startswith("#"))
        if x[3] is None:
            continue
        h = int(x[3])
        holds.append(h)
        if h < HOLD_MIN:
            bad.append(f"第 {x[0]} 行按住 {h} 毫秒 < 下限 {HOLD_MIN}")
        if h > between - HOLD_GAP:
            cap_fails.append(f"第 {x[0]} 行按住 {h} 毫秒 > 到下一个发声行 "
                             f"{between} − {HOLD_GAP} = {between - HOLD_GAP}")
    for f in cap_fails[:6]:
        bad.append(f)
    if len(cap_fails) > 6:
        bad.append(f"……另有 {len(cap_fails) - 6} 处同样的超上限")
    if notes and notes[-1][3]:
        holds.append(int(notes[-1][3]))

    # ---- G parser 回读 ----
    parsed = P.parse(str(path))
    p_note = [n for n in parsed if n.keys]
    timed = len(notes) + len(rests)          # 计时行（注释行不参与计时也不产出 Note）
    if len(parsed) != timed:
        bad.append(f"parser 读出 {len(parsed)} 个计时行，文件有 {timed} 个"
                   f"（全文 {len(lines)} 行 − 注释 {comments}）")
    if len(p_note) != len(notes):
        bad.append(f"parser 读出 {len(p_note)} 个发声行，文件有 {len(notes)} 个")
    diff = [(a, b) for a, b in zip([int(x[3]) if x[3] else None for x in notes],
                                   [n.hold for n in p_note])
            if a is not None and a != b]
    if diff:
        bad.append(f"按住值被解析器改动 {len(diff)} 处，例：{diff[:3]}")

    # ---- H 音域 ----
    lo = min(SEMITONE[k] for k in used)
    hi = max(SEMITONE[k] for k in used)
    if hi - lo > POOL_SPAN:
        bad.append(f"音域 {hi - lo} 半音，超出琴的 {POOL_SPAN}")

    # ---- I 时长（绝对时间轴）----
    t, last = 0, 0
    for line in lines:
        if not line or line.startswith("#"):
            continue
        t += int(line.split()[0])
        if len(line.split()) >= 3:
            last = int(line.split()[2])
    dur = t + last

    tag = "人声单声部" if strict else "自由（允许 21 键 / 和弦）"
    print(f"\n【{path.name}】档位：{tag}")
    print(f"  行 {len(lines)}（注释 {comments} / 发声 {len(notes)} / 休止 {len(rests)}）")
    print(f"  用到键位      {len(used)} 个：{''.join(sorted(used, key=ORDER.index))}"
          f"   最大同时按键 {max_chord}")
    print(f"  音域          {hi - lo} 半音（{min(used, key=SEMITONE.get)}~"
          f"{max(used, key=SEMITONE.get)}；琴上限 {POOL_SPAN}）")
    if holds:
        print(f"  按住时长      {min(holds)} ~ {max(holds)} 毫秒，中位 "
              f"{sorted(holds)[len(holds) // 2]}")
    print(f"  整曲时长      {dur / 1000:.1f} 秒")
    print(f"  结论          {'全部通过 ✓' if not bad else '★ ' + str(len(bad)) + ' 处问题'}")
    for b in bad:
        print(f"      × {b}")
    return not bad


def main(argv):
    targets = [Path(a) for a in argv] if argv else \
        sorted((ROOT / "scores").glob("*-原创.txt"))
    if not targets:
        print("没找到要复核的文件（scores/*-原创.txt）")
        return 1
    P = load_parser()
    ok = all([check(p, P) for p in targets])
    print()
    print("=" * 72)
    print(f"{len(targets)} 个文件，{'全部通过 ✓' if ok else '★ 存在问题'}")
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
